"""Simulated OTP inbox on redis-core, the delivery port for OTP_CHANNEL_MODE=simulated.

Nothing is sent to a real channel (ADR-0007, amendment 2026-09-29). Delivering a code
writes an inbox entry that the web client turns into a "you got an email with the
code" notice. A real provider replaces this class behind ``OtpDeliveryPort``.

Keys, all under ``REDIS_OTP_INBOX_KEY_PREFIX`` (default ``otp:inbox:``, inside the
``~otp:*`` ACL space of ``core-svc``) and using only GET, SET EX, DEL, WATCH, MULTI,
EXEC and UNWATCH, the commands that ACL already grants (no SCAN, MGET or sorted sets):

- ``<prefix>challenge:<challenge_id>``  the entry (JSON, holds the clear code); its
  TTL is the challenge TTL. The evaluation hook reads it directly.
- ``<prefix>session:<session_id>``      index of the session's challenge ids with
  their expiry (JSON, no codes), capped at ``MAX_MESSAGES_PER_SESSION``, so a
  session's inbox can be listed without SCAN.

Security rules:
- The clear code exists only in the entry, for the challenge TTL. It is never
  logged and is excluded from the model repr.
- Reads are scoped by session: the only way to list messages is through the
  requested session's index, and an entry whose stored session differs from the
  requested one is dropped whatever the index says.
- Unreadable entries are skipped without echoing their payload (it holds a code).
"""

import json
import logging
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import redis
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from banking_core.redis_client import create_redis_client

logger = logging.getLogger(__name__)

DEFAULT_INBOX_KEY_PREFIX = "otp:inbox:"
# A session can resend only a few codes (OTP_MAX_RESENDS); the cap bounds the index
# and the memory one session can hold, whatever the configuration says.
MAX_MESSAGES_PER_SESSION = 10
_INDEX_UPDATE_RETRIES = 10


class SimulatedInboxMessage(BaseModel):
    """One simulated delivery, as stored on redis-core."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    challenge_id: str
    channel: str
    destination_masked: str
    code: str = Field(repr=False)
    created_at: datetime
    expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SimulatedInbox:
    """Redis-backed inbox; implements ``OtpDeliveryPort``."""

    def __init__(
        self,
        redis_client: redis.Redis,
        key_prefix: str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._redis = redis_client
        self._clock = clock
        self.key_prefix = (
            key_prefix
            if key_prefix is not None
            else os.getenv("REDIS_OTP_INBOX_KEY_PREFIX", DEFAULT_INBOX_KEY_PREFIX)
        )

    def _entry_key(self, challenge_id: str) -> str:
        return f"{self.key_prefix}challenge:{challenge_id}"

    def _index_key(self, session_id: str) -> str:
        return f"{self.key_prefix}session:{session_id}"

    def deliver(
        self,
        *,
        session_id: str,
        challenge_id: str,
        channel: str,
        destination_masked: str,
        code: str,
        ttl_seconds: int,
    ) -> None:
        """Put the code in the session's inbox until the challenge expires."""
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be at least 1")
        now = self._clock()
        message = SimulatedInboxMessage(
            session_id=session_id,
            challenge_id=challenge_id,
            channel=channel,
            destination_masked=destination_masked,
            code=code,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._store(message, ttl_seconds)
        # Never the code, nor the session id (whoever holds it can read the inbox).
        logger.info(
            "OTP delivered to simulated inbox: challenge_id=%s channel=%s "
            "destination=%s",
            challenge_id,
            channel,
            destination_masked,
        )

    def messages(self, session_id: str) -> list[SimulatedInboxMessage]:
        """Unexpired messages of this session only, newest first."""
        challenge_ids = [
            challenge_id
            for challenge_id, _ in self._parse_index(
                self._redis.get(self._index_key(session_id))
            )
        ]
        if not challenge_ids:
            return []
        pipe = self._redis.pipeline(transaction=False)
        for challenge_id in challenge_ids:
            pipe.get(self._entry_key(challenge_id))
        now = self._clock()
        found: list[SimulatedInboxMessage] = []
        for raw in pipe.execute():
            message = self._parse_message(raw)
            if message is None or message.session_id != session_id:
                continue
            if message.expires_at <= now:
                continue
            found.append(message)
        found.sort(key=lambda m: m.created_at, reverse=True)
        return found

    def get_code(self, challenge_id: str) -> str | None:
        """Code of an unexpired challenge, whatever its session.

        For the evaluation hook only, which knows the challenge and not the session.
        """
        message = self._parse_message(self._redis.get(self._entry_key(challenge_id)))
        if message is None or message.expires_at <= self._clock():
            return None
        return message.code

    @staticmethod
    def _parse_index(raw: str | bytes | None) -> list[tuple[str, float]]:
        """Index entries as (challenge_id, expires_at epoch seconds), oldest first."""
        if raw is None:
            return []
        try:
            data = json.loads(raw)
            return [(str(item[0]), float(item[1])) for item in data]
        except (ValueError, TypeError, IndexError):
            logger.warning("Ignoring an unreadable simulated inbox index")
            return []

    @staticmethod
    def _parse_message(raw: str | bytes | None) -> SimulatedInboxMessage | None:
        if raw is None:
            return None
        try:
            return SimulatedInboxMessage.model_validate_json(raw)
        except ValidationError:
            # No details: the payload holds a clear code.
            logger.warning("Ignoring an unreadable simulated inbox entry")
            return None

    def _store(self, message: SimulatedInboxMessage, ttl_seconds: int) -> None:
        """Write the entry and update the session index in one transaction."""
        index_key = self._index_key(message.session_id)
        for _ in range(_INDEX_UPDATE_RETRIES):
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(index_key)
                    now = self._clock().timestamp()
                    entries = [
                        (cid, expires)
                        for cid, expires in self._parse_index(pipe.get(index_key))
                        if expires > now and cid != message.challenge_id
                    ]
                    entries.append(
                        (message.challenge_id, message.expires_at.timestamp())
                    )
                    dropped = entries[:-MAX_MESSAGES_PER_SESSION]
                    entries = entries[-MAX_MESSAGES_PER_SESSION:]
                    index_ttl = max(
                        1, math.ceil(max(expires for _, expires in entries) - now)
                    )
                    pipe.multi()
                    pipe.set(
                        self._entry_key(message.challenge_id),
                        message.model_dump_json(),
                        ex=ttl_seconds,
                    )
                    pipe.set(index_key, json.dumps(entries), ex=index_ttl)
                    for cid, _ in dropped:
                        pipe.delete(self._entry_key(cid))
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue
        raise RuntimeError("Could not update the simulated inbox index")


_global_inbox: SimulatedInbox | None = None


def get_simulated_inbox() -> SimulatedInbox:
    """The process-wide inbox on redis-core (its state lives in Redis, not here)."""
    global _global_inbox
    if _global_inbox is None:
        _global_inbox = SimulatedInbox(redis_client=create_redis_client())
    return _global_inbox


def set_simulated_inbox(inbox: SimulatedInbox | None) -> None:
    """Override (or reset with None) the process-wide inbox, for tests."""
    global _global_inbox
    _global_inbox = inbox
