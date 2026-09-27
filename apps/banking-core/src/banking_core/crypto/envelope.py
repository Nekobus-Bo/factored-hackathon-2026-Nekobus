"""Application-level envelope encryption using AES-256-GCM.

Provides:
- Per-record Data Encryption Key (DEK) wrapped by a Master Key (KEK) via HKDF-SHA256.
- Authenticated AES-GCM encryption per field bound to location via AAD.
- AAD format: b"<schema>.<table>.<column>:<pk>"
- Tamper detection, row-swap and column-swap rejection.
- Fail-closed key loading (no silent dev key fallback).
"""

import base64
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from banking_core.crypto.exceptions import (
    CryptoError,
    DecryptionError,
    EncryptionError,
    InvalidKeyError,
)

MASTER_KEK_SALT = b"pattern-blue-kek-salt-v1"
MASTER_KEK_INFO = b"pattern-blue-master-kek-v1"
ENVELOPE_VERSION_PREFIX = "v1"


def build_field_aad(schema: str, table: str, column: str, pk: str | uuid.UUID) -> bytes:
    """Build field-level AAD: b"<schema>.<table>.<column>:<pk>"."""
    return f"{schema}.{table}.{column}:{pk}".encode()


def build_record_aad(schema: str, table: str, pk: str | uuid.UUID) -> bytes:
    """Build record-level AAD for DEK wrapping: b"<schema>.<table>:<pk>"."""
    return f"{schema}.{table}:{pk}".encode()


def derive_record_aad_from_field_aad(field_aad: bytes) -> bytes:
    """Derive b"<schema>.<table>:<pk>" from b"<schema>.<table>.<column>:<pk>"."""
    decoded = field_aad.decode("utf-8")
    if ":" in decoded:
        col_path, pk_part = decoded.rsplit(":", 1)
        parts = col_path.split(".")
        if len(parts) >= 3:
            schema_table = ".".join(parts[:-1])
            return f"{schema_table}:{pk_part}".encode()
    return field_aad


def get_master_key(master_key: str | bytes | None = None) -> str | bytes:
    """Resolve master key or fail closed if missing."""
    if master_key is not None:
        return master_key
    env_key = os.getenv("MASTER_KEY")
    if not env_key:
        raise InvalidKeyError(
            "MASTER_KEY environment variable is required and cannot be empty"
        )
    return env_key


def derive_master_kek(master_key: str | bytes) -> bytes:
    """Derive a 256-bit AES-GCM Key Encryption Key (KEK) from MASTER_KEY."""
    raw = master_key.encode("utf-8") if isinstance(master_key, str) else master_key
    if not raw:
        raise InvalidKeyError("Master key cannot be empty")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=MASTER_KEK_SALT,
        info=MASTER_KEK_INFO,
    )
    return hkdf.derive(raw)


def generate_dek() -> bytes:
    """Generate a cryptographically secure 256-bit Data Encryption Key."""
    return os.urandom(32)


def wrap_dek(dek: bytes, master_key: str | bytes, aad: bytes) -> str:
    """Wrap a 32-byte DEK with the master key using AES-256-GCM bound to record AAD."""
    if len(dek) != 32:
        raise EncryptionError(f"DEK must be exactly 32 bytes, got {len(dek)}")
    if not isinstance(aad, bytes) or not aad:
        raise EncryptionError("AAD is required and must be non-empty bytes")
    try:
        kek = derive_master_kek(master_key)
        nonce = os.urandom(12)
        aesgcm = AESGCM(kek)
        ciphertext = aesgcm.encrypt(nonce, dek, associated_data=aad)
        payload = nonce + ciphertext
        return base64.urlsafe_b64encode(payload).decode("ascii")
    except Exception as exc:
        if isinstance(exc, CryptoError):
            raise
        raise EncryptionError(f"Failed to wrap DEK: {exc}") from exc


def unwrap_dek(wrapped_dek: str, master_key: str | bytes, aad: bytes) -> bytes:
    """Unwrap a DEK using the master key and bound record AAD.

    Raises:
        InvalidKeyError: If wrong master key or AAD mismatch.
        DecryptionError: If the payload is malformed.
    """
    if not isinstance(aad, bytes) or not aad:
        raise DecryptionError("AAD is required and must be non-empty bytes")
    try:
        payload = base64.urlsafe_b64decode(wrapped_dek.encode("ascii"))
    except Exception as exc:
        raise DecryptionError(
            f"Invalid base64 encoding for wrapped DEK: {exc}"
        ) from exc

    if len(payload) < 28:
        raise DecryptionError("Wrapped DEK payload is too short")

    nonce = payload[:12]
    ciphertext = payload[12:]
    kek = derive_master_kek(master_key)
    aesgcm = AESGCM(kek)
    try:
        dek = aesgcm.decrypt(nonce, ciphertext, associated_data=aad)
        if len(dek) != 32:
            raise DecryptionError(f"Unwrapped DEK has invalid length: {len(dek)}")
        return dek
    except InvalidTag as exc:
        raise InvalidKeyError(
            "Failed to unwrap DEK: invalid tag, wrong master key, or AAD mismatch"
        ) from exc
    except Exception as exc:
        raise DecryptionError(f"Failed to unwrap DEK: {exc}") from exc


def encrypt_with_dek(plaintext: str, dek: bytes, aad: bytes) -> str:
    """Encrypt plaintext with a raw DEK using AES-256-GCM bound to field AAD."""
    if not isinstance(plaintext, str):
        raise EncryptionError("Plaintext must be a string")
    if not isinstance(aad, bytes) or not aad:
        raise EncryptionError("AAD is required and must be non-empty bytes")
    try:
        nonce = os.urandom(12)
        aesgcm = AESGCM(dek)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=aad)
        payload = nonce + ct
        return base64.urlsafe_b64encode(payload).decode("ascii")
    except Exception as exc:
        if isinstance(exc, CryptoError):
            raise
        raise EncryptionError(f"Failed to encrypt with DEK: {exc}") from exc


def decrypt_with_dek(token: str, dek: bytes, aad: bytes) -> str:
    """Decrypt token with a raw DEK using AES-256-GCM bound to field AAD.

    Raises:
        DecryptionError: If token is malformed, tampered, or fails AAD check.
    """
    if not isinstance(aad, bytes) or not aad:
        raise DecryptionError("AAD is required and must be non-empty bytes")
    try:
        payload = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:
        raise DecryptionError(f"Invalid base64 payload: {exc}") from exc

    if len(payload) < 28:
        raise DecryptionError("Ciphertext payload is too short")

    nonce = payload[:12]
    ct = payload[12:]
    aesgcm = AESGCM(dek)
    try:
        pt_bytes = aesgcm.decrypt(nonce, ct, associated_data=aad)
        return pt_bytes.decode("utf-8")
    except InvalidTag as exc:
        raise DecryptionError(
            "Failed to decrypt: invalid tag, tampered data, or AAD mismatch"
        ) from exc
    except UnicodeDecodeError as exc:
        raise DecryptionError(
            f"Failed to decode decrypted plaintext as UTF-8: {exc}"
        ) from exc
    except Exception as exc:
        raise DecryptionError(f"Failed to decrypt with DEK: {exc}") from exc


def encrypt_field(
    plaintext: str,
    aad: bytes,
    master_key: str | bytes | None = None,
    dek: bytes | None = None,
    wrapped_dek: str | None = None,
    record_aad: bytes | None = None,
) -> str:
    """Encrypt a field value inside an envelope bound to AAD.

    Format: `v1:<wrapped_dek>:<field_ciphertext>`
    """
    resolved_master_key = get_master_key(master_key)
    rec_aad = record_aad or derive_record_aad_from_field_aad(aad)

    if dek is None:
        dek = generate_dek()
        wrapped_dek = wrap_dek(dek, resolved_master_key, aad=rec_aad)
    elif wrapped_dek is None:
        wrapped_dek = wrap_dek(dek, resolved_master_key, aad=rec_aad)

    field_ct = encrypt_with_dek(plaintext, dek, aad=aad)
    return f"{ENVELOPE_VERSION_PREFIX}:{wrapped_dek}:{field_ct}"


def decrypt_field(
    token: str,
    aad: bytes,
    master_key: str | bytes | None = None,
    record_aad: bytes | None = None,
) -> str:
    """Decrypt an envelope token `v1:<wrapped_dek>:<field_ciphertext>`.

    Raises:
        InvalidKeyError: If wrong master key or record AAD mismatch.
        DecryptionError: If tampered ciphertext, field AAD mismatch, or malformed token.
    """
    resolved_master_key = get_master_key(master_key)
    if not isinstance(token, str):
        raise DecryptionError("Token must be a string")

    parts = token.split(":")
    if len(parts) != 3 or parts[0] != ENVELOPE_VERSION_PREFIX:
        raise DecryptionError(
            f"Malformed token (expected '{ENVELOPE_VERSION_PREFIX}:<wrapped>:<ct>')"
        )

    _, wrapped_dek, field_ct = parts
    rec_aad = record_aad or derive_record_aad_from_field_aad(aad)
    dek = unwrap_dek(wrapped_dek, resolved_master_key, aad=rec_aad)
    return decrypt_with_dek(field_ct, dek, aad=aad)


class RecordEncryptor:
    """Helper to encrypt multiple fields for a single record reusing a DEK."""

    def __init__(
        self,
        schema: str,
        table: str,
        record_id: str | uuid.UUID,
        master_key: str | bytes | None = None,
        dek: bytes | None = None,
    ) -> None:
        self.schema = schema
        self.table = table
        self.record_id = str(record_id)
        self.master_key = get_master_key(master_key)
        self.dek = dek or generate_dek()
        self.record_aad = build_record_aad(self.schema, self.table, self.record_id)
        self.wrapped_dek = wrap_dek(self.dek, self.master_key, aad=self.record_aad)

    def encrypt_field(self, column: str, plaintext: str) -> str:
        """Encrypt a field using the record DEK and location-bound AAD."""
        field_aad = build_field_aad(self.schema, self.table, column, self.record_id)
        field_ct = encrypt_with_dek(plaintext, self.dek, aad=field_aad)
        return f"{ENVELOPE_VERSION_PREFIX}:{self.wrapped_dek}:{field_ct}"

    def encrypt(self, column: str, plaintext: str) -> str:
        """Alias for encrypt_field."""
        return self.encrypt_field(column, plaintext)

    def decrypt_field(self, column: str, token: str) -> str:
        """Decrypt a field for this record using its location-bound AAD."""
        field_aad = build_field_aad(self.schema, self.table, column, self.record_id)
        return decrypt_field(
            token=token,
            aad=field_aad,
            master_key=self.master_key,
            record_aad=self.record_aad,
        )

    def decrypt(self, column: str, token: str) -> str:
        """Alias for decrypt_field."""
        return self.decrypt_field(column, token)
