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
- The queue row and its audit row commit in one transaction; the receipt is
  then re-read from the database.
"""

import secrets
import string
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from contracts.envelope import Receipt, ResourceState, VerificationState
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffCreateOutput,
    HandoffPriority,
    HandoffStatus,
)
from sqlalchemy.orm import Session

from banking_core.audit.service import append as append_audit
from banking_core.control.policy import Decision
from banking_core.models.ops import AuditLog, Handoff

ACTION = "handoff.create"

_PRIORITY_ORDER = [
    HandoffPriority.LOW,
    HandoffPriority.NORMAL,
    HandoffPriority.HIGH,
    HandoffPriority.URGENT,
]

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
    return max(requested, floor, key=_PRIORITY_ORDER.index)


def _new_handoff_ref() -> str:
    # Letters only: opaque refs must never carry 12+ digits (PAN guard).
    return "hnd_" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(16))


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


def execute_handoff_create(
    db_session: Session,
    holder_customer_id: str | uuid.UUID | None,
    args: HandoffCreateInput,
    policy_decision: Decision,
    idempotency_scope: str,
    verification_state: VerificationState,
    session_ref: str | None = None,
) -> HandoffCreateResult:
    """Queue a structured handoff and return the receipt re-read after commit.

    Raises:
        ValueError: If policy_decision does not allow the call.
    """
    if not policy_decision.allowed:
        raise ValueError("handoff.create requires an allowed policy decision")
    session_ref = session_ref or idempotency_scope
    holder_id = (
        uuid.UUID(str(holder_customer_id)) if holder_customer_id is not None else None
    )
    priority = resolve_priority(args.priority, policy_decision, verification_state)

    try:
        summary = {
            "verified_facts": {
                "verification_state": verification_state.value,
                "customer_identified": holder_id is not None,
                "policy_flags": list(policy_decision.flags),
            },
            "actions_taken": _actions_taken(db_session, session_ref),
            "verification_method": _VERIFICATION_METHOD[verification_state],
            "open_questions": [{"source": "model_unverified", "text": args.summary}],
        }
        handoff = Handoff(
            handoff_ref=_new_handoff_ref(),
            session_ref=session_ref,
            customer_id=holder_id,
            reason=args.reason.value,
            priority=priority.value,
            department=args.department.value,
            status=HandoffStatus.QUEUED.value,
            summary=summary,
            idempotency_scope=idempotency_scope,
        )
        db_session.add(handoff)
        db_session.flush()
        # The model's free text stays in the queue row, never in the audit log.
        audit_row = append_audit(
            session=db_session,
            actor_type="customer_session",
            actor_ref=session_ref,
            action=ACTION,
            decision="allowed",
            reason_code=None,
            payload={
                "handoff_ref": handoff.handoff_ref,
                "reason": args.reason.value,
                "priority": priority.value,
                "department": args.department.value,
                "verification_state": verification_state.value,
                "flags": list(policy_decision.flags),
            },
        )
        handoff_id, audit_id = handoff.id, audit_row.id
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    db_session.expire_all()
    stored = db_session.get(Handoff, handoff_id)
    audit = db_session.get(AuditLog, audit_id)
    if stored is None or audit is None:
        raise RuntimeError("handoff receipt could not be re-read from the database")

    queue_position = db_session.scalar(
        sa.select(sa.func.count())
        .select_from(Handoff)
        .where(
            Handoff.status == HandoffStatus.QUEUED.value,
            Handoff.department == stored.department,
            sa.or_(
                _rank(Handoff.priority) > _rank(sa.literal(stored.priority)),
                sa.and_(
                    Handoff.priority == stored.priority,
                    Handoff.created_at <= stored.created_at,
                ),
            ),
        )
    )

    receipt = Receipt(
        action=ACTION,
        target_masked=stored.handoff_ref,
        state_before=ResourceState.NONE,
        state_after=ResourceState(stored.status),
        verified_at=stored.created_at,
        audit_id=f"aud_{audit.id:08d}",
    )
    output = HandoffCreateOutput(
        handoff_id=stored.handoff_ref,
        status=HandoffStatus(stored.status),
        department=Department(stored.department),
        queue_position=queue_position or None,
        created_at=stored.created_at,
        receipt=receipt,
    )
    return HandoffCreateResult(output=output, priority=HandoffPriority(stored.priority))


def _rank(column: Any) -> Any:
    return sa.case(
        {p.value: i for i, p in enumerate(_PRIORITY_ORDER)},
        value=column,
        else_=0,
    )
