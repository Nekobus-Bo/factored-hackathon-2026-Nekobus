"""The handoff queue: its ordering rule, and the back-office claim.

One rule decides a handoff's place in the queue, and two readers use it: the
handoff.create receipt (the customer's `queue_position`) and the back-office
list. It lives here so they cannot drift apart:

- A handoff waits behind the QUEUED handoffs of its own department that have a
  higher priority, or the same priority and were created no later.
- Its position is the count of those, itself included, so the first in line is 1.
- Only a QUEUED handoff has a position; any other status has none.

The claim (ADR-0013) is the back office's only write on the queue: it moves a
handoff to ASSIGNED and records who took it, with its audit row, atomically.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from contracts.tools.handoff_create import HandoffPriority, HandoffStatus
from sqlalchemy.orm import Session, aliased

from banking_core.audit.service import append as append_audit
from banking_core.models.ops import Handoff

# Lowest first: the index is the rank.
PRIORITY_ORDER = [
    HandoffPriority.LOW,
    HandoffPriority.NORMAL,
    HandoffPriority.HIGH,
    HandoffPriority.URGENT,
]

CLAIM_ACTION = "admin.handoff.claimed"

# The same key audit.service.append serializes chain writers on.
_AUDIT_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('ops.audit_log'))"


def priority_rank(column: Any) -> Any:
    """SQL expression: 0 (LOW) to 3 (URGENT) for a priority column or literal."""
    return sa.case(
        {p.value: i for i, p in enumerate(PRIORITY_ORDER)},
        value=column,
        else_=0,
    )


def queue_position_expression(outer: Any) -> Any:
    """SQL expression: the queue position of the `outer` handoff row, or NULL.

    `outer` is `Handoff` (or an alias of it) in the enclosing query, so one
    statement can rank many rows. NULL unless the row is QUEUED: a case a human
    already holds is not waiting in line, whatever is queued around it.
    """
    ahead = aliased(Handoff)
    position = (
        sa.select(sa.func.count())
        .select_from(ahead)
        .where(
            ahead.status == HandoffStatus.QUEUED.value,
            ahead.department == outer.department,
            sa.or_(
                priority_rank(ahead.priority) > priority_rank(outer.priority),
                sa.and_(
                    ahead.priority == outer.priority,
                    ahead.created_at <= outer.created_at,
                ),
            ),
        )
        .correlate(outer)
        .scalar_subquery()
    )
    return sa.case((outer.status == HandoffStatus.QUEUED.value, position), else_=None)


def queue_position(db_session: Session, handoff: Handoff) -> int | None:
    """The place of a stored handoff in its department's queue, or None."""
    return db_session.scalar(
        sa.select(queue_position_expression(Handoff)).where(Handoff.id == handoff.id)
    )


class HandoffNotFoundError(LookupError):
    """No handoff has that handoff_ref."""


class ClaimedByAnotherAgentError(Exception):
    """The handoff is already held by a different agent."""


@dataclass(frozen=True)
class ClaimResult:
    """What a claim did: the row as it now stands and whether it changed it."""

    handoff: Handoff
    claimed: bool


def claim_handoff(
    db_session: Session,
    handoff_ref: str,
    agent_ref: str,
    *,
    now: datetime | None = None,
) -> ClaimResult:
    """Assign a handoff to an agent, audited, in the caller's transaction.

    The audit row and the status change are one unit: the caller commits both
    or neither. Concurrent claims are serialized on the audit chain lock and
    then on the row lock, so exactly one agent wins; a claim by the agent who
    already holds the case changes nothing and writes no second audit row.

    Raises:
        HandoffNotFoundError: If no handoff has that reference.
        ClaimedByAnotherAgentError: If a different agent holds it.
    """
    # The audit lock first, then the row, the order handoff.create takes them in
    # when it raises an open handoff (its UPDATE is flushed by the audit append).
    # Locking the row first would let the two deadlock.
    bind = db_session.get_bind()
    if bind.dialect.name == "postgresql":
        db_session.execute(sa.text(_AUDIT_LOCK_SQL))
    handoff = db_session.scalar(
        sa.select(Handoff)
        .where(Handoff.handoff_ref == handoff_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if handoff is None:
        raise HandoffNotFoundError(handoff_ref)
    if handoff.assigned_agent is not None:
        if handoff.assigned_agent == agent_ref:
            return ClaimResult(handoff=handoff, claimed=False)
        raise ClaimedByAnotherAgentError(handoff_ref)

    claimed_at = now or datetime.now(UTC)
    before_status = handoff.status
    handoff.status = HandoffStatus.ASSIGNED.value
    handoff.assigned_agent = agent_ref
    handoff.assigned_at = claimed_at
    # No PII in the payload: the agent is the actor, the case is an opaque ref.
    append_audit(
        session=db_session,
        actor_type="agent",
        actor_ref=agent_ref,
        action=CLAIM_ACTION,
        decision="allowed",
        reason_code=None,
        payload={
            "handoff_ref": handoff.handoff_ref,
            "before_status": before_status,
            "after_status": handoff.status,
        },
        occurred_at=claimed_at,
    )
    return ClaimResult(handoff=handoff, claimed=True)
