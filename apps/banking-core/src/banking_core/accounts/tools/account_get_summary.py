"""Implementation of account.get_summary tool in banking-core.

Read-only and holder-scoped (ADR-0004): the holder comes from the caller's
session, never from tool arguments. No writes and no audit here; the
dispatcher audits.
"""

import uuid

import sqlalchemy as sa
from contracts.tools.account_get_summary import (
    AccountGetSummaryInput,
    AccountGetSummaryOutput,
    AccountStatus,
    AccountSummaryItem,
    AccountType,
)
from sqlalchemy.orm import Session

from banking_core.models.core_bank import Account


def execute_account_get_summary(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    args: AccountGetSummaryInput,
) -> AccountGetSummaryOutput:
    """Summarize the holder's accounts, including balances only when requested."""
    holder_id = uuid.UUID(str(holder_customer_id))
    stmt = (
        sa.select(Account)
        .where(Account.customer_id == holder_id)
        .order_by(Account.type, Account.id)
    )
    items = [
        AccountSummaryItem(
            account_ref=str(account.id),
            account_type=AccountType(account.type),
            currency=account.currency,
            available_balance_minor=(
                account.available_balance_minor if args.include_balances else None
            ),
            ledger_balance_minor=(
                account.ledger_balance_minor if args.include_balances else None
            ),
            status=AccountStatus(account.status),
        )
        for account in db_session.scalars(stmt).all()
    ]
    return AccountGetSummaryOutput(accounts=items)
