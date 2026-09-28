from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import fakeredis
import pytest
import sqlalchemy as sa
from banking_core.api.dispatcher import ToolDispatcher
from banking_core.api.routes_sessions import get_session_store, set_session_store
from banking_core.api.routes_tools import set_dispatcher
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.session import RedisSessionStore
from banking_core.db import get_db
from banking_core.identity import OtpChallengeStore, get_dev_sink
from banking_core.knowledge.tools.kb_search import get_kb_searcher
from banking_core.main import app, mount_dev_router_if_enabled
from banking_core.models.ops import AuditLog, Handoff, IdempotencyKey
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import create_scenario_fixtures
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
    dev_sink = get_dev_sink()
    dev_sink.clear()
    dispatcher = ToolDispatcher(
        config_repo=InMemoryControlConfigRepository(),
        session_store=session_store,
        delivery_port=dev_sink,
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
        dev_sink.clear()
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
            "document_front_ref": "card_front_12345",
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
