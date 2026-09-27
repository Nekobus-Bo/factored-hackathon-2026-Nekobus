"""Enumerations for banking-core domain models."""

import enum


class BlockReason(enum.StrEnum):
    """Reason for card blockage matching packages/contracts BlockReason."""

    LOST = "LOST"
    STOLEN = "STOLEN"
    UNRECOGNIZED_CHARGE = "UNRECOGNIZED_CHARGE"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class DocumentType(enum.StrEnum):
    """Document type matching packages/contracts DocumentType."""

    NATIONAL_ID = "NATIONAL_ID"
    PASSPORT = "PASSPORT"
    FOREIGN_ID = "FOREIGN_ID"
    TAX_ID = "TAX_ID"
