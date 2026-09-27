"""Data normalization utilities for deterministic blind indexing."""

import re

from banking_core.crypto.exceptions import NormalizationError
from banking_core.models.enums import DocumentType

NUMERIC_DOC_TYPES = {DocumentType.NATIONAL_ID, DocumentType.TAX_ID}
ALPHANUMERIC_DOC_TYPES = {DocumentType.PASSPORT, DocumentType.FOREIGN_ID}


def resolve_document_type(document_type: DocumentType | str | None) -> DocumentType:
    """Validate and convert document type to DocumentType enum member."""
    if not document_type:
        raise NormalizationError("Document type is required")
    if isinstance(document_type, DocumentType):
        return document_type
    try:
        return DocumentType(str(document_type).strip().upper())
    except (ValueError, AttributeError):
        raise NormalizationError(
            f"Unknown or invalid document type: '{document_type}'"
        ) from None


def normalize_document(value: str, document_type: DocumentType | str) -> str:
    """Normalize document identifier.

    - Numeric document types (NATIONAL_ID, TAX_ID): digits only.
    - Alphanumeric document types (PASSPORT, FOREIGN_ID): uppercase alphanumeric only.
    """
    if not value or not isinstance(value, str):
        raise NormalizationError("Document number must be a non-empty string")
    if ":" in value:
        raise NormalizationError(f"Document number cannot contain ':': '{value}'")

    doc_type = resolve_document_type(document_type)

    if doc_type in ALPHANUMERIC_DOC_TYPES:
        clean = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        if not clean:
            raise NormalizationError(
                f"Document of type '{doc_type.value}' must contain alphanumeric chars"
            )
        return clean

    # Numeric document types: digits only
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise NormalizationError(
            f"Document of type '{doc_type.value}' must contain at least one digit"
        )
    return digits


def normalize_email(value: str) -> str:
    """Normalize email address to trimmed lowercase.

    Example:
        '  Alice@Bank.COM ' -> 'alice@bank.com'
    """
    if not value or not isinstance(value, str):
        raise NormalizationError("Email must be a non-empty string")
    normalized = value.strip().lower()
    if not normalized:
        raise NormalizationError("Email cannot be empty after trimming")
    return normalized


def normalize_phone(value: str) -> str:
    """Normalize phone number to E.164 format (+<country_code><digits>).

    Must start with an explicit '+' international country prefix.
    Rejects numbers without '+'.
    """
    if not value or not isinstance(value, str):
        raise NormalizationError("Phone number must be a non-empty string")
    trimmed = value.strip()
    if not trimmed.startswith("+"):
        raise NormalizationError(
            f"Phone '{value}' must include an international prefix starting with '+'"
        )
    digits = re.sub(r"\D", "", trimmed)
    if not digits:
        raise NormalizationError("Phone number must contain digits after '+'")
    return f"+{digits}"


def normalize_for_field(
    field_name: str,
    value: str,
    document_type: DocumentType | str | None = None,
) -> str:
    """Dispatch normalization based on the canonical field name."""
    clean_field = field_name.strip().lower()
    if clean_field in ("document", "document_number", "document_number_bidx"):
        if document_type is None:
            raise NormalizationError(
                f"document_type is required when normalizing '{field_name}'"
            )
        return normalize_document(value, document_type=document_type)
    if clean_field in ("email", "email_address", "email_bidx"):
        return normalize_email(value)
    if clean_field in ("phone", "phone_number", "phone_bidx"):
        return normalize_phone(value)
    return value.strip()
