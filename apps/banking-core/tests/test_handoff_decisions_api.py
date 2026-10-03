"""An agent's decisions on a handoff, and the feedback the back office sees (ADR-0018).

`POST /v1/admin/handoffs/{ref}/close` and `.../escalate`: who may decide, what
each case allows (from decisions.json), the audit row in the same transaction,
idempotent repeats and one winner in a race. Then the detail's feedback and
allowed decisions, the list's disputed amount, the metrics additions, and the
checks on the rules file.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from banking_core.api import admin_router
from banking_core.audit.service import verify_chain
from banking_core.control.policy import Decision
from banking_core.db.session import get_session_maker
from banking_core.handoff.decisions import (
    DecisionRulesError,
    load_decision_rules,
)
from banking_core.handoff.feedback import record_feedback
from banking_core.handoff.tools import execute_handoff_create
from banking_core.models.ops import Handoff
from contracts.envelope import VerificationState
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffPriority,
    HandoffReason,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

ADMIN_TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
HANDOFFS = "/v1/admin/handoffs"
METRICS = "/v1/admin/metrics"
CLOSED = "admin.handoff.closed"
ESCALATED = "admin.handoff.escalated"
ANA = "ana.agent@bank.example"
BEN = "ben.agent@bank.example"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
VERIFIED = {"verified_facts": {"verification_state": "VERIFIED"}}
ANONYMOUS = {"verified_facts": {"verification_state": "ANONYMOUS"}}
PACKAGED_RULES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "banking_core"
    / "handoff"
    / "decisions.json"
)


def _clear() -> None:
    with get_session_maker()() as session:
        session.execute(sa.text("DELETE FROM ops.handoff"))
        session.commit()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    return app


@pytest.fixture
def client(db_session: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_TOKEN)
    _clear()
    try:
        with TestClient(_build_app()) as test_client:
            yield test_client
    finally:
        _clear()


def _add(
    ref: str,
    *,
    reason: str = "DISPUTE_CLAIM",
    priority: str = "HIGH",
    department: str = "DISPUTES",
    status: str = "QUEUED",
    summary: dict[str, Any] | None = None,
    assigned_agent: str | None = None,
    created_at: datetime = T0,
) -> None:
    with get_session_maker()() as session:
        session.add(
            Handoff(
                handoff_ref=ref,
                session_ref=f"sess_{ref}",
                reason=reason,
                priority=priority,
                department=department,
                status=status,
                summary=summary if summary is not None else VERIFIED,
                idempotency_scope=f"sess_{ref}",
                created_at=created_at,
                assigned_agent=assigned_agent,
                assigned_at=created_at if assigned_agent else None,
            )
        )
        session.commit()


def _close(
    client: TestClient,
    ref: str,
    outcome: str,
    reason: str | None = None,
    agent: str = ANA,
) -> Any:
    body: dict[str, Any] = {"agent_ref": agent, "outcome": outcome}
    if reason is not None:
        body["reason"] = reason
    return client.post(f"{HANDOFFS}/{ref}/close", headers=AUTH, json=body)


def _escalate(
    client: TestClient,
    ref: str,
    department: str,
    raise_to_urgent: bool = False,
    agent: str = ANA,
) -> Any:
    return client.post(
        f"{HANDOFFS}/{ref}/escalate",
        headers=AUTH,
        json={
            "agent_ref": agent,
            "department": department,
            "raise_to_urgent": raise_to_urgent,
        },
    )


def _audits(action: str) -> list[sa.Row[Any]]:
    with get_session_maker()() as session:
        return list(
            session.execute(
                sa.text(
                    "SELECT actor_type, actor_ref, decision, payload"
                    " FROM ops.audit_log WHERE action = :action ORDER BY id"
                ),
                {"action": action},
            ).all()
        )


def _stored(ref: str) -> Handoff:
    with get_session_maker()() as session:
        row = session.scalar(sa.select(Handoff).where(Handoff.handoff_ref == ref))
        assert row is not None
        session.expunge(row)
        return row


# --- close ----------------------------------------------------------------------


def test_closing_a_queued_case_claims_it_closes_it_and_audits_both(
    client: TestClient,
) -> None:
    _add("hnd_close")

    response = _close(client, "hnd_close", "APPROVED")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "CLOSED"
    assert body["outcome"] == "APPROVED"
    assert body["outcome_reason"] is None
    assert body["closed_by"] == ANA
    assert body["assigned_agent"] == ANA
    assert body["closed_at"] is not None
    assert body["queue_position"] is None
    # A closed case allows nothing more, and keeps what the customer was sent.
    decisions = body["decisions"]
    assert decisions["outcomes"] == []
    assert decisions["reject_reasons"] == []
    assert decisions["escalate_to"] == []
    assert set(decisions["closing_messages"]) == {"APPROVED"}
    [audit] = _audits(CLOSED)
    assert audit.actor_type == "agent"
    assert audit.actor_ref == ANA
    assert audit.decision == "allowed"
    assert audit.payload["handoff_ref"] == "hnd_close"
    assert audit.payload["before_status"] == "QUEUED"
    assert audit.payload["claimed"] is True
    assert audit.payload["outcome"] == "APPROVED"
    with get_session_maker()() as session:
        assert verify_chain(session)[0] is True


def test_the_same_close_again_changes_nothing(client: TestClient) -> None:
    _add("hnd_twice")
    first = _close(client, "hnd_twice", "REJECTED", "OUT_OF_TIME")

    again = _close(client, "hnd_twice", "REJECTED", "OUT_OF_TIME")

    assert again.status_code == 200
    assert again.json()["closed_at"] == first.json()["closed_at"]
    assert len(_audits(CLOSED)) == 1


@pytest.mark.parametrize(
    ("outcome", "reason", "agent"),
    [
        ("APPROVED", None, ANA),
        ("REJECTED", "INSUFFICIENT_EVIDENCE", ANA),
        ("REJECTED", "OUT_OF_TIME", BEN),
    ],
    ids=["other-outcome", "other-reason", "other-agent"],
)
def test_a_different_close_of_a_closed_case_is_refused(
    client: TestClient, outcome: str, reason: str | None, agent: str
) -> None:
    _add("hnd_done")
    assert _close(client, "hnd_done", "REJECTED", "OUT_OF_TIME").status_code == 200

    response = _close(client, "hnd_done", outcome, reason, agent)

    assert response.status_code == 409
    assert response.json() == {"detail": "already_closed"}
    assert len(_audits(CLOSED)) == 1


def test_a_case_another_agent_holds_cannot_be_closed(client: TestClient) -> None:
    _add("hnd_bens", status="ASSIGNED", assigned_agent=BEN)

    response = _close(client, "hnd_bens", "APPROVED")

    assert response.status_code == 409
    assert response.json() == {"detail": "claimed_by_another_agent"}
    assert _stored("hnd_bens").status == "ASSIGNED"
    assert _audits(CLOSED) == []


def test_the_holder_closes_without_a_second_claim(client: TestClient) -> None:
    _add("hnd_mine", status="ASSIGNED", assigned_agent=ANA)

    body = _close(client, "hnd_mine", "APPROVED").json()

    assert body["status"] == "CLOSED"
    [audit] = _audits(CLOSED)
    assert audit.payload["before_status"] == "ASSIGNED"
    assert audit.payload["claimed"] is False


@pytest.mark.parametrize(
    ("reason", "summary", "outcome", "reject", "code"),
    [
        # Approving a dispute needs the customer verified at the handoff.
        ("DISPUTE_CLAIM", ANONYMOUS, "APPROVED", None, "outcome_not_allowed"),
        ("SUSPECTED_FRAUD", {}, "APPROVED", None, "outcome_not_allowed"),
        # A customer request is closed as resolved, never approved or rejected.
        ("CUSTOMER_REQUEST", VERIFIED, "APPROVED", None, "outcome_not_allowed"),
        ("CUSTOMER_REQUEST", VERIFIED, "REJECTED", "OTHER", "outcome_not_allowed"),
        ("DISPUTE_CLAIM", VERIFIED, "RESOLVED", None, "outcome_not_allowed"),
        # A rejection names a reason this kind of case allows; nothing else does.
        ("DISPUTE_CLAIM", VERIFIED, "REJECTED", None, "reason_required"),
        (
            "DISPUTE_CLAIM",
            VERIFIED,
            "REJECTED",
            "MADE_BY_FAMILY_MEMBER",
            "reason_not_allowed",
        ),
        ("DISPUTE_CLAIM", VERIFIED, "APPROVED", "OTHER", "reason_not_allowed"),
    ],
    ids=[
        "approve-unverified-dispute",
        "approve-fraud-without-facts",
        "approve-request",
        "reject-request",
        "resolve-dispute",
        "reject-without-reason",
        "reject-with-foreign-reason",
        "approve-with-reason",
    ],
)
def test_a_decision_the_case_does_not_allow_is_refused(
    client: TestClient,
    reason: str,
    summary: dict[str, Any],
    outcome: str,
    reject: str | None,
    code: str,
) -> None:
    _add("hnd_rule", reason=reason, summary=summary)

    response = _close(client, "hnd_rule", outcome, reject)

    assert response.status_code == 409
    assert response.json() == {"detail": code}
    stored = _stored("hnd_rule")
    assert (stored.status, stored.assigned_agent) == ("QUEUED", None)
    assert _audits(CLOSED) == []


@pytest.mark.parametrize(
    ("reason", "summary", "outcome", "reject"),
    [
        ("UNRECOGNIZED_TRANSACTION", VERIFIED, "APPROVED", None),
        ("DISPUTE_CLAIM", ANONYMOUS, "REJECTED", "IDENTITY_NOT_VERIFIED"),
        ("SUSPECTED_FRAUD", VERIFIED, "REJECTED", "MADE_BY_FAMILY_MEMBER"),
        # A locked customer is not verified by definition; the agent checks another way.
        ("CUSTOMER_LOCKED", ANONYMOUS, "APPROVED", None),
        ("VERIFICATION_FAILED", ANONYMOUS, "REJECTED", "OTHER"),
        ("CUSTOMER_REQUEST", ANONYMOUS, "RESOLVED", None),
    ],
)
def test_every_kind_of_case_has_its_allowed_close(
    client: TestClient,
    reason: str,
    summary: dict[str, Any],
    outcome: str,
    reject: str | None,
) -> None:
    _add("hnd_ok", reason=reason, summary=summary)

    response = _close(client, "hnd_ok", outcome, reject)

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == outcome
    assert response.json()["outcome_reason"] == reject


def test_closing_an_unknown_case_is_404(client: TestClient) -> None:
    response = _close(client, "hnd_nobody", "APPROVED")

    assert response.status_code == 404
    assert response.json() == {"detail": "handoff_not_found"}


@pytest.mark.parametrize(
    "body",
    [
        {"agent_ref": ANA, "outcome": "MAYBE"},
        {"agent_ref": ANA, "outcome": "REJECTED", "reason": "BECAUSE"},
        {"agent_ref": "not-an-email", "outcome": "APPROVED"},
        {"agent_ref": ANA, "outcome": "APPROVED", "note": "free text"},
        {"outcome": "APPROVED"},
    ],
    ids=["bad-outcome", "bad-reason", "bad-agent", "extra-field", "no-agent"],
)
def test_a_malformed_close_is_422(client: TestClient, body: dict[str, Any]) -> None:
    _add("hnd_bad")

    response = client.post(f"{HANDOFFS}/hnd_bad/close", headers=AUTH, json=body)

    assert response.status_code == 422
    assert _audits(CLOSED) == []


def test_two_agents_closing_at_the_same_time_leave_exactly_one_winner(
    client: TestClient,
) -> None:
    _add("hnd_race")
    agents = [ANA, BEN] * 4
    barrier = threading.Barrier(len(agents))

    def attempt(agent: str) -> tuple[str, int]:
        with TestClient(_build_app()) as racer:
            barrier.wait()
            return agent, _close(racer, "hnd_race", "APPROVED", agent=agent).status_code

    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        outcomes = list(pool.map(attempt, agents))

    winner = _stored("hnd_race").closed_by
    assert winner in {ANA, BEN}
    loser = BEN if winner == ANA else ANA
    assert {(agent, code) for agent, code in outcomes} == {(winner, 200), (loser, 409)}
    assert len(_audits(CLOSED)) == 1
    with get_session_maker()() as session:
        assert verify_chain(session)[0] is True


def test_a_closed_handoff_is_not_open_for_handoff_create(client: TestClient) -> None:
    """After a close the same session may hand off again, as a new case."""

    def create() -> Any:
        with get_session_maker()() as session:
            return execute_handoff_create(
                db_session=session,
                holder_customer_id=None,
                args=HandoffCreateInput(
                    reason=HandoffReason.CUSTOMER_REQUEST,
                    summary="Customer asks for a person again.",
                    priority=HandoffPriority.NORMAL,
                    department=Department.CUSTOMER_SUPPORT,
                ),
                policy_decision=Decision(allowed=True),
                idempotency_scope="sess_again",
                verification_state_before=VerificationState.ANONYMOUS,
                verification_state_after=VerificationState.HANDED_OFF,
                session_id="sess_again",
            )

    first = create().output.handoff_id
    assert _close(client, first, "RESOLVED").status_code == 200

    second = create().output.handoff_id

    assert second != first


# --- escalate --------------------------------------------------------------------


def test_escalating_sends_the_case_back_to_the_queue_elsewhere(
    client: TestClient,
) -> None:
    _add("hnd_up", status="ASSIGNED", assigned_agent=ANA, priority="HIGH")

    response = _escalate(client, "hnd_up", "FRAUD_OPERATIONS", raise_to_urgent=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["assigned_agent"] is None
    assert body["assigned_at"] is None
    assert body["department"] == "FRAUD_OPERATIONS"
    assert body["priority"] == "URGENT"
    assert body["queue_position"] == 1
    [audit] = _audits(ESCALATED)
    assert audit.actor_ref == ANA
    assert audit.payload == {
        "handoff_ref": "hnd_up",
        "before_status": "ASSIGNED",
        "department_before": "DISPUTES",
        "department_after": "FRAUD_OPERATIONS",
        "priority_before": "HIGH",
        "priority_after": "URGENT",
    }


def test_escalating_in_place_only_raises_the_priority(client: TestClient) -> None:
    _add("hnd_raise", priority="NORMAL")

    body = _escalate(client, "hnd_raise", "DISPUTES", raise_to_urgent=True).json()

    assert (body["department"], body["priority"]) == ("DISPUTES", "URGENT")


@pytest.mark.parametrize(
    ("priority", "raise_to_urgent"),
    [("HIGH", False), ("URGENT", True)],
    ids=["same-department", "already-urgent"],
)
def test_an_escalation_that_changes_nothing_is_refused(
    client: TestClient, priority: str, raise_to_urgent: bool
) -> None:
    _add("hnd_same", priority=priority)

    response = _escalate(client, "hnd_same", "DISPUTES", raise_to_urgent)

    assert response.status_code == 409
    assert response.json() == {"detail": "nothing_to_escalate"}
    assert _audits(ESCALATED) == []


def test_escalating_never_lowers_the_priority(client: TestClient) -> None:
    _add("hnd_urgent", priority="URGENT")

    body = _escalate(client, "hnd_urgent", "CUSTOMER_SUPPORT").json()

    assert body["priority"] == "URGENT"


def test_a_closed_or_foreign_case_cannot_be_escalated(client: TestClient) -> None:
    _add("hnd_closed")
    _close(client, "hnd_closed", "APPROVED")
    _add("hnd_foreign", status="ASSIGNED", assigned_agent=BEN)

    closed = _escalate(client, "hnd_closed", "FRAUD_OPERATIONS")
    foreign = _escalate(client, "hnd_foreign", "FRAUD_OPERATIONS")

    assert (closed.status_code, closed.json()) == (409, {"detail": "already_closed"})
    assert (foreign.status_code, foreign.json()) == (
        409,
        {"detail": "claimed_by_another_agent"},
    )
    assert _audits(ESCALATED) == []


def test_after_an_escalation_another_agent_can_claim_it(client: TestClient) -> None:
    _add("hnd_pass", status="ASSIGNED", assigned_agent=ANA)
    _escalate(client, "hnd_pass", "FRAUD_OPERATIONS")

    response = client.post(
        f"{HANDOFFS}/hnd_pass/claim", headers=AUTH, json={"agent_ref": BEN}
    )

    assert response.status_code == 200
    assert response.json()["assigned_agent"] == BEN


# --- what the detail and the list carry -------------------------------------------


def test_the_detail_lists_what_the_case_allows(client: TestClient) -> None:
    _add("hnd_unverified", summary=ANONYMOUS)
    _add("hnd_request", reason="CUSTOMER_REQUEST", department="CUSTOMER_SUPPORT")

    unverified = client.get(f"{HANDOFFS}/hnd_unverified", headers=AUTH).json()
    request = client.get(f"{HANDOFFS}/hnd_request", headers=AUTH).json()

    assert unverified["decisions"]["outcomes"] == ["REJECTED"]
    assert unverified["decisions"]["reject_reasons"] == [
        "CUSTOMER_RECOGNIZES_CHARGE",
        "OUT_OF_TIME",
        "INSUFFICIENT_EVIDENCE",
        "IDENTITY_NOT_VERIFIED",
    ]
    assert set(unverified["decisions"]["closing_messages"]) == {"REJECTED"}
    assert set(unverified["decisions"]["closing_messages"]["REJECTED"]) == {
        "es",
        "pt",
        "en",
    }
    assert request["decisions"]["outcomes"] == ["RESOLVED"]
    assert request["decisions"]["reject_reasons"] == []
    assert request["decisions"]["escalate_to"] == ["FRAUD_OPERATIONS", "DISPUTES"]


def test_the_detail_carries_the_customers_answer(client: TestClient) -> None:
    _add("hnd_rated")
    with get_session_maker()() as session:
        record_feedback(session, "sess_hnd_rated", False, now=T0)
        session.commit()

    body = client.get(f"{HANDOFFS}/hnd_rated", headers=AUTH).json()

    assert body["feedback"] == {"helpful": False, "recorded_at": "2026-09-01T12:00:00Z"}


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            {
                "verified_facts": {
                    "disputed_transaction": {
                        "amount_minor": 245000000,
                        "currency": "COP",
                    }
                }
            },
            {"amount_minor": 245000000, "currency": "COP"},
        ),
        ({"verified_facts": {}}, None),
        ({"verified_facts": {"disputed_transaction": {"amount_minor": "12"}}}, None),
        (
            {
                "verified_facts": {
                    "disputed_transaction": {"amount_minor": 5, "currency": "pesos"}
                }
            },
            None,
        ),
        ({}, None),
    ],
    ids=["amount", "no-charge", "text-amount", "bad-currency", "no-facts"],
)
def test_the_list_shows_the_disputed_amount_when_there_is_one(
    client: TestClient, summary: dict[str, Any], expected: dict[str, Any] | None
) -> None:
    _add("hnd_amount", summary=summary)

    [item] = client.get(HANDOFFS, headers=AUTH).json()["items"]

    assert item["disputed_amount"] == expected


def test_the_list_can_show_closed_cases(client: TestClient) -> None:
    _add("hnd_open")
    _add("hnd_shut")
    _close(client, "hnd_shut", "APPROVED")

    default = client.get(HANDOFFS, headers=AUTH).json()["items"]
    closed = client.get(f"{HANDOFFS}?status=CLOSED", headers=AUTH).json()["items"]

    assert [item["handoff_ref"] for item in default] == ["hnd_open"]
    assert [item["handoff_ref"] for item in closed] == ["hnd_shut"]


# --- metrics ---------------------------------------------------------------------


def _rate(ref: str, helpful: bool, at: datetime) -> None:
    with get_session_maker()() as session:
        record_feedback(session, f"sess_{ref}", helpful, now=at)
        session.commit()


def test_metrics_count_feedback_the_queue_outcomes_and_the_previous_window(
    client: TestClient,
) -> None:
    now = datetime.now(UTC)
    recent, older = now - timedelta(hours=2), now - timedelta(hours=30)
    # This window: three handoffs, two answers (one no), one closed.
    _add("hnd_yes", created_at=recent)
    _add("hnd_no", reason="CUSTOMER_LOCKED", created_at=recent)
    _add("hnd_quiet", priority="URGENT", created_at=recent)
    _rate("hnd_yes", True, recent)
    _rate("hnd_no", False, recent + timedelta(minutes=5))
    _close(client, "hnd_yes", "APPROVED")
    # The window before: one handoff, answered yes, still waiting.
    _add("hnd_before", created_at=older)
    _rate("hnd_before", True, older)

    body = client.get(f"{METRICS}?hours=24", headers=AUTH).json()

    assert body["feedback"] == {"helpful": 1, "not_helpful": 1}
    assert body["recent_not_helpful"] == [
        {
            "handoff_ref": "hnd_no",
            "reason": "CUSTOMER_LOCKED",
            "recorded_at": body["recent_not_helpful"][0]["recorded_at"],
        }
    ]
    assert body["handoffs"]["by_status"]["CLOSED"] == 1
    assert body["handoffs"]["by_outcome"] == {
        "APPROVED": 1,
        "REJECTED": 0,
        "RESOLVED": 0,
    }
    # The queue is now: the older case waits too, and one waiting case is urgent.
    assert body["queue"]["waiting"] == 3
    assert body["queue"]["urgent"] == 1
    assert body["queue"]["oldest_created_at"] is not None
    assert body["previous"] == {
        "cards_blocked": 0,
        "otp": {"sent": 0, "verified": 0, "failed": 0},
        "handoffs_total": 1,
        "feedback": {"helpful": 1, "not_helpful": 0},
    }


# --- the rules file ---------------------------------------------------------------


def test_the_packaged_rules_cover_every_reason() -> None:
    rules = load_decision_rules(PACKAGED_RULES)

    assert set(rules) == set(HandoffReason)


def _write_rules(tmp_path: Path, mutate: Any) -> Path:
    raw = json.loads(PACKAGED_RULES.read_text(encoding="utf-8"))
    mutate(raw)
    target = tmp_path / "decisions.json"
    target.write_text(json.dumps(raw), encoding="utf-8")
    return target


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["rules"].pop(),
        lambda raw: raw["rules"].append(raw["rules"][0]),
        lambda raw: raw["rules"][0].update(reject_reasons=[]),
        lambda raw: raw["rules"][3].update(reject_reasons=["OTHER"]),
        lambda raw: raw["rules"][0]["messages"]["APPROVED"].pop("pt"),
        lambda raw: raw["rules"][0]["messages"].pop("REJECTED"),
        lambda raw: raw["rules"][0]["messages"]["APPROVED"].update(es="  "),
        lambda raw: raw["rules"][0].update(outcomes=["APPROVED", "MAYBE"]),
        lambda raw: raw["rules"][0].update(approve_requires_verified="yes"),
        lambda raw: raw["rules"][0].update(note="extra"),
    ],
    ids=[
        "reason-without-rule",
        "reason-twice",
        "reject-without-reasons",
        "reasons-without-reject",
        "missing-language",
        "missing-message",
        "blank-message",
        "unknown-outcome",
        "flag-not-bool",
        "extra-key",
    ],
)
def test_a_broken_rules_file_is_refused(tmp_path: Path, mutate: Any) -> None:
    with pytest.raises(DecisionRulesError):
        load_decision_rules(_write_rules(tmp_path, mutate))


def test_an_unreadable_rules_file_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "decisions.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(DecisionRulesError):
        load_decision_rules(broken)
    with pytest.raises(DecisionRulesError):
        load_decision_rules(tmp_path / "missing.json")
