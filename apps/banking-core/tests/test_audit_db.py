"""Integration tests for audit log hash chain and idempotency against Postgres."""

import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from banking_core.audit.pii_guard import PiiLeakError
from banking_core.audit.service import append, verify_chain
from banking_core.idempotency.exceptions import IdempotencyConflictError
from banking_core.idempotency.service import get_or_run, purge_expired_keys
from banking_core.models.ops import AuditLog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker


def test_chain_verifies(db_session: Session) -> None:
    """Verify that multiple appends construct a valid, verified hash chain."""
    entry1 = append(
        db_session,
        actor_type="customer_session",
        actor_ref="sess_001",
        action="customer.match",
        decision="allowed",
        reason_code=None,
        payload={"matched": True},
    )
    db_session.commit()

    entry2 = append(
        db_session,
        actor_type="customer_session",
        actor_ref="sess_001",
        action="otp.send",
        decision="allowed",
        reason_code=None,
        payload={"channel": "SMS", "destination_masked": "+57 300 *** 1234"},
    )
    db_session.commit()

    entry3 = append(
        db_session,
        actor_type="customer_session",
        actor_ref="sess_001",
        action="card.block",
        decision="allowed",
        reason_code=None,
        payload={"card_ref": "card_test1", "target_masked": "**** 1234"},
    )
    db_session.commit()

    # Verify link hashes
    assert entry1.prev_hash == "0" * 64
    assert entry2.prev_hash == entry1.hash
    assert entry3.prev_hash == entry2.hash

    is_valid, count, head_hash, broken_id, error_msg = verify_chain(db_session)
    assert is_valid is True
    assert count == 3
    assert head_hash == entry3.hash
    assert broken_id is None
    assert error_msg is None


def test_row_tampered_via_superuser_detected_by_verify_audit(
    db_session: Session,
) -> None:
    """Verify that a row modified via superuser (disabling trigger) is detected."""
    append(
        db_session,
        actor_type="customer_session",
        actor_ref="sess_001",
        action="card.list",
        decision="allowed",
        reason_code=None,
        payload={"cards": ["card_1"]},
    )
    entry2 = append(
        db_session,
        actor_type="customer_session",
        actor_ref="sess_001",
        action="card.block",
        decision="allowed",
        reason_code=None,
        payload={"card_ref": "card_1", "target_masked": "**** 1234"},
    )
    append(
        db_session,
        actor_type="system",
        actor_ref="system",
        action="handoff.create",
        decision="allowed",
        reason_code=None,
        payload={"reason": "DISPUTE"},
    )
    db_session.commit()

    # Chain initially verifies
    is_valid, count, head_hash, _, _ = verify_chain(db_session)
    assert is_valid is True
    assert count == 3
    assert head_hash is not None

    # Superuser tampering: disable trigger and alter payload
    db_session.execute(
        sa.text(
            "ALTER TABLE ops.audit_log DISABLE TRIGGER audit_log_prevent_modification"
        )
    )
    db_session.execute(
        sa.text(
            'UPDATE ops.audit_log SET payload = \'{"card_ref": "tampered"}\'::jsonb '
            "WHERE id = :id"
        ),
        {"id": entry2.id},
    )
    db_session.execute(
        sa.text(
            "ALTER TABLE ops.audit_log ENABLE TRIGGER audit_log_prevent_modification"
        )
    )
    db_session.commit()

    # Verification must detect the tampering
    is_valid, count, head_hash, broken_id, error_msg = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == entry2.id
    assert "Tampered row" in (error_msg or "")


def test_update_and_delete_blocked_by_trigger(db_session: Session) -> None:
    """Verify that UPDATE and DELETE on ops.audit_log raise database errors."""
    entry = append(
        db_session,
        actor_type="system",
        actor_ref="system",
        action="test.immutable",
        decision="allowed",
        reason_code=None,
        payload={"data": 123},
    )
    db_session.commit()

    # Attempt UPDATE
    with pytest.raises(DBAPIError) as exc_update:
        db_session.execute(
            sa.text("UPDATE ops.audit_log SET decision = 'error' WHERE id = :id"),
            {"id": entry.id},
        )
        db_session.commit()
    db_session.rollback()
    assert "ops.audit_log is append-only" in str(exc_update.value)

    # Attempt DELETE
    with pytest.raises(DBAPIError) as exc_delete:
        db_session.execute(
            sa.text("DELETE FROM ops.audit_log WHERE id = :id"),
            {"id": entry.id},
        )
        db_session.commit()
    db_session.rollback()
    assert "ops.audit_log is append-only" in str(exc_delete.value)


def test_truncate_blocked_by_trigger(db_session: Session) -> None:
    """Verify that TRUNCATE on ops.audit_log raises a database error."""
    append(
        db_session,
        actor_type="system",
        actor_ref="system",
        action="test.truncate_guard",
        decision="allowed",
        reason_code=None,
        payload={"data": 456},
    )
    db_session.commit()

    # Attempt TRUNCATE
    with pytest.raises(DBAPIError) as exc_truncate:
        db_session.execute(sa.text("TRUNCATE ops.audit_log"))
        db_session.commit()
    db_session.rollback()
    assert "ops.audit_log is append-only" in str(exc_truncate.value)
    assert "TRUNCATE" in str(exc_truncate.value)


def test_idempotent_replay_returns_same_response_and_does_not_run_twice(
    db_session: Session,
) -> None:
    """Verify idempotent replay caches response and does not re-execute."""
    execution_counter = 0

    def mock_runner() -> dict[str, str | int]:
        nonlocal execution_counter
        execution_counter += 1
        return {"receipt": "rcpt_test", "call_count": execution_counter}

    key = "idem_block_card_1234"
    tool = "card.block"
    args = {"card_ref": "card_test_1", "reason": "LOST"}

    # First call: executes runner
    res1, replayed1 = get_or_run(db_session, key, tool, args, mock_runner)
    db_session.commit()
    assert replayed1 is False
    assert execution_counter == 1
    assert res1["call_count"] == 1

    # Second call with same key and args: returns cached response
    res2, replayed2 = get_or_run(db_session, key, tool, args, mock_runner)
    assert replayed2 is True
    assert execution_counter == 1  # Runner was NOT called a second time
    assert res2 == res1


def test_key_reuse_with_different_args_raises_conflict(
    db_session: Session,
) -> None:
    """Verify key reuse with different args raises IdempotencyConflictError."""

    def runner() -> dict[str, str]:
        return {"status": "ok"}

    key = "idem_conflict_key_999"
    tool = "card.block"
    args1 = {"card_ref": "card_1", "reason": "LOST"}
    args2 = {"card_ref": "card_2", "reason": "STOLEN"}

    # Initial call succeeds
    get_or_run(db_session, key, tool, args1, runner)
    db_session.commit()

    # Re-call with different arguments raises conflict error
    with pytest.raises(IdempotencyConflictError) as exc_info:
        get_or_run(db_session, key, tool, args2, runner)

    err = exc_info.value
    assert err.key == key
    assert err.tool == tool
    assert err.reason_code == "INVALID_ARGUMENTS"


def test_pii_guard_rejects_email_in_payload_during_append(
    db_session: Session,
) -> None:
    """Verify that appending a payload with unmasked PII raises and writes nothing."""
    with pytest.raises(PiiLeakError, match="Unmasked email detected"):
        append(
            db_session,
            actor_type="customer_session",
            actor_ref="sess_001",
            action="customer.match",
            decision="allowed",
            reason_code=None,
            payload={"email": "victim@bank.com"},
        )

    # Confirm nothing was committed or inserted
    count = db_session.query(AuditLog).count()
    assert count == 0


def test_purge_expired_keys(db_session: Session) -> None:
    """Verify expired idempotency keys can be purged."""

    def runner() -> dict[str, str]:
        return {"ok": "true"}

    now = datetime.now(UTC)
    # Create key with 10 second TTL
    get_or_run(
        db_session,
        "idem_expire_123",
        "test.tool",
        {"a": 1},
        runner,
        ttl_seconds=10,
    )
    db_session.commit()

    # Before expiry: purge removes 0
    assert purge_expired_keys(db_session, now=now) == 0

    # After expiry: purge removes 1
    assert purge_expired_keys(db_session, now=datetime(2099, 1, 1, tzinfo=UTC)) >= 1
    db_session.commit()


def test_scoped_key_different_session_does_not_return_first_response(
    db_session: Session,
) -> None:
    """Verify that same key and args from a different session does not replay."""
    call_counts = {"sess_A": 0, "sess_B": 0}

    def runner_a() -> dict[str, Any]:
        call_counts["sess_A"] += 1
        return {"caller": "A", "count": call_counts["sess_A"]}

    def runner_b() -> dict[str, Any]:
        call_counts["sess_B"] += 1
        return {"caller": "B", "count": call_counts["sess_B"]}

    key = "idem_shared_key_101"
    tool = "card.block"
    args = {"card_ref": "card_test_abc"}

    # Call from session A
    res_a, replayed_a = get_or_run(
        db_session, key, tool, args, runner_a, session_id="sess_A"
    )
    db_session.commit()
    assert replayed_a is False
    assert res_a["caller"] == "A"
    assert call_counts["sess_A"] == 1

    # Call from session B with the same key and same args
    res_b, replayed_b = get_or_run(
        db_session, key, tool, args, runner_b, session_id="sess_B"
    )
    db_session.commit()
    # Must NOT replay session A's response
    assert replayed_b is False
    assert res_b["caller"] == "B"
    assert call_counts["sess_B"] == 1
    assert res_b != res_a


def test_concurrent_callers_execute_action_exactly_once(
    db_engine: sa.Engine,
) -> None:
    """Verify concurrent callers with same key execute action exactly once.

    Advisory locking ensures only one caller executes runner; all callers
    receive the exact same response.
    """
    key = "idem_concurrent_test_key"
    tool = "card.block"
    args = {"card_ref": "card_concurrent"}

    execution_count = 0
    lock = threading.Lock()

    def slow_runner() -> dict[str, Any]:
        nonlocal execution_count
        with lock:
            execution_count += 1
        time.sleep(0.1)
        return {"status": "blocked", "receipt": "rcpt_conc_123"}

    num_threads = 5
    results: list[tuple[dict[str, Any], bool]] = []
    errors: list[Exception] = []

    def worker() -> None:
        SessionMaker = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
        with SessionMaker() as session:
            try:
                res, replayed = get_or_run(
                    session, key, tool, args, slow_runner, session_id="sess_shared"
                )
                session.commit()
                with lock:
                    results.append((res, replayed))
            except Exception as e:
                session.rollback()
                with lock:
                    errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent workers encountered errors: {errors}"
    assert len(results) == num_threads
    # Action was executed exactly once!
    assert execution_count == 1

    # All threads received the identical response
    first_res = results[0][0]
    assert first_res == {"status": "blocked", "receipt": "rcpt_conc_123"}
    for res, _ in results:
        assert res == first_res

    # Exactly one thread executed (replayed=False); all others replayed (replayed=True)
    replayed_flags = [r[1] for r in results]
    assert replayed_flags.count(False) == 1
    assert replayed_flags.count(True) == num_threads - 1
