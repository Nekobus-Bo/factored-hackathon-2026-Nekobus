"""Idempotency store service for deduplicating state-changing tool executions."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from banking_core.idempotency.canonical import (
    compute_request_hash,
    compute_scoped_key,
    validate_idempotency_key,
)
from banking_core.idempotency.exceptions import IdempotencyConflictError
from banking_core.models.ops import IdempotencyKey


def get_or_run(
    session: Session,
    key: str,
    tool: str,
    args: dict[str, Any],
    runner: Callable[[], dict[str, Any]],
    scope: str | None = None,
    session_id: str | None = None,
    ttl_seconds: int = 86400,
) -> tuple[dict[str, Any], bool]:
    """Execute action with idempotency protection or replay previous response.

    Args:
        session: Active SQLAlchemy session.
        key: Idempotency key from client ToolCall.
        tool: Exact tool name (e.g. 'card.block').
        args: Input arguments dictionary.
        runner: Callable producing the response payload if execution is needed.
        scope: Optional scope identifier (defaults to session_id or 'global').
        session_id: Optional session identifier for scoping.
        ttl_seconds: Time-to-live for cached response (default 24h).

    Returns:
        tuple[dict[str, Any], bool]: (response_data, was_replayed)

    Raises:
        InvalidIdempotencyKeyError: If key format violates constraints.
        IdempotencyConflictError: If key is reused with differing arguments.
    """
    validate_idempotency_key(key)
    scope_resolved = scope or session_id or "global"
    scoped_key = compute_scoped_key(scope_resolved, tool, key)
    request_hash = compute_request_hash(tool, args)
    now = datetime.now(UTC)

    # 1. Serialize concurrent callers per scoped key with PostgreSQL advisory lock
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:scoped_key, 0))"),
            {"scoped_key": scoped_key},
        )

    # 2. Check for existing key with row lock under the advisory lock
    stmt = (
        sa.select(IdempotencyKey)
        .where(IdempotencyKey.scoped_key == scoped_key)
        .with_for_update()
    )
    existing = session.scalar(stmt)

    if existing is not None:
        # Check expiration
        if existing.expires_at is not None and existing.expires_at <= now:
            # Expired key is purged and allowed to be re-executed under this lock
            session.delete(existing)
            session.flush()
        else:
            # Active key found: verify request hash
            if existing.request_hash == request_hash:
                # Idempotent replay: return cached response without running again
                return existing.response, True
            else:
                # Conflict: same scoped key used with different arguments
                raise IdempotencyConflictError(
                    key=key,
                    tool=tool,
                    stored_request_hash=existing.request_hash,
                    current_request_hash=request_hash,
                )

    # 3. Key does not exist or was expired: execute runner
    response = runner()

    # 4. Store response in the same transaction
    expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None
    record = IdempotencyKey(
        scoped_key=scoped_key,
        scope=scope_resolved,
        tool=tool,
        key=key,
        request_hash=request_hash,
        response=response,
        created_at=now,
        expires_at=expires_at,
    )
    session.add(record)
    session.flush()

    return response, False


def purge_expired_keys(session: Session, now: datetime | None = None) -> int:
    """Delete expired idempotency entries.

    Returns:
        int: Number of deleted rows.
    """
    if now is None:
        now = datetime.now(UTC)

    stmt = sa.delete(IdempotencyKey).where(
        IdempotencyKey.expires_at.is_not(None),
        IdempotencyKey.expires_at <= now,
    )
    result = session.execute(stmt)
    session.flush()
    return int(result.rowcount or 0)
