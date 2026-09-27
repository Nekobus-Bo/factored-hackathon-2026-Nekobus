"""Contract for card.block tool."""

from enum import Enum

from pydantic import Field

from contracts.envelope import Receipt
from contracts.tools.base import BaseToolInput, BaseToolOutput
from contracts.tools.card_list import CardStatus


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
