"""Admin API for the handoff queue and the metrics (ADR-0013).

`GET /v1/admin/handoffs`, `GET /v1/admin/handoffs/{ref}`, `POST .../claim` and
`GET /v1/admin/metrics`: ordering and filters, the queue position rule shared
with the customer's handoff receipt, the claim (idempotent, one winner, audited
in the same transaction, chain intact) and the counts over a window.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from banking_core.api import admin_router
from banking_core.audit.service import append, verify_chain
from banking_core.control.policy import Decision
from banking_core.db.session import get_session_maker
from banking_core.handoff import queue as handoff_queue
from banking_core.handoff.queue import (
    ClaimedByAnotherAgentError,
    claim_handoff,
)
from banking_core.handoff.tools import execute_handoff_create
from banking_core.main import mount_admin_router_if_enabled
from banking_core.models.ops import Handoff
from contracts.audit import AuditPayload
from contracts.envelope import ToolResultStatus, VerificationState
from contracts.tools.card_list import CardStatus
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffPriority,
    HandoffReason,
    HandoffStatus,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

ADMIN_TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
HANDOFFS = "/v1/admin/handoffs"
METRICS = "/v1/admin/metrics"
CLAIMED = "admin.handoff.claimed"
ANA = "ana.agent@bank.example"
BEN = "ben.agent@bank.example"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _clear_handoffs() -> None:
    with get_session_maker()() as session:
        session.execute(sa.text("DELETE FROM ops.handoff"))
        session.commit()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    return app


@pytest.fixture
def client(db_session: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The admin router over the test database; audit rows and queue start empty."""
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    _clear_handoffs()
    try:
        with TestClient(_build_app()) as test_client:
            yield test_client
    finally:
        _clear_handoffs()


def _add(
    ref: str,
    *,
    priority: str = "NORMAL",
    department: str = "CUSTOMER_SUPPORT",
    status: str = "QUEUED",
    created_at: datetime = T0,
    summary: dict[str, Any] | None = None,
    assigned_agent: str | None = None,
    assigned_at: datetime | None = None,
    session_ref: str | None = None,
) -> None:
    with get_session_maker()() as session:
        session.add(
            Handoff(
                handoff_ref=ref,
                session_ref=session_ref or f"sess_{ref}",
                reason="DISPUTE_CLAIM",
                priority=priority,
                department=department,
                status=status,
                summary=summary if summary is not None else {"verified_facts": {}},
                idempotency_scope=f"sess_{ref}",
                created_at=created_at,
                assigned_agent=assigned_agent,
                assigned_at=assigned_at,
            )
        )
        session.commit()


def _minutes(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _list(client: TestClient, query: str = "") -> list[dict[str, Any]]:
    response = client.get(f"{HANDOFFS}{query}", headers=AUTH)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def _claim(client: TestClient, ref: str, agent: str = ANA) -> Any:
    return client.post(
        f"{HANDOFFS}/{ref}/claim", headers=AUTH, json={"agent_ref": agent}
    )


def _claim_audits() -> list[sa.Row[Any]]:
    with get_session_maker()() as session:
        return list(
            session.execute(
                sa.text(
                    "SELECT id, actor_type, actor_ref, decision, reason_code, "
                    "payload, occurred_at FROM ops.audit_log "
                    "WHERE action = :action ORDER BY id"
                ),
                {"action": CLAIMED},
            )
        )


def _stored(ref: str) -> Handoff:
    with get_session_maker()() as session:
        row = session.scalar(sa.select(Handoff).where(Handoff.handoff_ref == ref))
        assert row is not None
        session.expunge(row)
        return row


def _create_handoff(
    scope: str,
    priority: HandoffPriority = HandoffPriority.NORMAL,
    decision: Decision | None = None,
) -> Any:
    """handoff.create as the dispatcher runs it: a session of its own per call."""
    with get_session_maker()() as session:
        return execute_handoff_create(
            db_session=session,
            holder_customer_id=None,
            args=HandoffCreateInput(
                reason=HandoffReason.CUSTOMER_REQUEST,
                summary="Customer asks for a person to review the case.",
                priority=priority,
                department=Department.CUSTOMER_SUPPORT,
            ),
            policy_decision=decision or Decision(allowed=True),
            idempotency_scope=scope,
            verification_state_before=VerificationState.ANONYMOUS,
            verification_state_after=VerificationState.HANDED_OFF,
            session_id=scope,
        )


# --- authentication and mounting ---------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", HANDOFFS),
        ("GET", f"{HANDOFFS}/hnd_anything"),
        ("POST", f"{HANDOFFS}/hnd_anything/claim"),
        ("GET", METRICS),
    ],
)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": ADMIN_TOKEN}],
    ids=["no-token", "wrong-token", "no-scheme"],
)
def test_handoff_and_metrics_routes_require_the_admin_token(
    client: TestClient, method: str, path: str, headers: dict[str, str]
) -> None:
    if method == "POST":
        response = client.post(path, headers=headers, json={"agent_ref": ANA})
    else:
        response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_unauthenticated_claim_changes_nothing(client: TestClient) -> None:
    _add("hnd_locked")

    response = client.post(f"{HANDOFFS}/hnd_locked/claim", json={"agent_ref": ANA})

    assert response.status_code == 401
    stored = _stored("hnd_locked")
    assert (stored.status, stored.assigned_agent) == ("QUEUED", None)
    assert _claim_audits() == []


ROUTES = [
    ("GET", HANDOFFS),
    ("GET", f"{HANDOFFS}/hnd_x"),
    ("POST", f"{HANDOFFS}/hnd_x/claim"),
    ("GET", METRICS),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_the_routes_are_not_mounted_when_the_admin_api_is_disabled(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.setenv("ADMIN_API_ENABLED", "false")
    app = FastAPI()
    mount_admin_router_if_enabled(app)

    with TestClient(app) as disabled:
        response = disabled.request(
            method,
            path,
            headers=AUTH,
            json={"agent_ref": ANA} if method == "POST" else None,
        )

    assert response.status_code == 404


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_the_routes_are_mounted_and_guarded_when_the_admin_api_is_enabled(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.setenv("ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    app = FastAPI()
    mount_admin_router_if_enabled(app)

    with TestClient(app) as enabled:
        response = enabled.request(method, path, json=None)

    # Found, and refused for want of the token: not a 404.
    assert response.status_code == 401


# --- the list ------------------------------------------------------------------


def _seed_queue() -> None:
    _add("hnd_low", priority="LOW", created_at=_minutes(1))
    _add("hnd_urgent_late", priority="URGENT", created_at=_minutes(5))
    _add("hnd_high_late", priority="HIGH", created_at=_minutes(2))
    _add("hnd_urgent_early", priority="URGENT", created_at=_minutes(3))
    _add("hnd_normal", priority="NORMAL", created_at=_minutes(0))
    _add(
        "hnd_high_taken",
        priority="HIGH",
        status="ASSIGNED",
        created_at=_minutes(1),
        assigned_agent=ANA,
        assigned_at=_minutes(30),
    )
    _add("hnd_high_pending", priority="HIGH", status="PENDING", created_at=_minutes(0))
    _add(
        "hnd_urgent_disputes",
        priority="URGENT",
        department="DISPUTES",
        created_at=_minutes(9),
    )


def test_the_list_is_empty_when_nothing_is_queued(client: TestClient) -> None:
    assert client.get(HANDOFFS, headers=AUTH).json() == {"items": []}


def test_the_list_orders_by_priority_and_then_by_age(client: TestClient) -> None:
    _seed_queue()

    refs = [item["handoff_ref"] for item in _list(client)]

    # QUEUED and ASSIGNED by default: PENDING is not listed.
    assert refs == [
        "hnd_urgent_early",
        "hnd_urgent_late",
        "hnd_urgent_disputes",
        "hnd_high_taken",
        "hnd_high_late",
        "hnd_normal",
        "hnd_low",
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "?status=QUEUED",
            [
                "hnd_urgent_early",
                "hnd_urgent_late",
                "hnd_urgent_disputes",
                "hnd_high_late",
                "hnd_normal",
                "hnd_low",
            ],
        ),
        ("?status=ASSIGNED", ["hnd_high_taken"]),
        ("?status=PENDING", ["hnd_high_pending"]),
        (
            "?status=PENDING&status=ASSIGNED",
            ["hnd_high_pending", "hnd_high_taken"],
        ),
    ],
)
def test_the_list_filters_by_status(
    client: TestClient, query: str, expected: list[str]
) -> None:
    _seed_queue()

    assert [item["handoff_ref"] for item in _list(client, query)] == expected


def test_the_list_refuses_an_unknown_status(client: TestClient) -> None:
    response = client.get(f"{HANDOFFS}?status=DONE", headers=AUTH)

    assert response.status_code == 422


def test_a_list_item_has_the_documented_shape(client: TestClient) -> None:
    _add(
        "hnd_shape",
        priority="HIGH",
        department="FRAUD_OPERATIONS",
        created_at=_minutes(4),
        session_ref="sess_shape",
    )

    [item] = _list(client)

    assert item == {
        "handoff_ref": "hnd_shape",
        "status": "QUEUED",
        "priority": "HIGH",
        "department": "FRAUD_OPERATIONS",
        "reason": "DISPUTE_CLAIM",
        "created_at": "2026-09-01T12:04:00Z",
        "queue_position": 1,
        "assigned_agent": None,
        "assigned_at": None,
        "session_ref": "sess_shape",
        "outcome": None,
        "outcome_reason": None,
        "closed_by": None,
        "closed_at": None,
        "disputed_amount": None,
    }
    # The summary belongs to the detail.
    assert "summary" not in item


def test_queue_position_counts_the_queued_cases_ahead_in_the_department(
    client: TestClient,
) -> None:
    _seed_queue()

    positions = {
        item["handoff_ref"]: item["queue_position"]
        for item in _list(client, "?status=QUEUED&status=ASSIGNED&status=PENDING")
    }

    assert positions == {
        "hnd_urgent_early": 1,
        "hnd_urgent_late": 2,
        "hnd_high_late": 3,
        "hnd_normal": 4,
        "hnd_low": 5,
        # Its own department's queue.
        "hnd_urgent_disputes": 1,
        # Only a QUEUED case has a place in line.
        "hnd_high_taken": None,
        "hnd_high_pending": None,
    }


def test_queue_position_is_the_one_the_customers_receipt_reports(
    client: TestClient,
) -> None:
    """The list and handoff.create share one rule: they agree after every arrival."""
    arrivals = [
        ("sess_rule_1", HandoffPriority.NORMAL, None),
        # Raised to URGENT by the policy flag, whatever was asked.
        (
            "sess_rule_2",
            HandoffPriority.LOW,
            Decision(allowed=True, flags=["PRIORITY"]),
        ),
        ("sess_rule_3", HandoffPriority.NORMAL, None),
        ("sess_rule_4", HandoffPriority.HIGH, None),
    ]
    refs: dict[str, str] = {}
    for scope, priority, decision in arrivals:
        result = _create_handoff(scope, priority, decision)
        refs[scope] = result.output.handoff_id
        listed = {item["handoff_ref"]: item for item in _list(client)}
        assert result.output.queue_position is not None
        assert (
            listed[result.output.handoff_id]["queue_position"]
            == result.output.queue_position
        )

    final = {item["handoff_ref"]: item["queue_position"] for item in _list(client)}
    assert final == {
        refs["sess_rule_2"]: 1,
        refs["sess_rule_4"]: 2,
        refs["sess_rule_1"]: 3,
        refs["sess_rule_3"]: 4,
    }


def test_a_claimed_case_has_no_queue_position_in_the_customers_receipt_either(
    client: TestClient,
) -> None:
    first = _create_handoff("sess_repeat")
    assert first.output.queue_position == 1
    assert _claim(client, first.output.handoff_id).status_code == 200

    again = _create_handoff("sess_repeat")

    assert again.output.handoff_id == first.output.handoff_id
    assert again.output.status == HandoffStatus.ASSIGNED
    assert again.output.queue_position is None


# --- the detail ----------------------------------------------------------------


def test_the_detail_returns_the_summary_exactly_as_stored(
    client: TestClient,
) -> None:
    summary = {
        "verified_facts": {
            "verification_state": "VERIFIED",
            "disputed_transaction": {"amount_minor": 125000, "currency": "COP"},
        },
        "actions_taken": [{"action": "card.block", "decision": "allowed"}],
        "verification_method": "document_match_and_otp",
        "open_questions": [{"source": "model_unverified", "text": "Which charge?"}],
        "a_key_added_later": {"kept": True},
    }
    _add(
        "hnd_detail",
        priority="URGENT",
        department="DISPUTES",
        created_at=_minutes(7),
        summary=summary,
    )

    response = client.get(f"{HANDOFFS}/hnd_detail", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == summary
    decisions = body.pop("decisions")
    assert {k: v for k, v in body.items() if k != "summary"} == {
        "handoff_ref": "hnd_detail",
        "status": "QUEUED",
        "priority": "URGENT",
        "department": "DISPUTES",
        "reason": "DISPUTE_CLAIM",
        "created_at": "2026-09-01T12:07:00Z",
        "queue_position": 1,
        "assigned_agent": None,
        "assigned_at": None,
        "session_ref": "sess_hnd_detail",
        "outcome": None,
        "outcome_reason": None,
        "closed_by": None,
        "closed_at": None,
        # Read from the stored summary: no query of its own.
        "disputed_amount": {"amount_minor": 125000, "currency": "COP"},
        "feedback": None,
    }
    # A verified dispute: approve or reject, and any other department (ADR-0018).
    assert decisions["outcomes"] == ["APPROVED", "REJECTED"]
    assert decisions["escalate_to"] == ["FRAUD_OPERATIONS", "CUSTOMER_SUPPORT"]
    assert set(decisions["closing_messages"]) == {"APPROVED", "REJECTED"}


def test_the_detail_of_an_assigned_case_names_who_holds_it(
    client: TestClient,
) -> None:
    _add(
        "hnd_held",
        status="ASSIGNED",
        assigned_agent=ANA,
        assigned_at=_minutes(20),
    )

    body = client.get(f"{HANDOFFS}/hnd_held", headers=AUTH).json()

    assert body["status"] == "ASSIGNED"
    assert body["assigned_agent"] == ANA
    assert body["assigned_at"] == "2026-09-01T12:20:00Z"
    assert body["queue_position"] is None


def test_an_unknown_handoff_is_a_404(client: TestClient) -> None:
    response = client.get(f"{HANDOFFS}/hnd_nothing", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"detail": "handoff_not_found"}


# --- the claim -----------------------------------------------------------------


def test_a_claim_assigns_the_case_and_returns_it_as_stored(
    client: TestClient,
) -> None:
    _add("hnd_claim", priority="HIGH", summary={"verified_facts": {"x": 1}})

    response = _claim(client, "hnd_claim")

    assert response.status_code == 200, response.text
    body = response.json()
    stored = _stored("hnd_claim")
    assert stored.status == "ASSIGNED"
    assert stored.assigned_agent == ANA
    assert stored.assigned_at is not None
    assert body["status"] == "ASSIGNED"
    assert body["assigned_agent"] == ANA
    assert body["queue_position"] is None
    assert body["summary"] == {"verified_facts": {"x": 1}}
    assert datetime.fromisoformat(body["assigned_at"]) == stored.assigned_at
    assert body["assigned_at"].endswith("Z")
    # The queue now lists it as assigned.
    [item] = _list(client)
    assert (item["status"], item["assigned_agent"]) == ("ASSIGNED", ANA)


def test_a_claim_is_audited_as_the_agent_without_pii(client: TestClient) -> None:
    _add("hnd_audit")

    assert _claim(client, "hnd_audit").status_code == 200

    [audit] = _claim_audits()
    assert audit.actor_type == "agent"
    assert audit.actor_ref == ANA
    assert audit.decision == "allowed"
    assert audit.reason_code is None
    assert audit.payload == {
        "handoff_ref": "hnd_audit",
        "before_status": "QUEUED",
        "after_status": "ASSIGNED",
    }
    # One timestamp for the row and the audit entry.
    assert audit.occurred_at == _stored("hnd_audit").assigned_at
    with get_session_maker()() as session:
        valid, total, _, broken_id, error = verify_chain(session)
    assert (valid, broken_id, error) == (True, None, None)
    assert total == 1


def test_a_claim_extends_a_chain_that_already_has_entries(
    client: TestClient,
) -> None:
    with get_session_maker()() as session:
        append(
            session,
            actor_type="agent",
            actor_ref="admin",
            action="admin.policy_config.updated",
            decision="allowed",
            reason_code=None,
            payload={"version": 1},
        )
        session.commit()
    _add("hnd_chain_1")
    _add("hnd_chain_2")

    assert _claim(client, "hnd_chain_1", ANA).status_code == 200
    assert _claim(client, "hnd_chain_2", BEN).status_code == 200

    with get_session_maker()() as session:
        valid, total, _, broken_id, _ = verify_chain(session)
    assert (valid, total, broken_id) == (True, 3, None)


def test_a_pending_case_can_be_claimed(client: TestClient) -> None:
    _add("hnd_pending", status="PENDING")

    assert _claim(client, "hnd_pending").status_code == 200

    [audit] = _claim_audits()
    assert audit.payload["before_status"] == "PENDING"
    assert _stored("hnd_pending").status == "ASSIGNED"


def test_claiming_again_as_the_same_agent_changes_nothing(
    client: TestClient,
) -> None:
    _add("hnd_again")
    first = _claim(client, "hnd_again")
    assert first.status_code == 200
    audits_after_first = _claim_audits()

    second = _claim(client, "hnd_again")

    assert second.status_code == 200
    assert second.json() == first.json()
    assert _claim_audits() == audits_after_first
    assert len(audits_after_first) == 1


def test_claiming_a_case_another_agent_holds_is_a_409(client: TestClient) -> None:
    _add("hnd_contested")
    assert _claim(client, "hnd_contested", ANA).status_code == 200
    before = _stored("hnd_contested")

    response = _claim(client, "hnd_contested", BEN)

    assert response.status_code == 409
    assert response.json() == {"detail": "claimed_by_another_agent"}
    after = _stored("hnd_contested")
    assert (after.assigned_agent, after.assigned_at) == (ANA, before.assigned_at)
    assert len(_claim_audits()) == 1


def test_claiming_an_unknown_case_is_a_404_and_writes_nothing(
    client: TestClient,
) -> None:
    response = _claim(client, "hnd_nothing")

    assert response.status_code == 404
    assert response.json() == {"detail": "handoff_not_found"}
    assert _claim_audits() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"agent_ref": ""},
        {"agent_ref": "no-at-sign"},
        {"agent_ref": "two@@signs.example"},
        {"agent_ref": "has space@bank.example"},
        {"agent_ref": "a@"},
        {"agent_ref": "x" * 120 + "@bank.example"},
        {"agent_ref": ANA, "extra": True},
    ],
    ids=[
        "missing",
        "empty",
        "not-an-email",
        "two-at-signs",
        "space",
        "no-domain",
        "beyond-the-audit-column",
        "extra-field",
    ],
)
def test_a_claim_needs_an_email_for_the_agent(
    client: TestClient, body: dict[str, Any]
) -> None:
    _add("hnd_invalid")

    response = client.post(f"{HANDOFFS}/hnd_invalid/claim", headers=AUTH, json=body)

    assert response.status_code == 422
    assert _stored("hnd_invalid").assigned_agent is None
    assert _claim_audits() == []


def test_the_shortest_and_longest_agent_refs_are_accepted(
    client: TestClient,
) -> None:
    _add("hnd_short")
    _add("hnd_long")
    longest = "x" * (128 - len("@b.example")) + "@b.example"

    assert _claim(client, "hnd_short", "a@b").status_code == 200
    assert _claim(client, "hnd_long", longest).status_code == 200

    assert _stored("hnd_long").assigned_agent == longest
    assert {row.actor_ref for row in _claim_audits()} == {"a@b", longest}


def test_the_status_change_and_the_audit_row_are_one_transaction(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the claim fails after both writes, neither survives."""
    _add("hnd_atomic")

    real_append = handoff_queue.append_audit

    def failing_append(*args: Any, **kwargs: Any) -> Any:
        real_append(*args, **kwargs)  # the audit row and the update are flushed...
        raise RuntimeError("commit is never reached")  # ...and then it all fails

    monkeypatch.setattr(handoff_queue, "append_audit", failing_append)
    with TestClient(_build_app(), raise_server_exceptions=False) as failing:
        response = failing.post(
            f"{HANDOFFS}/hnd_atomic/claim", headers=AUTH, json={"agent_ref": ANA}
        )

    assert response.status_code == 500
    stored = _stored("hnd_atomic")
    assert (stored.status, stored.assigned_agent, stored.assigned_at) == (
        "QUEUED",
        None,
        None,
    )
    assert _claim_audits() == []


def test_two_agents_claiming_at_the_same_time_leave_exactly_one_winner(
    client: TestClient,
) -> None:
    _add("hnd_race")
    agents = [ANA, BEN] * 4
    barrier = threading.Barrier(len(agents))

    def attempt(agent: str) -> tuple[str, int]:
        with TestClient(_build_app()) as racer:
            barrier.wait()
            return agent, _claim(racer, "hnd_race", agent).status_code

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        outcomes = list(pool.map(attempt, agents))

    winner = _stored("hnd_race").assigned_agent
    assert winner in {ANA, BEN}
    # Every request of the winner succeeded (idempotent); every other one lost.
    assert {(agent, code) for agent, code in outcomes} == {
        (winner, 200),
        (BEN if winner == ANA else ANA, 409),
    }
    [audit] = _claim_audits()
    assert audit.actor_ref == winner
    with get_session_maker()() as session:
        assert verify_chain(session)[0] is True


def test_a_second_claim_waits_for_the_first_transaction_and_then_loses(
    client: TestClient,
) -> None:
    """Deterministic interleaving: the row is held while the second agent asks."""
    _add("hnd_wait")
    maker = get_session_maker()
    first = maker()
    second_outcome: list[BaseException | str] = []

    def second_claim() -> None:
        with maker() as session:
            try:
                claim_handoff(session, "hnd_wait", BEN)
            except ClaimedByAnotherAgentError as exc:
                second_outcome.append(exc)
            else:
                second_outcome.append("claimed")

    try:
        claim_handoff(first, "hnd_wait", ANA)  # flushed, not committed
        thread = threading.Thread(target=second_claim)
        thread.start()
        thread.join(timeout=1.0)
        # Blocked on the lock, not decided from a stale read.
        assert thread.is_alive()
        assert second_outcome == []
        first.commit()
        thread.join(timeout=10.0)
    finally:
        first.close()

    assert not thread.is_alive()
    assert len(second_outcome) == 1
    assert isinstance(second_outcome[0], ClaimedByAnotherAgentError)
    assert _stored("hnd_wait").assigned_agent == ANA
    assert len(_claim_audits()) == 1


# --- the metrics ---------------------------------------------------------------


def _tool_audit(
    action: str,
    decision: str,
    at: datetime,
    *,
    reason_code: str | None = None,
    status: ToolResultStatus = ToolResultStatus.OK,
    card_before: CardStatus | None = None,
    card_after: CardStatus | None = None,
    details: dict[str, Any] | None = None,
    actor: str = "sess_metrics",
) -> None:
    mutating = action in {"card.block", "otp.send", "otp.verify", "handoff.create"}
    payload = AuditPayload(
        verification_state_before=VerificationState.OTP_PENDING,
        verification_state_after=VerificationState.OTP_PENDING,
        status=status,
        reason=None,
        card_state_before=card_before,
        card_state_after=card_after,
        handoff_status=HandoffStatus.QUEUED if action == "handoff.create" else None,
        handoff_priority=HandoffPriority.HIGH if action == "handoff.create" else None,
        idempotency_scope=actor if mutating else None,
        details=details or {},
    )
    with get_session_maker()() as session:
        append(
            session,
            actor_type="customer_session",
            actor_ref=actor,
            action=action,
            decision=decision,
            reason_code=reason_code,
            payload=payload,
            occurred_at=at,
        )
        session.commit()


def _seed_activity(now: datetime) -> None:
    recent = now - timedelta(hours=2)
    stale = now - timedelta(hours=30)
    # Two cards blocked, one repeat on a blocked card, one refusal.
    for _ in range(2):
        _tool_audit(
            "card.block",
            "allowed",
            recent,
            reason_code="POLICY_FLAGGED",
            card_before=CardStatus.ACTIVE,
            card_after=CardStatus.BLOCKED,
            details={"already_blocked": False},
        )
    _tool_audit(
        "card.block",
        "allowed",
        recent,
        card_before=CardStatus.BLOCKED,
        card_after=CardStatus.BLOCKED,
        details={"already_blocked": True},
    )
    _tool_audit(
        "card.block",
        "refused",
        recent,
        reason_code="STATE_NOT_ALLOWED",
        status=ToolResultStatus.REFUSED,
    )
    # OTP: three sent, one code accepted, two rejected, one call refused.
    for _ in range(3):
        _tool_audit("otp.send", "allowed", recent, details={"channel": "EMAIL"})
    _tool_audit("otp.verify", "allowed", recent, details={"verified": True})
    for _ in range(2):
        _tool_audit(
            "otp.verify",
            "allowed",
            recent,
            details={"verified": False, "attempts_remaining": 2},
        )
    _tool_audit(
        "otp.verify",
        "refused",
        recent,
        reason_code="RATE_LIMITED",
        status=ToolResultStatus.REFUSED,
    )
    for ref in ("hnd_aaaaaaaa", "hnd_bbbbbbbb"):
        _tool_audit("handoff.create", "allowed", recent, details={"handoff_ref": ref})
    _tool_audit("customer.match", "allowed", recent, details={"matched": True})
    _tool_audit(
        "kb.search",
        "error",
        recent,
        reason_code="INTERNAL_ERROR",
        status=ToolResultStatus.ERROR,
    )
    # Audit rows that are not tool calls.
    with get_session_maker()() as session:
        append(
            session,
            actor_type="system",
            actor_ref="sess_metrics",
            action="security.customer_otp_locked",
            decision="refused",
            reason_code="RATE_LIMITED",
            payload={"reason": "customer_otp_failure_limit_reached"},
            occurred_at=recent,
        )
        append(
            session,
            actor_type="agent",
            actor_ref="admin",
            action="admin.demo.fixtures.reset",
            decision="allowed",
            reason_code=None,
            payload={"cards_reset": 1},
            occurred_at=recent,
        )
        session.commit()
    # Older than a day: outside the default window, inside a two-day one.
    for _ in range(5):
        _tool_audit(
            "card.block",
            "allowed",
            stale,
            card_before=CardStatus.ACTIVE,
            card_after=CardStatus.BLOCKED,
            details={"already_blocked": False},
        )
    _tool_audit("otp.send", "allowed", stale, details={"channel": "EMAIL"})
    _tool_audit("otp.verify", "allowed", stale, details={"verified": True})


def _seed_window_handoffs(now: datetime) -> None:
    recent = now - timedelta(hours=1)
    _add("hnd_m1", priority="URGENT", department="FRAUD_OPERATIONS", created_at=recent)
    _add("hnd_m2", priority="HIGH", department="FRAUD_OPERATIONS", created_at=recent)
    _add(
        "hnd_m3",
        priority="HIGH",
        department="DISPUTES",
        status="ASSIGNED",
        created_at=recent,
        assigned_agent=ANA,
        assigned_at=recent,
    )
    _add(
        "hnd_m4",
        priority="LOW",
        department="CUSTOMER_SUPPORT",
        status="PENDING",
        created_at=recent,
    )
    _add(
        "hnd_m_old",
        priority="NORMAL",
        department="CUSTOMER_SUPPORT",
        created_at=now - timedelta(hours=40),
    )


def _get_metrics(client: TestClient, query: str = "") -> dict[str, Any]:
    response = client.get(f"{METRICS}{query}", headers=AUTH)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_metrics_over_an_empty_system_are_zero_and_complete(
    client: TestClient,
) -> None:
    body = _get_metrics(client)

    assert set(body) == {
        "generated_at",
        "window_hours",
        "tool_calls",
        "handoffs",
        "cards_blocked",
        "otp",
        "feedback",
        "recent_not_helpful",
        "queue",
        "previous",
    }
    assert body["window_hours"] == 24
    assert body["tool_calls"] == []
    assert body["handoffs"] == {
        "total": 0,
        "by_status": {"QUEUED": 0, "ASSIGNED": 0, "PENDING": 0, "CLOSED": 0},
        "by_priority": {"URGENT": 0, "HIGH": 0, "NORMAL": 0, "LOW": 0},
        "by_department": {
            "FRAUD_OPERATIONS": 0,
            "CUSTOMER_SUPPORT": 0,
            "DISPUTES": 0,
        },
        "by_outcome": {"APPROVED": 0, "REJECTED": 0, "RESOLVED": 0},
    }
    assert body["cards_blocked"] == 0
    assert body["otp"] == {"sent": 0, "verified": 0, "failed": 0}
    assert body["feedback"] == {"helpful": 0, "not_helpful": 0}
    assert body["recent_not_helpful"] == []
    assert body["queue"] == {"waiting": 0, "urgent": 0, "oldest_created_at": None}
    assert body["previous"] == {
        "cards_blocked": 0,
        "otp": {"sent": 0, "verified": 0, "failed": 0},
        "handoffs_total": 0,
        "feedback": {"helpful": 0, "not_helpful": 0},
    }
    generated = datetime.fromisoformat(body["generated_at"])
    assert generated.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - generated) < timedelta(minutes=1)


def test_metrics_count_the_window_and_only_the_window(client: TestClient) -> None:
    now = datetime.now(UTC)
    _seed_activity(now)
    _seed_window_handoffs(now)

    body = _get_metrics(client, "?hours=24")

    assert body["window_hours"] == 24
    assert body["tool_calls"] == [
        {
            "action": "card.block",
            "decision": "allowed",
            "reason_code": None,
            "count": 1,
        },
        {
            "action": "card.block",
            "decision": "allowed",
            "reason_code": "POLICY_FLAGGED",
            "count": 2,
        },
        {
            "action": "card.block",
            "decision": "refused",
            "reason_code": "STATE_NOT_ALLOWED",
            "count": 1,
        },
        {
            "action": "customer.match",
            "decision": "allowed",
            "reason_code": None,
            "count": 1,
        },
        {
            "action": "handoff.create",
            "decision": "allowed",
            "reason_code": None,
            "count": 2,
        },
        {
            "action": "kb.search",
            "decision": "error",
            "reason_code": "INTERNAL_ERROR",
            "count": 1,
        },
        {
            "action": "otp.send",
            "decision": "allowed",
            "reason_code": None,
            "count": 3,
        },
        {
            "action": "otp.verify",
            "decision": "allowed",
            "reason_code": None,
            "count": 3,
        },
        {
            "action": "otp.verify",
            "decision": "refused",
            "reason_code": "RATE_LIMITED",
            "count": 1,
        },
    ]
    assert body["cards_blocked"] == 2
    assert body["otp"] == {"sent": 3, "verified": 1, "failed": 2}
    assert body["handoffs"] == {
        "total": 4,
        "by_status": {"QUEUED": 2, "ASSIGNED": 1, "PENDING": 1, "CLOSED": 0},
        "by_priority": {"URGENT": 1, "HIGH": 2, "NORMAL": 0, "LOW": 1},
        "by_department": {
            "FRAUD_OPERATIONS": 2,
            "CUSTOMER_SUPPORT": 1,
            "DISPUTES": 1,
        },
        "by_outcome": {"APPROVED": 0, "REJECTED": 0, "RESOLVED": 0},
    }


def test_a_wider_window_adds_what_is_older(client: TestClient) -> None:
    now = datetime.now(UTC)
    _seed_activity(now)
    _seed_window_handoffs(now)

    body = _get_metrics(client, "?hours=48")

    assert body["window_hours"] == 48
    assert body["cards_blocked"] == 7
    assert body["otp"] == {"sent": 4, "verified": 2, "failed": 2}
    assert body["handoffs"]["total"] == 5
    assert body["handoffs"]["by_priority"]["NORMAL"] == 1
    block_calls = [
        call
        for call in body["tool_calls"]
        if call["action"] == "card.block"
        and call["decision"] == "allowed"
        and call["reason_code"] is None
    ]
    assert block_calls == [
        {"action": "card.block", "decision": "allowed", "reason_code": None, "count": 6}
    ]


def test_a_narrow_window_leaves_out_the_recent_past(client: TestClient) -> None:
    _seed_activity(datetime.now(UTC))

    body = _get_metrics(client, "?hours=1")

    assert body["tool_calls"] == []
    assert body["cards_blocked"] == 0
    assert body["otp"] == {"sent": 0, "verified": 0, "failed": 0}


def test_metrics_carry_only_names_and_numbers(client: TestClient) -> None:
    now = datetime.now(UTC)
    _seed_activity(now)
    _seed_window_handoffs(now)

    text = client.get(METRICS, headers=AUTH).text

    # No session, agent, case or channel identifiers, nor any address.
    for private in ("sess_metrics", ANA, "hnd_", "@", "session_ref"):
        assert private not in text


@pytest.mark.parametrize("hours", [0, -1, 721, "many"])
def test_metrics_refuse_a_window_out_of_range(client: TestClient, hours: Any) -> None:
    assert client.get(f"{METRICS}?hours={hours}", headers=AUTH).status_code == 422


@pytest.mark.parametrize("hours", [1, 720])
def test_metrics_accept_the_ends_of_the_range(client: TestClient, hours: int) -> None:
    assert _get_metrics(client, f"?hours={hours}")["window_hours"] == hours
