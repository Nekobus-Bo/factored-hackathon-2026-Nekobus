"""An agent's decision on a handoff: close it with an outcome, or escalate it.

ADR-0018. Both are back-office writes on the queue, like the claim in
handoff.queue, and follow its rules: the audit lock first, then the row; the
change and its audit row commit together; the caller re-reads the row.

What each case allows comes from decisions.json, one rule per group of handoff
reasons: the outcomes, the reasons a rejection may give, and the message the
customer receives in es, pt and en. The file is loaded and checked once; a
broken file stops the service at startup instead of failing a close later.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from contracts.tools.handoff_create import (
    Department,
    HandoffPriority,
    HandoffReason,
    HandoffStatus,
)
from sqlalchemy.orm import Session

from banking_core.audit.service import append as append_audit
from banking_core.handoff.queue import (
    ClaimedByAnotherAgentError,
    HandoffNotFoundError,
)
from banking_core.models.ops import Handoff

CLOSE_ACTION = "admin.handoff.closed"
ESCALATE_ACTION = "admin.handoff.escalated"

DECISIONS_PATH_ENV = "HANDOFF_DECISIONS_PATH"
_DEFAULT_PATH = Path(__file__).with_name("decisions.json")
_LANGUAGES = ("es", "pt", "en")
_MAX_MESSAGE = 2000

# The same key audit.service.append serializes chain writers on (see handoff.queue).
_AUDIT_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('ops.audit_log'))"


class HandoffOutcome(StrEnum):
    """How an agent closed a case."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class RejectReason(StrEnum):
    """Why an agent rejected a case. decisions.json picks which apply where."""

    CUSTOMER_RECOGNIZES_CHARGE = "CUSTOMER_RECOGNIZES_CHARGE"
    MADE_BY_FAMILY_MEMBER = "MADE_BY_FAMILY_MEMBER"
    OUT_OF_TIME = "OUT_OF_TIME"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    IDENTITY_NOT_VERIFIED = "IDENTITY_NOT_VERIFIED"
    OTHER = "OTHER"


class DecisionRulesError(ValueError):
    """decisions.json is missing, unreadable or inconsistent."""


class AlreadyClosedError(Exception):
    """The handoff is closed, and this is not a repeat of the same close."""


class DecisionNotAllowedError(Exception):
    """The decision is not one this case allows; `code` says which rule failed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DecisionRule:
    """What the cases of some handoff reasons allow."""

    reasons: tuple[HandoffReason, ...]
    outcomes: tuple[HandoffOutcome, ...]
    approve_requires_verified: bool
    reject_reasons: tuple[RejectReason, ...]
    messages: dict[HandoffOutcome, dict[str, str]]


@dataclass(frozen=True)
class AllowedDecisions:
    """The decisions one case allows now, as the back office offers them."""

    outcomes: list[HandoffOutcome]
    reject_reasons: list[RejectReason]
    escalate_to: list[Department]
    closing_messages: dict[HandoffOutcome, dict[str, str]]


@dataclass(frozen=True)
class DecisionResult:
    """What a call did: the row as it now stands and whether it changed it."""

    handoff: Handoff
    changed: bool


def _parse_rules(raw: Any) -> dict[HandoffReason, DecisionRule]:
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise DecisionRulesError("expected an object with a 'rules' list")
    by_reason: dict[HandoffReason, DecisionRule] = {}
    for index, item in enumerate(raw["rules"]):
        where = f"rules[{index}]"
        try:
            keys = set(item)
            expected = {
                "reasons",
                "outcomes",
                "approve_requires_verified",
                "reject_reasons",
                "messages",
            }
            if keys != expected:
                raise DecisionRulesError(f"{where}: keys must be {sorted(expected)}")
            reasons = tuple(HandoffReason(value) for value in item["reasons"])
            outcomes = tuple(HandoffOutcome(value) for value in item["outcomes"])
            rejects = tuple(RejectReason(value) for value in item["reject_reasons"])
            requires_verified = item["approve_requires_verified"]
        except (TypeError, ValueError) as exc:
            raise DecisionRulesError(f"{where}: {exc}") from exc
        if not isinstance(requires_verified, bool):
            raise DecisionRulesError(f"{where}: approve_requires_verified is a bool")
        if not reasons or not outcomes:
            raise DecisionRulesError(f"{where}: reasons and outcomes cannot be empty")
        if (HandoffOutcome.REJECTED in outcomes) != bool(rejects):
            raise DecisionRulesError(
                f"{where}: reject_reasons are needed exactly when REJECTED is allowed"
            )
        messages_raw = item["messages"]
        if not isinstance(messages_raw, dict) or set(messages_raw) != {
            outcome.value for outcome in outcomes
        }:
            raise DecisionRulesError(f"{where}: one message per outcome")
        messages: dict[HandoffOutcome, dict[str, str]] = {}
        for outcome in outcomes:
            texts = messages_raw[outcome.value]
            if not isinstance(texts, dict) or set(texts) != set(_LANGUAGES):
                raise DecisionRulesError(f"{where}: {outcome.value} needs es, pt, en")
            for language, text in texts.items():
                if (
                    not isinstance(text, str)
                    or not 0 < len(text.strip()) <= _MAX_MESSAGE
                ):
                    raise DecisionRulesError(
                        f"{where}: {outcome.value}.{language} must be 1 to"
                        f" {_MAX_MESSAGE} characters"
                    )
            messages[outcome] = {language: texts[language] for language in _LANGUAGES}
        rule = DecisionRule(reasons, outcomes, requires_verified, rejects, messages)
        for reason in reasons:
            if reason in by_reason:
                raise DecisionRulesError(f"{where}: {reason.value} has two rules")
            by_reason[reason] = rule
    missing = [reason.value for reason in HandoffReason if reason not in by_reason]
    if missing:
        raise DecisionRulesError(f"no rule for {', '.join(missing)}")
    return by_reason


def load_decision_rules(path: Path | None = None) -> dict[HandoffReason, DecisionRule]:
    """Read and check the rules file: HANDOFF_DECISIONS_PATH, or the packaged one."""
    target = path or Path(os.getenv(DECISIONS_PATH_ENV) or _DEFAULT_PATH)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DecisionRulesError(f"cannot read {target}: {exc}") from exc
    return _parse_rules(raw)


@cache
def decision_rules() -> dict[HandoffReason, DecisionRule]:
    """The rules in force, loaded once."""
    return load_decision_rules()


def validate_decision_rules() -> None:
    """Startup check: a broken rules file stops the service."""
    decision_rules()


def _verified_at_handoff(handoff: Handoff) -> bool:
    facts = (handoff.summary or {}).get("verified_facts")
    return isinstance(facts, dict) and facts.get("verification_state") == "VERIFIED"


def allowed_decisions(handoff: Handoff) -> AllowedDecisions:
    """What the back office may offer for this case, whoever looks at it.

    A closed case allows nothing. Approving needs the customer verified when the
    handoff was created, if the rule says so. Escalating goes to any other
    department.
    """
    if handoff.status == HandoffStatus.CLOSED.value:
        return AllowedDecisions([], [], [], {})
    rule = decision_rules()[HandoffReason(handoff.reason)]
    outcomes = [
        outcome
        for outcome in rule.outcomes
        if not (
            outcome is HandoffOutcome.APPROVED
            and rule.approve_requires_verified
            and not _verified_at_handoff(handoff)
        )
    ]
    return AllowedDecisions(
        outcomes=outcomes,
        reject_reasons=list(rule.reject_reasons)
        if HandoffOutcome.REJECTED in outcomes
        else [],
        escalate_to=[d for d in Department if d.value != handoff.department],
        closing_messages={outcome: rule.messages[outcome] for outcome in outcomes},
    )


def _locked_handoff(db_session: Session, handoff_ref: str) -> Handoff:
    # The audit lock first, then the row: the order of the claim and handoff.create.
    if db_session.get_bind().dialect.name == "postgresql":
        db_session.execute(sa.text(_AUDIT_LOCK_SQL))
    handoff = db_session.scalar(
        sa.select(Handoff)
        .where(Handoff.handoff_ref == handoff_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if handoff is None:
        raise HandoffNotFoundError(handoff_ref)
    return handoff


def close_handoff(
    db_session: Session,
    handoff_ref: str,
    agent_ref: str,
    outcome: HandoffOutcome,
    reason: RejectReason | None,
    *,
    now: datetime | None = None,
) -> DecisionResult:
    """Close a case with an outcome, audited, in the caller's transaction.

    A queued case is claimed by the same write. The same close by the same agent
    again changes nothing (a retried request).

    Raises:
        HandoffNotFoundError: If no handoff has that reference.
        AlreadyClosedError: If it is closed by another call.
        ClaimedByAnotherAgentError: If another agent holds it.
        DecisionNotAllowedError: If the outcome or the reason is not allowed.
    """
    handoff = _locked_handoff(db_session, handoff_ref)
    if handoff.status == HandoffStatus.CLOSED.value:
        same = (
            handoff.closed_by == agent_ref
            and handoff.outcome == outcome.value
            and handoff.outcome_reason == (reason.value if reason else None)
        )
        if same:
            return DecisionResult(handoff=handoff, changed=False)
        raise AlreadyClosedError(handoff_ref)
    if handoff.assigned_agent is not None and handoff.assigned_agent != agent_ref:
        raise ClaimedByAnotherAgentError(handoff_ref)

    allowed = allowed_decisions(handoff)
    if outcome not in allowed.outcomes:
        raise DecisionNotAllowedError("outcome_not_allowed")
    if outcome is HandoffOutcome.REJECTED:
        if reason is None:
            raise DecisionNotAllowedError("reason_required")
        if reason not in allowed.reject_reasons:
            raise DecisionNotAllowedError("reason_not_allowed")
    elif reason is not None:
        raise DecisionNotAllowedError("reason_not_allowed")

    closed_at = now or datetime.now(UTC)
    before_status = handoff.status
    claimed = handoff.assigned_agent is None
    if claimed:
        handoff.assigned_agent = agent_ref
        handoff.assigned_at = closed_at
    handoff.status = HandoffStatus.CLOSED.value
    handoff.outcome = outcome.value
    handoff.outcome_reason = reason.value if reason else None
    handoff.closed_by = agent_ref
    handoff.closed_at = closed_at
    # No PII: the agent is the actor, the case an opaque ref, the rest enums.
    append_audit(
        session=db_session,
        actor_type="agent",
        actor_ref=agent_ref,
        action=CLOSE_ACTION,
        decision="allowed",
        reason_code=None,
        payload={
            "handoff_ref": handoff.handoff_ref,
            "before_status": before_status,
            "claimed": claimed,
            "outcome": outcome.value,
            "outcome_reason": handoff.outcome_reason,
        },
        occurred_at=closed_at,
    )
    return DecisionResult(handoff=handoff, changed=True)


def _raise_to_urgent(priority: str) -> str:
    return (
        HandoffPriority.URGENT.value
        if priority != HandoffPriority.URGENT.value
        else priority
    )


def escalate_handoff(
    db_session: Session,
    handoff_ref: str,
    agent_ref: str,
    department: Department,
    raise_to_urgent: bool,
    *,
    now: datetime | None = None,
) -> DecisionResult:
    """Send a case back to the queue, in another department or more urgent.

    The case loses its agent. The priority only goes up, to URGENT, never down.

    Raises:
        HandoffNotFoundError: If no handoff has that reference.
        AlreadyClosedError: If it is closed.
        ClaimedByAnotherAgentError: If another agent holds it.
        DecisionNotAllowedError: `nothing_to_escalate` if neither the department
            nor the priority would change.
    """
    handoff = _locked_handoff(db_session, handoff_ref)
    if handoff.status == HandoffStatus.CLOSED.value:
        raise AlreadyClosedError(handoff_ref)
    if handoff.assigned_agent is not None and handoff.assigned_agent != agent_ref:
        raise ClaimedByAnotherAgentError(handoff_ref)

    priority_after = (
        _raise_to_urgent(handoff.priority) if raise_to_urgent else handoff.priority
    )
    if department.value == handoff.department and priority_after == handoff.priority:
        raise DecisionNotAllowedError("nothing_to_escalate")

    escalated_at = now or datetime.now(UTC)
    payload = {
        "handoff_ref": handoff.handoff_ref,
        "before_status": handoff.status,
        "department_before": handoff.department,
        "department_after": department.value,
        "priority_before": handoff.priority,
        "priority_after": priority_after,
    }
    handoff.status = HandoffStatus.QUEUED.value
    handoff.assigned_agent = None
    handoff.assigned_at = None
    handoff.department = department.value
    handoff.priority = priority_after
    append_audit(
        session=db_session,
        actor_type="agent",
        actor_ref=agent_ref,
        action=ESCALATE_ACTION,
        decision="allowed",
        reason_code=None,
        payload=payload,
        occurred_at=escalated_at,
    )
    return DecisionResult(handoff=handoff, changed=True)
