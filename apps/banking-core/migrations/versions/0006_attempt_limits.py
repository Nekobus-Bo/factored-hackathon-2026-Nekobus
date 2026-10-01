"""Add the cross-session attempt limits to config.policy_config.

Revision ID: 0006_attempt_limits
Revises: 0005_dataset_cards
Create Date: 2026-09-29 09:00:00.000000

Failed otp.verify evaluations are counted per customer and failed customer.match
attempts per claimed document, across sessions (ADR-0004 amendment). The
thresholds are policy configuration (ADR-0002): typed columns, seeded from the
environment when the table is empty. Rows saved before this revision take the
defaults below, which are also the seed defaults in .env.example.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_attempt_limits"
down_revision: str | None = "0005_dataset_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (column, server default). Keep in step with PolicyConfig and .env.example.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("customer_otp_max_failures", "5"),
    ("customer_otp_window_seconds", "3600"),
    ("customer_otp_lock_seconds", "1800"),
    ("document_match_max_failures", "10"),
    ("document_match_window_seconds", "3600"),
)


def upgrade() -> None:
    for name, default in _COLUMNS:
        op.add_column(
            "policy_config",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
            schema="config",
        )


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("policy_config", name, schema="config")
