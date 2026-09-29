from __future__ import annotations

import json
import uuid
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import fakeredis
import pytest
import sqlalchemy as sa
from banking_core.api import routes_tools
from banking_core.api.dispatcher import ToolDispatcher
from banking_core.api.routes_sessions import get_session_store, set_session_store
from banking_core.api.routes_tools import set_dispatcher
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.policy import PolicyConfig
from banking_core.control.session import RedisSessionStore
from banking_core.db import get_db
from banking_core.identity import (
    OtpChallengeStore,
    SimulatedInbox,
    set_simulated_inbox,
)
from banking_core.knowledge.tools.kb_search import get_kb_searcher
from banking_core.main import app, mount_dev_router_if_enabled
from banking_core.models.core_bank import Card
from banking_core.models.ops import AuditLog, Handoff, IdempotencyKey
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import create_scenario_fixtures, fixture_uuid
from banking_core.seed.staging import (
    StagingAccount,
    StagingCard,
    StagingCustomer,
    StagingDataset,
    StagingTransaction,
)
from contracts.audit import AuditPayload
from contracts.envelope import ToolResultStatus, VerificationState
from contracts.tools import TOOL_CATALOG
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

TEST_MASTER_KEY = "00" * 32
TEST_BLIND_INDEX_SALT = "tool-wiring-http-test-salt"


@pytest.fixture
def api_client(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    monkeypatch.setenv("MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("BLIND_INDEX_SALT", TEST_BLIND_INDEX_SALT)
    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "true")
    monkeypatch.setenv("RETRIEVAL_MODE", "bm25")
    monkeypatch.setenv("RETRIEVAL_SCORE_FLOOR", "0")

    kb_path = tmp_path / "kb.jsonl"
    kb_path.write_text(
        json.dumps(
            {
                "id": "card_block.01.es",
                "topic_id": "card_block.01",
                "lang": "es",
                "title": "Bloqueo de tarjeta",
                "text": (
                    "Para bloquear una tarjeta robada o perdida, "
                    "confirme su identidad con un código OTP."
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KB_PATH", str(kb_path))
    get_kb_searcher.cache_clear()

    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    session_store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
    set_session_store(session_store)
    inbox = SimulatedInbox(redis_client=fake_redis)
    set_simulated_inbox(inbox)
    dispatcher = ToolDispatcher(
        config_repo=InMemoryControlConfigRepository(),
        session_store=session_store,
        delivery_port=inbox,
        challenge_store=OtpChallengeStore(redis_client=fake_redis),
    )
    set_dispatcher(dispatcher)
    mount_dev_router_if_enabled(app)

    session_maker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with session_maker() as db_session:
            yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        set_simulated_inbox(None)
        get_kb_searcher.cache_clear()


@pytest.fixture
def seeded_api(
    api_client: TestClient,
    db_session: Session,
) -> Generator[tuple[TestClient, Session], None, None]:
    bundle = create_scenario_fixtures()
    staging = StagingDataset(
        customers=[
            StagingCustomer.model_validate(customer) for customer in bundle.customers
        ],
        accounts=[
            StagingAccount.model_validate(account) for account in bundle.accounts
        ],
        cards=[StagingCard.model_validate(card) for card in bundle.cards],
        transactions=[
            StagingTransaction.model_validate(transaction)
            for transaction in bundle.transactions
        ],
    )
    load_curated_data(
        staging,
        session=db_session,
        master_key=TEST_MASTER_KEY,
        blind_index_salt=TEST_BLIND_INDEX_SALT,
        force=True,
    )
    yield api_client, db_session
    db_session.rollback()
    db_session.execute(
        sa.text(
            "TRUNCATE TABLE ops.handoff, core_bank.transaction, core_bank.card, "
            "core_bank.account, core_bank.customer CASCADE"
        )
    )
    db_session.commit()


def _call_tool(
    client: TestClient,
    session_id: str,
    tool: str,
    args: dict[str, object],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    call: dict[str, object] = {"tool": tool, "version": "1.0", "args": args}
    if idempotency_key is not None:
        call["idempotency_key"] = idempotency_key
    response = client.post(
        "/v1/tools/call",
        json=call,
        headers={"X-Session-Id": session_id},
    )
    assert response.status_code == 200, response.text
    # httpx.Response.json() is dynamically typed; assertions narrow this boundary value.
    body: Any = response.json()
    assert isinstance(body, dict)
    return body


def _audit_count(session: Session, action: str, session_id: str) -> int:
    session.expire_all()
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == action, AuditLog.actor_ref == session_id)
    )


def test_catalog_tools_execute_over_http_with_scoped_audits(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_response = client.post("/v1/sessions")
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]

    kb_result = _call_tool(
        client,
        session_id,
        "kb.search",
        {"query": "bloquear tarjeta robada", "locale": "es"},
    )
    assert kb_result["status"] == "ok"
    assert kb_result["data"]["results"][0]["article_id"] == "card_block.01.es"

    anonymous_summary = _call_tool(
        client, session_id, "account.get_summary", {"include_balances": True}
    )
    anonymous_transactions = _call_tool(
        client, session_id, "transaction.list_recent", {"limit": 10}
    )
    assert anonymous_summary["status"] == "refused"
    assert anonymous_summary["reason_code"] == "STATE_NOT_ALLOWED"
    assert anonymous_transactions["status"] == "refused"
    assert anonymous_transactions["reason_code"] == "STATE_NOT_ALLOWED"

    matched = _call_tool(
        client,
        session_id,
        "customer.match",
        {
            "document_type": "NATIONAL_ID",
            "document_number": "1020304050",
            "birth_date": "1988-05-20",
        },
    )
    assert matched["status"] == "ok" and matched["data"]["matched"] is True

    document = _call_tool(
        client,
        session_id,
        "identity.verify_document",
        {
            "document_type": "NATIONAL_ID",
            "document_front_ref": "sim-approve-front-0001",
        },
    )
    assert document["status"] == "ok"
    assert document["data"]["decision"] == "APPROVED"

    sent = _call_tool(
        client,
        session_id,
        "otp.send",
        {},
        "idem_otp_send_tool_wiring_01",
    )
    assert sent["status"] == "ok"
    challenge_id = sent["data"]["challenge_id"]
    code_response = client.get(f"/v1/dev/otp/{challenge_id}")
    assert code_response.status_code == 200
    verified = _call_tool(
        client,
        session_id,
        "otp.verify",
        {"code": code_response.json()["code"]},
        "idem_otp_verify_tool_wiring_01",
    )
    assert verified["status"] == "ok" and verified["data"]["verified"] is True

    summary = _call_tool(
        client, session_id, "account.get_summary", {"include_balances": False}
    )
    assert summary["status"] == "ok"
    [account] = summary["data"]["accounts"]
    assert account["available_balance_minor"] is None
    assert account["ledger_balance_minor"] is None

    transactions = _call_tool(
        client, session_id, "transaction.list_recent", {"limit": 10}
    )
    assert transactions["status"] == "ok"
    assert len(transactions["data"]["transactions"]) == 2
    foreign_transactions = _call_tool(
        client,
        session_id,
        "transaction.list_recent",
        {"card_ref": "card_demo_pt", "limit": 10},
    )
    assert foreign_transactions["status"] == "ok"
    assert foreign_transactions["data"]["transactions"] == []

    cards = _call_tool(client, session_id, "card.list", {})
    assert cards["status"] == "ok"
    assert [card["card_ref"] for card in cards["data"]["cards"]] == ["card_demo_es"]

    foreign_block = _call_tool(
        client,
        session_id,
        "card.block",
        {"card_ref": "card_demo_pt", "reason": "LOST"},
        "idem_card_block_foreign_01",
    )
    missing_block = _call_tool(
        client,
        session_id,
        "card.block",
        {"card_ref": "card_missing_01", "reason": "LOST"},
        "idem_card_block_missing_01",
    )
    assert (
        (foreign_block["status"], foreign_block["reason_code"])
        == (
            missing_block["status"],
            missing_block["reason_code"],
        )
        == ("error", "INTERNAL_ERROR")
    )

    block_call = {
        "card_ref": "card_demo_es",
        "reason": "UNRECOGNIZED_CHARGE",
    }
    blocked = _call_tool(
        client,
        session_id,
        "card.block",
        block_call,
        "idem_card_block_tool_wiring_01",
    )
    assert blocked["status"] == "ok"
    assert blocked["data"]["receipt"]["state_before"] == "ACTIVE"
    assert blocked["data"]["receipt"]["state_after"] == "BLOCKED"
    block_audits_after_write = _audit_count(db_session, "card.block", session_id)
    replayed = _call_tool(
        client,
        session_id,
        "card.block",
        block_call,
        "idem_card_block_tool_wiring_01",
    )
    assert replayed["data"] == blocked["data"]
    assert (
        _audit_count(db_session, "card.block", session_id) == block_audits_after_write
    )

    handoff = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "DISPUTE_CLAIM",
            "summary": "Customer disputes a recent card transaction.",
            "department": "DISPUTES",
        },
        "idem_handoff_tool_wiring_01",
    )
    assert handoff["status"] == "ok"
    assert handoff["data"]["receipt"]["state_after"] == "QUEUED"

    db_session.expire_all()
    audit_rows = list(
        db_session.scalars(
            sa.select(AuditLog).where(AuditLog.action.in_(tuple(TOOL_CATALOG)))
        )
    )
    assert {row.action for row in audit_rows} == set(TOOL_CATALOG)
    for row in audit_rows:
        payload = AuditPayload.model_validate(row.payload)
        assert row.actor_ref == session_id
        assert isinstance(payload.verification_state_before, VerificationState)
        assert isinstance(payload.verification_state_after, VerificationState)
        assert payload.status in set(ToolResultStatus)
        if TOOL_CATALOG[row.action].mutates_state:
            assert payload.idempotency_scope == session_id

    blocked_row = next(
        row
        for row in audit_rows
        if row.action == "card.block" and row.decision == "allowed"
    )
    block_payload = AuditPayload.model_validate(blocked_row.payload)
    assert block_payload.card_state_before.value == "ACTIVE"
    assert block_payload.card_state_after.value == "BLOCKED"
    handoff_row = next(row for row in audit_rows if row.action == "handoff.create")
    handoff_payload = AuditPayload.model_validate(handoff_row.payload)
    assert handoff_payload.handoff_status.value == "QUEUED"
    assert handoff_payload.handoff_priority is not None


def test_handoff_failure_before_idempotency_write_rolls_back_side_effects(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_response = api_client.post("/v1/sessions")
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]

    original_add = Session.add
    fail_key_write = True

    def fail_once_for_idempotency_key(
        session: Session, instance: object, _warn: bool = True
    ) -> None:
        nonlocal fail_key_write
        if fail_key_write and isinstance(instance, IdempotencyKey):
            fail_key_write = False
            raise RuntimeError("injected idempotency persistence failure")
        original_add(session, instance, _warn=_warn)

    monkeypatch.setattr(Session, "add", fail_once_for_idempotency_key)
    call_args = {
        "reason": "CUSTOMER_REQUEST",
        "summary": "Customer requests a human agent.",
        "department": "CUSTOMER_SUPPORT",
    }
    failed = _call_tool(
        api_client,
        session_id,
        "handoff.create",
        call_args,
        "idem_handoff_retry_failure_01",
    )
    assert failed["status"] == "error"
    assert failed["reason_code"] == "INTERNAL_ERROR"

    retried = _call_tool(
        api_client,
        session_id,
        "handoff.create",
        call_args,
        "idem_handoff_retry_failure_01",
    )
    assert retried["status"] == "ok"

    db_session.expire_all()
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Handoff)) == 1
    assert (
        db_session.scalar(sa.select(sa.func.count()).select_from(IdempotencyKey)) == 1
    )
    handoff_rows = list(
        db_session.scalars(
            sa.select(AuditLog).where(
                AuditLog.action == "handoff.create",
                AuditLog.actor_ref == session_id,
            )
        )
    )
    assert len(handoff_rows) == 2
    assert {
        AuditPayload.model_validate(row.payload).status for row in handoff_rows
    } == {
        ToolResultStatus.ERROR,
        ToolResultStatus.OK,
    }


MATCH_ARGS = {
    "document_type": "NATIONAL_ID",
    "document_number": "1020304050",
    "birth_date": "1988-05-20",
}


def _identified_session(client: TestClient) -> str:
    session_id: str = client.post("/v1/sessions").json()["session_id"]
    matched = _call_tool(client, session_id, "customer.match", MATCH_ARGS)
    assert matched["data"] == {"matched": True}
    return session_id


def _otp_pending_session(client: TestClient) -> tuple[str, str]:
    session_id = _identified_session(client)
    sent = _call_tool(client, session_id, "otp.send", {}, "idem_otp_send_setup_01")
    assert sent["status"] == "ok"
    return session_id, sent["data"]["challenge_id"]


def _dev_otp(client: TestClient, challenge_id: str) -> str:
    code: str = client.get(f"/v1/dev/otp/{challenge_id}").json()["code"]
    return code


@contextmanager
def _commit_fails_once() -> Iterator[None]:
    """Make the next Session.commit raise, as an audit or idempotency write can."""
    original = Session.commit
    armed = True

    def commit(self: Session) -> None:
        nonlocal armed
        if armed:
            armed = False
            raise RuntimeError("injected commit failure")
        original(self)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(Session, "commit", commit)
        yield


def _decisions(session: Session, action: str, session_id: str) -> list[str]:
    session.expire_all()
    return list(
        session.scalars(
            sa.select(AuditLog.decision)
            .where(AuditLog.action == action, AuditLog.actor_ref == session_id)
            .order_by(AuditLog.id)
        )
    )


def _idempotency_rows(session: Session, key: str) -> int:
    session.expire_all()
    return session.scalar(
        sa.select(sa.func.count())
        .select_from(IdempotencyKey)
        .where(IdempotencyKey.key == key)
    )


def test_failed_commit_leaves_the_session_unchanged_for_customer_match(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = client.post("/v1/sessions").json()["session_id"]
    store = get_session_store()
    before = store.get(session_id)

    with _commit_fails_once():
        failed = _call_tool(client, session_id, "customer.match", MATCH_ARGS)

    assert (failed["status"], failed["reason_code"]) == ("error", "INTERNAL_ERROR")
    assert store.get(session_id) == before
    assert before is not None and before.state == VerificationState.ANONYMOUS
    assert _decisions(db_session, "customer.match", session_id) == ["error"]

    retried = _call_tool(client, session_id, "customer.match", MATCH_ARGS)
    assert retried["data"] == {"matched": True}
    stored = store.get(session_id)
    assert stored is not None and stored.state == VerificationState.IDENTIFIED


def test_failed_commit_leaves_the_session_unchanged_for_otp_send(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = _identified_session(client)
    store = get_session_store()
    before = store.get(session_id)
    key = "idem_otp_send_commit_fail"

    with _commit_fails_once():
        failed = _call_tool(client, session_id, "otp.send", {}, key)

    assert (failed["status"], failed["reason_code"]) == ("error", "INTERNAL_ERROR")
    assert store.get(session_id) == before
    assert before is not None and before.state == VerificationState.IDENTIFIED
    assert before.otp_challenge_id is None
    assert _decisions(db_session, "otp.send", session_id) == ["error"]
    assert _idempotency_rows(db_session, key) == 0

    # The same key was never consumed: the retry runs, commits, then advances.
    retried = _call_tool(client, session_id, "otp.send", {}, key)
    assert retried["status"] == "ok"
    stored = store.get(session_id)
    assert stored is not None
    assert stored.state == VerificationState.OTP_PENDING
    assert stored.otp_challenge_id == retried["data"]["challenge_id"]
    assert _idempotency_rows(db_session, key) == 1


def test_failed_commit_never_leaves_a_verified_session_without_audit(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id, challenge_id = _otp_pending_session(client)
    store = get_session_store()
    before = store.get(session_id)
    key = "idem_otp_verify_commit_fail"
    code = _dev_otp(client, challenge_id)

    with _commit_fails_once():
        failed = _call_tool(client, session_id, "otp.verify", {"code": code}, key)

    assert (failed["status"], failed["reason_code"]) == ("error", "INTERNAL_ERROR")
    stored = store.get(session_id)
    assert stored == before
    assert stored is not None and stored.state == VerificationState.OTP_PENDING
    assert _decisions(db_session, "otp.verify", session_id) == ["error"]
    assert _idempotency_rows(db_session, key) == 0


def test_failed_commit_does_not_refund_the_otp_attempt(
    seeded_api: tuple[TestClient, Session],
) -> None:
    """The attempt counter lives in Redis and is consumed before the comparison."""
    client, db_session = seeded_api
    session_id, challenge_id = _otp_pending_session(client)
    store = get_session_store()
    before = store.get(session_id)
    challenges = OtpChallengeStore(redis_client=store.client)

    with _commit_fails_once():
        failed = _call_tool(
            client,
            session_id,
            "otp.verify",
            {"code": "000000"},
            "idem_otp_verify_wrong_commit_fail",
        )

    assert failed["status"] == "error"
    assert store.get(session_id) == before
    assert before is not None and before.failed_verifies == 0
    assert challenges.evaluations(challenge_id) == 1
    assert _decisions(db_session, "otp.verify", session_id) == ["error"]


def test_session_save_failing_after_the_commit_fails_closed(
    seeded_api: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit first, save second: a failed save leaves the session where it was."""
    client, db_session = seeded_api
    session_id = _identified_session(client)
    store = get_session_store()
    before = store.get(session_id)
    key = "idem_otp_send_save_fail"

    def broken_save(*args: object, **kwargs: object) -> None:
        raise ConnectionError("redis unavailable")

    with monkeypatch.context() as patcher:
        patcher.setattr(RedisSessionStore, "save", broken_save)
        failed = _call_tool(client, session_id, "otp.send", {}, key)

    assert (failed["status"], failed["reason_code"]) == ("error", "INTERNAL_ERROR")
    assert store.get(session_id) == before
    assert before is not None and before.state == VerificationState.IDENTIFIED
    # The database side committed and says so; only the session did not advance.
    assert _decisions(db_session, "otp.send", session_id) == ["allowed", "error"]
    assert _idempotency_rows(db_session, key) == 1


def _verified_session(client: TestClient) -> str:
    session_id, challenge_id = _otp_pending_session(client)
    verified = _call_tool(
        client,
        session_id,
        "otp.verify",
        {"code": _dev_otp(client, challenge_id)},
        "idem_otp_verify_setup_01",
    )
    assert verified["data"]["verified"] is True
    return session_id


def test_idempotency_conflict_is_refused_not_an_internal_error(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = _verified_session(client)
    key = "idem_card_block_conflict_01"

    blocked = _call_tool(
        client,
        session_id,
        "card.block",
        {"card_ref": "card_demo_es", "reason": "LOST"},
        key,
    )
    assert blocked["status"] == "ok"

    conflict = _call_tool(
        client,
        session_id,
        "card.block",
        {"card_ref": "card_demo_es", "reason": "STOLEN"},
        key,
    )

    assert conflict == {
        "tool": "card.block",
        "status": "refused",
        "reason_code": "INVALID_ARGUMENTS",
        "data": None,
    }
    assert _decisions(db_session, "card.block", session_id) == ["allowed", "refused"]
    assert _idempotency_rows(db_session, key) == 1
    # The original call still replays untouched.
    replayed = _call_tool(
        client,
        session_id,
        "card.block",
        {"card_ref": "card_demo_es", "reason": "LOST"},
        key,
    )
    assert replayed["data"] == blocked["data"]


def test_repeated_handoff_returns_the_open_one_even_when_handed_off(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = _identified_session(client)
    first = _call_tool(
        client,
        session_id,
        "handoff.create",
        {"reason": "DISPUTE_CLAIM", "summary": "Customer disputes a charge."},
        "idem_handoff_first_01",
    )
    assert first["status"] == "ok"
    stored = get_session_store().get(session_id)
    assert stored is not None and stored.state == VerificationState.HANDED_OFF

    # A different key, different arguments, and now in HANDED_OFF.
    second = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "CUSTOMER_REQUEST",
            "summary": "Customer asks again for a person.",
            "priority": "URGENT",
        },
        "idem_handoff_second_01",
    )

    assert second["status"] == "ok"
    assert second["data"]["handoff_id"] == first["data"]["handoff_id"]
    assert second["data"]["priority"] == first["data"]["priority"]
    receipt = second["data"]["receipt"]
    assert (receipt["state_before"], receipt["state_after"]) == ("QUEUED", "QUEUED")
    assert receipt["audit_id"] != first["data"]["receipt"]["audit_id"]

    db_session.expire_all()
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Handoff)) == 1
    audits = list(
        db_session.scalars(
            sa.select(AuditLog)
            .where(
                AuditLog.action == "handoff.create",
                AuditLog.actor_ref == session_id,
            )
            .order_by(AuditLog.id)
        )
    )
    assert [a.decision for a in audits] == ["allowed", "allowed"]
    assert audits[1].payload["details"]["already_open"] is True
    assert audits[1].payload["verification_state_before"] == "HANDED_OFF"
    assert receipt["audit_id"] == f"aud_{audits[1].id:08d}"

    # The repeat itself replays like any other write.
    replay = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "CUSTOMER_REQUEST",
            "summary": "Customer asks again for a person.",
            "priority": "URGENT",
        },
        "idem_handoff_second_01",
    )
    assert replay["data"] == second["data"]
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Handoff)) == 1


# --- The disputed transaction and the handoff requirement (ADR-0003 amendment) ---

ES_CHARGE = str(fixture_uuid("es-demo-unrecognized-tx"))
PT_CHARGE = str(fixture_uuid("pt-demo-unrecognized-tx"))
REQUIRED_URGENT_DISPUTES = {
    "level": "REQUIRED",
    "priority": "URGENT",
    "department": "DISPUTES",
    "reason": "UNRECOGNIZED_TRANSACTION",
}
NO_REQUIREMENT = {
    "level": "NONE",
    "priority": None,
    "department": None,
    "reason": None,
}


def _set_policy(mode: str, threshold_minor: int | None = None) -> None:
    """Change the policy the test dispatcher enforces (the es customer uses COP)."""
    dispatcher = routes_tools._dispatcher
    assert dispatcher is not None
    thresholds = {"COP": threshold_minor} if threshold_minor is not None else {}
    config = PolicyConfig(
        thresholds_minor={"COP": 200000000, **thresholds},
        currency="COP",
        amount_mode=mode,  # type: ignore[arg-type]
    )
    dispatcher.config_repo.set_policy_config(config)  # type: ignore[attr-defined]


def _block(
    client: TestClient, session_id: str, key: str, **args: object
) -> dict[str, Any]:
    call = {"card_ref": "card_demo_es", "reason": "UNRECOGNIZED_CHARGE", **args}
    return _call_tool(client, session_id, "card.block", call, key)


def _remembered(session_id: str) -> dict[str, Any] | None:
    stored = get_session_store().get(session_id)
    assert stored is not None
    if stored.handoff_requirement is None:
        return None
    return stored.handoff_requirement.model_dump(mode="json")


def test_card_block_reads_the_amount_of_the_linked_transaction(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=1000)

    blocked = _block(
        client, session_id, "idem_block_amount_01", transaction_id=ES_CHARGE
    )

    assert blocked["status"] == "ok"
    assert blocked["data"]["handoff_requirement"] == REQUIRED_URGENT_DISPUTES
    # banking-core remembers it, so a later handoff cannot be pulled down.
    assert _remembered(session_id) == REQUIRED_URGENT_DISPUTES

    handoff = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "CUSTOMER_REQUEST",
            "summary": "Customer wants a person to look at the charge.",
            "priority": "LOW",
            "department": "CUSTOMER_SUPPORT",
            "transaction_id": ES_CHARGE,
        },
        "idem_handoff_amount_01",
    )

    assert handoff["status"] == "ok"
    assert handoff["data"]["priority"] == "URGENT"
    assert handoff["data"]["department"] == "DISPUTES"
    db_session.expire_all()
    [row] = db_session.scalars(sa.select(Handoff)).all()
    assert (row.priority, row.department) == ("URGENT", "DISPUTES")
    facts = row.summary["verified_facts"]["disputed_transaction"]
    assert facts["transaction_id"] == ES_CHARGE
    assert (facts["amount_minor"], facts["currency"]) == (35000000, "COP")
    assert facts["merchant"] == "Global Electronics Megastore"
    assert facts["card_masked"] == "**** **** **** 1050"
    assert "posted_at" in facts


def test_a_charge_under_the_threshold_leaves_the_case_automated(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, _ = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=40000000)  # the charge is 35,000,000

    blocked = _block(
        client, session_id, "idem_block_under_01", transaction_id=ES_CHARGE
    )

    assert blocked["status"] == "ok"
    assert blocked["data"]["handoff_requirement"] == NO_REQUIREMENT
    assert _remembered(session_id) is None


def test_flag_mode_recommends_and_the_handoff_gets_the_normal_floor(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, _ = seeded_api
    session_id = _verified_session(client)
    _set_policy("flag", threshold_minor=1000)

    blocked = _block(client, session_id, "idem_block_flag_01", transaction_id=ES_CHARGE)

    assert blocked["data"]["handoff_requirement"] == {
        **REQUIRED_URGENT_DISPUTES,
        "level": "RECOMMENDED",
        "priority": "NORMAL",
    }
    handoff = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "DISPUTE_CLAIM",
            "summary": "Customer asks for a person.",
            "priority": "LOW",
        },
        "idem_handoff_flag_01",
    )
    assert (handoff["data"]["priority"], handoff["data"]["department"]) == (
        "NORMAL",
        "DISPUTES",
    )


def test_a_dispute_reason_without_a_linked_charge_fails_safe(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, _ = seeded_api
    session_id = _verified_session(client)

    blocked = _block(client, session_id, "idem_block_nolink_01")

    assert blocked["data"]["handoff_requirement"] == REQUIRED_URGENT_DISPUTES
    assert _remembered(session_id) == REQUIRED_URGENT_DISPUTES


@pytest.mark.parametrize(
    "extra_args",
    [
        {"amount_minor": 1},
        {"disputed_amount_minor": 1, "currency": "COP"},
        {"transaction_id": 12345678},
    ],
    ids=["amount", "amount-and-currency", "non-string-transaction"],
)
def test_card_block_accepts_no_amount_and_no_odd_transaction_id(
    seeded_api: tuple[TestClient, Session], extra_args: dict[str, object]
) -> None:
    """There is no amount argument: the contract rejects the call before any policy."""
    client, db_session = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=1000)

    response = client.post(
        "/v1/tools/call",
        json={
            "tool": "card.block",
            "version": "1.0",
            "args": {"card_ref": "card_demo_es", "reason": "LOST", **extra_args},
            "idempotency_key": "idem_block_argamount_01",
        },
        headers={"X-Session-Id": session_id},
    )

    assert response.status_code == 422
    db_session.expire_all()
    card = db_session.scalar(sa.select(Card).where(Card.card_ref == "card_demo_es"))
    assert card is not None and card.status == "ACTIVE"
    assert _remembered(session_id) is None


def test_a_weaker_requirement_never_replaces_the_remembered_one(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, _ = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=1000)
    _block(client, session_id, "idem_block_strong_01", transaction_id=ES_CHARGE)

    # The same card again for a reason with no charge to compare: NONE.
    again = _block(client, session_id, "idem_block_weak_01", reason="LOST")

    assert again["data"]["handoff_requirement"] == NO_REQUIREMENT
    assert _remembered(session_id) == REQUIRED_URGENT_DISPUTES


def test_a_failed_session_save_is_finished_by_the_replay(
    seeded_api: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit first, save second: the retry of the same call remembers it."""
    client, db_session = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=1000)
    key = "idem_block_save_fail_01"

    def broken_save(*args: object, **kwargs: object) -> None:
        raise ConnectionError("redis unavailable")

    with monkeypatch.context() as patcher:
        patcher.setattr(RedisSessionStore, "save", broken_save)
        failed = _block(client, session_id, key, transaction_id=ES_CHARGE)

    assert (failed["status"], failed["reason_code"]) == ("error", "INTERNAL_ERROR")
    assert _remembered(session_id) is None
    assert _idempotency_rows(db_session, key) == 1

    replayed = _block(client, session_id, key, transaction_id=ES_CHARGE)

    assert replayed["status"] == "ok"
    assert replayed["data"]["handoff_requirement"] == REQUIRED_URGENT_DISPUTES
    assert _remembered(session_id) == REQUIRED_URGENT_DISPUTES


@pytest.mark.parametrize(
    "transaction_id",
    [
        PT_CHARGE,  # someone else's
        str(uuid.uuid4()),  # does not exist
        "not-a-uuid-at-all",
        "x" * 64,
    ],
    ids=["foreign", "missing", "malformed", "long"],
)
def test_a_transaction_that_does_not_resolve_is_refused_the_same_way(
    seeded_api: tuple[TestClient, Session], transaction_id: object
) -> None:
    client, db_session = seeded_api
    session_id = _verified_session(client)
    _set_policy("block", threshold_minor=1000)

    blocked = _block(
        client, session_id, "idem_block_bad_tx_01", transaction_id=transaction_id
    )
    handoff = _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "DISPUTE_CLAIM",
            "summary": "Customer disputes a charge.",
            "transaction_id": transaction_id,
        },
        "idem_handoff_bad_tx_01",
    )

    for result, tool in ((blocked, "card.block"), (handoff, "handoff.create")):
        assert result == {
            "tool": tool,
            "status": "refused",
            "reason_code": "INVALID_ARGUMENTS",
            "data": None,
        }
    # Nothing happened, and every refusal is audited with the same reason.
    db_session.expire_all()
    card = db_session.scalar(sa.select(Card).where(Card.card_ref == "card_demo_es"))
    assert card is not None and card.status == "ACTIVE"
    assert db_session.scalars(sa.select(Handoff)).all() == []
    assert _idempotency_rows(db_session, "idem_block_bad_tx_01") == 0
    assert _idempotency_rows(db_session, "idem_handoff_bad_tx_01") == 0
    refusals = db_session.scalars(
        sa.select(AuditLog).where(
            AuditLog.actor_ref == session_id, AuditLog.decision == "refused"
        )
    ).all()
    assert {(row.action, row.reason_code) for row in refusals} == {
        ("card.block", "INVALID_ARGUMENTS"),
        ("handoff.create", "INVALID_ARGUMENTS"),
    }
    assert {row.payload["reason"] for row in refusals} == {
        "disputed_transaction_not_resolved"
    }
    assert get_session_store().get(session_id).state == VerificationState.VERIFIED  # type: ignore[union-attr]


def test_a_foreign_and_a_missing_transaction_cannot_be_told_apart(
    seeded_api: tuple[TestClient, Session],
) -> None:
    client, db_session = seeded_api
    session_id = _verified_session(client)
    responses = [
        _block(client, session_id, f"idem_block_probe_{n}", transaction_id=tx)
        for n, tx in enumerate((PT_CHARGE, str(uuid.uuid4())))
    ]

    assert responses[0] == responses[1]
    db_session.expire_all()
    payloads = [
        (row.reason_code, row.payload["reason"], row.payload["details"])
        for row in db_session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.actor_ref == session_id, AuditLog.action == "card.block")
            .order_by(AuditLog.id)
        )
    ]
    assert payloads[0] == payloads[1]


def _handoff_with_transaction(
    client: TestClient, session_id: str, transaction_id: str, key: str
) -> dict[str, Any]:
    return _call_tool(
        client,
        session_id,
        "handoff.create",
        {
            "reason": "CUSTOMER_REQUEST",
            "summary": "Customer asks for a person.",
            "transaction_id": transaction_id,
        },
        key,
    )


def test_a_handoff_outside_a_verified_session_attaches_no_charge(
    seeded_api: tuple[TestClient, Session],
) -> None:
    """Attaching a charge reads customer data: only a verified session gets it.

    The id is dropped, not refused (an escalation is never held up), and an own,
    a foreign and a missing id are answered alike, so nothing is confirmed.
    """
    client, db_session = seeded_api
    unverified = [
        client.post("/v1/sessions").json()["session_id"],  # no holder yet
        _identified_session(client),  # holder claimed, no OTP
        _identified_session(client),
        _identified_session(client),
    ]
    ids = [ES_CHARGE, ES_CHARGE, PT_CHARGE, str(uuid.uuid4())]

    results = [
        _handoff_with_transaction(client, session_id, tx, f"idem_handoff_unv_{n}")
        for n, (session_id, tx) in enumerate(zip(unverified, ids, strict=True))
    ]

    for result in results:
        assert result["status"] == "ok"
        assert "disputed_transaction" not in result["data"]["summary"]["verified_facts"]
    db_session.expire_all()
    rows = db_session.scalars(sa.select(Handoff)).all()
    assert len(rows) == 4
    assert all("disputed_transaction" not in r.summary["verified_facts"] for r in rows)
    audits = db_session.scalars(
        sa.select(AuditLog).where(AuditLog.action == "handoff.create")
    ).all()
    assert all("transaction_id" not in a.payload["details"] for a in audits)


def test_card_block_state_is_checked_before_any_transaction_lookup(
    seeded_api: tuple[TestClient, Session],
) -> None:
    """An identified customer's own, a foreign and a missing charge look alike."""
    client, db_session = seeded_api
    session_id = _identified_session(client)

    results = [
        _block(client, session_id, f"idem_block_state_{n}", transaction_id=tx)
        for n, tx in enumerate((ES_CHARGE, PT_CHARGE, str(uuid.uuid4())))
    ]

    for result in results:
        assert (result["status"], result["reason_code"]) == (
            "refused",
            "STATE_NOT_ALLOWED",
        )
    db_session.expire_all()
    card = db_session.scalar(sa.select(Card).where(Card.card_ref == "card_demo_es"))
    assert card is not None and card.status == "ACTIVE"
