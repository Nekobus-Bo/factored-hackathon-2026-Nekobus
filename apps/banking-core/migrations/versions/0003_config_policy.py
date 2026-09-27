"""Add config.policy_config and config.tool_policy tables.

Revision ID: 0003_config_policy
Revises: 0002_ops_audit_idempotency
Create Date: 2026-09-27 08:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_config_policy"
down_revision: str | None = "0002_ops_audit_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Ensure config schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS config")

    # 2. config.policy_config
    op.create_table(
        "policy_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="COP",
        ),
        sa.Column(
            "amount_mode",
            sa.String(length=16),
            nullable=False,
            server_default="flag",
        ),
        sa.Column(
            "thresholds_minor",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rate_limit_attempts_per_session",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "otp_max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "otp_max_resends",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column(
            "otp_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        sa.Column(
            "session_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default="3600",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_mode IN ('flag', 'block')",
            name="ck_policy_config_amount_mode",
        ),
        schema="config",
    )
    op.create_index(
        "ix_config_policy_config_version",
        "policy_config",
        ["version"],
        unique=True,
        schema="config",
    )
    op.create_index(
        "ix_config_policy_config_is_active",
        "policy_config",
        ["is_active"],
        schema="config",
    )

    # 3. config.tool_policy
    op.create_table(
        "tool_policy",
        sa.Column("tool_name", sa.String(length=128), primary_key=True),
        sa.Column(
            "permitted_states",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="config",
    )


def downgrade() -> None:
    # Drop tool_policy
    op.drop_table("tool_policy", schema="config")

    # Drop policy_config
    op.drop_table("policy_config", schema="config")

    # Drop config schema
    op.execute("DROP SCHEMA IF EXISTS config CASCADE")
