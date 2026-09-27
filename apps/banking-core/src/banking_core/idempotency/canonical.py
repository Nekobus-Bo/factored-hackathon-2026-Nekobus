"""Canonical JSON request hashing and idempotency key validation."""

import hashlib
import json
import re
from typing import Any

from banking_core.idempotency.exceptions import InvalidIdempotencyKeyError

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9._:-]{8,128}$"
_KEY_RE = re.compile(IDEMPOTENCY_KEY_PATTERN)


def validate_idempotency_key(key: str) -> None:
    """Validate that the idempotency key satisfies format constraints.

    Must be 8 to 128 characters containing only alphanumeric, '.', '_', ':', and '-'.
    Matches ToolCall.idempotency_key contract requirement.
    """
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise InvalidIdempotencyKeyError(key=str(key))


def compute_scoped_key(scope: str, tool: str, key: str) -> str:
    """Format scoped idempotency key as scope:tool:key."""
    return f"{scope}:{tool}:{key}"


def compute_request_hash(
    tool_or_args: str | dict[str, Any], args: dict[str, Any] | None = None
) -> str:
    """Compute deterministic SHA-256 hash of tool and arguments.

    Keys are sorted and whitespace is stripped to guarantee identical hashes
    for semantically equivalent argument dictionaries.
    """
    if args is None:
        if isinstance(tool_or_args, dict):
            payload: dict[str, Any] = {"args": tool_or_args, "tool": ""}
        else:
            payload = {"args": {}, "tool": str(tool_or_args)}
    else:
        payload = {"args": args, "tool": str(tool_or_args)}

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
