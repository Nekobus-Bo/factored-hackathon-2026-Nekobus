"""Audit logging package with hash chaining and PII guard."""

from banking_core.audit.canonical import (
    GENESIS_PREV_HASH,
    canonical_entry_json,
    compute_entry_hash,
)
from banking_core.audit.pii_guard import PiiLeakError, check_payload
from banking_core.audit.service import append, verify_chain

__all__ = [
    "GENESIS_PREV_HASH",
    "PiiLeakError",
    "append",
    "canonical_entry_json",
    "check_payload",
    "compute_entry_hash",
    "verify_chain",
]
