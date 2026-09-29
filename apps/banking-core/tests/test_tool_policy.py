"""Versioned tool policy: seed, saves, audit, floor and live effect (ADR-0002)."""

import threading

import banking_core.main as main
import pytest
import sqlalchemy as sa
from banking_core.control.authorize import Authorizer
from banking_core.control.config import DatabaseControlConfigRepository
from banking_core.control.session import SessionState
from banking_core.control.tool_policy import (
    TOOL_POLICY_AUDIT_ACTION,
    ToolPolicyRejected,
    active_tool_policy,
    baseline_matrix,
    effective_matrix,
    reset_tool_policy_to_seed,
    save_tool_policy,
    seed_disabled_tools,
    seed_matrix,
)
from banking_core.main import app
from banking_core.models.config import ToolPolicyRecord
from contracts.envelope import ReasonCode, ToolCall, VerificationState
from contracts.tools import CODE_FLOOR, TOOL_CATALOG
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

VERIFIED = VerificationState.VERIFIED
SUMMARY_CALL = ToolCall(tool="account.get_summary", args={})
VERIFIED_SESSION = SessionState(session_id="s-tool-policy", state=VERIFIED)


@pytest.fixture(autouse=True)
def default_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLICY_SEED_DISABLED_TOOLS", raising=False)


def _versions(session: Session) -> list[tuple[int, bool]]:
    session.expire_all()
    rows = session.execute(
        sa.select(ToolPolicyRecord.version, ToolPolicyRecord.is_active).order_by(
            ToolPolicyRecord.version
        )
    ).all()
    return [(row.version, row.is_active) for row in rows]


def _audit_rows(
    session: Session,
    seed: bool = False,
) -> list[sa.Row]:  # type: ignore[type-arg]
    """Tool policy audit rows: the changes, or with `seed` the seeding of version 1."""
    op = "=" if seed else "<>"
    return list(
        session.execute(
            sa.text(
                "SELECT actor_type, actor_ref, decision, payload FROM ops.audit_log "
                "WHERE action = :action "
                f"AND payload->>'source' {op} 'seed' ORDER BY id"
            ),
            {"action": TOOL_POLICY_AUDIT_ACTION},
        )
    )


def test_seed_disables_only_account_summary_by_default(
    db_engine: sa.Engine, db_session: Session
) -> None:
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))

    assert repo.get_tool_permitted_states("account.get_summary") == frozenset()
    assert repo.get_tool_permitted_states("transaction.list_recent") == frozenset(
        {VERIFIED}
    )
    assert _versions(db_session) == [(1, True)]
    record = db_session.execute(sa.select(ToolPolicyRecord)).scalar_one()
    assert record.matrix["account.get_summary"] == []
    assert set(record.matrix) == set(TOOL_CATALOG)


def test_the_seed_is_audited_once_as_a_change_from_the_catalog_defaults(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    for _ in range(3):
        with maker() as session:
            active_tool_policy(session)

    [entry] = _audit_rows(db_session, seed=True)
    assert (entry.actor_type, entry.actor_ref, entry.decision) == (
        "system",
        "seed",
        "allowed",
    )
    assert entry.payload == {
        "version": 1,
        "previous_version": None,
        "source": "seed",
        "changes": [
            {"tool": "account.get_summary", "before": ["VERIFIED"], "after": []}
        ],
    }
    assert _audit_rows(db_session) == []


def test_seed_from_environment_lists_disabled_tools(
    db_engine: sa.Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", " card.list , account.get_summary")
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))

    assert repo.get_tool_permitted_states("card.list") == frozenset()
    assert repo.get_tool_permitted_states("account.get_summary") == frozenset()
    assert repo.get_tool_permitted_states("card.block") == frozenset({VERIFIED})


def test_empty_seed_variable_disables_nothing(
    db_engine: sa.Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", "")
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))

    assert repo.get_tool_permitted_states("account.get_summary") == frozenset(
        {VERIFIED}
    )


def test_unknown_tool_in_the_seed_fails_loudly(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", "account.get_summary,card.nuke")

    with pytest.raises(ValueError, match=r"unknown tool.*card\.nuke"):
        seed_disabled_tools()
    with pytest.raises(ValueError, match="card.nuke"):
        active_tool_policy(db_session)
    assert _versions(db_session) == []


def test_the_seed_can_only_restrict_the_baseline() -> None:
    baseline = baseline_matrix()
    for name, states in seed_matrix().items():
        assert {VerificationState(s) for s in states} <= baseline[name]
        assert baseline[name] <= CODE_FLOOR[name]


def test_environment_is_not_read_again_once_a_version_exists(
    db_engine: sa.Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))
    assert repo.get_tool_permitted_states("account.get_summary") == frozenset()

    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", "")

    assert repo.get_tool_permitted_states("account.get_summary") == frozenset()
    assert _versions(db_session) == [(1, True)]


def test_concurrent_first_seed_creates_one_version(
    db_engine: sa.Engine, db_session: Session
) -> None:
    workers = 4
    barrier = threading.Barrier(workers)
    maker = sessionmaker(bind=db_engine)
    errors: list[BaseException] = []
    seen: list[int] = []

    def seed() -> None:
        try:
            with maker() as session:
                barrier.wait()
                seen.append(active_tool_policy(session).version)
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=seed) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert seen == [1] * workers
    assert _versions(db_session) == [(1, True)]


def test_a_save_is_a_new_active_version_with_an_audit_row(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        active_tool_policy(session)
        result = save_tool_policy(
            session, {"account.get_summary": {VERIFIED}}, actor_ref="admin"
        )
        session.commit()

    assert result.version == 2
    assert result.previous_version == 1
    assert result.changes == [
        {"tool": "account.get_summary", "before": [], "after": ["VERIFIED"]}
    ]
    assert _versions(db_session) == [(1, False), (2, True)]
    [entry] = _audit_rows(db_session)
    assert (entry.actor_type, entry.actor_ref, entry.decision) == (
        "agent",
        "admin",
        "allowed",
    )
    assert entry.payload == {
        "version": 2,
        "previous_version": 1,
        "source": "admin_api",
        "changes": result.changes,
    }


def test_a_save_carries_over_the_tools_it_does_not_name(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        save_tool_policy(session, {"card.list": set()})
        save_tool_policy(session, {"account.get_summary": {VERIFIED}})
        session.commit()
        record = active_tool_policy(session)

    assert record.matrix["card.list"] == []
    assert record.matrix["account.get_summary"] == ["VERIFIED"]
    assert record.matrix["card.block"] == ["VERIFIED"]
    assert [v for v, _ in _versions(db_session)] == [1, 2, 3]


def test_a_version_is_not_saved_when_its_audit_row_cannot_be(
    db_engine: sa.Engine,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        active_tool_policy(session)

    def failing_append(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("banking_core.control.tool_policy.append", failing_append)
    with maker() as session:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            save_tool_policy(session, {"account.get_summary": {VERIFIED}})
            session.commit()

    assert _versions(db_session) == [(1, True)]
    with maker() as session:
        assert active_tool_policy(session).matrix["account.get_summary"] == []


def test_a_state_beyond_the_floor_is_refused_not_clamped(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        active_tool_policy(session)
        with pytest.raises(ToolPolicyRejected) as raised:
            save_tool_policy(
                session,
                {
                    "card.block": {VerificationState.ANONYMOUS, VERIFIED},
                    "account.get_summary": {VerificationState.IDENTIFIED},
                    "no.such_tool": {VERIFIED},
                    "card.list": {VERIFIED},
                },
            )
        session.rollback()

    problems = {p["tool"]: p for p in raised.value.problems}
    assert set(problems) == {"card.block", "account.get_summary", "no.such_tool"}
    assert problems["card.block"]["type"] == "code_floor_violation"
    assert "ANONYMOUS" in problems["card.block"]["message"]
    assert "Code floor allows ['VERIFIED']" in problems["card.block"]["message"]
    assert problems["no.such_tool"]["type"] == "unknown_tool"
    # Nothing was written, not even the acceptable part of the request.
    assert _versions(db_session) == [(1, True)]
    assert _audit_rows(db_session) == []


def test_every_state_of_every_tool_beyond_the_floor_is_refused(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        for tool_name, floor in CODE_FLOOR.items():
            for state in set(VerificationState) - floor:
                with pytest.raises(ToolPolicyRejected):
                    save_tool_policy(session, {tool_name: {state}})
                session.rollback()
    assert _versions(db_session) in ([], [(1, True)])
    assert _audit_rows(db_session) == []


def test_a_change_reaches_the_next_call_without_a_restart(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """One long-lived authorizer (as in a running process) sees each new version."""
    maker = sessionmaker(bind=db_engine)
    authorizer = Authorizer(
        config_repo=DatabaseControlConfigRepository(session_factory=maker)
    )

    refused = authorizer.authorize(SUMMARY_CALL, VERIFIED_SESSION)
    assert refused.allowed is False
    assert refused.reason_code == ReasonCode.STATE_NOT_ALLOWED
    assert refused.flags == ["TOOL_DISABLED"]

    with maker() as session:
        save_tool_policy(session, {"account.get_summary": {VERIFIED}})
        session.commit()
    assert authorizer.authorize(SUMMARY_CALL, VERIFIED_SESSION).allowed is True

    with maker() as session:
        save_tool_policy(session, {"account.get_summary": set()})
        session.commit()
    disabled_again = authorizer.authorize(SUMMARY_CALL, VERIFIED_SESSION)
    assert disabled_again.allowed is False
    assert disabled_again.flags == ["TOOL_DISABLED"]


def test_an_enabled_tool_is_still_refused_outside_its_states(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    authorizer = Authorizer(
        config_repo=DatabaseControlConfigRepository(session_factory=maker)
    )
    with maker() as session:
        save_tool_policy(session, {"account.get_summary": {VERIFIED}})
        session.commit()

    decision = authorizer.authorize(
        SUMMARY_CALL,
        SessionState(session_id="s-anon", state=VerificationState.ANONYMOUS),
    )

    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.STATE_NOT_ALLOWED
    assert decision.flags == ["STATE_ANONYMOUS_NOT_PERMITTED"]


def test_readiness_needs_a_loadable_tool_policy(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad seed is a not-ready service, not a refusal on a customer's first call."""
    monkeypatch.setattr(main, "get_kb_searcher", lambda: None)
    client = TestClient(app)

    monkeypatch.setenv("POLICY_SEED_DISABLED_TOOLS", "card.nuke")
    broken = client.get("/ready")
    assert broken.status_code == 503
    assert broken.json()["reason"] == "policy config unavailable (ValueError)"
    assert _versions(db_session) == []

    monkeypatch.delenv("POLICY_SEED_DISABLED_TOOLS")
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert _versions(db_session) == [(1, True)]


def test_effective_matrix_of_the_active_version(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        matrix = effective_matrix(active_tool_policy(session))

    assert matrix["account.get_summary"] == frozenset()
    assert matrix["kb.search"] == frozenset(VerificationState)


def test_reset_to_seed_writes_nothing_when_already_at_the_seed(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        result = reset_tool_policy_to_seed(session)
        session.commit()

    assert result.changed is False
    assert result.version == 1
    assert _versions(db_session) == [(1, True)]
    assert _audit_rows(db_session) == []


def test_reset_to_seed_restores_it_as_a_new_audited_version(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        save_tool_policy(session, {"account.get_summary": {VERIFIED}})
        save_tool_policy(session, {"card.list": set()})
        session.commit()
    with maker() as session:
        result = reset_tool_policy_to_seed(session)
        session.commit()

    assert result.changed is True
    assert result.version == 4
    assert {c["tool"] for c in result.changes} == {"account.get_summary", "card.list"}
    assert _versions(db_session)[-1] == (4, True)
    assert [v for v, active in _versions(db_session) if active] == [4]
    payload = _audit_rows(db_session)[-1].payload
    assert payload["source"] == "demo_reset"
    with maker() as session:
        assert active_tool_policy(session).matrix == seed_matrix()


def test_concurrent_saves_are_serialized_into_consecutive_versions(
    db_engine: sa.Engine, db_session: Session
) -> None:
    workers = 4
    tools = [
        "card.list",
        "transaction.list_recent",
        "account.get_summary",
        "card.block",
    ]
    barrier = threading.Barrier(workers)
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        active_tool_policy(session)
    errors: list[BaseException] = []

    def save(tool: str) -> None:
        try:
            with maker() as session:
                barrier.wait()
                save_tool_policy(session, {tool: set()})
                session.commit()
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(tool,)) for tool in tools]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert _versions(db_session) == [
        (1, False),
        (2, False),
        (3, False),
        (4, False),
        (5, True),
    ]
    with maker() as session:
        matrix = active_tool_policy(session).matrix
    # No save lost another's change.
    assert all(matrix[tool] == [] for tool in tools)
    assert len(_audit_rows(db_session)) == workers


def test_the_database_allows_a_single_active_version(
    db_engine: sa.Engine, db_session: Session
) -> None:
    maker = sessionmaker(bind=db_engine)
    with maker() as session:
        active_tool_policy(session)
    with maker() as session:
        session.add(ToolPolicyRecord(version=2, is_active=True, matrix={}))
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()
