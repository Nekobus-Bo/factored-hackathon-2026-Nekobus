"""Crypto module for application-level field encryption and blind indexing."""

from banking_core.crypto.blind_index import (
    compute_blind_index,
    derive_blind_index_key,
)
from banking_core.crypto.envelope import (
    RecordEncryptor,
    build_field_aad,
    build_record_aad,
    decrypt_field,
    decrypt_with_dek,
    derive_master_kek,
    derive_record_aad_from_field_aad,
    encrypt_field,
    encrypt_with_dek,
    generate_dek,
    get_master_key,
    unwrap_dek,
    wrap_dek,
)
from banking_core.crypto.exceptions import (
    CryptoError,
    DecryptionError,
    EncryptionError,
    InvalidKeyError,
    NormalizationError,
)
from banking_core.crypto.normalize import (
    normalize_document,
    normalize_email,
    normalize_for_field,
    normalize_phone,
)

__all__ = [
    "CryptoError",
    "DecryptionError",
    "EncryptionError",
    "InvalidKeyError",
    "NormalizationError",
    "RecordEncryptor",
    "build_field_aad",
    "build_record_aad",
    "compute_blind_index",
    "decrypt_field",
    "decrypt_with_dek",
    "derive_blind_index_key",
    "derive_master_kek",
    "derive_record_aad_from_field_aad",
    "encrypt_field",
    "encrypt_with_dek",
    "generate_dek",
    "get_master_key",
    "normalize_document",
    "normalize_email",
    "normalize_for_field",
    "normalize_phone",
    "unwrap_dek",
    "wrap_dek",
]
