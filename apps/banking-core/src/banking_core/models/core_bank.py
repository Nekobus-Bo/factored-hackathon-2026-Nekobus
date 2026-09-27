"""SQLAlchemy models for the `core_bank` schema."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from banking_core.models.base import Base
from banking_core.models.enums import BlockReason, DocumentType


class Customer(Base):
    """Customer entity with encrypted PII and blind indexes for searchability."""

    __tablename__ = "customer"
    __table_args__ = (
        CheckConstraint(
            "preferred_locale IN ('es', 'pt', 'en')",
            name="ck_customer_locale",
        ),
        CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_customer_data_origin",
        ),
        UniqueConstraint(
            "document_type",
            "document_number_bidx",
            name="uq_customer_document",
        ),
        {"schema": "core_bank"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(
            DocumentType,
            name="document_type_enum",
            schema="core_bank",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    document_number_enc: Mapped[str] = mapped_column(Text, nullable=False)
    document_number_bidx: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    full_name_enc: Mapped[str] = mapped_column(Text, nullable=False)
    email_enc: Mapped[str] = mapped_column(Text, nullable=False)
    email_bidx: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone_enc: Mapped[str] = mapped_column(Text, nullable=False)
    phone_bidx: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    birth_date_enc: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_locale: Mapped[str] = mapped_column(
        String(8), nullable=False, default="es"
    )
    registered_otp_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    data_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Lineage columns (docs/data.md)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    accounts: Mapped[list["Account"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class Account(Base):
    """Bank account entity."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_account_data_origin",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_account_currency",
        ),
        {"schema": "core_bank"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_bank.customer.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    available_balance_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    ledger_balance_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    # Lineage columns
    data_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="accounts")
    cards: Mapped[list["Card"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class Card(Base):
    """Payment card entity associated with an account."""

    __tablename__ = "card"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'BLOCKED')",
            name="ck_card_status",
        ),
        CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_card_data_origin",
        ),
        {"schema": "core_bank"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_bank.account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    card_ref: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    pan_last4: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    pan_enc: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blocked_reason: Mapped[BlockReason | None] = mapped_column(
        SAEnum(
            BlockReason,
            name="block_reason_enum",
            schema="core_bank",
            native_enum=True,
        ),
        nullable=True,
    )

    # Lineage columns
    data_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="cards")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="card",
    )


class Transaction(Base):
    """Financial transaction on an account and optional card."""

    __tablename__ = "transaction"
    __table_args__ = (
        CheckConstraint(
            "data_origin IN ('synthetic', 'dataset')",
            name="ck_transaction_data_origin",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_transaction_currency",
        ),
        {"schema": "core_bank"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_bank.account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_bank.card.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    mcc: Mapped[str] = mapped_column(String(8), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SETTLED")
    dispute_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Lineage columns
    data_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="synthetic"
    )
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    card: Mapped["Card | None"] = relationship(back_populates="transactions")
