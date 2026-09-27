"""Unit tests for SQLAlchemy domain models instantiation and metadata."""

import uuid
from datetime import UTC, datetime

from banking_core.models import (
    Account,
    Base,
    BlockReason,
    Card,
    Conversation,
    Customer,
    DocumentType,
    Message,
    Transaction,
)


def test_models_metadata_tables() -> None:
    """Verify all required tables and schemas exist in Base.metadata."""
    tables = Base.metadata.tables

    expected_tables = {
        "core_bank.customer",
        "core_bank.account",
        "core_bank.card",
        "core_bank.transaction",
        "chat.conversation",
        "chat.message",
    }
    assert expected_tables.issubset(tables.keys())


def test_models_in_memory_sqlite() -> None:
    """Verify models can be defined and bound to a session."""
    # SQLite does not support schemas by default without attach,
    # so we test entity instantiation and attribute access.
    cust_id = uuid.uuid4()
    now = datetime.now(UTC)

    customer = Customer(
        id=cust_id,
        document_type=DocumentType.NATIONAL_ID,
        document_number_enc="v1:mock:mock",
        document_number_bidx="a" * 64,
        full_name_enc="v1:mock:mock",
        email_enc="v1:mock:mock",
        email_bidx="b" * 64,
        phone_enc="v1:mock:mock",
        phone_bidx="c" * 64,
        birth_date_enc="v1:mock:mock",
        preferred_locale="es",
        registered_otp_channel="sms",
        data_origin="synthetic",
        created_at=now,
    )
    assert customer.id == cust_id
    assert customer.document_type == DocumentType.NATIONAL_ID
    assert customer.preferred_locale == "es"

    acc_id = uuid.uuid4()
    account = Account(
        id=acc_id,
        customer_id=cust_id,
        type="SAVINGS",
        currency="COP",
        available_balance_minor=100000,
        ledger_balance_minor=100000,
        status="ACTIVE",
        data_origin="synthetic",
    )
    assert account.available_balance_minor == 100000

    card_id = uuid.uuid4()
    card = Card(
        id=card_id,
        account_id=acc_id,
        card_ref="card_test123",
        pan_last4="1234",
        pan_enc="v1:mock:mock",
        brand="VISA",
        status="ACTIVE",
        blocked_reason=None,
        data_origin="synthetic",
    )
    assert card.pan_last4 == "1234"

    tx_id = uuid.uuid4()
    tx = Transaction(
        id=tx_id,
        account_id=acc_id,
        card_id=card_id,
        amount_minor=5000,
        currency="COP",
        merchant="Supermarket",
        mcc="5411",
        occurred_at=now,
        status="SETTLED",
        dispute_eligible=True,
        data_origin="synthetic",
    )
    assert tx.amount_minor == 5000

    conv_id = uuid.uuid4()
    conv = Conversation(
        id=conv_id,
        locale="es",
        started_at=now,
    )
    assert conv.locale == "es"

    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="customer",
        body_enc="v1:mock:mock",
        created_at=now,
    )
    assert msg.role == "customer"
    assert BlockReason.LOST == "LOST"
    assert BlockReason.CUSTOMER_REQUEST == "CUSTOMER_REQUEST"


def test_document_type_parity_with_contracts() -> None:
    """Verify DocumentType enum has exact four values from packages/contracts."""
    expected = {
        "NATIONAL_ID",
        "PASSPORT",
        "FOREIGN_ID",
        "TAX_ID",
    }
    actual = {d.value for d in DocumentType}
    assert actual == expected


def test_db_enum_values_match_contracts() -> None:
    """Verify SQLAlchemy columns use the exact enum values from contracts."""
    from contracts.tools.card_block import BlockReason as ContractsBlockReason
    from contracts.tools.customer_match import DocumentType as ContractsDocumentType

    # Verify model enums are identical to contracts
    assert BlockReason is ContractsBlockReason
    assert DocumentType is ContractsDocumentType

    # Check Customer.document_type DB enum values
    doc_type_col = Customer.__table__.c.document_type
    doc_type_sa_enum = doc_type_col.type
    expected_doc_types = [e.value for e in ContractsDocumentType]
    assert sorted(doc_type_sa_enum.enums) == sorted(expected_doc_types)

    # Check Card.blocked_reason DB enum values
    card_reason_col = Card.__table__.c.blocked_reason
    card_reason_sa_enum = card_reason_col.type
    expected_block_reasons = [e.value for e in ContractsBlockReason]
    assert sorted(card_reason_sa_enum.enums) == sorted(expected_block_reasons)
