"""Cryptographic and normalization exceptions."""


class CryptoError(Exception):
    """Base exception for all cryptographic operations."""


class EncryptionError(CryptoError):
    """Raised when encryption fails."""


class DecryptionError(CryptoError):
    """Raised when decryption fails (e.g. invalid tag, wrong key, tampered payload)."""


class InvalidKeyError(DecryptionError):
    """Raised when an invalid or wrong master key is used."""


class NormalizationError(CryptoError, ValueError):
    """Raised when normalizing an input value fails."""
