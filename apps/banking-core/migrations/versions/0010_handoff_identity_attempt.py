"""Add handoff_reasons_requiring_identity_attempt to config.policy_config.

Revision ID: 0010_handoff_identity_attempt
Revises: 0009_assistant_feedback
Create Date: 2026-10-02 23:00:00.000000

From ANONYMOUS, handoff.create with one of these reasons is refused until one
customer.match has been tried in the session (ADR-0003 amendment 2026-10-02).
The list is policy configuration (ADR-0002): a JSONB list of HandoffReason
values, seeded from the environment when the table is empty. Rows saved before
this revision take the default below, which is also the seed default in
.env.example.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_handoff_identity_attempt"
down_revision: str | None = "0009_assistant_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep in step with PolicyConfig and .env.example.
_DEFAULT = (
    '\'["DISPUTE_CLAIM", "UNRECOGNIZED_TRANSACTION", "VERIFICATION_FAILED"]\'::jsonb'
)


def upgrade() -> None:
    op.add_column(
        "policy_config",
        sa.Column(
            "handoff_reasons_requiring_identity_attempt",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(_DEFAULT),
        ),
        schema="config",
    )


def downgrade() -> None:
    op.drop_column(
        "policy_config", "handoff_reasons_requiring_identity_attempt", schema="config"
    )
