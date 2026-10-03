"""Let an agent close a handoff: the CLOSED status and the decision columns.

Revision ID: 0010_handoff_decisions
Revises: 0009_assistant_feedback
Create Date: 2026-10-02 23:00:00.000000

The back office closes a case with an outcome or escalates it (ADR-0018). A close
sets the status to CLOSED and records the outcome (APPROVED, REJECTED or
RESOLVED), the reject reason, the agent and the time. All four columns are
nullable: every row that exists is open.

Downgrading reopens nothing silently: it refuses while a CLOSED row exists,
because the old status constraint cannot hold it. The audit rows of the closes
stay either way.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_handoff_decisions"
down_revision: str | None = "0009_assistant_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = "status IN ('QUEUED', 'ASSIGNED', 'PENDING')"
_NEW_STATUSES = "status IN ('QUEUED', 'ASSIGNED', 'PENDING', 'CLOSED')"


def upgrade() -> None:
    op.drop_constraint("ck_handoff_status", "handoff", schema="ops", type_="check")
    op.create_check_constraint(
        "ck_handoff_status", "handoff", _NEW_STATUSES, schema="ops"
    )
    op.add_column("handoff", sa.Column("outcome", sa.String(16)), schema="ops")
    op.add_column("handoff", sa.Column("outcome_reason", sa.String(64)), schema="ops")
    op.add_column("handoff", sa.Column("closed_by", sa.String(254)), schema="ops")
    op.add_column(
        "handoff", sa.Column("closed_at", sa.DateTime(timezone=True)), schema="ops"
    )
    op.create_check_constraint(
        "ck_handoff_outcome",
        "handoff",
        "outcome IS NULL OR outcome IN ('APPROVED', 'REJECTED', 'RESOLVED')",
        schema="ops",
    )


def downgrade() -> None:
    closed = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM ops.handoff WHERE status = 'CLOSED'"))
        .scalar_one()
    )
    if closed:
        raise RuntimeError(
            f"{closed} closed handoff(s) exist; reopen or delete them before"
            " downgrading 0010_handoff_decisions"
        )
    op.drop_constraint("ck_handoff_outcome", "handoff", schema="ops", type_="check")
    op.drop_column("handoff", "closed_at", schema="ops")
    op.drop_column("handoff", "closed_by", schema="ops")
    op.drop_column("handoff", "outcome_reason", schema="ops")
    op.drop_column("handoff", "outcome", schema="ops")
    op.drop_constraint("ck_handoff_status", "handoff", schema="ops", type_="check")
    op.create_check_constraint(
        "ck_handoff_status", "handoff", _OLD_STATUSES, schema="ops"
    )
