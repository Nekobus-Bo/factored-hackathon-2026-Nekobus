"""Unit tests for redis session storage and pinned holder security (ADR-0004).

Uses fakeredis to test RedisSessionStore in-memory without running containers.
"""

from datetime import UTC, datetime

import fakeredis
import pytest
from banking_core.control.authorize import Authorizer
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.session import (
    RedisSessionStore,
    SessionState,
    validate_no_holder_tampering,
)
from contracts.envelope import ToolCall, VerificationState


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


def test_session_state_schema_and_serialization() -> None:
    now = datetime.now(UTC)
    session = SessionState(
        session_id="sess_123",
        state=VerificationState.IDENTIFIED,
        pinned_holder_id="cust_987",
        attempts=2,
        otp_challenge_id="chal_456",
        otp_resends=1,
        updated_at=now,
    )

    data = session.to_redis_dict()
    assert data["session_id"] == "sess_123"
    assert data["state"] == "IDENTIFIED"
    assert data["pinned_holder_id"] == "cust_987"
    assert data["attempts"] == 2
    assert data["otp_challenge_id"] == "chal_456"
    assert data["otp_resends"] == 1

    # Re-deserialization
    json_str = session.model_dump_json()
    loaded = SessionState.model_validate_json(json_str)
    assert loaded.session_id == session.session_id
    assert loaded.state == session.state
    assert loaded.pinned_holder_id == session.pinned_holder_id
    assert loaded.otp_resends == session.otp_resends


def test_redis_session_store_crud(fake_redis: fakeredis.FakeRedis) -> None:
    store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)

    # Initial get returns None
    assert store.get("sess_new") is None

    # get_or_create creates anonymous session
    session = store.get_or_create("sess_new")
    assert session.session_id == "sess_new"
    assert session.state == VerificationState.ANONYMOUS
    assert session.pinned_holder_id is None

    # Update and save
    session.state = VerificationState.IDENTIFIED
    session.pinned_holder_id = "holder_pinned_1"
    store.save(session)

    # Retrieve again
    retrieved = store.get("sess_new")
    assert retrieved is not None
    assert retrieved.state == VerificationState.IDENTIFIED
    assert retrieved.pinned_holder_id == "holder_pinned_1"

    # Delete
    store.delete("sess_new")
    assert store.get("sess_new") is None


def test_redis_session_atomic_update(fake_redis: fakeredis.FakeRedis) -> None:
    store = RedisSessionStore(redis_client=fake_redis, default_ttl=3600)
    store.get_or_create("sess_atomic")

    def increment_attempts(s: SessionState) -> SessionState:
        s.attempts += 1
        return s

    # First update
    s1 = store.atomic_update("sess_atomic", increment_attempts)
    assert s1.attempts == 1

    # Second update
    s2 = store.atomic_update("sess_atomic", increment_attempts)
    assert s2.attempts == 2

    # Check in redis
    loaded = store.get("sess_atomic")
    assert loaded is not None
    assert loaded.attempts == 2


def _ttl(store: RedisSessionStore, session_id: str) -> int:
    return int(store.client.ttl(f"{store.key_prefix}{session_id}"))


def test_save_uses_the_configured_ttl_not_the_seed_default(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    store = RedisSessionStore(
        redis_client=fake_redis, default_ttl=3600, ttl_provider=lambda: 900
    )

    store.save(SessionState(session_id="sess_cfg_ttl"))

    assert 0 < _ttl(store, "sess_cfg_ttl") <= 900


def test_configured_ttl_is_read_on_every_save(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    configured = {"ttl": 900}
    store = RedisSessionStore(
        redis_client=fake_redis, ttl_provider=lambda: configured["ttl"]
    )
    session = SessionState(session_id="sess_cfg_change")
    store.save(session)
    assert _ttl(store, "sess_cfg_change") <= 900

    configured["ttl"] = 120  # an operator lowers it; no restart
    store.save(session)

    assert 0 < _ttl(store, "sess_cfg_change") <= 120


def test_explicit_ttl_wins_over_the_provider(fake_redis: fakeredis.FakeRedis) -> None:
    store = RedisSessionStore(redis_client=fake_redis, ttl_provider=lambda: 900)

    store.save(SessionState(session_id="sess_explicit"), ttl_seconds=60)

    assert 0 < _ttl(store, "sess_explicit") <= 60


def test_atomic_update_also_uses_the_configured_ttl(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    store = RedisSessionStore(redis_client=fake_redis, ttl_provider=lambda: 900)

    store.atomic_update("sess_atomic_ttl", lambda s: s)

    assert 0 < _ttl(store, "sess_atomic_ttl") <= 900


def _unavailable() -> int:
    raise ConnectionError("policy database unavailable")


@pytest.mark.parametrize("provider", [_unavailable, lambda: 0, lambda: -5])
def test_unusable_configuration_falls_back_to_the_seed_default(
    fake_redis: fakeredis.FakeRedis, provider: object
) -> None:
    store = RedisSessionStore(
        redis_client=fake_redis,
        default_ttl=1800,
        ttl_provider=provider,  # type: ignore[arg-type]
    )

    store.save(SessionState(session_id="sess_fallback"))

    assert 900 < _ttl(store, "sess_fallback") <= 1800


def test_pinned_holder_cannot_be_tampered_by_tool_args() -> None:
    """ADR-0004 IDOR check: tool args cannot contain customer or holder IDs."""
    illegal_args_list = [
        {"holder_id": "cust_attacker"},
        {"pinned_holder_id": "cust_attacker"},
        {"customer_id": "cust_attacker"},
    ]

    for args in illegal_args_list:
        with pytest.raises(ValueError, match="Unauthorized argument"):
            validate_no_holder_tampering(args)


def test_contracts_toolcall_forbids_holder_tampering_in_args() -> None:
    """Contracts ToolCall schema forbids extra holder arguments (ADR-0004)."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ToolCall(
            tool="card.list",
            args={"holder_id": "spoofed_holder"},
        )


def test_pinned_holder_unaffected_by_valid_tool_args() -> None:
    """Valid tool calls cannot alter pinned_holder_id."""
    authorizer = Authorizer(config_repo=InMemoryControlConfigRepository())
    session = SessionState(
        session_id="s1",
        state=VerificationState.VERIFIED,
        pinned_holder_id="legitimate_holder",
    )

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_secure_ref", "reason": "LOST"},
        idempotency_key="idem_key_12345",
    )

    decision = authorizer.authorize(tool_call, session)
    assert decision.allowed is True
    # Pinned holder remains unchanged
    assert session.pinned_holder_id == "legitimate_holder"
