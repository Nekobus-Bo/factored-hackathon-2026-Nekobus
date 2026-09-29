"""Resolve the transaction a write tool refers to by its opaque transaction_id.

card.block and handoff.create take the id of the charge the customer disputes
(ADR-0003 amendment 2026-09-29). Everything about that charge, above all its
amount, is read here from the database and nothing from the tool arguments.

Ownership (ADR-0004, IDOR): the transaction must belong to an account of the
pinned holder and, when a card is given, be on that card. A transaction that
does not exist, that belongs to someone else, that is on another card, and an
id that is not even a UUID all raise the same error: the caller cannot tell
them apart, so the tool cannot be used to probe for other customers' data.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from banking_core.models.core_bank import Account, Card, Transaction


class TransactionNotFoundError(LookupError):
    """No such transaction for this holder: missing, not theirs or on another card."""


@dataclass(frozen=True)
class DisputedTransaction:
    """The database facts about a disputed transaction, safe to show a human."""

    transaction_id: str
    card_ref: str
    card_masked: str
    amount_minor: int
    currency: str
    merchant_name: str
    posted_at: datetime


def load_disputed_transaction(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    transaction_id: str,
    card_ref: str | None = None,
) -> DisputedTransaction:
    """Load a card transaction of the holder, optionally required to be on `card_ref`.

    Raises:
        TransactionNotFoundError: For every way the transaction is not the
            holder's (or not on that card), with no way to tell them apart.
    """
    holder_id = uuid.UUID(str(holder_customer_id))
    try:
        tx_id = uuid.UUID(transaction_id)
    except ValueError:
        raise TransactionNotFoundError from None

    stmt = (
        sa.select(Transaction, Card.card_ref, Card.pan_last4)
        .join(Account, Transaction.account_id == Account.id)
        .join(Card, Transaction.card_id == Card.id)
        .where(Transaction.id == tx_id, Account.customer_id == holder_id)
    )
    if card_ref is not None:
        stmt = stmt.where(Card.card_ref == card_ref)

    row = db_session.execute(stmt).one_or_none()
    if row is None:
        raise TransactionNotFoundError
    transaction, found_card_ref, pan_last4 = row
    return DisputedTransaction(
        transaction_id=str(transaction.id),
        card_ref=found_card_ref,
        # Cards loaded from a dataset may have no PAN: fall back to the opaque ref.
        card_masked=f"**** **** **** {pan_last4}" if pan_last4 else found_card_ref,
        amount_minor=transaction.amount_minor,
        currency=transaction.currency,
        merchant_name=transaction.merchant,
        posted_at=transaction.occurred_at,
    )
