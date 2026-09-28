"""Placeholder map encryption at rest (ADR-0001, ADR-0004, AGENTS rule 5).

Design choice: the placeholder map ([CARD_1], [DOC_1], ... -> raw PII) is
needed server-side to rehydrate banking-core tool arguments and to keep
placeholders stable across turns. Two guarantees:

1. Server-side only: no chat response (create, message, transcript) ever
   includes it; the client sees masked text and blocks only.
2. Encrypted at rest: redis-edge may persist RDB/AOF snapshots or be dumped
   operationally, so the map is encrypted before it is written, with Fernet
   (AES-128-CBC + HMAC-SHA256) keyed by SESSION_SECRET. The rest of the state
   (masked history) is stored in clear.
"""

import base64
import hashlib
import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CryptoError(Exception):
    """Raised when placeholder map encryption or decryption fails."""


def derive_fernet_key(secret: str) -> bytes:
    """Derive a URL-safe base64-encoded 32-byte Fernet key from a string secret."""
    if not secret:
        raise ValueError("Session secret must not be empty")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class PlaceholderEncryptor:
    """Handles Fernet encryption/decryption of placeholder maps stored in Redis."""

    def __init__(self, secret: str) -> None:
        key = derive_fernet_key(secret)
        self._fernet = Fernet(key)

    def encrypt_map(self, placeholder_map: dict[str, Any]) -> str:
        """Serialize and encrypt a placeholder mapping dict into a ciphertext string."""
        if not placeholder_map:
            return ""
        try:
            payload = json.dumps(placeholder_map, sort_keys=True).encode("utf-8")
            token = self._fernet.encrypt(payload)
            return token.decode("ascii")
        except Exception as exc:
            logger.error("Failed to encrypt placeholder map: %s", exc)
            raise CryptoError(f"Encryption failed: {exc}") from exc

    def decrypt_map(self, encrypted_token: str | None) -> dict[str, str]:
        """Decrypt a ciphertext string back into a placeholder mapping dict."""
        if not encrypted_token or not encrypted_token.strip():
            return {}
        try:
            decrypted = self._fernet.decrypt(encrypted_token.strip().encode("ascii"))
            data = json.loads(decrypted.decode("utf-8"))
            if not isinstance(data, dict):
                raise CryptoError("Decrypted placeholder map is not a dictionary")
            return {str(k): str(v) for k, v in data.items()}
        except InvalidToken as exc:
            logger.error("Invalid token when decrypting placeholder map: %s", exc)
            raise CryptoError("Invalid encryption token for placeholder map") from exc
        except Exception as exc:
            logger.error("Failed to decrypt placeholder map: %s", exc)
            raise CryptoError(f"Decryption failed: {exc}") from exc
