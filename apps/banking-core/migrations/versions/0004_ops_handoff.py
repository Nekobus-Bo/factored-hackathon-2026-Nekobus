"""Add ops.handoff, the back-office queue behind handoff.create.

Revision ID: 0004_ops_handoff
Revises: 0003_config_policy
Create Date: 2026-09-27 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_ops_handoff"
down_revision: str | None = "0003_config_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "handoff",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("handoff_ref", sa.String(length=64), nullable=False),
        sa.Column("session_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_bank.customer.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("department", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="QUEUED"
        ),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_scope", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("handoff_ref", name="uq_handoff_handoff_ref"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'ASSIGNED', 'PENDING')", name="ck_handoff_status"
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')",
            name="ck_handoff_priority",
        ),
        sa.CheckConstraint(
            "department IN ('FRAUD_OPERATIONS', 'CUSTOMER_SUPPORT', 'DISPUTES')",
            name="ck_handoff_department",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_handoff_queue",
        "handoff",
        ["status", "priority", "created_at"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_handoff_session_ref", "handoff", ["session_ref"], schema="ops"
    )
    op.create_index(
        "ix_ops_handoff_customer_id", "handoff", ["customer_id"], schema="ops"
    )


def downgrade() -> None:
    op.drop_index("ix_ops_handoff_customer_id", table_name="handoff", schema="ops")
    op.drop_index("ix_ops_handoff_session_ref", table_name="handoff", schema="ops")
    op.drop_index("ix_handoff_queue", table_name="handoff", schema="ops")
    op.drop_table("handoff", schema="ops")
