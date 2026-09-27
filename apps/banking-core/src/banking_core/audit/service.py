"""Service layer for append-only audit logging and hash chain verification."""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from banking_core.audit.canonical import (
    GENESIS_PREV_HASH,
    canonical_entry_json,
    compute_entry_hash,
)
from banking_core.audit.pii_guard import check_payload
from banking_core.models.ops import AuditLog


def append(
    session: Session,
    actor_type: str,
    actor_ref: str,
    action: str,
    decision: str,
    reason_code: str | None,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> AuditLog:
    """Append a validated, tamper-evident entry to ops.audit_log.

    Guarantees:
    1. Payload is inspected for unmasked PII; raises PiiLeakError if found.
    2. Concurrent appends are serialized via transaction-level advisory locking
       (or row-level locking on the chain tail) to prevent chain forks.
    3. The prev_hash is chained to the latest entry (or GENESIS_PREV_HASH if empty).
    4. The hash is computed deterministically as sha256(prev_hash + canonical_json).
    """
    # 1. Inspect payload for PII leaks
    check_payload(payload)

    if occurred_at is None:
        occurred_at = datetime.now(UTC)
    elif occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    else:
        occurred_at = occurred_at.astimezone(UTC)

    # 2. Serialize concurrent appends using PostgreSQL advisory lock
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        # Advisory transaction lock on hash of table name prevents concurrent forks
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtext('ops.audit_log'))")
        )

    # 3. Retrieve chain tail with row lock
    tail_stmt = (
        sa.select(AuditLog).order_by(AuditLog.id.desc()).limit(1).with_for_update()
    )
    tail = session.scalar(tail_stmt)
    prev_hash = tail.hash if tail is not None else GENESIS_PREV_HASH

    # 4. Compute canonical JSON of the entry without hash
    entry_dict: dict[str, Any] = {
        "action": action,
        "actor_ref": actor_ref,
        "actor_type": actor_type,
        "decision": decision,
        "occurred_at": occurred_at,
        "payload": payload,
        "reason_code": reason_code,
    }
    canonical_json = canonical_entry_json(entry_dict)
    calculated_hash = compute_entry_hash(prev_hash, canonical_json)

    # 5. Insert record
    record = AuditLog(
        occurred_at=occurred_at,
        actor_type=actor_type,
        actor_ref=actor_ref,
        action=action,
        decision=decision,
        reason_code=reason_code,
        payload=payload,
        prev_hash=prev_hash,
        hash=calculated_hash,
    )
    session.add(record)
    session.flush()
    return record


def verify_chain(
    session: Session,
) -> tuple[bool, int, str | None, int | None, str | None]:
    """Walk and verify the cryptographic integrity of the audit log hash chain.

    Returns:
        tuple[bool, int, str | None, int | None, str | None]:
            (is_valid, total_verified_count, head_hash, broken_entry_id, error_message)
    """
    stmt = sa.select(AuditLog).order_by(AuditLog.id.asc())
    rows = list(session.scalars(stmt))

    if not rows:
        return True, 0, None, None, None

    head_hash = rows[-1].hash
    expected_prev_hash = GENESIS_PREV_HASH

    for row in rows:
        # Check prev_hash linkage
        if row.prev_hash != expected_prev_hash:
            return (
                False,
                len(rows),
                head_hash,
                row.id,
                f"Broken link at id={row.id}: prev_hash mismatch "
                f"(stored '{row.prev_hash}', expected '{expected_prev_hash}')",
            )

        # Re-compute hash from canonical entry
        entry_dict: dict[str, Any] = {
            "action": row.action,
            "actor_ref": row.actor_ref,
            "actor_type": row.actor_type,
            "decision": row.decision,
            "occurred_at": row.occurred_at,
            "payload": row.payload,
            "reason_code": row.reason_code,
        }
        canonical_json = canonical_entry_json(entry_dict)
        computed_hash = compute_entry_hash(row.prev_hash, canonical_json)

        if row.hash != computed_hash:
            return (
                False,
                len(rows),
                head_hash,
                row.id,
                f"Tampered row at id={row.id}: hash mismatch "
                f"(stored '{row.hash}', computed '{computed_hash}')",
            )

        expected_prev_hash = row.hash

    return True, len(rows), head_hash, None, None
