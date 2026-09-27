"""Blind index calculation using HMAC-SHA256 and HKDF field-derived keys."""

import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from banking_core.crypto.exceptions import InvalidKeyError, NormalizationError
from banking_core.crypto.normalize import (
    normalize_document,
    normalize_for_field,
    resolve_document_type,
)
from banking_core.models.enums import DocumentType


def derive_blind_index_key(salt: str | bytes, field_name: str) -> bytes:
    """Derive a per-field 256-bit key from BLIND_INDEX_SALT using HKDF-SHA256.

    The field name is passed as the HKDF `info` parameter to ensure key isolation
    across different attributes.
    """
    salt_bytes = salt.encode("utf-8") if isinstance(salt, str) else salt
    if not salt_bytes:
        raise InvalidKeyError("Blind index salt cannot be empty")
    info_bytes = field_name.encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=info_bytes,
    )
    return hkdf.derive(salt_bytes)


def compute_blind_index(
    value: str,
    field_name: str,
    salt: str | bytes | None = None,
    normalize: bool = True,
    document_type: DocumentType | str | None = None,
) -> str:
    """Compute deterministic HMAC-SHA256 blind index for a given field and value.

    Args:
        value: Input value to index.
        field_name: Canonical attribute name (e.g. 'document_number', 'email', 'phone').
        salt: Optional salt. If None, loaded from env `BLIND_INDEX_SALT`.
        normalize: Whether to apply canonical normalization before indexing.
        document_type: Required DocumentType enum or string when indexing documents.

    Returns:
        Hex-encoded 64-character SHA-256 HMAC digest.

    Raises:
        InvalidKeyError: If salt is missing or empty.
        NormalizationError: If document_type is missing/invalid or normalized value
            contains ':'.
    """
    if salt is None:
        salt = os.getenv("BLIND_INDEX_SALT")
        if not salt:
            raise InvalidKeyError(
                "BLIND_INDEX_SALT environment variable is required and cannot be empty"
            )

    clean_field = field_name.strip().lower()
    if clean_field in ("document", "document_number", "document_number_bidx"):
        if document_type is None:
            raise NormalizationError(
                f"document_type is required when indexing '{field_name}'"
            )
        doc_type = resolve_document_type(document_type)
        if normalize:
            norm_doc = normalize_document(value, document_type=doc_type)
        else:
            norm_doc = value

        if ":" in norm_doc:
            raise NormalizationError(
                f"Document value cannot contain ':' after normalization: '{norm_doc}'"
            )
        raw_or_norm = f"{doc_type.value}:{norm_doc}"
    else:
        raw_or_norm = (
            normalize_for_field(field_name, value, document_type=document_type)
            if normalize
            else value
        )

    key = derive_blind_index_key(salt, field_name)
    digest = hmac.new(key, raw_or_norm.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest
