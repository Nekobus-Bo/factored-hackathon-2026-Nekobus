"""Contract for account.get_summary tool."""

from enum import Enum

from pydantic import Field, StrictBool, StrictInt

from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput


class AccountType(str, Enum):
    """Type of deposit or credit account."""

    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    CREDIT_LINE = "CREDIT_LINE"


class AccountStatus(str, Enum):
    """Lifecycle status of an account."""

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AccountGetSummaryInput(BaseToolInput):
    """Input payload for retrieving account summary.

    HARD RULE (ADR-0004 IDOR): customer identity is pinned in the session.
    No account_id, customer_id, owner, or holder parameter is accepted from the model.
    """

    include_balances: StrictBool = Field(
        default=True,
        description="Whether to include available and ledger balance figures",
    )


class AccountSummaryItem(BaseToolModel):
    """Account financial summary with minor currency units."""

    account_ref: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Opaque account reference token",
    )
    account_type: AccountType = Field(
        ...,
        description="Type of banking account",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 three-letter currency code",
    )
    available_balance_minor: StrictInt | None = Field(
        default=None,
        description="Available spendable balance in minor units, when requested",
    )
    ledger_balance_minor: StrictInt | None = Field(
        default=None,
        description="Total ledger balance in minor units, when requested",
    )
    status: AccountStatus = Field(
        ...,
        description="Current operational status of account",
    )


class AccountGetSummaryOutput(BaseToolOutput):
    """Account summaries for the pinned customer."""

    accounts: list[AccountSummaryItem] = Field(
        default_factory=list,
        description="Accounts belonging to the pinned session customer",
    )
