"""Contract for customer.match tool."""

from datetime import date
from enum import Enum

from pydantic import Field, StrictBool

from contracts.tools.base import BaseToolInput, BaseToolOutput


class DocumentType(str, Enum):
    """Supported identification document types."""

    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"
    FOREIGN_ID = "FOREIGN_ID"
    TAX_ID = "TAX_ID"


class CustomerMatchInput(BaseToolInput):
    """Input payload for matching claimed identification data.

    ADR-0004 IDOR mitigation: does not accept customer IDs or account identifiers.
    """

    document_type: DocumentType = Field(
        ...,
        description="Type of identification document presented by customer",
    )
    document_number: str = Field(
        ...,
        min_length=4,
        max_length=32,
        pattern=r"^[A-Za-z0-9\-.]+$",
        description="Identification document number without spaces",
    )
    birth_date: date | None = Field(
        default=None,
        description="Optional date of birth (YYYY-MM-DD) for secondary matching",
    )


class CustomerMatchOutput(BaseToolOutput):
    """Result of identity match.

    ADR-0004: returns only boolean match status.
    Responses are strictly indistinguishable for non-existent data to prevent enumeration.
    """

    matched: StrictBool = Field(
        ...,
        description="True if claimed data matched banking records; false otherwise",
    )
