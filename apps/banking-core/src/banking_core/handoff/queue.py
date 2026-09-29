"""The handoff queue: the rule that orders it.

One rule decides a handoff's place in the queue, and two readers use it: the
handoff.create receipt (the customer's `queue_position`) and the back-office
list. It lives here so they cannot drift apart:

- A handoff waits behind the QUEUED handoffs of its own department that have a
  higher priority, or the same priority and were created no later.
- Its position is the count of those, itself included, so the first in line is 1.
- Only a QUEUED handoff has a position; any other status has none.
"""

from typing import Any

import sqlalchemy as sa
from contracts.tools.handoff_create import HandoffPriority, HandoffStatus
from sqlalchemy.orm import Session, aliased

from banking_core.models.ops import Handoff

# Lowest first: the index is the rank.
PRIORITY_ORDER = [
    HandoffPriority.LOW,
    HandoffPriority.NORMAL,
    HandoffPriority.HIGH,
    HandoffPriority.URGENT,
]


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
