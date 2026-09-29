"""Cross-session attempt limits on redis-core (ADR-0004, amendment 2026-09-29).

The counters of a session (`SessionState.attempts`, `failed_verifies`) start over
with every session, and a session costs an attacker one unauthenticated request.
These limits do not depend on the session:

- Failed `otp.verify` evaluations are counted per CUSTOMER. At the configured
  maximum within the window the customer is locked for the configured duration:
  no new code is delivered and no code is evaluated, from any session.
- Failed `customer.match` attempts are counted per claimed DOCUMENT, keyed by
  its blind index, whether or not a customer with that document exists. Past the
  maximum, matches answer `matched=false` without checking.

Windows are fixed and opened by the first failure: the counter is created with
`SET key 0 NX EX <window>` and incremented in the same MULTI, so it always has a
TTL and INCR never extends it. Up to twice the maximum can fit around a window
boundary (the last of one window and the first of the next); the customer lock,
not the window, is what stops a sustained attack.

Keys (prefix `REDIS_ATTEMPT_LIMIT_KEY_PREFIX`, default `limit:`) hold only an
internal customer UUID or a blind index, never PII:

    <prefix>customer:<uuid>:otp_failures    counter, TTL = window
    <prefix>customer:<uuid>:otp_lock        marker,  TTL = lock duration
    <prefix>document:<blind index>:match_failures    counter, TTL = window

Only GET, SET, INCR, WATCH, MULTI, EXEC and UNWATCH are used, all in the
`core-svc` ACL (docs/deployment.md), plus the prefix pattern `~limit:*`.

Every match is counted BEFORE it is evaluated (an atomic reservation, like the
OTP evaluation counter) so parallel requests cannot all pass a check-then-act
gap; a match that succeeds gives its reservation back, so only failures stay.
"""

import logging
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from banking_core.control.policy import PolicyConfig

logger = logging.getLogger(__name__)

DEFAULT_KEY_PREFIX = "limit:"

# Length of the blind-index reference that identifies a document in audit rows:
# a prefix long enough to correlate, and the audit PII guard reads 32+ hex
# characters as a hash rather than as an identifier.
DOCUMENT_REF_LENGTH = 32

_BLIND_INDEX_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_RETRIES = 5


def document_ref(blind_index: str) -> str:
    """Short reference to a document for audit rows; not reversible, not PII."""
    return blind_index[:DOCUMENT_REF_LENGTH]


@dataclass(frozen=True)
class DocumentAttempt:
    """One reserved match attempt against the counters of a claimed document.

    A claimed document can have several blind indexes (one per equivalent
    document type); the attempt is counted on all of them, so the limit is the
    same whichever equivalent type the caller names.
    """

    counters: tuple[str, ...]
    blocked: bool
    # Reference of the document whose limit this very attempt crossed (the first
    # blocked one of a window); None for every other attempt.
    limit_reached_ref: str | None = None


class AttemptLimitStore:
    """Counters and locks that outlive a session, on redis-core."""

    def __init__(
        self,
        redis_client: redis.Redis,
        key_prefix: str | None = None,
    ) -> None:
        self._client = redis_client
        self.key_prefix = (
            key_prefix
            if key_prefix is not None
            else os.getenv("REDIS_ATTEMPT_LIMIT_KEY_PREFIX", DEFAULT_KEY_PREFIX)
        )

    # -- keys ---------------------------------------------------------------

    def _customer_key(self, customer_id: str, suffix: str) -> str:
        # uuid.UUID refuses anything else: a document number or a name handed in
        # by mistake would become part of a Redis key.
        return f"{self.key_prefix}customer:{uuid.UUID(customer_id)}:{suffix}"

    def _failures_key(self, customer_id: str) -> str:
        return self._customer_key(customer_id, "otp_failures")

    def _lock_key(self, customer_id: str) -> str:
        return self._customer_key(customer_id, "otp_lock")

    def _document_key(self, blind_index: str) -> str:
        if not _BLIND_INDEX_RE.fullmatch(blind_index):
            raise ValueError("a document limit is keyed by its blind index only")
        return f"{self.key_prefix}document:{blind_index}:match_failures"

    # -- primitives ---------------------------------------------------------

    def _count(self, key: str, window_seconds: int) -> int:
        """Increment a fixed-window counter, creating it with its TTL if absent."""
        pipe = self._client.pipeline(transaction=True)
        pipe.set(key, 0, nx=True, ex=window_seconds)
        pipe.incr(key)
        return int(pipe.execute()[-1])

    def _decrement_if_positive(self, key: str) -> None:
        """Give one count back; never creates a key and never touches its TTL."""
        with self._client.pipeline() as pipe:
            for _ in range(_RELEASE_RETRIES):
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if raw is None or int(raw) <= 0:
                        pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.set(key, int(raw) - 1, xx=True, keepttl=True)
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue
        # Fails toward the stricter side: the attempt just stays counted.
        logger.warning("A document attempt could not be given back and stays counted")

    # -- customers (otp.send / otp.verify) ----------------------------------

    def customer_locked(self, customer_id: str) -> bool:
        """Whether the customer is locked out of OTP right now."""
        return self._client.get(self._lock_key(customer_id)) is not None

    def record_failed_verify(
        self,
        customer_id: str,
        *,
        max_failures: int,
        window_seconds: int,
        lock_seconds: int,
    ) -> bool:
        """Count one failed otp.verify evaluation; True if it locked the customer.

        Only the call that creates the lock gets True, so the lock event is
        audited once. The failure counter is not reset by the lock: it ages out
        with its window, so a failure right after the lock ends, inside the same
        window, locks again.
        """
        count = self._count(self._failures_key(customer_id), window_seconds)
        if count < max_failures:
            return False
        return bool(
            self._client.set(self._lock_key(customer_id), "1", nx=True, ex=lock_seconds)
        )

    # -- documents (customer.match) -----------------------------------------

    def reserve_document_attempt(
        self,
        blind_indexes: Sequence[str],
        *,
        max_failures: int,
        window_seconds: int,
    ) -> DocumentAttempt:
        """Count a match attempt on its document(s) before evaluating it.

        The attempt is blocked when any of the counters is already past the
        maximum: the caller answers `matched=false` without checking. A blocked
        attempt is counted too, so the window is not extended by it (INCR keeps
        the TTL) but the count keeps telling how hard the document is hit.
        """
        unique = tuple(dict.fromkeys(blind_indexes))
        if not unique:
            return DocumentAttempt(counters=(), blocked=False)
        keys = tuple(self._document_key(b) for b in unique)
        pipe = self._client.pipeline(transaction=True)
        for key in keys:
            pipe.set(key, 0, nx=True, ex=window_seconds)
            pipe.incr(key)
        counts = [int(c) for c in pipe.execute()[1::2]]
        reached = next(
            (
                document_ref(blind_index)
                for blind_index, count in zip(unique, counts, strict=True)
                if count == max_failures + 1
            ),
            None,
        )
        return DocumentAttempt(
            counters=keys,
            blocked=any(count > max_failures for count in counts),
            limit_reached_ref=reached,
        )

    def release_document_attempt(self, attempt: DocumentAttempt) -> None:
        """Give the reservation back: the match succeeded, so it is no failure."""
        for key in attempt.counters:
            self._decrement_if_positive(key)

    # -- demo reset ---------------------------------------------------------

    def clear_customer(self, customer_id: str) -> int:
        """Forget a customer's failures and lock; how many keys were removed.

        For the operator-only demo fixture reset, so evaluation runs start from
        the same state. Nothing on the tool path calls it.
        """
        return int(
            self._client.delete(
                self._failures_key(customer_id), self._lock_key(customer_id)
            )
        )

    def clear_documents(self, blind_indexes: Sequence[str]) -> int:
        """Forget the failed matches of documents; how many keys were removed."""
        keys = [self._document_key(b) for b in dict.fromkeys(blind_indexes)]
        return int(self._client.delete(*keys)) if keys else 0


@dataclass(frozen=True)
class AttemptLimits:
    """The store bound to the thresholds of one policy config (ADR-0002).

    Thresholds are configuration, read per call from the active policy config;
    the store itself only knows numbers.
    """

    store: AttemptLimitStore
    customer_otp_max_failures: int
    customer_otp_window_seconds: int
    customer_otp_lock_seconds: int
    document_match_max_failures: int
    document_match_window_seconds: int

    @classmethod
    def from_config(
        cls, store: AttemptLimitStore, config: "PolicyConfig"
    ) -> "AttemptLimits":
        return cls(
            store=store,
            customer_otp_max_failures=config.customer_otp_max_failures,
            customer_otp_window_seconds=config.customer_otp_window_seconds,
            customer_otp_lock_seconds=config.customer_otp_lock_seconds,
            document_match_max_failures=config.document_match_max_failures,
            document_match_window_seconds=config.document_match_window_seconds,
        )

    def customer_locked(self, customer_id: str) -> bool:
        return self.store.customer_locked(customer_id)

    def record_failed_verify(self, customer_id: str) -> bool:
        return self.store.record_failed_verify(
            customer_id,
            max_failures=self.customer_otp_max_failures,
            window_seconds=self.customer_otp_window_seconds,
            lock_seconds=self.customer_otp_lock_seconds,
        )

    def reserve_document_attempt(self, blind_indexes: Sequence[str]) -> DocumentAttempt:
        return self.store.reserve_document_attempt(
            blind_indexes,
            max_failures=self.document_match_max_failures,
            window_seconds=self.document_match_window_seconds,
        )

    def release_document_attempt(self, attempt: DocumentAttempt) -> None:
        self.store.release_document_attempt(attempt)
