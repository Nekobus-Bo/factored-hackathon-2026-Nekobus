"""Contract for identity.verify_document tool."""

from enum import Enum

from pydantic import Field

from contracts.tools.base import BaseToolInput, BaseToolOutput
from contracts.tools.customer_match import DocumentType


class DocumentDecision(str, Enum):
    """Simulated provider decision outcome (ADR-0007)."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class IdentityVerifyDocumentInput(BaseToolInput):
    """Input payload for document identity verification.

    Takes opaque asset references, never raw biometric files or customer IDs.
    """

    document_type: DocumentType = Field(
        ...,
        description="Type of identity document submitted",
    )
    document_front_ref: str = Field(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_\-.]+$",
        description="Opaque storage reference for front document image",
    )
    document_back_ref: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_\-.]+$",
        description="Optional opaque storage reference for back document image",
    )


class IdentityVerifyDocumentOutput(BaseToolOutput):
    """Simulated identity document verification response.

    ADR-0007: simulated provider output; never sufficient alone to authorize actions.
    """

    decision: DocumentDecision = Field(
        ...,
        description="Verification outcome from simulated provider",
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Deterministic list of checks and reasons (e.g. LIVENESS_PASSED)",
    )
