"""Conversation session store on redis-edge (the orchestrator's own Redis).

The orchestrator has no access to redis-core or the database (ADR-0004).
State is stored as JSON with a TTL refreshed on every save; the placeholder
map is encrypted before it reaches Redis (see session/crypto.py).
"""

import json
import logging
import secrets
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import WatchError

from orchestrator.log_redaction import redact
from orchestrator.session.crypto import CryptoError, PlaceholderEncryptor
from orchestrator.session.models import ConversationState

logger = logging.getLogger(__name__)

_ENCRYPTED_MAP_FIELD = "placeholder_map_enc"


class SessionStore:
    """Load, save and lock conversations in redis-edge."""

    def __init__(
        self,
        redis: Redis,
        encryptor: PlaceholderEncryptor,
        ttl_seconds: int,
        lock_timeout_seconds: float,
        key_prefix: str = "orch:conv:",
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self.redis = redis
        self.encryptor = encryptor
        self.ttl_seconds = ttl_seconds
        self.lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))
        self.key_prefix = key_prefix

    def _key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}{conversation_id}"

    def _lock_key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}{conversation_id}:lock"

    def _serialize(self, state: ConversationState) -> str:
        payload: dict[str, Any] = state.model_dump(
            mode="json", exclude={"placeholder_map"}
        )
        payload[_ENCRYPTED_MAP_FIELD] = self.encryptor.encrypt_map(
            state.placeholder_map
        )
        return json.dumps(payload)

    async def save(self, state: ConversationState) -> None:
        """Persist state and refresh its TTL (no turn in flight: creation)."""
        await self.redis.set(
            self._key(state.conversation_id),
            self._serialize(state),
            ex=self.ttl_seconds,
        )

    async def save_fenced(self, state: ConversationState, token: str) -> bool:
        """Persist only if `token` still holds the turn lock (WATCH + MULTI).

        Returns False, without writing, when the lock expired or changed hands:
        a slow turn must never overwrite the state of a newer turn.
        """
        lock_key = self._lock_key(state.conversation_id)
        data = self._serialize(state)
        async with self.redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(lock_key)
                current = await pipe.get(lock_key)
                if current is None or _as_str(current) != token:
                    await pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(self._key(state.conversation_id), data, ex=self.ttl_seconds)
                await pipe.execute()
            except WatchError:
                return False
        return True

    async def get(self, conversation_id: str) -> ConversationState | None:
        """Return the state, or None if missing, expired or unreadable."""
        raw = await self.redis.get(self._key(conversation_id))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            encrypted = payload.pop(_ENCRYPTED_MAP_FIELD, "")
            payload["placeholder_map"] = self.encryptor.decrypt_map(encrypted)
            return ConversationState.model_validate(payload)
        except (ValueError, ValidationError, CryptoError):
            logger.error("Unreadable conversation state (%s)", redact(conversation_id))
            return None

    async def acquire_turn_lock(self, conversation_id: str) -> str | None:
        """Take the single in-flight-turn lock. Returns a token, or None if held."""
        token = secrets.token_hex(16)
        acquired = await self.redis.set(
            self._lock_key(conversation_id),
            token,
            nx=True,
            px=self.lock_timeout_ms,
        )
        return token if acquired else None

    async def release_turn_lock(self, conversation_id: str, token: str) -> None:
        """Release the lock only if we still own it (compare-and-delete)."""
        key = self._lock_key(conversation_id)
        async with self.redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(key)
                current = await pipe.get(key)
                if current is None or _as_str(current) != token:
                    await pipe.unwatch()
                    return
                pipe.multi()
                pipe.delete(key)
                await pipe.execute()
            except WatchError:
                # The lock changed hands between GET and DEL: not ours anymore.
                logger.warning("Turn lock changed during release")


def _as_str(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value
