"""DB-backed tests for the VERIFIED read tools (2B-3b) over the seed fixtures.

Covers holder scoping per locale, IDOR (another customer's card_ref or data is
never returned), the transaction page cap, and contract round-trips.
"""

import uuid
from collections.abc import Generator
from datetime import timedelta

import pytest
import sqlalchemy as sa
from banking_core.accounts.tools import execute_account_get_summary
from banking_core.cards.tools import execute_card_list
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
from banking_core.transactions.tools import execute_transaction_list_recent
from banking_core.transactions.tools.transaction_list_recent import (
    TRANSACTION_LIST_HARD_CAP,
    resolve_max_limit,
)
from contracts.tools.account_get_summary import (
    AccountGetSummaryInput,
    AccountGetSummaryOutput,
)
from contracts.tools.card_list import (
    CardListInput,
    CardListOutput,
    CardStatusFilter,
    CardType,
)
from contracts.tools.transaction_list_recent import (
    TransactionListRecentInput,
    TransactionListRecentOutput,
)
from sqlalchemy.orm import Session

LOCALES = {"es": "COP", "pt": "BRL", "en": "USD"}
LAST4 = {"es": "1050", "pt": "1060", "en": "1070"}


def demo_holder(locale: str) -> uuid.UUID:
    return fixture_uuid(f"{locale}-demo-customer")


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
        blind_index_salt="test-salt-read-tools",
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


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_card_list_is_scoped_to_holder_and_masked(seeded: Session, locale: str) -> None:
    out = execute_card_list(seeded, str(demo_holder(locale)), CardListInput())

    assert [c.card_ref for c in out.cards] == [f"card_demo_{locale}"]
    card = out.cards[0]
    assert card.masked_pan == f"**** **** **** {LAST4[locale]}"
    assert card.card_type == CardType.DEBIT
    assert card.expiry_month is None and card.expiry_year is None
    dumped = out.model_dump_json()
    assert CardListOutput.model_validate_json(dumped) == out
    # The seeded PANs end in these digits; only the last four may appear.
    assert "5099881" not in dumped


def test_card_list_status_filter(seeded: Session) -> None:
    holder = fixture_uuid("es-blocked-customer")
    blocked = execute_card_list(
        seeded, holder, CardListInput(status_filter=CardStatusFilter.BLOCKED)
    )
    active = execute_card_list(
        seeded, holder, CardListInput(status_filter=CardStatusFilter.ACTIVE)
    )
    assert blocked.cards and all(c.status.value == "BLOCKED" for c in blocked.cards)
    assert all(c.status.value == "ACTIVE" for c in active.cards)


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_transaction_list_recent_is_scoped_and_newest_first(
    seeded: Session, locale: str
) -> None:
    out = execute_transaction_list_recent(
        seeded, demo_holder(locale), TransactionListRecentInput()
    )

    assert len(out.transactions) == 2
    assert {t.card_ref for t in out.transactions} == {f"card_demo_{locale}"}
    assert {t.currency for t in out.transactions} == {LOCALES[locale]}
    posted = [t.posted_at for t in out.transactions]
    assert posted == sorted(posted, reverse=True)
    assert [t.merchant_name for t in out.transactions] == [
        "Local Artisan Bakery",
        "Global Electronics Megastore",
    ]
    assert TransactionListRecentOutput.model_validate_json(out.model_dump_json()) == out


def test_transaction_list_recent_rejects_another_holders_card_ref(
    seeded: Session,
) -> None:
    """IDOR: a valid card_ref of another customer returns nothing."""
    out = execute_transaction_list_recent(
        seeded,
        demo_holder("es"),
        TransactionListRecentInput(card_ref="card_demo_pt"),
    )
    assert out.transactions == []

    own = execute_transaction_list_recent(
        seeded,
        demo_holder("es"),
        TransactionListRecentInput(card_ref="card_demo_es"),
    )
    assert len(own.transactions) == 2


def test_transaction_list_recent_caps_the_page(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    card_id = fixture_uuid("es-demo-card")
    account_id = fixture_uuid("es-demo-account")
    base = seeded.get(Transaction, fixture_uuid("es-demo-legit-tx"))
    assert base is not None
    for i in range(60):
        seeded.add(
            Transaction(
                account_id=account_id,
                card_id=card_id,
                amount_minor=1000 + i,
                currency="COP",
                merchant=f"Extra Merchant {i}",
                mcc="5411",
                occurred_at=base.occurred_at - timedelta(days=10, minutes=i),
                status="SETTLED",
                dispute_eligible=True,
            )
        )
    seeded.flush()
    holder = demo_holder("es")

    full = execute_transaction_list_recent(
        seeded, holder, TransactionListRecentInput(limit=50)
    )
    assert len(full.transactions) == TRANSACTION_LIST_HARD_CAP
    assert full.transactions[0].merchant_name == "Local Artisan Bakery"

    capped = execute_transaction_list_recent(
        seeded, holder, TransactionListRecentInput(limit=50), max_limit=5
    )
    assert len(capped.transactions) == 5

    monkeypatch.setenv("TRANSACTION_LIST_MAX_LIMIT", "7")
    from_env = execute_transaction_list_recent(
        seeded, holder, TransactionListRecentInput(limit=50)
    )
    assert len(from_env.transactions) == 7

    assert resolve_max_limit(500) == TRANSACTION_LIST_HARD_CAP
    monkeypatch.setenv("TRANSACTION_LIST_MAX_LIMIT", "many")
    with pytest.raises(ValueError, match="TRANSACTION_LIST_MAX_LIMIT"):
        resolve_max_limit()


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_account_get_summary_is_scoped_to_holder(seeded: Session, locale: str) -> None:
    out = execute_account_get_summary(
        seeded, demo_holder(locale), AccountGetSummaryInput()
    )

    assert [a.account_ref for a in out.accounts] == [
        str(fixture_uuid(f"{locale}-demo-account"))
    ]
    account = out.accounts[0]
    assert account.currency == LOCALES[locale]
    assert account.account_type.value == "CHECKING"
    assert isinstance(account.available_balance_minor, int)
    assert AccountGetSummaryOutput.model_validate_json(out.model_dump_json()) == out


def test_account_get_summary_can_omit_balances(seeded: Session) -> None:
    output = execute_account_get_summary(
        seeded,
        demo_holder("es"),
        AccountGetSummaryInput(include_balances=False),
    )

    [account] = output.accounts
    assert account.available_balance_minor is None
    assert account.ledger_balance_minor is None
    assert (
        AccountGetSummaryOutput.model_validate_json(output.model_dump_json()) == output
    )


def test_unknown_holder_sees_nothing(seeded: Session) -> None:
    stranger = uuid.uuid4()
    assert execute_card_list(seeded, stranger, CardListInput()).cards == []
    assert (
        execute_transaction_list_recent(
            seeded, stranger, TransactionListRecentInput()
        ).transactions
        == []
    )
    assert (
        execute_account_get_summary(seeded, stranger, AccountGetSummaryInput()).accounts
        == []
    )
