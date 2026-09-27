"""Unit tests for audit log canonical serialization and hash chain computation."""

import hashlib
import json
from datetime import UTC, datetime

from banking_core.audit.canonical import (
    GENESIS_PREV_HASH,
    canonical_entry_json,
    compute_entry_hash,
    format_iso_datetime,
)


def test_genesis_prev_hash() -> None:
    """Verify genesis prev_hash is exactly 64 zeros."""
    assert GENESIS_PREV_HASH == "0" * 64
    assert len(GENESIS_PREV_HASH) == 64


def test_canonical_entry_json_key_sorting_and_whitespace() -> None:
    """Verify keys are sorted alphabetically and whitespace is eliminated."""
    entry = {
        "decision": "allowed",
        "actor_type": "customer_session",
        "action": "card.block",
        "payload": {"card_ref": "card_abc123", "target_masked": "**** 1234"},
        "reason_code": None,
        "actor_ref": "sess_123",
        "occurred_at": "2026-09-26T23:00:00+00:00",
    }
    canonical = canonical_entry_json(entry)
    expected = (
        '{"action":"card.block","actor_ref":"sess_123","actor_type":"customer_session",'
        '"decision":"allowed","occurred_at":"2026-09-26T23:00:00+00:00",'
        '"payload":{"card_ref":"card_abc123","target_masked":"**** 1234"},'
        '"reason_code":null}'
    )
    assert canonical == expected


def test_canonical_entry_json_excludes_chaining_and_id_fields() -> None:
    """Verify hash, prev_hash, and id are stripped from canonical representation."""
    entry = {
        "id": 42,
        "prev_hash": "a" * 64,
        "hash": "b" * 64,
        "action": "otp.send",
        "actor_type": "customer_session",
        "actor_ref": "sess_123",
        "decision": "allowed",
        "reason_code": None,
        "payload": {},
        "occurred_at": "2026-09-26T23:00:00+00:00",
    }
    canonical = canonical_entry_json(entry)
    data = json.loads(canonical)
    assert "id" not in data
    assert "prev_hash" not in data
    assert "hash" not in data
    assert data["action"] == "otp.send"


def test_canonical_entry_json_formats_datetime_object() -> None:
    """Verify datetime instances are formatted as UTC ISO strings."""
    dt = datetime(2026, 9, 26, 23, 15, 30, tzinfo=UTC)
    entry = {
        "action": "test.action",
        "actor_ref": "ref_1",
        "actor_type": "system",
        "decision": "allowed",
        "reason_code": None,
        "payload": {},
        "occurred_at": dt,
    }
    canonical = canonical_entry_json(entry)
    data = json.loads(canonical)
    assert data["occurred_at"] == "2026-09-26T23:15:30+00:00"


def test_compute_entry_hash() -> None:
    """Verify hash = sha256(prev_hash + canonical_json)."""
    prev_hash = "0" * 64
    canonical = '{"action":"test"}'
    expected = hashlib.sha256(f"{prev_hash}{canonical}".encode()).hexdigest()
    actual = compute_entry_hash(prev_hash, canonical)
    assert actual == expected
    assert len(actual) == 64


def test_format_iso_datetime_utc() -> None:
    """Verify UTC datetime formatting."""
    dt = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)
    assert format_iso_datetime(dt) == "2026-09-26T12:00:00+00:00"
