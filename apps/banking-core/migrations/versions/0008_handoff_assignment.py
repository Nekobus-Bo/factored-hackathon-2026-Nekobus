"""Record who took a handoff and when: ops.handoff.assigned_agent / assigned_at.

Revision ID: 0008_handoff_assignment
Revises: 0007_tool_policy_versions
Create Date: 2026-09-29 18:00:00.000000

The back office claims a queued handoff (ADR-0013). The claim sets the status to
ASSIGNED and records the agent's email and the time. Both columns are nullable:
every row that exists, and every QUEUED or PENDING row, has no agent.

No backfill: a handoff already ASSIGNED before this revision (nothing wrote that
status until now) keeps both columns empty. Downgrading drops the columns and
with them who held each case; the audit rows of the claims stay.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_handoff_assignment"
down_revision: str | None = "0007_tool_policy_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "handoff",
        sa.Column("assigned_agent", sa.String(length=254), nullable=True),
        schema="ops",
    )
    op.add_column(
        "handoff",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_column("handoff", "assigned_at", schema="ops")
    op.drop_column("handoff", "assigned_agent", schema="ops")
