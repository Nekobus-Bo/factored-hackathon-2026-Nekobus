"""Canonical JSON serialization and hash chain computation for audit log."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

GENESIS_PREV_HASH: str = "0" * 64


def format_iso_datetime(dt: datetime) -> str:
    """Format datetime as canonical ISO 8601 string in UTC.

    Preserves exact microsecond precision if non-zero, standardized to UTC '+00:00'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    # Python 3.12+ isoformat on UTC uses '+00:00'
    return dt.isoformat()


def canonical_entry_json(entry: dict[str, Any]) -> str:
    """Produce deterministic canonical JSON representation of an audit log entry.

    Rule: The entry without hash and chaining metadata (prev_hash, hash, id).
    Keys are sorted alphabetically, whitespace is eliminated, and datetime
    fields are formatted deterministically in UTC ISO 8601.
    """
    # Exclude chaining and auto-generated primary key fields
    filtered: dict[str, Any] = {
        k: v for k, v in entry.items() if k not in ("hash", "prev_hash", "id")
    }

    # Normalize occurred_at if passed as datetime
    if "occurred_at" in filtered:
        val = filtered["occurred_at"]
        if isinstance(val, datetime):
            filtered["occurred_at"] = format_iso_datetime(val)
        elif isinstance(val, str):
            filtered["occurred_at"] = val

    return json.dumps(
        filtered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_entry_hash(prev_hash: str, canonical_json: str) -> str:
    """Compute sha256(prev_hash + canonical JSON of the entry without hash)."""
    data = f"{prev_hash}{canonical_json}".encode()
    return hashlib.sha256(data).hexdigest()
