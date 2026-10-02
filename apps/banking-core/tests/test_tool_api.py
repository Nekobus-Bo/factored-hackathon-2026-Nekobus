"""Integration and unit tests for banking-core HTTP tool API (task 2B-3a).

Covers:
- POST /v1/sessions -> opaque session_id
- POST /v1/tools/call dispatcher with X-Session-Id header
- Full FSM progression: ANONYMOUS -> IDENTIFIED -> OTP_PENDING -> VERIFIED over HTTP
- Authorizer state checks (refusal with STATE_NOT_ALLOWED)
- Idempotency replay with identical receipt without second execution
- Audit rows recording verification_state_before and verification_state_after
- Document type equivalence: TAX_ID == NATIONAL_ID for pt market
- Sentinel NONE for registered_otp_channel -> refused POLICY_BLOCKED
- IDOR argument injection rejection
- Dev OTP hook permissions (403 when disabled)
- Indistinguishable non-match responses
- Hardening: per-session lock + atomic OTP counter under concurrency, no per-IP
  limit (X-Forwarded-For ignored), no salt fallback, hashed OTP, SESSION_BUSY,
  and a decrypt spent on customer.match misses
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from banking_core.api import routes_sessions
from banking_core.api.dispatcher import ToolDispatcher
from banking_core.api.routes_sessions import get_session_store, set_session_store
from banking_core.api.routes_tools import (
    set_dispatcher,
)
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.policy import PolicyConfig
from banking_core.control.session import RedisSessionStore
from banking_core.crypto import RecordEncryptor, compute_blind_index
from banking_core.db import get_db
from banking_core.identity import (
    OtpChallengeStore,
    SimulatedInbox,
    set_simulated_inbox,
)
from banking_core.main import app, mount_dev_router_if_enabled
from banking_core.models.core_bank import Customer
from banking_core.models.ops import AuditLog, IdempotencyKey
from contracts.envelope import (
    VerificationState,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_MASTER_KEY = "00" * 32
TEST_SALT = "test-salt-secret-12345"


class MockDbSession:
    """Mock SQLAlchemy Session maintaining in-memory audit log and customer records."""

    def __init__(self, customers: list[Customer] | None = None) -> None:
        self.customers: list[Customer] = customers or []
        self.audit_logs: list[AuditLog] = []
        self.idempotency_keys: list[IdempotencyKey] = []
        self._next_id = 1

    def get_bind(self) -> Any:
        return None

    def get(self, entity_class: Any, pk: Any) -> Any:
        if entity_class == Customer:
            for c in self.customers:
                if str(c.id) == str(pk) or c.id == pk:
                    return c
        return None

    def scalars(self, stmt: Any) -> Any:
        # Mock execution for customer select with bind parameter filtering
        try:
            params = stmt.compile().params
            doc_type = None
            doc_bidx = None
            for k, v in params.items():
                if "document_type" in k:
                    doc_type = v
                elif "document_number_bidx" in k:
                    doc_bidx = v
            results = []
            for c in self.customers:
                if doc_type is not None and c.document_type != doc_type:
                    continue
                if doc_bidx is not None and c.document_number_bidx != doc_bidx:
                    continue
                results.append(c)
        except Exception:
            results = list(self.customers)
        mock_result = MagicMock()
        mock_result.all.return_value = results
        return mock_result

    def scalar(self, stmt: Any) -> Any:
        # Check target model from statement
        try:
            col_desc = stmt.column_descriptions[0]
            target = col_desc.get("type") or col_desc.get("entity")
        except Exception:
            target = None

        is_audit = target == AuditLog or (
            target and getattr(target, "__name__", "") == "AuditLog"
        )
        if is_audit:
            return self.audit_logs[-1] if self.audit_logs else None

        if target == IdempotencyKey or (
            target and getattr(target, "__name__", "") == "IdempotencyKey"
        ):
            # Check for matching scoped_key if in parameters
            try:
                params = stmt.compile().params
                scoped_key = None
                for k, v in params.items():
                    if "scoped_key" in k:
                        scoped_key = v
                        break
                if scoped_key:
                    for item in self.idempotency_keys:
                        if item.scoped_key == scoped_key:
                            return item
            except Exception:
                pass
            return None

        return None

    def add(self, obj: Any) -> None:
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = self._next_id
            self._next_id += 1
        if isinstance(obj, AuditLog):
            self.audit_logs.append(obj)
        elif isinstance(obj, IdempotencyKey):
            self.idempotency_keys.append(obj)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _create_test_customers() -> list[Customer]:
    """Create test customers (es, pt, and pt_no_channel)."""
    now = datetime.now(UTC)
    custs = []

    # 1. Customer ES (Carlos Gomez, 1020304050, NATIONAL_ID)
    es_id = uuid.uuid4()
    es_enc = RecordEncryptor("core_bank", "customer", es_id, TEST_MASTER_KEY)
    custs.append(
        Customer(
            id=es_id,
            document_type="NATIONAL_ID",
            document_number_enc=es_enc.encrypt("document_number_enc", "1020304050"),
            document_number_bidx=compute_blind_index(
                "1020304050", "document_number", TEST_SALT, document_type="NATIONAL_ID"
            ),
            full_name_enc=es_enc.encrypt("full_name_enc", "Carlos Gomez"),
            email_enc=es_enc.encrypt("email_enc", "carlos@example.com"),
            email_bidx=compute_blind_index("carlos@example.com", "email", TEST_SALT),
            phone_enc=es_enc.encrypt("phone_enc", "+573001234567"),
            phone_bidx=compute_blind_index("+573001234567", "phone", TEST_SALT),
            birth_date_enc=es_enc.encrypt("birth_date_enc", "1985-05-15"),
            preferred_locale="es",
            registered_otp_channel="SMS",
            data_origin="synthetic",
            created_at=now,
            loaded_at=now,
        )
    )

    # 2. Customer PT (Mariana Silva, 12345678900, stored as NATIONAL_ID)
    pt_id = uuid.uuid4()
    pt_enc = RecordEncryptor("core_bank", "customer", pt_id, TEST_MASTER_KEY)
    custs.append(
        Customer(
            id=pt_id,
            document_type="NATIONAL_ID",
            document_number_enc=pt_enc.encrypt("document_number_enc", "12345678900"),
            document_number_bidx=compute_blind_index(
                "12345678900", "document_number", TEST_SALT, document_type="NATIONAL_ID"
            ),
            full_name_enc=pt_enc.encrypt("full_name_enc", "Mariana Silva"),
            email_enc=pt_enc.encrypt("email_enc", "mariana@example.com"),
            email_bidx=compute_blind_index("mariana@example.com", "email", TEST_SALT),
            phone_enc=pt_enc.encrypt("phone_enc", "+5511987654321"),
            phone_bidx=compute_blind_index("+5511987654321", "phone", TEST_SALT),
            birth_date_enc=pt_enc.encrypt("birth_date_enc", "1990-10-20"),
            preferred_locale="pt",
            registered_otp_channel="SMS",
            data_origin="synthetic",
            created_at=now,
            loaded_at=now,
        )
    )

    # 3. Customer PT without OTP channel (registered_otp_channel = "NONE")
    no_otp_id = uuid.uuid4()
    no_otp_enc = RecordEncryptor("core_bank", "customer", no_otp_id, TEST_MASTER_KEY)
    custs.append(
        Customer(
            id=no_otp_id,
            document_type="NATIONAL_ID",
            document_number_enc=no_otp_enc.encrypt(
                "document_number_enc", "98765432199"
            ),
            document_number_bidx=compute_blind_index(
                "98765432199", "document_number", TEST_SALT, document_type="NATIONAL_ID"
            ),
            full_name_enc=no_otp_enc.encrypt("full_name_enc", "Lucas Oliveira"),
            email_enc=no_otp_enc.encrypt("email_enc", "lucas@example.com"),
            email_bidx=compute_blind_index("lucas@example.com", "email", TEST_SALT),
            phone_enc=no_otp_enc.encrypt("phone_enc", "+5511911112222"),
            phone_bidx=compute_blind_index("+5511911112222", "phone", TEST_SALT),
            birth_date_enc=no_otp_enc.encrypt("birth_date_enc", "1992-02-14"),
            preferred_locale="pt",
            registered_otp_channel="NONE",
            data_origin="synthetic",
            created_at=now,
            loaded_at=now,
        )
    )
    return custs


@pytest.fixture
def test_setup(monkeypatch: pytest.MonkeyPatch):
    """Setup in-memory dependencies and client for HTTP tool API tests."""
    monkeypatch.setenv("MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("BLIND_INDEX_SALT", TEST_SALT)
    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "true")
    mount_dev_router_if_enabled(app)

    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    session_store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
    set_session_store(session_store)

    mock_db = MockDbSession(customers=_create_test_customers())

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_store] = lambda: session_store

    from banking_core.api.dispatcher import ToolDispatcher

    inbox = SimulatedInbox(redis_client=fake_redis)
    set_simulated_inbox(inbox)
    challenge_store = OtpChallengeStore(redis_client=fake_redis)
    dispatcher = ToolDispatcher(
        config_repo=InMemoryControlConfigRepository(),
        session_store=session_store,
        delivery_port=inbox,
        challenge_store=challenge_store,
    )
    set_dispatcher(dispatcher)

    client = TestClient(app)
    yield client, mock_db, session_store, inbox
    app.dependency_overrides.clear()
    set_simulated_inbox(None)


def test_session_creation(test_setup) -> None:
    """Test POST /v1/sessions returns opaque session ID and ANONYMOUS state."""
    client, _, session_store, _ = test_setup
    resp = client.post("/v1/sessions")
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    session_id = data["session_id"]
    assert session_id.startswith("sess_")

    stored = session_store.get(session_id)
    assert stored is not None
    assert stored.state == VerificationState.ANONYMOUS
    assert stored.pinned_holder_id is None


def test_missing_or_invalid_session_id(test_setup) -> None:
    """Test /v1/tools/call requires valid X-Session-Id header."""
    client, _, _, _ = test_setup
    call_payload = {
        "tool": "customer.match",
        "version": "1.0",
        "args": {
            "document_type": "NATIONAL_ID",
            "document_number": "1020304050",
        },
    }

    # Missing header -> 400 Bad Request
    resp1 = client.post("/v1/tools/call", json=call_payload)
    assert resp1.status_code == 400
    assert "Missing required 'X-Session-Id' header" in resp1.json()["detail"]

    # Unknown session -> 404 Not Found
    resp2 = client.post(
        "/v1/tools/call",
        json=call_payload,
        headers={"X-Session-Id": "sess_nonexistent_123"},
    )
    assert resp2.status_code == 404
    assert "not found or expired" in resp2.json()["detail"]


def test_full_fsm_lifecycle_http(test_setup) -> None:
    """Prove ANONYMOUS -> IDENTIFIED -> OTP_PENDING -> VERIFIED over HTTP.

    Also verifies:
    - verification_state_before recorded in audit row
    - receipts generated on mutating steps
    - Model response does NOT leak audit fields
    """
    client, mock_db, session_store, inbox = test_setup

    # 1. Create session -> ANONYMOUS
    sess_resp = client.post("/v1/sessions")
    session_id = sess_resp.json()["session_id"]
    headers = {"X-Session-Id": session_id}

    # 2. customer.match -> transitions to IDENTIFIED
    match_payload = {
        "tool": "customer.match",
        "version": "1.0",
        "args": {
            "document_type": "NATIONAL_ID",
            "document_number": "1020304050",
        },
    }
    match_resp = client.post("/v1/tools/call", json=match_payload, headers=headers)
    assert match_resp.status_code == 200
    res_match = match_resp.json()
    assert res_match["tool"] == "customer.match"
    assert res_match["status"] == "ok"
    assert res_match["data"] == {"matched": True}
    assert "verification_state_before" not in res_match

    # Verify session transitioned to IDENTIFIED and pinned holder
    sess_after_match = session_store.get(session_id)
    assert sess_after_match.state == VerificationState.IDENTIFIED
    assert sess_after_match.pinned_holder_id is not None

    # Verify audit row
    last_audit = mock_db.audit_logs[-1]
    assert last_audit.action == "customer.match"
    assert last_audit.decision == "allowed"
    assert last_audit.payload["verification_state_before"] == "ANONYMOUS"
    assert last_audit.payload["verification_state_after"] == "IDENTIFIED"
    assert last_audit.payload["details"]["matched"] is True

    # 3. otp.send -> transitions to OTP_PENDING
    send_payload = {
        "tool": "otp.send",
        "version": "1.0",
        "args": {},
        "idempotency_key": "idem_otp_send_001",
    }
    send_resp = client.post("/v1/tools/call", json=send_payload, headers=headers)
    assert send_resp.status_code == 200
    res_send = send_resp.json()
    assert res_send["tool"] == "otp.send"
    assert res_send["status"] == "ok"
    assert res_send["data"]["sent"] is True
    assert res_send["data"]["channel"] == "SMS"
    assert res_send["data"]["destination_masked"] == "+57 *** *** 4567"
    challenge_id = res_send["data"]["challenge_id"]
    assert challenge_id.startswith("chal_")

    # Receipt verification
    receipt = res_send["data"]["receipt"]
    assert receipt["action"] == "otp.send"
    assert receipt["target_masked"] == "+57 *** *** 4567"
    assert receipt["state_before"] == "IDENTIFIED"
    assert receipt["state_after"] == "OTP_PENDING"

    # Verify session transitioned to OTP_PENDING
    sess_after_send = session_store.get(session_id)
    assert sess_after_send.state == VerificationState.OTP_PENDING
    assert sess_after_send.otp_challenge_id == challenge_id

    # Verify audit row
    send_audit = mock_db.audit_logs[-1]
    assert send_audit.action == "otp.send"
    assert send_audit.payload["verification_state_before"] == "IDENTIFIED"
    assert send_audit.payload["verification_state_after"] == "OTP_PENDING"

    # 4. Fetch the delivered code from the session's simulated inbox
    [message] = inbox.messages(session_id)
    assert message.challenge_id == challenge_id
    code = inbox.get_code(challenge_id)
    assert code == message.code
    assert code is not None
    assert len(code) == 6

    # 5. otp.verify -> transitions to VERIFIED
    verify_payload = {
        "tool": "otp.verify",
        "version": "1.0",
        "args": {"code": code},
        "idempotency_key": "idem_otp_verify_001",
    }
    verify_resp = client.post("/v1/tools/call", json=verify_payload, headers=headers)
    assert verify_resp.status_code == 200
    res_verify = verify_resp.json()
    assert res_verify["tool"] == "otp.verify"
    assert res_verify["status"] == "ok"
    assert res_verify["data"]["verified"] is True
    assert res_verify["data"]["state"] == "VERIFIED"

    # Verify receipt
    v_receipt = res_verify["data"]["receipt"]
    assert v_receipt["action"] == "otp.verify"
    assert v_receipt["state_before"] == "OTP_PENDING"
    assert v_receipt["state_after"] == "VERIFIED"

    # Verify session is VERIFIED
    sess_after_verify = session_store.get(session_id)
    assert sess_after_verify.state == VerificationState.VERIFIED
    assert sess_after_verify.otp_challenge_id is None

    # Verify audit row
    verify_audit = mock_db.audit_logs[-1]
    assert verify_audit.action == "otp.verify"
    assert verify_audit.payload["verification_state_before"] == "OTP_PENDING"
    assert verify_audit.payload["verification_state_after"] == "VERIFIED"


def test_the_simulated_inbox_serves_the_code_only_to_the_session_that_asked(
    test_setup, caplog: pytest.LogCaptureFixture
) -> None:
    """otp.send -> inbox endpoint -> otp.verify; the code goes nowhere else."""
    client, mock_db, _, inbox = test_setup

    def call(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = client.post(
            "/v1/tools/call", json=payload, headers={"X-Session-Id": session_id}
        )
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        return body

    mine = client.post("/v1/sessions").json()["session_id"]
    other = client.post("/v1/sessions").json()["session_id"]
    assert call(
        mine,
        {
            "tool": "customer.match",
            "args": {"document_type": "NATIONAL_ID", "document_number": "1020304050"},
        },
    )["data"] == {"matched": True}
    with caplog.at_level(logging.DEBUG):
        sent = call(
            mine,
            {"tool": "otp.send", "args": {}, "idempotency_key": "idem_inbox_send_01"},
        )
    challenge_id = sent["data"]["challenge_id"]

    listing = client.get(f"/v1/sessions/{mine}/simulated-inbox").json()

    [message] = listing["messages"]
    code = message["code"]
    assert re.fullmatch(r"\d{6}", code)
    assert message["challenge_id"] == challenge_id
    assert message["channel"] == sent["data"]["channel"]
    assert message["destination_masked"] == sent["data"]["destination_masked"]
    assert client.get(f"/v1/sessions/{other}/simulated-inbox").json() == {
        "messages": []
    }

    # The code is nowhere the model, the logs or the audit trail could see it.
    assert code not in json.dumps(sent)
    assert code not in caplog.text
    assert all(code not in json.dumps(row.payload) for row in mock_db.audit_logs)

    verified = call(
        mine,
        {
            "tool": "otp.verify",
            "args": {"code": code},
            "idempotency_key": "idem_inbox_verify_01",
        },
    )
    assert verified["data"]["verified"] is True
    assert code not in json.dumps(verified)
    assert all(code not in json.dumps(row.payload) for row in mock_db.audit_logs)


def test_tool_outside_allowed_states_is_refused(test_setup) -> None:
    """Verify authorizer refuses tools outside their permitted states."""
    client, mock_db, _, _ = test_setup

    # Create session (starts in ANONYMOUS)
    sess_resp = client.post("/v1/sessions")
    headers = {"X-Session-Id": sess_resp.json()["session_id"]}

    # 1. Calling otp.send in ANONYMOUS is refused
    resp1 = client.post(
        "/v1/tools/call",
        json={
            "tool": "otp.send",
            "version": "1.0",
            "args": {},
            "idempotency_key": "idem_send_unauth_1",
        },
        headers=headers,
    )
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["status"] == "refused"
    assert res1["reason_code"] == "STATE_NOT_ALLOWED"
    assert res1["data"] is None

    # Verify audit row records refused call with verification_state_before
    audit1 = mock_db.audit_logs[-1]
    assert audit1.action == "otp.send"
    assert audit1.decision == "refused"
    assert audit1.reason_code == "STATE_NOT_ALLOWED"
    assert audit1.payload["verification_state_before"] == "ANONYMOUS"
    assert audit1.payload["verification_state_after"] == "ANONYMOUS"

    # 2. Calling otp.verify in ANONYMOUS is refused
    resp2 = client.post(
        "/v1/tools/call",
        json={
            "tool": "otp.verify",
            "version": "1.0",
            "args": {"code": "123456"},
            "idempotency_key": "idem_verify_unauth_1",
        },
        headers=headers,
    )
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["status"] == "refused"
    assert res2["reason_code"] == "STATE_NOT_ALLOWED"

    # 3. Calling identity.verify_document in ANONYMOUS is refused
    resp3 = client.post(
        "/v1/tools/call",
        json={
            "tool": "identity.verify_document",
            "version": "1.0",
            "args": {
                "document_type": "NATIONAL_ID",
                "document_front_ref": "card_front_12345",
            },
        },
        headers=headers,
    )
    assert resp3.status_code == 200
    res3 = resp3.json()
    assert res3["status"] == "refused"
    assert res3["reason_code"] == "STATE_NOT_ALLOWED"


def test_idempotency_replay_identical_receipt(test_setup) -> None:
    """Verify replaying idempotency key returns same receipt without re-execution."""
    client, mock_db, _, inbox = test_setup

    # Setup session in IDENTIFIED state
    sess_resp = client.post("/v1/sessions")
    headers = {"X-Session-Id": sess_resp.json()["session_id"]}

    client.post(
        "/v1/tools/call",
        json={
            "tool": "customer.match",
            "version": "1.0",
            "args": {
                "document_type": "NATIONAL_ID",
                "document_number": "1020304050",
            },
        },
        headers=headers,
    )

    send_payload = {
        "tool": "otp.send",
        "version": "1.0",
        "args": {},
        "idempotency_key": "idem_replay_test_key_001",
    }

    # First call: executes tool
    resp1 = client.post("/v1/tools/call", json=send_payload, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()["data"]
    chal_id1 = data1["challenge_id"]
    receipt1 = data1["receipt"]

    audit_count_after_first = len(mock_db.audit_logs)

    # Second call (replay with same idempotency_key): returns cached receipt
    resp2 = client.post("/v1/tools/call", json=send_payload, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]

    # Output matches identically
    assert data1 == data2
    assert data2["challenge_id"] == chal_id1
    assert data2["receipt"] == receipt1

    # A replay returns the original result without a second tool audit row.
    assert len(mock_db.audit_logs) == audit_count_after_first


def test_pt_market_tax_id_equivalence(test_setup) -> None:
    """Test TAX_ID == NATIONAL_ID equivalence for the pt market."""
    client, _, session_store, _ = test_setup

    # Create session
    sess_resp = client.post("/v1/sessions")
    session_id = sess_resp.json()["session_id"]
    headers = {"X-Session-Id": session_id}

    # Customer in DB stored with document_type="NATIONAL_ID", number="12345678900".
    # Caller sends document_type="TAX_ID" (common for Portuguese "Meu CPF é...").
    match_payload = {
        "tool": "customer.match",
        "version": "1.0",
        "args": {
            "document_type": "TAX_ID",
            "document_number": "12345678900",
        },
    }
    resp = client.post("/v1/tools/call", json=match_payload, headers=headers)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "ok"
    assert res["data"] == {"matched": True}

    # Session transitions to IDENTIFIED
    sess = session_store.get(session_id)
    assert sess.state == VerificationState.IDENTIFIED
    assert sess.pinned_holder_id is not None

    # Indistinguishable output for non-existent document
    sess_resp2 = client.post("/v1/sessions")
    headers2 = {"X-Session-Id": sess_resp2.json()["session_id"]}
    nomatch_payload = {
        "tool": "customer.match",
        "version": "1.0",
        "args": {
            "document_type": "TAX_ID",
            "document_number": "99999999999",
        },
    }
    resp_nomatch = client.post("/v1/tools/call", json=nomatch_payload, headers=headers2)
    assert resp_nomatch.status_code == 200
    assert resp_nomatch.json()["data"] == {"matched": False}


def test_no_registered_otp_channel_handoff(test_setup) -> None:
    """Test customer with registered_otp_channel='NONE' triggers POLICY_BLOCKED."""
    client, mock_db, _, _ = test_setup

    sess_resp = client.post("/v1/sessions")
    headers = {"X-Session-Id": sess_resp.json()["session_id"]}

    # Match customer who has registered_otp_channel="NONE"
    client.post(
        "/v1/tools/call",
        json={
            "tool": "customer.match",
            "version": "1.0",
            "args": {
                "document_type": "NATIONAL_ID",
                "document_number": "98765432199",
            },
        },
        headers=headers,
    )

    # Calling otp.send must refuse with POLICY_BLOCKED
    resp = client.post(
        "/v1/tools/call",
        json={
            "tool": "otp.send",
            "version": "1.0",
            "args": {},
            "idempotency_key": "idem_no_otp_channel_1",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "refused"
    assert res["reason_code"] == "POLICY_BLOCKED"
    assert res["data"] is None

    # Verify audit row
    last_audit = mock_db.audit_logs[-1]
    assert last_audit.action == "otp.send"
    assert last_audit.decision == "refused"
    assert last_audit.reason_code == "POLICY_BLOCKED"


def test_idor_argument_tampering_rejected(test_setup) -> None:
    """Verify tool calls attempting to inject customer_id or holder_id are rejected."""
    client, _, _, _ = test_setup

    sess_resp = client.post("/v1/sessions")
    headers = {"X-Session-Id": sess_resp.json()["session_id"]}

    # Attempt to inject customer_id in arguments
    malicious_call = {
        "tool": "customer.match",
        "version": "1.0",
        "args": {
            "document_type": "NATIONAL_ID",
            "document_number": "1020304050",
            "customer_id": "00000000-0000-0000-0000-000000000000",
        },
    }
    # Contracts input_model rejects extra arguments (extra='forbid')
    # and dispatcher additionally enforces validate_no_holder_tampering
    resp = client.post("/v1/tools/call", json=malicious_call, headers=headers)
    assert resp.status_code == 422 or resp.json().get("status") == "refused"


def test_dev_otp_router_is_mounted_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = SimulatedInbox(redis_client=fakeredis.FakeRedis(decode_responses=True))
    set_simulated_inbox(inbox)
    inbox.deliver(
        session_id="sess_hook_1",
        challenge_id="chal_hook_1",
        channel="EMAIL",
        destination_masked="a***@example.com",
        code="654321",
        ttl_seconds=300,
    )

    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "false")
    disabled_app = FastAPI()
    mount_dev_router_if_enabled(disabled_app)
    assert not any(
        getattr(route, "path", None) == "/v1/dev/otp/{challenge_id}"
        for route in disabled_app.routes
    )

    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "true")
    enabled_app = FastAPI()
    mount_dev_router_if_enabled(enabled_app)
    try:
        with TestClient(enabled_app) as client:
            response = client.get("/v1/dev/otp/chal_hook_1")
    finally:
        set_simulated_inbox(None)

    assert response.status_code == 200
    assert response.json()["code"] == "654321"


@pytest.mark.parametrize("app_env", ["production", "Production", "  PRODUCTION "])
def test_dev_otp_hook_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "true")
    monkeypatch.setenv("APP_ENV", app_env)
    application = FastAPI()

    with pytest.raises(RuntimeError, match="ALLOW_DEV_OTP_HOOK"):
        mount_dev_router_if_enabled(application)

    assert not any(
        getattr(route, "path", None) == "/v1/dev/otp/{challenge_id}"
        for route in application.routes
    )


def test_dev_otp_hook_off_in_production_starts_and_stays_unmounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_DEV_OTP_HOOK", "false")
    monkeypatch.setenv("APP_ENV", "production")
    application = FastAPI()

    mount_dev_router_if_enabled(application)

    assert not any(
        getattr(route, "path", None) == "/v1/dev/otp/{challenge_id}"
        for route in application.routes
    )


def test_service_import_aborts_when_dev_otp_hook_is_on_in_production() -> None:
    """The real entrypoint refuses to start, not only the helper."""
    env = {
        **os.environ,
        "ALLOW_DEV_OTP_HOOK": "true",
        "APP_ENV": "production",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import banking_core.main"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "ALLOW_DEV_OTP_HOOK cannot be enabled" in result.stderr


def _verify_document(
    client: TestClient, headers: dict[str, str], front_ref: str
) -> dict[str, Any]:
    response = client.post(
        "/v1/tools/call",
        json={
            "tool": "identity.verify_document",
            "version": "1.0",
            "args": {"document_type": "NATIONAL_ID", "document_front_ref": front_ref},
        },
        headers=headers,
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize(
    ("front_ref", "decision", "reason", "score_check"),
    [
        (
            "sim-approve-front-0001",
            "APPROVED",
            "DOCUMENT_AUTHENTIC",
            lambda score: score >= 0.9,
        ),
        (
            "sim-reject-front-0001",
            "REJECTED",
            "DOCUMENT_NOT_AUTHENTIC",
            lambda score: score <= 0.2,
        ),
        # No provider result for an asset the simulator does not know: a human
        # decides. Unknown, lookalike and case-variant refs are never approved.
        ("card_front_12345", "MANUAL_REVIEW_REQUIRED", "NO_PROVIDER_RESULT", None),
        (
            "SIM-APPROVE-front-0001",
            "MANUAL_REVIEW_REQUIRED",
            "NO_PROVIDER_RESULT",
            None,
        ),
        (
            "xsim-approve-front-0001",
            "MANUAL_REVIEW_REQUIRED",
            "NO_PROVIDER_RESULT",
            None,
        ),
        (
            "sim-approved-front-0001",
            "MANUAL_REVIEW_REQUIRED",
            "NO_PROVIDER_RESULT",
            None,
        ),
    ],
)
def test_identity_verify_document_simulated_provider_follows_the_asset_ref(
    test_setup,
    front_ref: str,
    decision: str,
    reason: str,
    score_check: Any,
) -> None:
    """The simulated provider is deterministic and never approves by default."""
    client, mock_db, session_store, _ = test_setup
    session_id = client.post("/v1/sessions").json()["session_id"]
    headers = {"X-Session-Id": session_id}
    client.post(
        "/v1/tools/call",
        json={
            "tool": "customer.match",
            "version": "1.0",
            "args": {"document_type": "NATIONAL_ID", "document_number": "1020304050"},
        },
        headers=headers,
    )
    before = session_store.get(session_id)
    assert before is not None and before.state == VerificationState.IDENTIFIED

    res = _verify_document(client, headers, front_ref)

    assert res["status"] == "ok"
    assert res["data"]["decision"] == decision
    assert reason in res["data"]["reasons"]
    if score_check is not None:
        assert score_check(res["data"]["score"])
    # Same input, same answer.
    assert _verify_document(client, headers, front_ref) == res
    # It reports; it never moves the verification state, even when APPROVED.
    assert session_store.get(session_id) == before
    audit = mock_db.audit_logs[-1]
    assert audit.action == "identity.verify_document"
    assert audit.payload["verification_state_before"] == "IDENTIFIED"
    assert audit.payload["verification_state_after"] == "IDENTIFIED"
    assert audit.payload["details"]["decision"] == decision


OTP_MAX_ATTEMPTS = 3
MATCH_ES = {
    "tool": "customer.match",
    "version": "1.0",
    "args": {"document_type": "NATIONAL_ID", "document_number": "1020304050"},
}


MATCH_PT = {
    "tool": "customer.match",
    "version": "1.0",
    "args": {"document_type": "NATIONAL_ID", "document_number": "12345678900"},
}


class Harness:
    def __init__(self, lock_wait_ms: int) -> None:
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.session_store = RedisSessionStore(redis_client=self.redis)
        self.challenge_store = OtpChallengeStore(redis_client=self.redis)
        self.inbox = SimulatedInbox(redis_client=self.redis)
        self.db = MockDbSession(customers=_create_test_customers())
        self.dispatcher = ToolDispatcher(
            config_repo=InMemoryControlConfigRepository(),
            session_store=self.session_store,
            delivery_port=self.inbox,
            challenge_store=self.challenge_store,
            lock_ttl_ms=10000,
            lock_wait_ms=lock_wait_ms,
        )

    def client(self) -> TestClient:
        return TestClient(app)

    def new_session(self) -> str:
        session_id: str = self.client().post("/v1/sessions").json()["session_id"]
        return session_id

    def call(
        self, session_id: str, payload: dict[str, Any], **headers: str
    ) -> dict[str, Any]:
        resp = self.client().post(
            "/v1/tools/call",
            json=payload,
            headers={"X-Session-Id": session_id, **headers},
        )
        assert resp.status_code == 200, resp.text
        body: dict[str, Any] = resp.json()
        # Every result carries the flow hint (ADR-0016); tests of the result
        # itself compare without it, test_flow_hint_* read it here.
        self.last_flow = body.pop("flow", None)
        return body


@pytest.fixture
def make_harness(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("BLIND_INDEX_SALT", TEST_SALT)
    monkeypatch.setenv("OTP_MAX_ATTEMPTS", str(OTP_MAX_ATTEMPTS))

    def build(lock_wait_ms: int = 5000) -> Harness:
        h = Harness(lock_wait_ms=lock_wait_ms)
        set_session_store(h.session_store)
        set_simulated_inbox(h.inbox)
        app.dependency_overrides[get_db] = lambda: h.db
        app.dependency_overrides[get_session_store] = lambda: h.session_store
        set_dispatcher(h.dispatcher)
        return h

    yield build
    app.dependency_overrides.clear()
    set_simulated_inbox(None)


def _to_otp_pending(h: Harness) -> tuple[str, str]:
    session_id = h.new_session()
    assert h.call(session_id, MATCH_ES)["data"] == {"matched": True}
    sent = h.call(
        session_id,
        {"tool": "otp.send", "args": {}, "idempotency_key": "idem_send_hardening"},
    )
    assert sent["status"] == "ok"
    return session_id, sent["data"]["challenge_id"]


def test_parallel_wrong_verifies_evaluate_exactly_max_attempts_then_lock(
    make_harness,
) -> None:
    h = make_harness()
    session_id, challenge_id = _to_otp_pending(h)
    results: list[dict[str, Any]] = []
    barrier = threading.Barrier(20)

    # Widen the read-modify-write window so an unserialized dispatch would race.
    original_verify = h.challenge_store.verify_challenge

    def slow_verify(challenge_id: str, code: str) -> tuple[bool, int, str | None]:
        time.sleep(0.02)
        return original_verify(challenge_id, code)

    h.challenge_store.verify_challenge = slow_verify  # type: ignore[method-assign]

    def guess(i: int) -> None:
        barrier.wait()
        results.append(
            h.call(
                session_id,
                {
                    "tool": "otp.verify",
                    "args": {"code": "000000"},
                    "idempotency_key": f"idem_verify_parallel_{i:02d}",
                },
            )
        )

    threads = [threading.Thread(target=guess, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    evaluated = [r for r in results if r["status"] == "ok"]
    assert len(results) == 20
    assert len(evaluated) == OTP_MAX_ATTEMPTS
    assert all(r["data"]["verified"] is False for r in evaluated)
    assert h.challenge_store.evaluations(challenge_id) == OTP_MAX_ATTEMPTS
    assert {r["reason_code"] for r in results if r["status"] != "ok"} == {
        "STATE_NOT_ALLOWED"
    }
    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.LOCKED


def test_evaluation_counter_is_atomic_at_the_store(make_harness) -> None:
    """Even without the session lock, the store never evaluates past max_attempts."""
    h = make_harness()
    h.challenge_store.create_challenge(
        "chal_storelevel01", "cust", "123456", "SMS", "+57 *** *** 4567"
    )
    outcomes: list[tuple[bool, int, str | None]] = []
    barrier = threading.Barrier(20)

    def guess() -> None:
        barrier.wait()
        outcomes.append(
            h.challenge_store.verify_challenge("chal_storelevel01", "999999")
        )

    threads = [threading.Thread(target=guess) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    remaining = sorted(o[1] for o in outcomes)
    assert remaining.count(0) == 20 - (OTP_MAX_ATTEMPTS - 1)
    assert sorted(set(remaining) - {0}) == list(range(1, OTP_MAX_ATTEMPTS))
    # Right code after lockout is rejected: the challenge is gone.
    assert h.challenge_store.verify_challenge("chal_storelevel01", "123456")[0] is False


def test_otp_is_stored_hashed_never_in_clear(make_harness) -> None:
    h = make_harness()
    h.challenge_store.create_challenge(
        "chal_hashcheck01", "cust", "482913", "SMS", "+57 *** *** 4567"
    )
    raw = h.redis.get("otp:challenge:chal_hashcheck01")
    assert raw is not None
    stored = json.loads(raw)
    assert "code" not in stored
    assert "482913" not in raw
    assert len(stored["code_hmac"]) == 64
    assert h.challenge_store.verify_challenge("chal_hashcheck01", "482913")[0] is True


def test_no_per_ip_limit_and_forwarded_for_is_ignored(make_harness) -> None:
    h = make_harness()
    for i in range(25):
        session_id = h.new_session()
        result = h.call(
            session_id,
            MATCH_ES,
            **{"X-Forwarded-For": f"203.0.113.{i % 2}, 10.0.0.1"},
        )
        assert result["status"] == "ok", result
        assert result.get("reason_code") != "RATE_LIMITED"


def test_missing_blind_index_salt_fails_closed(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_harness()
    monkeypatch.delenv("BLIND_INDEX_SALT")
    session_id = h.new_session()

    result = h.call(session_id, MATCH_ES)

    assert result["status"] == "error"
    assert result["reason_code"] == "INTERNAL_ERROR"
    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.ANONYMOUS


def test_busy_session_lock_is_a_retryable_refusal(make_harness) -> None:
    h = make_harness(lock_wait_ms=50)
    session_id = h.new_session()

    with h.session_store.lock(session_id, ttl_ms=5000, wait_ms=0) as held:
        assert held is True
        busy = h.call(session_id, MATCH_ES)
    flow = h.last_flow
    assert busy == {
        "tool": "customer.match",
        "status": "refused",
        "reason_code": "SESSION_BUSY",
        "data": None,
    }
    # The busy refusal still says where the session stands (ADR-0016); it does
    # not name the refused tool as the next step.
    assert flow["state"] == "ANONYMOUS"
    assert flow["next"] == ["handoff.create"]
    assert h.db.audit_logs[-1].reason_code == "SESSION_BUSY"

    # Released in finally: the retry goes through.
    assert h.call(session_id, MATCH_ES)["status"] == "ok"


def test_invalid_database_enum_is_returned_as_internal_error(make_harness) -> None:
    harness = make_harness()
    session_id = harness.new_session()
    session = harness.session_store.get(session_id)
    assert session is not None
    session.state = VerificationState.VERIFIED
    session.pinned_holder_id = str(harness.db.customers[0].id)
    harness.session_store.save(session)

    with patch(
        "banking_core.api.dispatcher.execute_account_get_summary",
        side_effect=ValueError("invalid account enum from database"),
    ):
        result = harness.call(
            session_id,
            {"tool": "account.get_summary", "args": {"include_balances": True}},
        )

    assert result["status"] == "error"
    assert result["reason_code"] == "INTERNAL_ERROR"
    assert harness.db.audit_logs[-1].payload["status"] == "error"


@pytest.mark.parametrize("document_number", ["1020304050", "5550001112"])
def test_customer_match_spends_one_decrypt_on_hit_and_miss(
    make_harness, document_number: str
) -> None:
    h = make_harness()
    session_id = h.new_session()
    payload = {
        "tool": "customer.match",
        "args": {
            "document_type": "NATIONAL_ID",
            "document_number": document_number,
            "birth_date": "1985-05-15",
        },
    }
    with patch.object(
        RecordEncryptor, "decrypt", autospec=True, side_effect=RecordEncryptor.decrypt
    ) as decrypt:
        result = h.call(session_id, payload)

    assert result["status"] == "ok"
    assert decrypt.call_count == 1


def _otp_send(h: Harness, session_id: str, key: str) -> dict[str, Any]:
    return h.call(session_id, {"tool": "otp.send", "args": {}, "idempotency_key": key})


def _stored_challenges(h: Harness) -> set[str]:
    return {
        key
        for key in h.redis.keys("otp:challenge:*")
        if not key.endswith(":evaluations")
    }


def test_locking_resend_delivers_nothing_stores_no_challenge_and_locks(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTP_MAX_RESENDS", "2")
    h = make_harness()
    session_id, _ = _to_otp_pending(h)
    resent = _otp_send(h, session_id, "idem_resend_allowed_01")
    assert resent["status"] == "ok"
    challenge_id = resent["data"]["challenge_id"]
    challenges_before = _stored_challenges(h)
    audits_before = len(h.db.audit_logs)

    sink = h.inbox
    with patch.object(sink, "deliver", wraps=sink.deliver) as deliver:
        locking = _otp_send(h, session_id, "idem_resend_locking_01")

    assert locking == {
        "tool": "otp.send",
        "status": "refused",
        "reason_code": "RATE_LIMITED",
        "data": None,
    }
    deliver.assert_not_called()
    assert _stored_challenges(h) == challenges_before
    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.LOCKED
    assert session.otp_challenge_id == challenge_id
    assert len(h.db.audit_logs) == audits_before + 1
    audit = h.db.audit_logs[-1]
    assert (audit.action, audit.decision, audit.reason_code) == (
        "otp.send",
        "refused",
        "RATE_LIMITED",
    )
    assert audit.payload["verification_state_before"] == "OTP_PENDING"
    assert audit.payload["verification_state_after"] == "LOCKED"
    assert audit.payload["reason"] == "otp_resend_limit_exceeded"

    # Locked for good: no further code, and no way to verify the earlier one.
    for tool, args in (("otp.send", {}), ("otp.verify", {"code": "000000"})):
        after = h.call(
            session_id,
            {"tool": tool, "args": args, "idempotency_key": f"idem_after_lock_{tool}"},
        )
        assert after["reason_code"] == "STATE_NOT_ALLOWED"


def test_replayed_resend_is_not_counted_against_the_limit(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTP_MAX_RESENDS", "2")
    h = make_harness()
    session_id, _ = _to_otp_pending(h)
    first = _otp_send(h, session_id, "idem_resend_replayed_01")
    assert first["status"] == "ok"

    sink = h.inbox
    with patch.object(sink, "deliver", wraps=sink.deliver) as deliver:
        replays = [
            _otp_send(h, session_id, "idem_resend_replayed_01") for _ in range(3)
        ]

    assert replays == [first] * 3
    deliver.assert_not_called()
    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.OTP_PENDING
    assert session.otp_resends == 1


@pytest.mark.parametrize("channel", ["pigeon", "", "   "])
def test_unrecognized_registered_channel_fails_closed_like_none(
    make_harness, channel: str
) -> None:
    h = make_harness()
    h.db.customers[0].registered_otp_channel = channel
    session_id = h.new_session()
    assert h.call(session_id, MATCH_ES)["data"] == {"matched": True}

    sink = h.inbox
    with patch.object(sink, "deliver", wraps=sink.deliver) as deliver:
        result = _otp_send(h, session_id, "idem_unknown_channel_01")

    assert result == {
        "tool": "otp.send",
        "status": "refused",
        "reason_code": "POLICY_BLOCKED",
        "data": None,
    }
    deliver.assert_not_called()
    assert not _stored_challenges(h)
    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.IDENTIFIED
    audit = h.db.audit_logs[-1]
    assert (audit.action, audit.decision, audit.reason_code) == (
        "otp.send",
        "refused",
        "POLICY_BLOCKED",
    )
    assert audit.payload["reason"] == "unrecognized_otp_channel"


def _session_ttl(h: Harness, session_id: str) -> int:
    return int(h.redis.ttl(f"{h.session_store.key_prefix}{session_id}"))


def test_every_session_save_uses_the_configured_session_ttl(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store's own default is 3600; the policy config says 900."""
    monkeypatch.setenv("SESSION_TTL_SECONDS", "900")
    monkeypatch.setenv("OTP_MAX_RESENDS", "2")
    h = make_harness()
    assert h.session_store.default_ttl == 3600
    session_id = h.new_session()

    assert h.call(session_id, MATCH_ES)["status"] == "ok"
    assert 0 < _session_ttl(h, session_id) <= 900

    # Reset it high to prove each dispatch re-applies the configured TTL.
    h.redis.expire(f"{h.session_store.key_prefix}{session_id}", 3000)
    sent = _otp_send(h, session_id, "idem_ttl_send_01")
    assert sent["status"] == "ok"
    assert 0 < _session_ttl(h, session_id) <= 900

    h.redis.expire(f"{h.session_store.key_prefix}{session_id}", 3000)
    code = h.inbox.get_code(sent["data"]["challenge_id"])
    verified = h.call(
        session_id,
        {
            "tool": "otp.verify",
            "args": {"code": code},
            "idempotency_key": "idem_ttl_verify_01",
        },
    )
    assert verified["data"]["verified"] is True
    assert 0 < _session_ttl(h, session_id) <= 900


def test_locking_refusal_saves_the_session_with_the_configured_ttl(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SESSION_TTL_SECONDS", "900")
    monkeypatch.setenv("OTP_MAX_RESENDS", "2")
    h = make_harness()
    session_id, _ = _to_otp_pending(h)
    assert _otp_send(h, session_id, "idem_ttl_resend_01")["status"] == "ok"
    h.redis.expire(f"{h.session_store.key_prefix}{session_id}", 3000)

    locking = _otp_send(h, session_id, "idem_ttl_locking_01")

    assert locking["reason_code"] == "RATE_LIMITED"
    assert 0 < _session_ttl(h, session_id) <= 900


def _fresh_session_store_for_app(
    monkeypatch: pytest.MonkeyPatch, config: PolicyConfig | None
) -> fakeredis.FakeRedis:
    """Let the app build its own store, as on startup, over a fake Redis."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        "banking_core.control.session.create_redis_client", lambda: fake
    )
    monkeypatch.setattr(routes_sessions, "_session_store", None)

    def repo() -> InMemoryControlConfigRepository:
        if config is None:
            raise ConnectionError("policy database unavailable")
        return InMemoryControlConfigRepository(policy_config=config)

    monkeypatch.setattr(routes_sessions, "get_control_config_repository", repo)
    return fake


def test_session_creation_uses_the_configured_session_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fresh_session_store_for_app(
        monkeypatch, PolicyConfig(session_ttl_seconds=900)
    )

    response = TestClient(app).post("/v1/sessions")

    assert response.status_code == 201
    [key] = fake.keys("session:*")
    assert 0 < fake.ttl(key) <= 900


def test_session_creation_falls_back_to_the_seed_ttl_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fresh_session_store_for_app(monkeypatch, None)

    response = TestClient(app).post("/v1/sessions")

    assert response.status_code == 201
    [key] = fake.keys("session:*")
    assert 900 < fake.ttl(key) <= 3600


def test_idempotency_key_reused_with_other_arguments_is_a_refusal(
    make_harness,
) -> None:
    h = make_harness()
    session_id, challenge_id = _to_otp_pending(h)
    key = "idem_verify_conflict_01"

    first = h.call(
        session_id,
        {"tool": "otp.verify", "args": {"code": "000000"}, "idempotency_key": key},
    )
    assert first["status"] == "ok" and first["data"]["verified"] is False
    before = h.session_store.get(session_id)
    audits_before = len(h.db.audit_logs)

    conflict = h.call(
        session_id,
        {"tool": "otp.verify", "args": {"code": "111111"}, "idempotency_key": key},
    )

    assert conflict == {
        "tool": "otp.verify",
        "status": "refused",
        "reason_code": "INVALID_ARGUMENTS",
        "data": None,
    }
    # The runner never ran: no second evaluation, no session change.
    assert h.challenge_store.evaluations(challenge_id) == 1
    assert h.session_store.get(session_id) == before
    assert len(h.db.audit_logs) == audits_before + 1
    audit = h.db.audit_logs[-1]
    assert (audit.action, audit.decision, audit.reason_code) == (
        "otp.verify",
        "refused",
        "INVALID_ARGUMENTS",
    )
    assert audit.payload["idempotency_scope"] == session_id


# --- Cross-session OTP lock per customer (attempt limits) ---------------------

CUSTOMER_OTP_MAX_FAILURES = 4


def _customer_id(h: Harness) -> str:
    return str(h.db.customers[0].id)


def _wrong_verify(h: Harness, session_id: str, key: str) -> dict[str, Any]:
    return h.call(
        session_id,
        {"tool": "otp.verify", "args": {"code": "000000"}, "idempotency_key": key},
    )


def _lock_customer_through_two_sessions(h: Harness) -> None:
    """3 failures fill session A (its own limit); the 4th, in B, locks the customer."""
    session_a, _ = _to_otp_pending(h)
    for i in range(OTP_MAX_ATTEMPTS):
        _wrong_verify(h, session_a, f"idem_lock_a_{i}")
    session_b, _ = _to_otp_pending(h)
    tripping = _wrong_verify(h, session_b, "idem_lock_b_0")
    assert tripping["data"]["state"] == "LOCKED"
    assert h.dispatcher.attempt_limit_store.customer_locked(_customer_id(h))


@pytest.fixture
def lock_harness(make_harness, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "RATE_LIMIT_CUSTOMER_OTP_MAX_FAILURES", str(CUSTOMER_OTP_MAX_FAILURES)
    )
    return make_harness


def test_failed_verifies_in_different_sessions_add_up_to_a_customer_lock(
    lock_harness,
) -> None:
    h = lock_harness()
    limits = h.dispatcher.attempt_limit_store
    session_a, _ = _to_otp_pending(h)
    for i in range(OTP_MAX_ATTEMPTS):
        _wrong_verify(h, session_a, f"idem_add_a_{i}")
    stored_a = h.session_store.get(session_a)
    assert stored_a is not None and stored_a.state == VerificationState.LOCKED
    # A session that ends LOCKED by OTP failures has counted every failure.
    assert not limits.customer_locked(_customer_id(h))

    session_b, _ = _to_otp_pending(h)
    tripping = _wrong_verify(h, session_b, "idem_add_b_0")

    # One failure in B, far below the session limit: the customer limit is what
    # ends it. No attempts are left and the receipt says LOCKED.
    assert tripping["status"] == "ok"
    assert tripping["data"]["verified"] is False
    assert tripping["data"]["state"] == "LOCKED"
    assert tripping["data"]["attempts_remaining"] == 0
    assert tripping["data"]["receipt"]["state_after"] == "LOCKED"
    stored_b = h.session_store.get(session_b)
    assert stored_b is not None and stored_b.state == VerificationState.LOCKED
    assert limits.customer_locked(_customer_id(h))


def test_other_customers_are_not_locked_by_someone_elses_failures(
    lock_harness,
) -> None:
    h = lock_harness()
    _lock_customer_through_two_sessions(h)

    session_id = h.new_session()
    assert h.call(session_id, MATCH_PT)["data"] == {"matched": True}
    sent = _otp_send(h, session_id, "idem_other_customer")

    assert sent["status"] == "ok"


def test_locked_customer_gets_no_code_from_a_new_session(lock_harness) -> None:
    h = lock_harness()
    _lock_customer_through_two_sessions(h)
    challenges_before = _stored_challenges(h)
    session_id = h.new_session()
    assert h.call(session_id, MATCH_ES)["data"] == {"matched": True}
    audits_before = len(h.db.audit_logs)

    sink = h.inbox
    with patch.object(sink, "deliver", wraps=sink.deliver) as deliver:
        refused = _otp_send(h, session_id, "idem_locked_send")

    assert refused == {
        "tool": "otp.send",
        "status": "refused",
        "reason_code": "RATE_LIMITED",
        "data": None,
    }
    deliver.assert_not_called()
    assert _stored_challenges(h) == challenges_before
    session = h.session_store.get(session_id)
    assert session is not None and session.state == VerificationState.LOCKED
    assert len(h.db.audit_logs) == audits_before + 1
    audit = h.db.audit_logs[-1]
    assert (audit.action, audit.decision, audit.reason_code) == (
        "otp.send",
        "refused",
        "RATE_LIMITED",
    )
    assert audit.payload["reason"] == "customer_otp_locked"
    assert audit.payload["verification_state_before"] == "IDENTIFIED"
    assert audit.payload["verification_state_after"] == "LOCKED"
    assert audit.payload["details"]["customer_id"] == _customer_id(h)

    # From here the session is LOCKED like any other: handoff only.
    again = _otp_send(h, session_id, "idem_locked_send_again")
    assert again["reason_code"] == "STATE_NOT_ALLOWED"


def test_resend_from_a_pending_session_is_refused_while_the_customer_is_locked(
    lock_harness,
) -> None:
    h = lock_harness()
    pending, _ = _to_otp_pending(h)
    _lock_customer_through_two_sessions(h)
    challenges_before = _stored_challenges(h)

    sink = h.inbox
    with patch.object(sink, "deliver", wraps=sink.deliver) as deliver:
        refused = _otp_send(h, pending, "idem_locked_resend")

    assert refused["reason_code"] == "RATE_LIMITED"
    deliver.assert_not_called()
    assert _stored_challenges(h) == challenges_before
    session = h.session_store.get(pending)
    assert session is not None and session.state == VerificationState.LOCKED


def test_locked_customer_cannot_verify_even_the_right_code(lock_harness) -> None:
    h = lock_harness()
    pending, challenge_id = _to_otp_pending(h)
    right_code = h.inbox.get_code(challenge_id)
    _lock_customer_through_two_sessions(h)
    evaluations_before = h.challenge_store.evaluations(challenge_id)

    refused = h.call(
        pending,
        {
            "tool": "otp.verify",
            "args": {"code": right_code},
            "idempotency_key": "idem_locked_verify_right",
        },
    )

    assert refused == {
        "tool": "otp.verify",
        "status": "refused",
        "reason_code": "RATE_LIMITED",
        "data": None,
    }
    # Never compared: the challenge saw no evaluation and nothing was verified.
    assert h.challenge_store.evaluations(challenge_id) == evaluations_before
    session = h.session_store.get(pending)
    assert session is not None and session.state == VerificationState.LOCKED
    audit = h.db.audit_logs[-1]
    assert (audit.action, audit.decision, audit.reason_code) == (
        "otp.verify",
        "refused",
        "RATE_LIMITED",
    )
    assert audit.payload["reason"] == "customer_otp_locked"


def test_customer_lock_is_audited_once_without_pii(lock_harness) -> None:
    h = lock_harness()
    _lock_customer_through_two_sessions(h)

    events = [a for a in h.db.audit_logs if a.action == "security.customer_otp_locked"]

    assert len(events) == 1
    event = events[0]
    assert (event.actor_type, event.decision, event.reason_code) == (
        "system",
        "refused",
        "RATE_LIMITED",
    )
    assert event.payload["reason"] == "customer_otp_failure_limit_reached"
    assert event.payload["verification_state_before"] == "OTP_PENDING"
    assert event.payload["verification_state_after"] == "LOCKED"
    assert event.payload["details"] == {
        "customer_id": _customer_id(h),
        "max_failures": CUSTOMER_OTP_MAX_FAILURES,
        "window_seconds": 3600,
        "lock_seconds": 1800,
    }
    rendered = json.dumps(event.payload)
    for pii in ("1020304050", "Carlos", "carlos@example.com", "+573001234567"):
        assert pii not in rendered


def test_retrying_the_tripping_verify_counts_and_audits_nothing_more(
    lock_harness,
) -> None:
    h = lock_harness()
    session_a, _ = _to_otp_pending(h)
    for i in range(OTP_MAX_ATTEMPTS):
        _wrong_verify(h, session_a, f"idem_replay_a_{i}")
    session_b, _ = _to_otp_pending(h)
    _wrong_verify(h, session_b, "idem_replay_b")
    failures_key = f"limit:customer:{_customer_id(h)}:otp_failures"
    assert h.redis.get(failures_key) == str(CUSTOMER_OTP_MAX_FAILURES)

    # The session is LOCKED now: a retry never reaches the tool.
    retry = _wrong_verify(h, session_b, "idem_replay_b")

    assert retry["reason_code"] == "STATE_NOT_ALLOWED"
    assert h.redis.get(failures_key) == str(CUSTOMER_OTP_MAX_FAILURES)
    events = [a for a in h.db.audit_logs if a.action == "security.customer_otp_locked"]
    assert len(events) == 1


def test_customer_lock_ends_after_its_duration(lock_harness) -> None:
    h = lock_harness()
    _lock_customer_through_two_sessions(h)
    lock_key = f"limit:customer:{_customer_id(h)}:otp_lock"
    assert 0 < h.redis.ttl(lock_key) <= 1800

    h.redis.delete(lock_key)  # what the TTL does at the end of the lock
    session_id = h.new_session()
    assert h.call(session_id, MATCH_ES)["data"] == {"matched": True}

    assert _otp_send(h, session_id, "idem_after_lock_ends")["status"] == "ok"


def test_a_correct_code_is_not_counted_as_a_failure(lock_harness) -> None:
    h = lock_harness()
    session_id, challenge_id = _to_otp_pending(h)
    code = h.inbox.get_code(challenge_id)

    verified = h.call(
        session_id,
        {
            "tool": "otp.verify",
            "args": {"code": code},
            "idempotency_key": "idem_right_code",
        },
    )

    assert verified["data"]["verified"] is True
    assert h.redis.keys("limit:customer:*") == []


def test_customer_limit_keys_hold_only_the_customer_uuid(lock_harness) -> None:
    h = lock_harness()
    _lock_customer_through_two_sessions(h)

    keys = sorted(h.redis.keys("limit:customer:*"))

    assert keys == [
        f"limit:customer:{_customer_id(h)}:otp_failures",
        f"limit:customer:{_customer_id(h)}:otp_lock",
    ]


def test_customer_limit_thresholds_come_from_the_policy_config(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_CUSTOMER_OTP_MAX_FAILURES", "2")
    monkeypatch.setenv("RATE_LIMIT_CUSTOMER_OTP_LOCK_SECONDS", "120")
    h = make_harness()
    session_a, _ = _to_otp_pending(h)
    _wrong_verify(h, session_a, "idem_cfg_a_0")
    tripping = _wrong_verify(h, session_a, "idem_cfg_a_1")

    assert tripping["data"]["state"] == "LOCKED"
    lock_key = f"limit:customer:{_customer_id(h)}:otp_lock"
    assert 0 < h.redis.ttl(lock_key) <= 120


# --- Cross-session match limit per claimed document (attempt limits) ----------

DOCUMENT_MATCH_MAX_FAILURES = 4
ES_DOCUMENT = "1020304050"
UNKNOWN_DOCUMENT = "5550001112"
RIGHT_BIRTH_DATE = "1985-05-15"
WRONG_BIRTH_DATE = "1970-01-01"


def _match(
    h: Harness,
    session_id: str,
    number: str = ES_DOCUMENT,
    birth_date: str | None = WRONG_BIRTH_DATE,
    document_type: str = "NATIONAL_ID",
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "document_type": document_type,
        "document_number": number,
    }
    if birth_date is not None:
        args["birth_date"] = birth_date
    return h.call(session_id, {"tool": "customer.match", "args": args})


def _match_in_new_session(h: Harness, *args: Any, **kwargs: Any) -> dict[str, Any]:
    return _match(h, h.new_session(), *args, **kwargs)


def _match_audits(h: Harness) -> list[Any]:
    return [a for a in h.db.audit_logs if a.action == "customer.match"]


@pytest.fixture
def match_harness(make_harness, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "RATE_LIMIT_DOCUMENT_MATCH_MAX_FAILURES", str(DOCUMENT_MATCH_MAX_FAILURES)
    )
    return make_harness


def test_failed_matches_on_one_document_are_limited_across_sessions(
    match_harness,
) -> None:
    h = match_harness()
    for _ in range(DOCUMENT_MATCH_MAX_FAILURES):
        result = _match_in_new_session(h, birth_date=WRONG_BIRTH_DATE)
        assert result["data"] == {"matched": False}

    # Past the maximum even the RIGHT data answers matched=false, from any session.
    session_id = h.new_session()
    limited = _match(h, session_id, birth_date=RIGHT_BIRTH_DATE)

    assert limited == {
        "tool": "customer.match",
        "status": "ok",
        "reason_code": None,
        "data": {"matched": False},
    }
    assert _match_in_new_session(h, birth_date=RIGHT_BIRTH_DATE)["data"] == {
        "matched": False
    }
    # It still counts against the session that asked, like any failed match.
    session = h.session_store.get(session_id)
    assert session is not None
    assert (session.attempts, session.failed_matches) == (1, 1)
    assert session.state == VerificationState.ANONYMOUS
    # Another document is untouched.
    assert _match_in_new_session(h, "12345678900", birth_date="1990-10-20")["data"] == {
        "matched": True
    }


def test_a_limited_match_looks_nothing_up(match_harness) -> None:
    h = match_harness()
    for _ in range(DOCUMENT_MATCH_MAX_FAILURES):
        _match_in_new_session(h)
    session_id = h.new_session()

    with (
        patch.object(h.db, "scalars", wraps=h.db.scalars) as probes,
        patch.object(
            RecordEncryptor,
            "decrypt",
            autospec=True,
            side_effect=RecordEncryptor.decrypt,
        ) as decrypt,
    ):
        result = _match(h, session_id, birth_date=RIGHT_BIRTH_DATE)

    assert result["data"] == {"matched": False}
    probes.assert_not_called()
    decrypt.assert_not_called()


def _observable(h: Harness, results: list[dict[str, Any]], audits_from: int) -> Any:
    """What a caller sees of each call, and the audit fields of each, sans refs."""
    rows = []
    for row in h.db.audit_logs[audits_from:]:
        payload = json.loads(json.dumps(row.payload))
        payload.get("details", {}).pop("document_ref", None)
        rows.append(
            (row.actor_type, row.action, row.decision, row.reason_code, payload)
        )
    return results, rows


def test_existing_and_unknown_documents_are_indistinguishable_through_the_limit(
    match_harness,
) -> None:
    h = match_harness()
    calls = DOCUMENT_MATCH_MAX_FAILURES + 3

    def run(number: str) -> Any:
        start = len(h.db.audit_logs)
        results = [
            _match_in_new_session(h, number, birth_date=WRONG_BIRTH_DATE)
            for _ in range(calls)
        ]
        return _observable(h, results, start)

    existing = run(ES_DOCUMENT)
    unknown = run(UNKNOWN_DOCUMENT)

    # Same responses, same audit rows (actor, action, decision, reason, payload,
    # including which calls were limited and the lock event): only the opaque
    # document reference differs.
    assert existing == unknown
    assert [r["data"] for r in existing[0]] == [{"matched": False}] * calls


def test_a_successful_match_is_not_a_failure(match_harness) -> None:
    h = match_harness()

    results = [
        _match_in_new_session(h, birth_date=RIGHT_BIRTH_DATE)
        for _ in range(DOCUMENT_MATCH_MAX_FAILURES * 3)
    ]

    assert all(r["data"] == {"matched": True} for r in results)
    # The counter went back to zero after each match: the failures still fit.
    for _ in range(DOCUMENT_MATCH_MAX_FAILURES):
        assert _match_in_new_session(h, birth_date=WRONG_BIRTH_DATE)["data"] == {
            "matched": False
        }
    assert (
        _match_in_new_session(h, birth_date=RIGHT_BIRTH_DATE)["data"]["matched"]
        is False
    )


def test_equivalent_document_types_share_one_limit(match_harness) -> None:
    h = match_harness()
    half = DOCUMENT_MATCH_MAX_FAILURES // 2
    pt_number = "12345678900"
    for _ in range(half):
        _match_in_new_session(
            h, pt_number, birth_date=WRONG_BIRTH_DATE, document_type="TAX_ID"
        )
    for _ in range(DOCUMENT_MATCH_MAX_FAILURES - half):
        _match_in_new_session(
            h, pt_number, birth_date=WRONG_BIRTH_DATE, document_type="NATIONAL_ID"
        )

    for document_type in ("TAX_ID", "NATIONAL_ID"):
        result = _match_in_new_session(
            h, pt_number, birth_date="1990-10-20", document_type=document_type
        )
        assert result["data"] == {"matched": False}


def test_document_limit_is_audited_once_without_pii(match_harness) -> None:
    h = match_harness()
    calls = DOCUMENT_MATCH_MAX_FAILURES + 3
    for _ in range(calls):
        _match_in_new_session(h)

    events = [
        a for a in h.db.audit_logs if a.action == "security.document_match_limited"
    ]

    assert len(events) == 1
    event = events[0]
    assert (event.actor_type, event.decision, event.reason_code) == (
        "system",
        "refused",
        "RATE_LIMITED",
    )
    assert event.payload["reason"] == "document_match_failure_limit_reached"
    bidx = compute_blind_index(
        ES_DOCUMENT, "document_number", TEST_SALT, document_type="NATIONAL_ID"
    )
    assert event.payload["details"] == {
        "document_ref": bidx[:32],
        "max_failures": DOCUMENT_MATCH_MAX_FAILURES,
        "window_seconds": 3600,
    }
    rendered = json.dumps(event.payload)
    for pii in (ES_DOCUMENT, "Carlos", "1985-05-15", WRONG_BIRTH_DATE):
        assert pii not in rendered
    # Each call the limit answered says so; the ones before it do not.
    flags = [a.payload["details"].get("limited", False) for a in _match_audits(h)]
    assert flags == [False] * DOCUMENT_MATCH_MAX_FAILURES + [True] * 3


def test_document_limit_keys_hold_only_blind_indexes(match_harness) -> None:
    h = match_harness()
    for number in (ES_DOCUMENT, UNKNOWN_DOCUMENT):
        _match_in_new_session(h, number)

    keys = h.redis.keys("limit:document:*")

    # One key per claimed document and equivalent type (NATIONAL_ID == TAX_ID).
    assert len(keys) == 4
    for key in keys:
        assert re.fullmatch(r"limit:document:[0-9a-f]{64}:match_failures", key)
        assert ES_DOCUMENT not in key and UNKNOWN_DOCUMENT not in key


def test_limited_matches_still_lock_the_session_at_its_own_limit(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_DOCUMENT_MATCH_MAX_FAILURES", "1")
    monkeypatch.setenv("RATE_LIMIT_ATTEMPTS_PER_SESSION", "3")
    h = make_harness()
    session_id = h.new_session()

    for _ in range(3):
        assert _match(h, session_id)["data"] == {"matched": False}

    session = h.session_store.get(session_id)
    assert session is not None
    assert session.state == VerificationState.LOCKED
    assert session.attempts == 3


def test_document_limit_window_comes_from_the_policy_config(
    make_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_DOCUMENT_MATCH_WINDOW_SECONDS", "120")
    h = make_harness()

    _match_in_new_session(h)

    keys = h.redis.keys("limit:document:*")
    assert keys
    for key in keys:
        assert 0 < h.redis.ttl(key) <= 120


def test_parallel_sessions_never_evaluate_past_the_document_maximum(
    match_harness,
) -> None:
    h = match_harness()
    session_ids = [h.new_session() for _ in range(24)]
    results: list[dict[str, Any]] = []
    barrier = threading.Barrier(len(session_ids))

    def guess(session_id: str) -> None:
        barrier.wait()
        results.append(_match(h, session_id, UNKNOWN_DOCUMENT))

    threads = [threading.Thread(target=guess, args=(s,)) for s in session_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r["data"] == {"matched": False} for r in results)
    audits = _match_audits(h)
    assert len(audits) == len(session_ids)
    evaluated = [a for a in audits if not a.payload["details"].get("limited")]
    assert len(evaluated) == DOCUMENT_MATCH_MAX_FAILURES


def test_flow_hint_after_a_match_and_a_premature_card_list(make_harness) -> None:
    # The stall of ADR-0016: matched, then card.list before the code.
    h = make_harness()
    session_id = h.new_session()
    assert h.call(session_id, MATCH_ES)["data"] == {"matched": True}
    assert h.last_flow["state"] == "IDENTIFIED"
    assert h.last_flow["next"] == ["otp.send"]

    refused = h.call(session_id, {"tool": "card.list", "version": "1.0", "args": {}})
    assert refused["reason_code"] == "STATE_NOT_ALLOWED"
    assert h.last_flow["required_states"] == ["VERIFIED"]
    assert h.last_flow["next"] == ["otp.send"]
