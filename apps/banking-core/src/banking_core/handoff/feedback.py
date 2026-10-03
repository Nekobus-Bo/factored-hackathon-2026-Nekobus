"""The customer's answer to "did the assistant help?" (ADR-0017).

The chat asks once a conversation has been handed to a person. banking-core keeps
one answer per handoff, for the newest handoff of the session, and writes its
audit row in the same transaction. The handoff is the natural key: the same
answer again changes nothing, a different one is refused and the first stands.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from banking_core.audit.service import append as append_audit
from banking_core.models.ops import AssistantFeedback, Handoff

FEEDBACK_ACTION = "feedback.recorded"

# The same key audit.service.append serializes chain writers on (see handoff.queue).
_AUDIT_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('ops.audit_log'))"


class NoHandoffError(Exception):
    """The session has no handoff: there is nothing to rate yet."""


class AlreadyAnsweredError(Exception):
    """The handoff already has a different answer: the first one stands."""


@dataclass(frozen=True)
class FeedbackResult:
    """What a call did: the handoff it rated and whether it wrote the answer."""

    handoff_ref: str
    recorded: bool


@dataclass(frozen=True)
class StoredFeedback:
    """An answer as the database holds it: the receipt of record_feedback."""

    handoff_ref: str
    helpful: bool
    recorded_at: datetime


def record_feedback(
    db_session: Session,
    session_ref: str,
    helpful: bool,
    *,
    now: datetime | None = None,
) -> FeedbackResult:
    """Store the answer for the session's newest handoff, audited.

    Runs in the caller's transaction: the caller commits the answer and its audit
    row together, or neither.

    Raises:
        NoHandoffError: If the session has no handoff.
        AlreadyAnsweredError: If that handoff already has the other answer.
    """
    # The audit lock first, then the row: the order the back-office claim takes
    # them in, so the two cannot deadlock on the same handoff.
    if db_session.get_bind().dialect.name == "postgresql":
        db_session.execute(sa.text(_AUDIT_LOCK_SQL))
    handoff = db_session.scalar(
        sa.select(Handoff)
        .where(Handoff.session_ref == session_ref)
        .order_by(Handoff.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if handoff is None:
        raise NoHandoffError(session_ref)

    existing = db_session.scalar(
        sa.select(AssistantFeedback).where(AssistantFeedback.handoff_id == handoff.id)
    )
    if existing is not None:
        if existing.helpful == helpful:
            return FeedbackResult(handoff_ref=handoff.handoff_ref, recorded=False)
        raise AlreadyAnsweredError(handoff.handoff_ref)

    recorded_at = now or datetime.now(UTC)
    db_session.add(
        AssistantFeedback(
            handoff_id=handoff.id, helpful=helpful, created_at=recorded_at
        )
    )
    # No PII: the session is the actor, the case an opaque ref, the answer a bool.
    append_audit(
        session=db_session,
        actor_type="customer_session",
        actor_ref=session_ref,
        action=FEEDBACK_ACTION,
        decision="allowed",
        reason_code=None,
        payload={"handoff_ref": handoff.handoff_ref, "helpful": helpful},
        occurred_at=recorded_at,
    )
    return FeedbackResult(handoff_ref=handoff.handoff_ref, recorded=True)


def read_feedback(db_session: Session, handoff_ref: str) -> StoredFeedback | None:
    """The stored answer of a handoff, or None."""
    row = db_session.execute(
        sa.select(
            Handoff.handoff_ref, AssistantFeedback.helpful, AssistantFeedback.created_at
        )
        .join(AssistantFeedback, AssistantFeedback.handoff_id == Handoff.id)
        .where(Handoff.handoff_ref == handoff_ref)
    ).one_or_none()
    if row is None:
        return None
    return StoredFeedback(handoff_ref=row[0], helpful=row[1], recorded_at=row[2])
