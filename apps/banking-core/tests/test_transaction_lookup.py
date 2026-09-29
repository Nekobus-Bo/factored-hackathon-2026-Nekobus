"""DB-backed tests for the disputed-transaction lookup (ADR-0003 amendment 2026-09-29).

The amount a write tool's policy sees is read here from the database. The lookup
must be holder-scoped and answer identically for a transaction that does not
exist and one that belongs to someone else (ADR-0004, IDOR).
"""

import uuid
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from banking_core.models.core_bank import Transaction
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import create_scenario_fixtures, fixture_uuid
from banking_core.seed.staging import (
    StagingAccount,
    StagingCard,
    StagingCustomer,
    StagingDataset,
    StagingTransaction,
)
from banking_core.transactions.lookup import (
    TransactionNotFoundError,
    load_disputed_transaction,
)
from sqlalchemy.orm import Session

# The unrecognized "Global Electronics Megastore" charge every demo customer holds.
UNRECOGNIZED = {
    "es": ("COP", 35000000, "1050"),
    "pt": ("BRL", 48000, "1060"),
    "en": ("USD", 13999, "1070"),
}


def holder(locale: str) -> uuid.UUID:
    return fixture_uuid(f"{locale}-demo-customer")


def unrecognized_id(locale: str) -> str:
    return str(fixture_uuid(f"{locale}-demo-unrecognized-tx"))


@pytest.fixture
def seeded(db_session: Session) -> Generator[Session, None, None]:
    bundle = create_scenario_fixtures()
    staging = StagingDataset(
        customers=[StagingCustomer.model_validate(c) for c in bundle.customers],
        accounts=[StagingAccount.model_validate(a) for a in bundle.accounts],
        cards=[StagingCard.model_validate(c) for c in bundle.cards],
        transactions=[
            StagingTransaction.model_validate(t) for t in bundle.transactions
        ],
    )
    load_curated_data(
        staging,
        session=db_session,
        master_key="00" * 32,
        blind_index_salt="test-salt-transaction-lookup",
        force=True,
    )
    yield db_session
    db_session.rollback()
    db_session.execute(
        sa.text(
            "TRUNCATE TABLE core_bank.transaction, core_bank.card, "
            "core_bank.account, core_bank.customer CASCADE"
        )
    )
    db_session.commit()


@pytest.mark.parametrize("locale", sorted(UNRECOGNIZED))
def test_returns_the_facts_stored_in_the_database(seeded: Session, locale: str) -> None:
    currency, amount_minor, last4 = UNRECOGNIZED[locale]

    found = load_disputed_transaction(seeded, holder(locale), unrecognized_id(locale))

    assert found.transaction_id == unrecognized_id(locale)
    assert (found.amount_minor, found.currency) == (amount_minor, currency)
    assert found.merchant_name == "Global Electronics Megastore"
    assert found.card_ref == f"card_demo_{locale}"
    assert found.card_masked == f"**** **** **** {last4}"
    assert found.posted_at.tzinfo is not None


def test_a_card_filter_keeps_only_a_transaction_on_that_card(seeded: Session) -> None:
    own = load_disputed_transaction(
        seeded, holder("en"), unrecognized_id("en"), card_ref="card_demo_en"
    )
    assert own.card_ref == "card_demo_en"

    with pytest.raises(TransactionNotFoundError):
        load_disputed_transaction(
            seeded, holder("en"), unrecognized_id("en"), card_ref="card_demo_es"
        )


def test_a_transaction_of_another_customer_is_not_found(seeded: Session) -> None:
    with pytest.raises(TransactionNotFoundError):
        load_disputed_transaction(seeded, holder("es"), unrecognized_id("en"))
    with pytest.raises(TransactionNotFoundError):
        load_disputed_transaction(
            seeded, holder("es"), unrecognized_id("en"), card_ref="card_demo_en"
        )


def test_a_transaction_without_a_card_is_not_found(seeded: Session) -> None:
    seeded.execute(
        sa.update(Transaction)
        .where(Transaction.id == uuid.UUID(unrecognized_id("en")))
        .values(card_id=None)
    )
    seeded.flush()

    with pytest.raises(TransactionNotFoundError):
        load_disputed_transaction(seeded, holder("en"), unrecognized_id("en"))


def test_every_way_of_not_being_found_looks_the_same(seeded: Session) -> None:
    """A missing id, a foreign id and a malformed id cannot be told apart."""
    attempts = [
        (holder("es"), str(uuid.uuid4()), None),  # does not exist
        (holder("es"), unrecognized_id("en"), None),  # belongs to someone else
        (holder("en"), unrecognized_id("en"), "card_demo_es"),  # on another card
        (holder("es"), "not-a-uuid-at-all", None),  # malformed
        (holder("es"), "x" * 64, None),  # malformed, at the contract's maximum length
    ]
    errors = []
    for holder_id, transaction_id, card_ref in attempts:
        with pytest.raises(TransactionNotFoundError) as caught:
            load_disputed_transaction(seeded, holder_id, transaction_id, card_ref)
        errors.append((type(caught.value), caught.value.args, str(caught.value)))

    assert len(set(errors)) == 1
