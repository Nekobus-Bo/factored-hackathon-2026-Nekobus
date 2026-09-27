"""Initial schema for core_bank, chat, and ops.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-09-26 22:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS core_bank")
    op.execute("CREATE SCHEMA IF NOT EXISTS chat")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    # 2. Enums in core_bank
    document_type_enum = postgresql.ENUM(
        "NATIONAL_ID",
        "PASSPORT",
        "FOREIGN_ID",
        "TAX_ID",
        name="document_type_enum",
        schema="core_bank",
        create_type=False,
    )
    document_type_enum.create(op.get_bind(), checkfirst=True)

    block_reason_enum = postgresql.ENUM(
        "LOST",
        "STOLEN",
        "UNRECOGNIZED_CHARGE",
        "SUSPICIOUS_ACTIVITY",
        "CUSTOMER_REQUEST",
        name="block_reason_enum",
        schema="core_bank",
        create_type=False,
    )
    block_reason_enum.create(op.get_bind(), checkfirst=True)

    # 3. Tables in core_bank
    op.create_table(
        "customer",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_type", document_type_enum, nullable=False),
        sa.Column("document_number_enc", sa.Text(), nullable=False),
        sa.Column("document_number_bidx", sa.String(length=64), nullable=False),
        sa.Column("full_name_enc", sa.Text(), nullable=False),
        sa.Column("email_enc", sa.Text(), nullable=False),
        sa.Column("email_bidx", sa.String(length=64), nullable=False),
        sa.Column("phone_enc", sa.Text(), nullable=False),
        sa.Column("phone_bidx", sa.String(length=64), nullable=False),
        sa.Column("birth_date_enc", sa.Text(), nullable=False),
        sa.Column(
            "preferred_locale",
            sa.String(length=8),
            server_default="es",
            nullable=False,
        ),
        sa.Column("registered_otp_channel", sa.String(length=32), nullable=False),
        sa.Column(
            "data_origin",
            sa.String(length=32),
            server_default="synthetic",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "preferred_locale IN ('es', 'pt', 'en')",
            name="ck_customer_locale",
        ),
        sa.CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_customer_data_origin",
        ),
        sa.UniqueConstraint(
            "document_type",
            "document_number_bidx",
            name="uq_customer_document",
        ),
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_customer_document_number_bidx",
        "customer",
        ["document_number_bidx"],
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_customer_email_bidx",
        "customer",
        ["email_bidx"],
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_customer_phone_bidx",
        "customer",
        ["phone_bidx"],
        schema="core_bank",
    )

    op.create_table(
        "account",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_bank.customer.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "available_balance_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "ledger_balance_minor",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "data_origin",
            sa.String(length=32),
            server_default="synthetic",
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_account_data_origin",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_account_currency",
        ),
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_account_customer_id",
        "account",
        ["customer_id"],
        schema="core_bank",
    )

    op.create_table(
        "card",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_bank.account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_ref", sa.String(length=64), nullable=False, unique=True),
        sa.Column("pan_last4", sa.String(length=4), nullable=False),
        sa.Column("pan_enc", sa.Text(), nullable=False),
        sa.Column("brand", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "blocked_reason",
            block_reason_enum,
            nullable=True,
        ),
        sa.Column(
            "data_origin",
            sa.String(length=32),
            server_default="synthetic",
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'BLOCKED')",
            name="ck_card_status",
        ),
        sa.CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_card_data_origin",
        ),
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_card_account_id",
        "card",
        ["account_id"],
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_card_pan_last4",
        "card",
        ["pan_last4"],
        schema="core_bank",
    )

    op.create_table(
        "transaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_bank.account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_bank.card.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("mcc", sa.String(length=8), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="SETTLED",
            nullable=False,
        ),
        sa.Column(
            "dispute_eligible",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "data_origin",
            sa.String(length=32),
            server_default="synthetic",
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_transaction_data_origin",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_transaction_currency",
        ),
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_transaction_account_id",
        "transaction",
        ["account_id"],
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_transaction_card_id",
        "transaction",
        ["card_id"],
        schema="core_bank",
    )
    op.create_index(
        "ix_core_bank_transaction_occurred_at",
        "transaction",
        ["occurred_at"],
        schema="core_bank",
    )

    # 4. Tables in chat (without wrapped_dek)
    op.create_table(
        "conversation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "locale",
            sa.String(length=8),
            server_default="es",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="chat",
    )

    op.create_table(
        "message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat.conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("body_enc", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="chat",
    )
    op.create_index(
        "ix_chat_message_conversation_id",
        "message",
        ["conversation_id"],
        schema="chat",
    )
    op.create_index(
        "ix_chat_message_created_at",
        "message",
        ["created_at"],
        schema="chat",
    )


def downgrade() -> None:
    # Drop chat tables
    op.drop_table("message", schema="chat")
    op.drop_table("conversation", schema="chat")

    # Drop core_bank tables
    op.drop_table("transaction", schema="core_bank")
    op.drop_table("card", schema="core_bank")
    op.drop_table("account", schema="core_bank")
    op.drop_table("customer", schema="core_bank")

    # Drop enums
    sa.Enum(name="document_type_enum", schema="core_bank").drop(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(name="block_reason_enum", schema="core_bank").drop(
        op.get_bind(), checkfirst=True
    )

    # Drop schemas
    op.execute("DROP SCHEMA IF EXISTS ops CASCADE")
    op.execute("DROP SCHEMA IF EXISTS chat CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core_bank CASCADE")
