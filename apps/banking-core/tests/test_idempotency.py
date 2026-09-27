"""Unit tests for idempotency key validation and request hashing."""

import pytest
from banking_core.idempotency.canonical import (
    compute_request_hash,
    validate_idempotency_key,
)
from banking_core.idempotency.exceptions import (
    IdempotencyConflictError,
    InvalidIdempotencyKeyError,
)


def test_idempotency_key_validation() -> None:
    """Verify valid and invalid idempotency key patterns."""
    valid_keys = [
        "idem_12345678",
        "key:with:colons:123",
        "req.456-789_abc",
        "a" * 8,
        "a" * 128,
    ]
    for key in valid_keys:
        validate_idempotency_key(key)

    invalid_keys = [
        "short",  # < 8 chars
        "a" * 129,  # > 128 chars
        "key with spaces",
        "key/with/slashes",
        "key@with@symbols",
        "",
    ]
    for key in invalid_keys:
        with pytest.raises(InvalidIdempotencyKeyError):
            validate_idempotency_key(key)


def test_compute_request_hash_deterministic() -> None:
    """Verify compute_request_hash sorts dictionary keys and ignores ordering."""
    args1 = {"b": 2, "a": 1, "c": [1, 2, 3]}
    args2 = {"a": 1, "c": [1, 2, 3], "b": 2}
    assert compute_request_hash(args1) == compute_request_hash(args2)
    assert compute_request_hash("card.block", args1) == compute_request_hash(
        "card.block", args2
    )

    args3 = {"a": 1, "b": 3}
    assert compute_request_hash(args1) != compute_request_hash(args3)


def test_compute_request_hash_includes_tool() -> None:
    """Verify compute_request_hash produces different hashes for different tools."""
    args = {"card_ref": "card_abc123"}
    hash1 = compute_request_hash("card.block", args)
    hash2 = compute_request_hash("card.unblock", args)
    assert hash1 != hash2


def test_compute_scoped_key() -> None:
    """Verify compute_scoped_key formats key as scope:tool:key."""
    from banking_core.idempotency.canonical import compute_scoped_key

    scoped = compute_scoped_key("sess_123", "card.block", "idem_45678901")
    assert scoped == "sess_123:card.block:idem_45678901"


def test_idempotency_conflict_error_properties() -> None:
    """Verify IdempotencyConflictError carries required reason code and hashes."""
    err = IdempotencyConflictError(
        key="idem_12345678",
        tool="card.block",
        stored_request_hash="hash1",
        current_request_hash="hash2",
    )
    assert err.key == "idem_12345678"
    assert err.tool == "card.block"
    assert err.reason_code == "INVALID_ARGUMENTS"
    assert err.stored_request_hash == "hash1"
    assert err.current_request_hash == "hash2"
    assert "Idempotency conflict" in str(err)
