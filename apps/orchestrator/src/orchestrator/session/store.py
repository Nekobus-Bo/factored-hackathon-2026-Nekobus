"""Conversation session store on redis-edge (the orchestrator's own Redis).

The orchestrator has no access to redis-core or the database (ADR-0004).
State is stored as JSON with a TTL refreshed on every save; the placeholder
map is encrypted before it reaches Redis (see session/crypto.py).

Next to each conversation lives a reverse index entry, banking session id ->
conversation id (`orch:session:<banking_session_id>`), so the agent API can go
from what a handoff records (`ops.handoff.session_ref`, the banking-core session
id) to the conversation. It is written with the conversation and expires with
it: every save sets both keys with the same TTL, in one transaction. It holds an
opaque id only, no text.
"""

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import WatchError

from orchestrator.log_redaction import redact
from orchestrator.session.crypto import CryptoError, PlaceholderEncryptor
from orchestrator.session.models import ConversationState

logger = logging.getLogger(__name__)

_ENCRYPTED_MAP_FIELD = "placeholder_map_enc"
_LOCK_POLL_SECONDS = 0.05


class SessionStore:
    """Load, save and lock conversations in redis-edge."""

    def __init__(
        self,
        redis: Redis,
        encryptor: PlaceholderEncryptor,
        ttl_seconds: int,
        lock_timeout_seconds: float,
        key_prefix: str = "orch:conv:",
        session_index_prefix: str = "orch:session:",
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self.redis = redis
        self.encryptor = encryptor
        self.ttl_seconds = ttl_seconds
        self.lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))
        self.key_prefix = key_prefix
        self.session_index_prefix = session_index_prefix

    def _key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}{conversation_id}"

    def _index_key(self, banking_session_id: str) -> str:
        return f"{self.session_index_prefix}{banking_session_id}"

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
        """Persist state and its session index, refreshing both TTLs.

        For creation, when no turn can be in flight.
        """
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(
                self._key(state.conversation_id),
                self._serialize(state),
                ex=self.ttl_seconds,
            )
            pipe.set(
                self._index_key(state.banking_session_id),
                state.conversation_id,
                ex=self.ttl_seconds,
            )
            await pipe.execute()

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
                pipe.set(
                    self._index_key(state.banking_session_id),
                    state.conversation_id,
                    ex=self.ttl_seconds,
                )
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

    async def conversation_id_for_session(self, banking_session_id: str) -> str | None:
        """The conversation of a banking-core session id, or None if unknown.

        Answers from the reverse index only; the caller loads the conversation
        and checks it still exists and belongs to that session.
        """
        raw = await self.redis.get(self._index_key(banking_session_id))
        return _as_str(raw) if raw is not None else None

    async def acquire_turn_lock(
        self, conversation_id: str, wait_seconds: float = 0.0
    ) -> str | None:
        """Take the single in-flight-turn lock. Returns a token, or None if held.

        By default one attempt. With `wait_seconds`, keeps trying until then:
        the agent API waits for a customer turn in flight instead of failing.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            token = secrets.token_hex(16)
            acquired = await self.redis.set(
                self._lock_key(conversation_id),
                token,
                nx=True,
                px=self.lock_timeout_ms,
            )
            if acquired:
                return token
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(_LOCK_POLL_SECONDS)

    @asynccontextmanager
    async def turn_lock(
        self, conversation_id: str, wait_seconds: float = 0.0
    ) -> AsyncIterator[str | None]:
        """Hold the turn lock for a block; yields the token, or None if not taken."""
        token = await self.acquire_turn_lock(conversation_id, wait_seconds)
        try:
            yield token
        finally:
            if token is not None:
                await self.release_turn_lock(conversation_id, token)

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
