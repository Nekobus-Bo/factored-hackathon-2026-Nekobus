"""Operational counts for the back office, read from the audit log and the queue.

Everything here is a count of rows already in `ops.audit_log` (within a time
window) and `ops.handoff` (created within the same window). Nothing is read
from the customer tables and no row is returned: only names, enums and numbers,
so the result holds no PII by construction.

Which audit rows mean what (real action names, see the dispatcher and tools):

- A *tool call* is a row whose action is a tool of the catalog (`card.block`,
  `otp.verify`, `handoff.create`...), counted by action, decision and reason
  code. Other rows (`security.*`, `admin.*`, `customer.locked`) are not tool calls.
- *Cards blocked* are `card.block` rows that allowed the call and moved the card
  to BLOCKED from another state; a repeat on a blocked card is a call, not a block.
- *OTP sent* are allowed `otp.send` rows. *Verified* and *failed* are allowed
  `otp.verify` rows whose recorded outcome (`details.verified`) is true or false:
  a code was compared. A refused `otp.verify` (wrong state, customer locked) never
  compared one, so it is a tool call, not a failure.
- *Feedback* (ADR-0017) counts the answers of the handoffs created in the window,
  so it compares with the handoff total. *Queue* is now, not the window: what
  waits for a person as the metrics are read.
- *Previous* is the same summary for the window just before, for the change the
  back office shows next to each number (ADR-0018).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from contracts.tools import TOOL_CATALOG
from contracts.tools.card_list import CardStatus
from contracts.tools.handoff_create import Department, HandoffPriority, HandoffStatus
from sqlalchemy.orm import Session

from banking_core.handoff.decisions import HandoffOutcome
from banking_core.models.ops import AssistantFeedback, AuditLog, Handoff

CARD_BLOCK_ACTION = "card.block"
OTP_SEND_ACTION = "otp.send"
OTP_VERIFY_ACTION = "otp.verify"


@dataclass(frozen=True)
class ToolCallCount:
    action: str
    decision: str
    reason_code: str | None
    count: int


@dataclass(frozen=True)
class HandoffCounts:
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_department: dict[str, int]
    by_outcome: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedbackCounts:
    helpful: int
    not_helpful: int


@dataclass(frozen=True)
class NotHelpfulCase:
    handoff_ref: str
    reason: str
    recorded_at: datetime


@dataclass(frozen=True)
class QueueNow:
    waiting: int
    urgent: int
    oldest_created_at: datetime | None


@dataclass(frozen=True)
class WindowSummary:
    """The headline numbers of one window, for comparing two."""

    cards_blocked: int
    otp: "OtpCounts"
    handoffs_total: int
    feedback: FeedbackCounts


@dataclass(frozen=True)
class OtpCounts:
    sent: int
    verified: int
    failed: int


@dataclass(frozen=True)
class MetricsSnapshot:
    generated_at: datetime
    window_hours: int
    tool_calls: list[ToolCallCount] = field(default_factory=list)
    handoffs: HandoffCounts = field(
        default_factory=lambda: HandoffCounts(0, {}, {}, {})
    )
    cards_blocked: int = 0
    otp: OtpCounts = field(default_factory=lambda: OtpCounts(0, 0, 0))
    feedback: FeedbackCounts = field(default_factory=lambda: FeedbackCounts(0, 0))
    recent_not_helpful: list[NotHelpfulCase] = field(default_factory=list)
    queue: QueueNow = field(default_factory=lambda: QueueNow(0, 0, None))
    previous: WindowSummary | None = None


RECENT_NOT_HELPFUL = 5


def collect_metrics(
    session: Session,
    hours: int,
    now: datetime | None = None,
    *,
    with_previous: bool = True,
) -> MetricsSnapshot:
    """Count what happened in the last `hours` hours, up to `now`.

    With `with_previous`, also the summary of the `hours` before that.
    """
    generated_at = now or datetime.now(UTC)
    since = generated_at - timedelta(hours=hours)
    in_window = (AuditLog.occurred_at >= since, AuditLog.occurred_at <= generated_at)

    tool_rows = session.execute(
        sa.select(
            AuditLog.action,
            AuditLog.decision,
            AuditLog.reason_code,
            sa.func.count().label("n"),
        )
        .where(*in_window, AuditLog.action.in_(sorted(TOOL_CATALOG)))
        .group_by(AuditLog.action, AuditLog.decision, AuditLog.reason_code)
        .order_by(
            AuditLog.action, AuditLog.decision, AuditLog.reason_code.nulls_first()
        )
    ).all()

    payload = AuditLog.payload
    allowed = AuditLog.decision == "allowed"
    verified = payload["details"]["verified"].astext
    outcome = session.execute(
        sa.select(
            sa.func.count()
            .filter(
                AuditLog.action == CARD_BLOCK_ACTION,
                allowed,
                payload["card_state_after"].astext == CardStatus.BLOCKED.value,
                payload["card_state_before"].astext.is_distinct_from(
                    CardStatus.BLOCKED.value
                ),
            )
            .label("cards_blocked"),
            sa.func.count()
            .filter(AuditLog.action == OTP_SEND_ACTION, allowed)
            .label("otp_sent"),
            sa.func.count()
            .filter(AuditLog.action == OTP_VERIFY_ACTION, allowed, verified == "true")
            .label("otp_verified"),
            sa.func.count()
            .filter(AuditLog.action == OTP_VERIFY_ACTION, allowed, verified == "false")
            .label("otp_failed"),
        ).where(*in_window)
    ).one()

    handoff_in_window = (
        Handoff.created_at >= since,
        Handoff.created_at <= generated_at,
    )
    handoff_rows = session.execute(
        sa.select(
            Handoff.status,
            Handoff.priority,
            Handoff.department,
            Handoff.outcome,
            sa.func.count().label("n"),
        )
        .where(*handoff_in_window)
        .group_by(Handoff.status, Handoff.priority, Handoff.department, Handoff.outcome)
    ).all()
    # Every known value is present, at zero if need be, so a reader never has to
    # guess whether a missing key means none or unknown.
    by_status = {status.value: 0 for status in HandoffStatus}
    by_priority = {priority.value: 0 for priority in reversed(list(HandoffPriority))}
    by_department = {department.value: 0 for department in Department}
    by_outcome = {outcome.value: 0 for outcome in HandoffOutcome}
    for status, priority, department, closed_as, n in handoff_rows:
        by_status[status] = by_status.get(status, 0) + n
        by_priority[priority] = by_priority.get(priority, 0) + n
        by_department[department] = by_department.get(department, 0) + n
        if closed_as is not None:
            by_outcome[closed_as] = by_outcome.get(closed_as, 0) + n

    feedback_row = session.execute(
        sa.select(
            sa.func.count().filter(AssistantFeedback.helpful.is_(True)),
            sa.func.count().filter(AssistantFeedback.helpful.is_(False)),
        )
        .select_from(AssistantFeedback)
        .join(Handoff, Handoff.id == AssistantFeedback.handoff_id)
        .where(*handoff_in_window)
    ).one()
    feedback = FeedbackCounts(helpful=feedback_row[0], not_helpful=feedback_row[1])

    recent: list[NotHelpfulCase] = []
    queue = QueueNow(0, 0, None)
    previous: WindowSummary | None = None
    if with_previous:
        recent = [
            NotHelpfulCase(row.handoff_ref, row.reason, row.created_at)
            for row in session.execute(
                sa.select(
                    Handoff.handoff_ref, Handoff.reason, AssistantFeedback.created_at
                )
                .join(AssistantFeedback, AssistantFeedback.handoff_id == Handoff.id)
                .where(*handoff_in_window, AssistantFeedback.helpful.is_(False))
                .order_by(AssistantFeedback.created_at.desc(), Handoff.id)
                .limit(RECENT_NOT_HELPFUL)
            ).all()
        ]
        waiting, urgent, oldest = session.execute(
            sa.select(
                sa.func.count(),
                sa.func.count().filter(
                    Handoff.priority == HandoffPriority.URGENT.value
                ),
                sa.func.min(Handoff.created_at),
            ).where(Handoff.status == HandoffStatus.QUEUED.value)
        ).one()
        queue = QueueNow(waiting=waiting, urgent=urgent, oldest_created_at=oldest)
        before = collect_metrics(session, hours, since, with_previous=False)
        previous = WindowSummary(
            cards_blocked=before.cards_blocked,
            otp=before.otp,
            handoffs_total=before.handoffs.total,
            feedback=before.feedback,
        )

    return MetricsSnapshot(
        generated_at=generated_at,
        window_hours=hours,
        tool_calls=[
            ToolCallCount(row.action, row.decision, row.reason_code, row.n)
            for row in tool_rows
        ],
        handoffs=HandoffCounts(
            total=sum(by_status.values()),
            by_status=by_status,
            by_priority=by_priority,
            by_department=by_department,
            by_outcome=by_outcome,
        ),
        cards_blocked=outcome.cards_blocked,
        otp=OtpCounts(
            sent=outcome.otp_sent,
            verified=outcome.otp_verified,
            failed=outcome.otp_failed,
        ),
        feedback=feedback,
        recent_not_helpful=recent,
        queue=queue,
        previous=previous,
    )
