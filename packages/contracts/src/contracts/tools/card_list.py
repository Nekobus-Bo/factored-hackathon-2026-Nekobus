"""Contract for card.list tool."""

from enum import Enum

from pydantic import Field, StrictInt

from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput


class CardStatus(str, Enum):
    """Lifecycle status of a payment card."""

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    FROZEN = "FROZEN"
    EXPIRED = "EXPIRED"


class CardType(str, Enum):
    """Product type of payment card."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class CardStatusFilter(str, Enum):
    """Filter criteria for listing cards."""

    ALL = "ALL"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    FROZEN = "FROZEN"


class CardItem(BaseToolModel):
    """Card summary with masked PAN.

    ADR-0004 IDOR mitigation: card_ref is an opaque reference token returned
    to the model. The model must use card_ref for downstream card operations.
    """

    card_ref: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Opaque card identifier used for tool calls like card.block",
    )
    masked_pan: str = Field(
        ...,
        pattern=r"^\*{4}\s?\*{4}\s?\*{4}\s?\d{4}$",
        description="Masked Primary Account Number (e.g. **** **** **** 1234)",
    )
    card_type: CardType = Field(
        ...,
        description="Card product category (DEBIT or CREDIT)",
    )
    status: CardStatus = Field(
        ...,
        description="Current operational status of card",
    )
    expiry_month: StrictInt | None = Field(
        default=None,
        ge=1,
        le=12,
        description="Two-digit expiry month; None when the source has no expiry",
    )
    expiry_year: StrictInt | None = Field(
        default=None,
        ge=2024,
        le=2040,
        description="Four-digit expiry year; None when the source has no expiry",
    )


class CardListInput(BaseToolInput):
    """Input payload for listing cards.

    Customer identity is pinned server-side in banking-core session.
    """

    status_filter: CardStatusFilter = Field(
        default=CardStatusFilter.ALL,
        description="Optional filter by card operational status",
    )


class CardListOutput(BaseToolOutput):
    """List of payment cards for the pinned customer."""

    cards: list[CardItem] = Field(
        default_factory=list,
        description="List of cards associated with the verified customer",
    )
