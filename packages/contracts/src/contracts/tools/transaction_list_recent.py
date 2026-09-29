"""Contract for transaction.list_recent tool."""

from datetime import datetime
from enum import Enum

from pydantic import Field, StrictBool, StrictInt

from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput

# One definition of the opaque transaction id constraints: the id returned here
# is the id card.block and handoff.create accept back.
TRANSACTION_ID_MIN_LENGTH = 8
TRANSACTION_ID_MAX_LENGTH = 64


class TransactionStatus(str, Enum):
    """Settlement status of a transaction."""

    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"


class TransactionListRecentInput(BaseToolInput):
    """Input payload for retrieving recent customer transactions.

    IDOR mitigation: card_ref is an opaque token from card.list, not an account number.
    Customer identity is resolved server-side from the verified session.
    """

    card_ref: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_\-]+$",
        description="Optional opaque card reference to filter transactions",
    )
    limit: StrictInt = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of transactions to retrieve (1-50)",
    )


class TransactionItem(BaseToolModel):
    """Individual transaction record with integer minor currency units."""

    transaction_id: str = Field(
        ...,
        min_length=TRANSACTION_ID_MIN_LENGTH,
        max_length=TRANSACTION_ID_MAX_LENGTH,
        description="Opaque transaction identifier",
    )
    card_ref: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Opaque card reference associated with transaction",
    )
    amount_minor: StrictInt = Field(
        ...,
        ge=0,
        description="Monetary transaction amount in integer minor units (e.g. cents)",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 three-letter currency code (e.g. COP, USD)",
    )
    merchant_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Merchant or counterparty name",
    )
    merchant_category: str | None = Field(
        default=None,
        max_length=60,
        description="Merchant category or business code",
    )
    posted_at: datetime = Field(
        ...,
        description="Timestamp when transaction was posted",
    )
    status: TransactionStatus = Field(
        ...,
        description="Current transaction status",
    )
    is_disputable: StrictBool = Field(
        default=True,
        description="Whether transaction is eligible for fraud dispute handoff",
    )


class TransactionListRecentOutput(BaseToolOutput):
    """Recent transaction history for customer."""

    transactions: list[TransactionItem] = Field(
        default_factory=list,
        description="List of recent transactions ordered by posting date descending",
    )
