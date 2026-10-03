"""Implementation of handoff.create tool in banking-core.

Rules (ADR-0003 Appendix A, AGENTS rule 4):
- Available in every verification state, including LOCKED: a locked customer
  always reaches a human. The holder is optional for that reason.
- The four elements of the structured handoff are assembled server-side:
  verified facts and verification method come from the session state, actions
  taken from this session's audit rows; only the open questions carry the
  model's summary, labeled as unverified.
- Priority is the highest of the requested one and what policy flags and the
  session state require; the model can raise it, never lower it.
- A session that remembers a handoff requirement (a card.block decided one,
  ADR-0003 amendment 2026-09-29) gets at least that priority and always that
  department, whatever the model asked for: banking-core raises, never lowers.
- A transaction_id names the disputed charge. It is loaded from the database
  for the session holder, and its amount, currency, merchant, date and masked
  card go into the server-built verified facts; an id that does not resolve
  raises TransactionNotFoundError, the same for every reason.
- The queue row and its audit row commit in one transaction; the receipt is
  then re-read from the database.
- At most one open handoff (QUEUED, ASSIGNED or PENDING) per banking session: a
  further call returns the existing handoff instead of queueing a duplicate, and
  is audited like any other call. A customer who asks twice reaches the same
  human once. If the session's requirement asks for more priority than that
  handoff has, the handoff is raised to it (and the raise is audited) rather
  than answered as it was; only the requirement raises it, a higher priority
  requested by the model does not.
"""

import secrets
import string
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from contracts.audit import AuditDetail, AuditPayload
from contracts.envelope import (
    Receipt,
    ResourceState,
    ToolResultStatus,
    VerificationState,
)
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffCreateOutput,
    HandoffPriority,
    HandoffRequirement,
    HandoffRequirementLevel,
    HandoffStatus,
    HandoffSummary,
)
from sqlalchemy.orm import Session

from banking_core.audit.service import append as append_audit
from banking_core.control.policy import Decision
from banking_core.handoff.queue import PRIORITY_ORDER, queue_position
from banking_core.models.ops import AuditLog, Handoff
from banking_core.transactions.lookup import (
    DisputedTransaction,
    TransactionNotFoundError,
    load_disputed_transaction,
)

ACTION = "handoff.create"

# Every status the queue holds is an open one (see ck_handoff_status).
# A closed handoff (ADR-0018) is not open: the session may hand off again.
_OPEN_STATUSES = tuple(
    status.value for status in HandoffStatus if status is not HandoffStatus.CLOSED
)

_VERIFICATION_METHOD = {
    VerificationState.ANONYMOUS: "none",
    VerificationState.IDENTIFIED: "document_match_only",
    VerificationState.OTP_PENDING: "document_match_otp_pending",
    VerificationState.VERIFIED: "document_match_and_otp",
    VerificationState.LOCKED: "locked_after_failed_verification",
    VerificationState.HANDED_OFF: "previously_handed_off",
}


@dataclass(frozen=True)
class HandoffCreateResult:
    """Contract output plus the priority actually queued."""

    output: HandoffCreateOutput
    priority: HandoffPriority


def resolve_priority(
    requested: HandoffPriority,
    policy_decision: Decision,
    verification_state: VerificationState,
) -> HandoffPriority:
    """Highest of the requested priority and the policy/state floor."""
    floor = HandoffPriority.LOW
    if "PRIORITY" in policy_decision.flags:
        floor = HandoffPriority.URGENT
    elif (
        "HANDOFF_REQUIRED" in policy_decision.flags
        or verification_state == VerificationState.LOCKED
    ):
        floor = HandoffPriority.HIGH
    return max(requested, floor, key=PRIORITY_ORDER.index)


def _raise_to(priority: HandoffPriority, floor: HandoffPriority) -> HandoffPriority:
    """The higher of two priorities."""
    return max(priority, floor, key=PRIORITY_ORDER.index)


def _applicable_requirement(
    requirement: HandoffRequirement | None,
) -> HandoffRequirement | None:
    """The session requirement when it asks for anything (NONE asks for nothing)."""
    if requirement is None or requirement.level is HandoffRequirementLevel.NONE:
        return None
    return requirement


def _disputed_transaction_facts(disputed: DisputedTransaction) -> dict[str, Any]:
    """The database facts about the disputed charge, as verified handoff facts."""
    return {
        "transaction_id": disputed.transaction_id,
        "amount_minor": disputed.amount_minor,
        "currency": disputed.currency,
        "merchant": disputed.merchant_name,
        "posted_at": disputed.posted_at.isoformat(),
        "card_masked": disputed.card_masked,
    }


def _new_handoff_ref() -> str:
    # Letters only: opaque refs must never carry 12+ digits (PAN guard).
    return "hnd_" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


def _lock_session_handoffs(db_session: Session, session_id: str) -> None:
    """Serialize handoff creation per session inside this transaction.

    The dispatcher already serializes a session's calls with its Redis lock; this
    keeps "one open handoff per session" true even if that lock expires mid-call.
    """
    bind = db_session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db_session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"handoff.create:{session_id}"},
        )


def _open_handoff(db_session: Session, session_id: str) -> Handoff | None:
    return db_session.scalar(
        sa.select(Handoff)
        .where(Handoff.session_ref == session_id, Handoff.status.in_(_OPEN_STATUSES))
        .order_by(Handoff.created_at, Handoff.id)
        .limit(1)
    )


def _actions_taken(db_session: Session, session_ref: str) -> list[dict[str, Any]]:
    rows = db_session.scalars(
        sa.select(AuditLog)
        .where(AuditLog.actor_ref == session_ref)
        .order_by(AuditLog.id)
    ).all()
    return [
        {
            "action": row.action,
            "decision": row.decision,
            "reason_code": row.reason_code,
            "audit_id": f"aud_{row.id:08d}",
        }
        for row in rows
    ]


def reread_handoff_create_result(
    db_session: Session,
    existing_output: HandoffCreateOutput,
) -> HandoffCreateResult:
    """Refresh an idempotent handoff response from committed queue/audit rows."""
    db_session.expire_all()
    stored = db_session.scalar(
        sa.select(Handoff).where(Handoff.handoff_ref == existing_output.handoff_id)
    )
    audit_id = int(existing_output.receipt.audit_id.removeprefix("aud_"))
    audit = db_session.get(AuditLog, audit_id)
    if stored is None or audit is None:
        raise RuntimeError("handoff receipt could not be re-read from the database")

    receipt = Receipt(
        action=ACTION,
        target_masked=stored.handoff_ref,
        # Not stored anywhere: NONE for a new handoff, the open status for a repeat.
        state_before=existing_output.receipt.state_before,
        state_after=ResourceState(stored.status),
        verified_at=stored.created_at,
        audit_id=f"aud_{audit.id:08d}",
    )
    refreshed_output = existing_output.model_copy(
        update={
            "handoff_id": stored.handoff_ref,
            "status": HandoffStatus(stored.status),
            "department": Department(stored.department),
            "priority": HandoffPriority(stored.priority),
            "summary": HandoffSummary.model_validate(stored.summary),
            "created_at": stored.created_at,
            "receipt": receipt,
        }
    )
    return HandoffCreateResult(
        output=refreshed_output,
        priority=HandoffPriority(stored.priority),
    )


def execute_handoff_create(
    db_session: Session,
    holder_customer_id: str | uuid.UUID | None,
    args: HandoffCreateInput,
    policy_decision: Decision,
    idempotency_scope: str,
    verification_state_before: VerificationState,
    verification_state_after: VerificationState,
    session_id: str,
    session_requirement: HandoffRequirement | None = None,
    *,
    commit: bool = True,
) -> HandoffCreateResult:
    """Queue a handoff and re-read its receipt within the caller's transaction.

    `session_requirement` is the strongest requirement banking-core remembers for
    the session (never from the model): its priority is a floor for the queued
    priority and its department replaces the requested one.

    When the session already has an open handoff nothing is queued: that handoff
    is returned (receipt state_before = state_after = its status) and the call is
    audited with already_open; a session requirement with a higher priority
    raises that handoff to it.

    When ``commit`` is false, the dispatcher commits the handoff, audit and
    idempotency record atomically.

    Raises:
        ValueError: If policy_decision does not allow the call.
        TransactionNotFoundError: If args.transaction_id is not a transaction of
            the holder (missing, someone else's, or there is no holder).
    """
    if not policy_decision.allowed:
        raise ValueError("handoff.create requires an allowed policy decision")
    holder_id = (
        uuid.UUID(str(holder_customer_id)) if holder_customer_id is not None else None
    )
    priority = resolve_priority(
        args.priority, policy_decision, verification_state_before
    )
    department = args.department
    requirement = _applicable_requirement(session_requirement)
    requirement_details: dict[str, AuditDetail] = {}
    if requirement is not None:
        requirement_priority = requirement.priority or HandoffPriority.LOW
        floored = _raise_to(priority, requirement_priority)
        if floored != priority:
            requirement_details["priority_raised_from"] = priority.value
            priority = floored
        if requirement.department is not None and requirement.department != department:
            requirement_details["department_requested"] = department.value
            department = requirement.department
        requirement_details["handoff_requirement"] = requirement.level.value

    disputed: DisputedTransaction | None = None
    if args.transaction_id is not None:
        if holder_id is None:
            raise TransactionNotFoundError
        disputed = load_disputed_transaction(db_session, holder_id, args.transaction_id)

    try:
        _lock_session_handoffs(db_session, session_id)
        existing = _open_handoff(db_session, session_id)
        extra_details: dict[str, AuditDetail] = {}
        if existing is not None:
            handoff_ref = existing.handoff_ref
            state_before = ResourceState(existing.status)
            queued_status = HandoffStatus(existing.status)
            queued_priority = HandoffPriority(existing.priority)
            queued_department = existing.department
            extra_details["already_open"] = True
            # Only the requirement raises an open handoff; a priority the model
            # asks for on a repeat does not.
            if requirement is not None and requirement.priority is not None:
                raised = _raise_to(queued_priority, requirement.priority)
                if raised != queued_priority:
                    extra_details["priority_raised_from"] = queued_priority.value
                    extra_details["handoff_requirement"] = requirement.level.value
                    # Flushed with the audit row below, before the re-read.
                    existing.priority = raised.value
                    queued_priority = raised
        else:
            verified_facts: dict[str, Any] = {
                "verification_state": verification_state_before.value,
                "customer_identified": holder_id is not None,
                "policy_flags": list(policy_decision.flags),
            }
            if disputed is not None:
                verified_facts["disputed_transaction"] = _disputed_transaction_facts(
                    disputed
                )
            summary = {
                "verified_facts": verified_facts,
                "actions_taken": _actions_taken(db_session, session_id),
                "verification_method": _VERIFICATION_METHOD[verification_state_before],
                "open_questions": [
                    {"source": "model_unverified", "text": args.summary}
                ],
            }
            handoff = Handoff(
                handoff_ref=_new_handoff_ref(),
                session_ref=session_id,
                customer_id=holder_id,
                reason=args.reason.value,
                priority=priority.value,
                department=department.value,
                status=HandoffStatus.QUEUED.value,
                summary=summary,
                idempotency_scope=idempotency_scope,
            )
            db_session.add(handoff)
            db_session.flush()
            handoff_ref = handoff.handoff_ref
            state_before = ResourceState.NONE
            queued_status = HandoffStatus.QUEUED
            queued_priority = priority
            queued_department = department.value
            extra_details.update(requirement_details)
            if disputed is not None:
                extra_details["transaction_id"] = disputed.transaction_id
        # The model's free text stays in the queue row, never in the audit log.
        audit_row = append_audit(
            session=db_session,
            actor_type="customer_session",
            actor_ref=session_id,
            action=ACTION,
            decision="allowed",
            reason_code=None,
            payload=AuditPayload(
                verification_state_before=verification_state_before,
                verification_state_after=verification_state_after,
                status=ToolResultStatus.OK,
                reason=args.reason.value,
                handoff_status=queued_status,
                handoff_priority=queued_priority,
                idempotency_scope=idempotency_scope,
                details={
                    "department": queued_department,
                    "handoff_ref": handoff_ref,
                    "flags": list(policy_decision.flags),
                    **extra_details,
                },
            ),
        )
        audit_id = audit_row.id
        if commit:
            db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    db_session.expire_all()
    stored = db_session.scalar(
        sa.select(Handoff).where(Handoff.handoff_ref == handoff_ref)
    )
    audit = db_session.get(AuditLog, audit_id)
    if stored is None or audit is None:
        raise RuntimeError("handoff receipt could not be re-read from the database")

    position = queue_position(db_session, stored)
    receipt = Receipt(
        action=ACTION,
        target_masked=stored.handoff_ref,
        state_before=state_before,
        state_after=ResourceState(stored.status),
        verified_at=stored.created_at,
        audit_id=f"aud_{audit.id:08d}",
    )
    output = HandoffCreateOutput(
        handoff_id=stored.handoff_ref,
        status=HandoffStatus(stored.status),
        department=Department(stored.department),
        priority=HandoffPriority(stored.priority),
        summary=HandoffSummary.model_validate(stored.summary),
        queue_position=position,
        created_at=stored.created_at,
        receipt=receipt,
    )
    return HandoffCreateResult(output=output, priority=HandoffPriority(stored.priority))
