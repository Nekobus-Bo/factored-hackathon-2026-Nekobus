"""Add ops.assistant_feedback: the customer's answer to "did the assistant help?".

Revision ID: 0009_assistant_feedback
Revises: 0008_handoff_assignment
Create Date: 2026-10-02 21:00:00.000000

The chat asks once, after a handoff (ADR-0017). One answer per handoff: the
unique handoff_id makes a repeated request a no-op and keeps the first answer.
Deleting a handoff deletes its answer, so the seed's TRUNCATE ... CASCADE and
the tests' DELETE FROM ops.handoff keep working. Downgrading drops the table and
the answers in it; their audit rows (feedback.recorded) stay.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009_assistant_feedback"
down_revision: str | None = "0008_handoff_assignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "handoff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ops.handoff.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("handoff_id", name="uq_assistant_feedback_handoff_id"),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("assistant_feedback", schema="ops")
