"""Per-client-IP rate limit on conversation creation, on redis-edge.

POST /v1/conversations is unauthenticated and opens a banking-core session with
fresh counters, so without a limit an attacker can open conversations at will.
This is a fixed-window counter per client address: at most
RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR creations per address per window; over it,
the route answers 429 with Retry-After and opens no banking session.

The address is never stored. The Redis key holds only a keyed hash of it (HMAC
keyed from SESSION_SECRET), under the `orch:` prefix the edge ACL allows:

    <prefix>conversations:<hmac hex>:<window index>

The window index is the clock divided by the window, so the key changes when the
window does and Retry-After is computed locally. INCR and EXPIRE go in one MULTI,
so a counter can never be left without a TTL. Commands used: INCR (redis-py sends
INCRBY), EXPIRE, MULTI, EXEC: see the edge-svc ACL in docs/deployment.md.
"""

import hashlib
import hmac
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from redis.asyncio import Redis

# The unit of RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR: the name of the setting says
# "per hour", so this is not a second threshold to tune.
WINDOW_SECONDS = 3600

_KEY_DOMAIN = b"pattern-blue/orchestrator/ip-rate-limit/v1"


@dataclass(frozen=True)
class RateLimitDecision:
    """Whether one more creation is allowed, and when the window ends."""

    allowed: bool
    retry_after_seconds: int


class ConversationRateLimiter:
    """Fixed-window creation counter per client address on redis-edge."""

    def __init__(
        self,
        redis: Redis,
        secret: str,
        limit: int,
        key_prefix: str = "orch:ratelimit:",
        window_seconds: int = WINDOW_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        if not secret:
            raise ValueError("secret must not be empty")
        self.redis = redis
        self.limit = limit
        self.key_prefix = key_prefix
        self.window_seconds = window_seconds
        self._clock = clock
        # Domain-separated from the Fernet key SESSION_SECRET also derives.
        self._mac_key = hmac.new(
            secret.encode("utf-8"), _KEY_DOMAIN, hashlib.sha256
        ).digest()

    def _address_digest(self, client_ip: str) -> str:
        return hmac.new(
            self._mac_key, client_ip.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _key(self, client_ip: str, window_index: int) -> str:
        return (
            f"{self.key_prefix}conversations:"
            f"{self._address_digest(client_ip)}:{window_index}"
        )

    async def hit(self, client_ip: str) -> RateLimitDecision:
        """Count one creation attempt from client_ip and say whether it may go on.

        Every attempt is counted, refused ones too. Redis errors propagate: the
        caller fails closed rather than serve without the limit.
        """
        now = self._clock()
        window_index = int(now // self.window_seconds)
        retry_after = max(
            1, math.ceil(self.window_seconds - (now % self.window_seconds))
        )
        key = self._key(client_ip, window_index)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self.window_seconds)
            count = int((await pipe.execute())[0])
        return RateLimitDecision(
            allowed=count <= self.limit, retry_after_seconds=retry_after
        )
