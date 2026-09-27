"""Session management and state persistence on redis-core for banking-core.

Session schema: session_id -> {state, pinned_holder_id, attempts,
otp_challenge_id, updated_at}.
Security rules:
- pinned_holder_id is strictly established server-side on verified match.
- Pinned holder can NEVER be supplied or altered by model tool args (ADR-0004).
- Concurrency: Atomic updates using Redis WATCH / MULTI / EXEC.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import redis
from contracts.envelope import VerificationState
from pydantic import BaseModel, ConfigDict, Field


class SessionState(BaseModel):
    """Customer verification and security session state.

    Stored in redis-core. pinned_holder_id is strictly server-controlled.
    """

    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(..., min_length=1, description="Unique session identifier")
    state: VerificationState = Field(
        default=VerificationState.ANONYMOUS,
        description="Current FSM verification state",
    )
    pinned_holder_id: str | None = Field(
        default=None,
        description="Pinned customer/holder ID; never from model",
    )
    attempts: int = Field(default=0, ge=0, description="Total attempts in this session")
    otp_challenge_id: str | None = Field(
        default=None,
        description="Active OTP challenge identifier if pending",
    )
    failed_matches: int = Field(
        default=0, ge=0, description="Failed customer match attempts"
    )
    failed_verifies: int = Field(
        default=0, ge=0, description="Failed OTP verify attempts"
    )
    otp_resends: int = Field(
        default=0, ge=0, description="Count of OTP resends in session"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last state modification",
    )

    def to_redis_dict(self) -> dict[str, Any]:
        """Convert session to the canonical dictionary representation."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "pinned_holder_id": self.pinned_holder_id,
            "attempts": self.attempts,
            "otp_challenge_id": self.otp_challenge_id,
            "failed_matches": self.failed_matches,
            "failed_verifies": self.failed_verifies,
            "otp_resends": self.otp_resends,
            "updated_at": self.updated_at.isoformat(),
        }


def validate_no_holder_tampering(tool_args: dict[str, Any]) -> None:
    """Enforce ADR-0004 IDOR mitigation: tool arguments cannot override account holder.

    The account holder is pinned in banking-core session state, never passed
    as a parameter from the untrusted model or conversational orchestrator.
    """
    forbidden_keys = {"holder_id", "pinned_holder_id", "customer_id"}
    for key in forbidden_keys:
        if key in tool_args:
            raise ValueError(
                f"Unauthorized argument '{key}' in tool arguments. "
                "Account holder identity is strictly pinned in session (ADR-0004)."
            )


class RedisSessionStore:
    """Redis-backed session store using redis-core.

    Supports atomic updates via Redis optimistic locking (WATCH/MULTI/EXEC).
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        default_ttl: int = 3600,
        key_prefix: str = "session:",
    ) -> None:
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        if redis_client is not None:
            self._client = redis_client
        else:
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6379"))
            password = os.getenv("REDIS_PASSWORD") or None
            self._client = redis.Redis(
                host=host,
                port=port,
                password=password,
                decode_responses=True,
            )

    @property
    def client(self) -> redis.Redis:
        """Underlying redis client."""
        return self._client

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    def get(self, session_id: str) -> SessionState | None:
        """Retrieve session state by ID, or None if expired/not found."""
        key = self._key(session_id)
        raw = self._client.get(key)
        if raw is None:
            return None
        return SessionState.model_validate_json(raw)

    def get_or_create(self, session_id: str) -> SessionState:
        """Retrieve existing session state or create a fresh anonymous session."""
        session = self.get(session_id)
        if session is None:
            session = SessionState(session_id=session_id)
            self.save(session)
        return session

    def save(self, session: SessionState, ttl_seconds: int | None = None) -> None:
        """Save session state with configured TTL."""
        key = self._key(session.session_id)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        session.updated_at = datetime.now(UTC)
        self._client.set(key, session.model_dump_json(), ex=ttl)

    def atomic_update(
        self,
        session_id: str,
        update_fn: Callable[[SessionState], SessionState],
        ttl_seconds: int | None = None,
        max_retries: int = 10,
    ) -> SessionState:
        """Atomically update session state via Redis WATCH/MULTI concurrency.

        If a concurrent writer modifies the key between read and write, WatchError
        is raised and the transaction retries up to max_retries.
        """
        key = self._key(session_id)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        for _ in range(max_retries):
            pipe = self._client.pipeline()
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if raw is None:
                    session = SessionState(session_id=session_id)
                else:
                    session = SessionState.model_validate_json(raw)

                updated = update_fn(session)
                updated.updated_at = datetime.now(UTC)

                pipe.multi()
                pipe.set(key, updated.model_dump_json(), ex=ttl)
                pipe.execute()
                return updated
            except redis.WatchError:
                continue
            finally:
                pipe.reset()

        raise RuntimeError(
            f"Failed to update session '{session_id}' after {max_retries} retries"
        )

    def delete(self, session_id: str) -> None:
        """Delete session from Redis."""
        self._client.delete(self._key(session_id))
