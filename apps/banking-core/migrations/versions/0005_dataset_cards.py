"""Allow dataset cards without a PAN and add card type and expiry.

Revision ID: 0005_dataset_cards
Revises: 0004_ops_handoff
Create Date: 2026-09-27 18:00:00.000000

Dataset cards (data_origin='dataset') are loaded with last4 only: the PAN is
never stored for them. Synthetic cards keep their encrypted synthetic PAN.
card_type and expiry come only from the delivered dataset; synthetic cards
leave them NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_dataset_cards"
down_revision: str | None = "0004_ops_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("card", "pan_enc", nullable=True, schema="core_bank")
    op.create_check_constraint(
        "ck_card_pan_only_synthetic",
        "card",
        "data_origin = 'synthetic' OR pan_enc IS NULL",
        schema="core_bank",
    )
    op.add_column(
        "card",
        sa.Column("card_type", sa.String(length=16), nullable=True),
        schema="core_bank",
    )
    op.add_column(
        "card",
        sa.Column("expiry_month", sa.SmallInteger(), nullable=True),
        schema="core_bank",
    )
    op.add_column(
        "card",
        sa.Column("expiry_year", sa.SmallInteger(), nullable=True),
        schema="core_bank",
    )
    op.create_check_constraint(
        "ck_card_card_type",
        "card",
        "card_type IS NULL OR card_type IN ('DEBIT', 'CREDIT')",
        schema="core_bank",
    )
    op.create_check_constraint(
        "ck_card_expiry",
        "card",
        "(expiry_month IS NULL AND expiry_year IS NULL) OR "
        "(expiry_month BETWEEN 1 AND 12 AND expiry_year BETWEEN 2000 AND 2100)",
        schema="core_bank",
    )


def downgrade() -> None:
    op.drop_constraint("ck_card_expiry", "card", schema="core_bank", type_="check")
    op.drop_constraint("ck_card_card_type", "card", schema="core_bank", type_="check")
    op.drop_column("card", "expiry_year", schema="core_bank")
    op.drop_column("card", "expiry_month", schema="core_bank")
    op.drop_column("card", "card_type", schema="core_bank")
    op.drop_constraint(
        "ck_card_pan_only_synthetic", "card", schema="core_bank", type_="check"
    )
    # Dataset cards have no PAN; they cannot survive a NOT NULL pan_enc.
    op.execute("DELETE FROM core_bank.card WHERE pan_enc IS NULL")
    op.alter_column("card", "pan_enc", nullable=False, schema="core_bank")
