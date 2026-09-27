"""Implementation of card.block tool in banking-core.

Rules (ADR-0003, ADR-0004, AGENTS rule 4):
- The card is resolved by card_ref AND the holder from the caller's session; a
  card of another customer is indistinguishable from a missing one.
- The authorizer's policy decision is an input: card.block is never refused by
  amount here, its flags only travel with the result and the audit row.
- The status change and its audit row commit in one transaction; the receipt is
  then re-read from the database, never built from the arguments.
- An already BLOCKED card is not written again: the call is audited and returns
  a receipt with state_before == state_after == BLOCKED.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
from contracts.envelope import Receipt, ResourceState
from contracts.tools.card_block import CardBlockInput, CardBlockOutput
from contracts.tools.card_list import CardStatus
from sqlalchemy.orm import Session

from banking_core.audit.service import append as append_audit
from banking_core.control.policy import Decision
from banking_core.models.core_bank import Account, Card
from banking_core.models.ops import AuditLog

ACTION = "card.block"


class CardNotFoundError(LookupError):
    """No card with that card_ref belongs to the holder (missing or not theirs)."""


@dataclass(frozen=True)
class CardBlockResult:
    """Contract output plus the advisory policy flags for the caller to act on."""

    output: CardBlockOutput
    flags: list[str] = field(default_factory=list)


def format_audit_id(audit_row_id: int) -> str:
    return f"aud_{audit_row_id:08d}"


def execute_card_block(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    args: CardBlockInput,
    policy_decision: Decision,
    idempotency_scope: str,
) -> CardBlockResult:
    """Block the holder's card and return the receipt re-read after commit.

    Raises:
        ValueError: If policy_decision does not allow the call.
        CardNotFoundError: If the card does not exist or is not the holder's.
    """
    if not policy_decision.allowed:
        raise ValueError("card.block requires an allowed policy decision")
    holder_id = uuid.UUID(str(holder_customer_id))

    try:
        card = db_session.execute(
            sa.select(Card)
            .join(Account, Card.account_id == Account.id)
            .where(Card.card_ref == args.card_ref, Account.customer_id == holder_id)
            .with_for_update(of=Card)
        ).scalar_one_or_none()
        if card is None:
            raise CardNotFoundError(args.card_ref)

        state_before = card.status
        already_blocked = state_before == CardStatus.BLOCKED.value
        if not already_blocked:
            card.status = CardStatus.BLOCKED.value
            card.blocked_at = datetime.now(UTC)
            card.blocked_reason = args.reason

        audit_row = append_audit(
            session=db_session,
            actor_type="customer_session",
            actor_ref=idempotency_scope,
            action=ACTION,
            decision="allowed",
            reason_code=(
                policy_decision.reason_code.value
                if policy_decision.reason_code
                else None
            ),
            payload={
                "card_ref": args.card_ref,
                "reason": args.reason.value,
                "state_before": state_before,
                "state_after": CardStatus.BLOCKED.value,
                "already_blocked": already_blocked,
                "flags": list(policy_decision.flags),
            },
        )
        card_id, audit_id = card.id, audit_row.id
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    # Re-read what was committed; nothing below comes from the arguments.
    db_session.expire_all()
    stored = db_session.execute(
        sa.select(Card.card_ref, Card.status, Card.pan_last4, Card.blocked_at).where(
            Card.id == card_id
        )
    ).one()
    audit = db_session.get(AuditLog, audit_id)
    if audit is None or stored.blocked_at is None:
        raise RuntimeError("card.block receipt could not be re-read from the database")

    receipt = Receipt(
        action=ACTION,
        target_masked=f"**** **** **** {stored.pan_last4}",
        state_before=ResourceState(audit.payload["state_before"]),
        state_after=ResourceState(stored.status),
        verified_at=stored.blocked_at,
        audit_id=format_audit_id(audit.id),
    )
    output = CardBlockOutput(
        card_ref=stored.card_ref,
        status=CardStatus(stored.status),
        receipt=receipt,
    )
    return CardBlockResult(output=output, flags=list(policy_decision.flags))
