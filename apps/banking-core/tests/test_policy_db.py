"""Integration tests for database-backed policy configuration and seeding (ADR-0002)."""

import os
import threading
from collections.abc import Generator
from unittest.mock import patch

import banking_core.main as main
import pytest
import sqlalchemy as sa
from banking_core.control.authorize import Authorizer
from banking_core.control.config import (
    DatabaseControlConfigRepository,
    InMemoryControlConfigRepository,
    get_control_config_repository,
)
from banking_core.control.loader import load_policy_config, save_policy_config
from banking_core.control.policy import PolicyConfig
from banking_core.control.session import SessionState
from banking_core.db import session as db_session_module
from banking_core.main import app
from banking_core.models.config import PolicyConfigRecord, ToolPolicyRecord
from contracts.envelope import ReasonCode, ToolCall, VerificationState
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

CARD_BLOCK_CALL = ToolCall(
    tool="card.block",
    args={"card_ref": "card_test_123", "reason": "LOST"},
    idempotency_key="idem_key_policy_db_1",
)
VERIFIED_SESSION = SessionState(session_id="s-db", state=VerificationState.VERIFIED)


def _bad_credentials_url(postgres_url: str) -> str:
    url = sa.engine.make_url(postgres_url).set(password="wrong-password")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def fresh_db_singletons() -> Generator[None, None, None]:
    """Reset the process-wide engine so each test resolves DATABASE_URL again."""

    def reset() -> None:
        if db_session_module._engine is not None:
            db_session_module._engine.dispose()
        db_session_module._engine = None
        db_session_module._SessionLocal = None

    reset()
    yield
    reset()


def test_policy_loader_seeds_from_env_on_empty_db(db_session: Session) -> None:
    """On first run with empty DB, loader seeds from environment.

    Also verifies that the active record is saved in policy_config table.
    """
    # Ensure tables are empty
    count = db_session.query(PolicyConfigRecord).count()
    assert count == 0

    env_vars = {
        "POLICY_SEED_THRESHOLDS_MINOR": '{"USD": 45000, "EUR": 45000}',
        "POLICY_SEED_AMOUNT_MODE": "block",
        "DEFAULT_CURRENCY": "USD",
        "RATE_LIMIT_ATTEMPTS_PER_SESSION": "7",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        loaded_cfg = load_policy_config(db_session)
        db_session.commit()

    assert loaded_cfg.thresholds_minor["USD"] == 45000
    assert loaded_cfg.thresholds_minor["EUR"] == 45000
    assert loaded_cfg.amount_mode == "block"
    assert loaded_cfg.currency == "USD"
    assert loaded_cfg.rate_limit_attempts_per_session == 7

    # DB now has exactly 1 active record
    records = db_session.query(PolicyConfigRecord).filter_by(is_active=True).all()
    assert len(records) == 1
    assert records[0].version == 1
    assert records[0].amount_mode == "block"
    assert records[0].currency == "USD"


def test_policy_loader_returns_persisted_db_config_on_subsequent_runs(
    db_session: Session,
) -> None:
    """Subsequent calls read from DB and do not re-seed from env."""
    # Seed initial config
    cfg1 = PolicyConfig(
        thresholds_minor={"USD": 88000, "COP": 150000000},
        currency="USD",
        amount_mode="flag",
    )
    save_policy_config(cfg1, db_session)
    db_session.commit()

    # Even if environment changes, loader returns DB record
    with patch.dict(
        os.environ,
        {"POLICY_SEED_AMOUNT_MODE": "block", "DEFAULT_CURRENCY": "COP"},
        clear=False,
    ):
        loaded = load_policy_config(db_session)
        assert loaded.currency == "USD"
        assert loaded.amount_mode == "flag"
        assert loaded.thresholds_minor["USD"] == 88000


def test_tool_policy_loader_and_repository(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """Verify tool policy seeding, repository operations, and code floor protection."""
    SessionMaker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    repo = DatabaseControlConfigRepository(session_factory=SessionMaker)

    # 1. First read loads tool permitted states
    allowed = repo.get_tool_permitted_states("card.block")
    assert allowed == frozenset({VerificationState.VERIFIED})

    # Unauthenticated tool
    kb_states = repo.get_tool_permitted_states("kb.search")
    assert VerificationState.ANONYMOUS in kb_states

    # 2. Update tool policy to restrict states (e.g. only VERIFIED)
    repo.set_tool_permitted_states(
        "card.block",
        states={VerificationState.VERIFIED},
    )
    updated_states = repo.get_tool_permitted_states("card.block")
    assert updated_states == frozenset({VerificationState.VERIFIED})

    # 3. CODE_FLOOR enforcement: cannot lower write tool below VERIFIED
    with pytest.raises(
        ValueError,
        match="cannot widen tool 'card.block' permitted states beyond CODE_FLOOR",
    ):
        repo.set_tool_permitted_states(
            "card.block",
            states={VerificationState.ANONYMOUS},
        )


def test_bad_db_credentials_refuse_closed_and_never_fall_back(
    postgres_url: str,
) -> None:
    """Unreachable DB config: refusal with a closed code, no env or InMemory config."""
    engine = sa.create_engine(_bad_credentials_url(postgres_url))
    try:
        repo = DatabaseControlConfigRepository(
            session_factory=sessionmaker(bind=engine)
        )

        with pytest.raises(sa.exc.OperationalError):
            repo.get_policy_config()

        decision = Authorizer(config_repo=repo).authorize(
            CARD_BLOCK_CALL, VERIFIED_SESSION
        )
        assert decision.allowed is False
        assert decision.reason_code == ReasonCode.INTERNAL_ERROR
        assert decision.flags == ["POLICY_CONFIG_UNAVAILABLE"]
    finally:
        engine.dispose()

    runtime_repo = get_control_config_repository()
    assert isinstance(runtime_repo, DatabaseControlConfigRepository)
    assert not isinstance(runtime_repo, InMemoryControlConfigRepository)


def test_readiness_fails_on_bad_credentials_and_recovers_on_retry(
    postgres_url: str,
    db_session: Session,
    fresh_db_singletons: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not ready while DB config cannot load; ready on the next probe once it can."""
    client = TestClient(app)

    monkeypatch.setenv("DATABASE_URL", _bad_credentials_url(postgres_url))
    monkeypatch.setattr(main, "get_kb_searcher", lambda: None)
    not_ready = client.get("/ready")
    assert not_ready.status_code == 503
    body = not_ready.json()
    assert body["status"] == "not_ready"
    assert body["reason"] == "policy config unavailable (OperationalError)"
    assert "wrong-password" not in not_ready.text

    decision = Authorizer().authorize(CARD_BLOCK_CALL, VERIFIED_SESSION)
    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.INTERNAL_ERROR

    # No permanent poison: the next probe with a reachable DB succeeds.
    db_session_module._engine.dispose()  # type: ignore[union-attr]
    db_session_module._engine = None
    db_session_module._SessionLocal = None
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_widened_tool_row_in_db_is_refused_as_code_floor_violation(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """A row edited directly in the DB beyond CODE_FLOOR is refused, not a 500."""
    db_session.add(
        ToolPolicyRecord(
            tool_name="card.block",
            permitted_states=["ANONYMOUS", "VERIFIED"],
        )
    )
    db_session.commit()
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))

    decision = Authorizer(config_repo=repo).authorize(CARD_BLOCK_CALL, VERIFIED_SESSION)

    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.CODE_FLOOR_VIOLATION
    assert decision.flags == ["CODE_FLOOR_VIOLATION"]


def test_concurrent_first_seed_creates_one_row(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """Parallel first loads on an empty table agree on a single seeded version."""
    workers = 4
    barrier = threading.Barrier(workers)
    maker = sessionmaker(bind=db_engine)
    results: list[PolicyConfig] = []
    errors: list[BaseException] = []

    def seed() -> None:
        try:
            with maker() as session:
                barrier.wait()
                results.append(load_policy_config(session))
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=seed) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == workers
    assert all(result == results[0] for result in results)
    assert db_session.query(PolicyConfigRecord).count() == 1


def test_empty_permitted_states_in_db_disables_the_tool(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """A stored [] means the operator disabled the tool; no catalog fallback."""
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))
    repo.set_tool_permitted_states("card.block", set())

    stored = db_session.get(ToolPolicyRecord, "card.block")
    assert stored is not None and stored.permitted_states == []
    assert repo.get_tool_permitted_states("card.block") == frozenset()
    decision = Authorizer(config_repo=repo).authorize(CARD_BLOCK_CALL, VERIFIED_SESSION)

    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.STATE_NOT_ALLOWED


def test_corrupt_tool_row_is_config_unavailable_not_code_floor(
    db_engine: sa.Engine, db_session: Session
) -> None:
    """A non-floor ValueError from stored config maps to INTERNAL_ERROR."""
    db_session.add(
        ToolPolicyRecord(tool_name="card.block", permitted_states=["NOT_A_STATE"])
    )
    db_session.commit()
    repo = DatabaseControlConfigRepository(session_factory=sessionmaker(bind=db_engine))

    decision = Authorizer(config_repo=repo).authorize(CARD_BLOCK_CALL, VERIFIED_SESSION)

    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.INTERNAL_ERROR
    assert decision.flags == ["POLICY_CONFIG_UNAVAILABLE"]


def test_missing_db_password_is_config_unavailable_not_code_floor(
    fresh_db_singletons: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_database_url's ValueError is a configuration fault, not a floor breach."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    decision = Authorizer(config_repo=get_control_config_repository()).authorize(
        CARD_BLOCK_CALL, VERIFIED_SESSION
    )

    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.INTERNAL_ERROR
    assert decision.flags == ["POLICY_CONFIG_UNAVAILABLE"]
