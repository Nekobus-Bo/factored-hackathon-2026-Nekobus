"""Add ops.audit_log with hash chain and ops.idempotency_key.

Revision ID: 0002_ops_audit_idempotency
Revises: 0001_initial_schema
Create Date: 2026-09-26 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_ops_audit_idempotency"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Ensure ops schema exists
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    # 2. ops.audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('system', 'customer_session', 'agent')",
            name="ck_audit_log_actor_type",
        ),
        sa.CheckConstraint(
            "decision IN ('allowed', 'refused', 'error')",
            name="ck_audit_log_decision",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_ops_audit_log_occurred_at",
        "audit_log",
        ["occurred_at"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_audit_log_action",
        "audit_log",
        ["action"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_audit_log_actor_ref",
        "audit_log",
        ["actor_ref"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_audit_log_prev_hash",
        "audit_log",
        ["prev_hash"],
        schema="ops",
    )

    # 3. Append-only trigger on ops.audit_log: disallow UPDATE, DELETE and TRUNCATE
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.prevent_audit_log_modification()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'ops.audit_log is append-only: % operations are prohibited',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_prevent_modification
        BEFORE UPDATE OR DELETE ON ops.audit_log
        FOR EACH ROW EXECUTE FUNCTION ops.prevent_audit_log_modification();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_prevent_truncate
        BEFORE TRUNCATE ON ops.audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION ops.prevent_audit_log_modification();
        """
    )

    # 4. ops.idempotency_key
    op.create_table(
        "idempotency_key",
        sa.Column("scoped_key", sa.String(length=256), primary_key=True),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "key ~ '^[A-Za-z0-9._:-]{8,128}$'",
            name="ck_idempotency_key_pattern",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_ops_idempotency_key_scope",
        "idempotency_key",
        ["scope"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_idempotency_key_tool",
        "idempotency_key",
        ["tool"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_idempotency_key_created_at",
        "idempotency_key",
        ["created_at"],
        schema="ops",
    )
    op.create_index(
        "ix_ops_idempotency_key_expires_at",
        "idempotency_key",
        ["expires_at"],
        schema="ops",
    )


def downgrade() -> None:
    # Drop idempotency_key table
    op.drop_table("idempotency_key", schema="ops")

    # Drop triggers and function
    op.execute("DROP TRIGGER IF EXISTS audit_log_prevent_truncate ON ops.audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_prevent_modification ON ops.audit_log")
    op.execute("DROP FUNCTION IF EXISTS ops.prevent_audit_log_modification()")

    # Drop audit_log table
    op.drop_table("audit_log", schema="ops")
