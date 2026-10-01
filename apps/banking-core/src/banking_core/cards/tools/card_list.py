"""Implementation of card.list tool in banking-core.

Read-only and holder-scoped (ADR-0004): the holder comes from the caller's
session, never from tool arguments. Cards are exposed as card_ref plus a masked
PAN built from the stored last four digits; the encrypted PAN is never read.
No writes and no audit here; the dispatcher audits.
"""

import uuid

import sqlalchemy as sa
from contracts.tools.card_list import (
    CardItem,
    CardListInput,
    CardListOutput,
    CardStatus,
    CardStatusFilter,
    CardType,
)
from sqlalchemy.orm import Session, defer

from banking_core.models.core_bank import Account, Card


def _masked_pan(last4: str) -> str:
    return f"**** **** **** {last4}"


def _card_type(card: Card, account_type: str) -> CardType:
    # Prefer a stored card_type (nullable column added by migration 0005, set only
    # for dataset cards); otherwise derive it from the account product.
    stored = getattr(card, "card_type", None)
    if stored:
        return CardType(stored)
    return CardType.CREDIT if account_type == "CREDIT_LINE" else CardType.DEBIT


def execute_card_list(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    args: CardListInput,
) -> CardListOutput:
    """List the holder's cards, optionally filtered by status."""
    holder_id = uuid.UUID(str(holder_customer_id))
    stmt = (
        sa.select(Card, Account.type)
        .join(Account, Card.account_id == Account.id)
        .where(Account.customer_id == holder_id)
        .order_by(Card.card_ref)
        .options(defer(Card.pan_enc, raiseload=True))
    )
    if args.status_filter != CardStatusFilter.ALL:
        stmt = stmt.where(Card.status == args.status_filter.value)

    items = [
        CardItem(
            card_ref=card.card_ref,
            masked_pan=_masked_pan(card.pan_last4),
            card_type=_card_type(card, account_type),
            status=CardStatus(card.status),
            expiry_month=getattr(card, "expiry_month", None),
            expiry_year=getattr(card, "expiry_year", None),
        )
        for card, account_type in db_session.execute(stmt).all()
    ]
    return CardListOutput(cards=items)
