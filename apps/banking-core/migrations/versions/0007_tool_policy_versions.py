"""Version config.tool_policy like config.policy_config.

Revision ID: 0007_tool_policy_versions
Revises: 0006_attempt_limits
Create Date: 2026-09-29 12:00:00.000000

The tool policy (the state x tool matrix, which can only restrict the code floor)
was one unversioned row per tool. It becomes one document per version, the same
shape as config.policy_config: `version`, `is_active` and a `matrix` mapping each
tool to the verification states that enable it (`[]` disables it). Every change is
a new row (ADR-0002); the audit row that goes with it is written by the code that
saves it.

Rows saved before this revision become version 1, active, so an existing
configuration is never replaced by the environment seed. With no rows the table
stays empty and the first read seeds version 1 from POLICY_SEED_DISABLED_TOOLS.

Downgrading keeps only the active version, as one row per tool; older versions
are dropped.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_tool_policy_versions"
down_revision: str | None = "0006_attempt_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    legacy = bind.execute(
        sa.text(
            "SELECT tool_name, permitted_states FROM config.tool_policy "
            "ORDER BY tool_name"
        )
    ).all()
    matrix = {row.tool_name: row.permitted_states for row in legacy}

    op.drop_table("tool_policy", schema="config")
    op.create_table(
        "tool_policy",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("matrix", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="config",
    )
    op.create_index(
        "ix_config_tool_policy_version",
        "tool_policy",
        ["version"],
        unique=True,
        schema="config",
    )
    # At most one active version, whatever the writers do.
    op.create_index(
        "ux_config_tool_policy_one_active",
        "tool_policy",
        ["is_active"],
        unique=True,
        schema="config",
        postgresql_where=sa.text("is_active"),
    )

    if matrix:
        bind.execute(
            sa.text(
                "INSERT INTO config.tool_policy (version, is_active, matrix) "
                "VALUES (1, true, CAST(:matrix AS jsonb))"
            ),
            {"matrix": json.dumps(matrix)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    active = bind.execute(
        sa.text(
            "SELECT matrix FROM config.tool_policy WHERE is_active "
            "ORDER BY version DESC LIMIT 1"
        )
    ).scalar_one_or_none()

    op.drop_table("tool_policy", schema="config")
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
    for tool_name, states in (active or {}).items():
        bind.execute(
            sa.text(
                "INSERT INTO config.tool_policy (tool_name, permitted_states) "
                "VALUES (:tool_name, CAST(:states AS jsonb))"
            ),
            {"tool_name": tool_name, "states": json.dumps(states)},
        )
