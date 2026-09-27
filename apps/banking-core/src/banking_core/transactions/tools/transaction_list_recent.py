"""Implementation of transaction.list_recent tool in banking-core.

Read-only and holder-scoped (ADR-0004): the holder comes from the caller's
session, never from tool arguments, and a card_ref of another customer simply
matches nothing. No writes and no audit here; the dispatcher audits.

Only card transactions are listed: the contract requires a card_ref per item.
"""

import os
import uuid

import sqlalchemy as sa
from contracts.tools.transaction_list_recent import (
    TransactionItem,
    TransactionListRecentInput,
    TransactionListRecentOutput,
    TransactionStatus,
)
from sqlalchemy.orm import Session

from banking_core.models.core_bank import Account, Card, Transaction

# Non-configurable ceiling, equal to the contract's maximum for `limit`.
TRANSACTION_LIST_HARD_CAP = 50


def resolve_max_limit(configured: int | None = None) -> int:
    """Resolve the configured page ceiling, clamped to the hard cap.

    Seeded from TRANSACTION_LIST_MAX_LIMIT; an invalid value fails loudly.
    """
    if configured is None:
        raw = os.getenv("TRANSACTION_LIST_MAX_LIMIT", str(TRANSACTION_LIST_HARD_CAP))
        try:
            configured = int(raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid integer value for TRANSACTION_LIST_MAX_LIMIT: '{raw}'"
            ) from exc
    if configured < 1:
        raise ValueError("TRANSACTION_LIST_MAX_LIMIT must be at least 1")
    return min(configured, TRANSACTION_LIST_HARD_CAP)


def execute_transaction_list_recent(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    args: TransactionListRecentInput,
    max_limit: int | None = None,
) -> TransactionListRecentOutput:
    """List the holder's most recent card transactions, newest first."""
    holder_id = uuid.UUID(str(holder_customer_id))
    limit = min(args.limit, resolve_max_limit(max_limit))

    stmt = (
        sa.select(Transaction, Card.card_ref)
        .join(Account, Transaction.account_id == Account.id)
        .join(Card, Transaction.card_id == Card.id)
        .where(Account.customer_id == holder_id)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(limit)
    )
    if args.card_ref is not None:
        stmt = stmt.where(Card.card_ref == args.card_ref)

    items = [
        TransactionItem(
            transaction_id=str(tx.id),
            card_ref=card_ref,
            amount_minor=tx.amount_minor,
            currency=tx.currency,
            merchant_name=tx.merchant,
            merchant_category=tx.mcc,
            posted_at=tx.occurred_at,
            status=TransactionStatus(tx.status),
            is_disputable=tx.dispute_eligible,
        )
        for tx, card_ref in db_session.execute(stmt).all()
    ]
    return TransactionListRecentOutput(transactions=items)
