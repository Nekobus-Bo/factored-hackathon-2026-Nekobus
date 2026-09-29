"""Contract for card.block tool."""

from enum import Enum

from pydantic import Field

from contracts.envelope import Receipt
from contracts.tools.base import BaseToolInput, BaseToolOutput
from contracts.tools.card_list import CardStatus
from contracts.tools.handoff_create import HandoffRequirement
from contracts.tools.transaction_list_recent import (
    TRANSACTION_ID_MAX_LENGTH,
    TRANSACTION_ID_MIN_LENGTH,
)


class BlockReason(str, Enum):
    """Categorized justification for card blocking without free-form text."""

    LOST = "LOST"
    STOLEN = "STOLEN"
    UNRECOGNIZED_CHARGE = "UNRECOGNIZED_CHARGE"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class CardBlockInput(BaseToolInput):
    """Input payload to block a payment card.

    HARD RULE (ADR-0004 IDOR): targets a card ONLY by an opaque card_ref
    previously returned by card.list. Free-text notes are removed to eliminate
    PII leakage into DB/audit.

    There is deliberately no amount field (ADR-0003 amendment 2026-09-29): the
    amount the risk threshold compares comes from the database row of the
    disputed transaction, never from the model or the customer's words.
    """

    card_ref: str = Field(
        ...,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Opaque card reference returned by card.list",
    )
    reason: BlockReason = Field(
        ...,
        description="Structured business reason for blocking the card",
    )
    transaction_id: str | None = Field(
        default=None,
        min_length=TRANSACTION_ID_MIN_LENGTH,
        max_length=TRANSACTION_ID_MAX_LENGTH,
        description=(
            "Opaque transaction id returned by transaction.list_recent for the "
            "charge the customer disputes, on the card being blocked. "
            "banking-core reads its amount from the database. Never invent or "
            "guess one, and never state an amount"
        ),
    )


class CardBlockOutput(BaseToolOutput):
    """Result of card blocking action.

    Returns the verified receipt re-read from the database (ADR-0003).
    """

    card_ref: str = Field(
        ...,
        description="Opaque reference of the blocked card",
    )
    status: CardStatus = Field(
        default=CardStatus.BLOCKED,
        description="Updated card status",
    )
    receipt: Receipt = Field(
        ...,
        description="Verified receipt re-read from the database",
    )
    handoff_requirement: HandoffRequirement = Field(
        default_factory=HandoffRequirement,
        description=(
            "Policy outcome for the case (NONE, RECOMMENDED or REQUIRED, with "
            "priority, department and reason), decided by banking-core from the "
            "disputed transaction in the database. Also returned on an "
            "idempotent replay. The default only lets a response stored before "
            "this field existed validate; banking-core always sets it"
        ),
    )
