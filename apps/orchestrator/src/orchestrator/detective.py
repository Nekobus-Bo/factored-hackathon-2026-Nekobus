"""Detective mode's on/off switch (ADR-0019).

`DETECTIVE_MODE` says whether an environment offers detective mode at all, and
starts it on. Within that, the back office turns it off and on at runtime (agent
API), for every conversation at once and without a restart. The state is one key
on redis-edge, the orchestrator's own Redis: nothing here reaches banking-core.

Unavailable, it is off whatever the key says. Available and never switched, it is
on. If redis-edge cannot be read it falls back to that default: the trace holds
masked values only, so failing open costs nothing a customer could not see.
"""

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_ON = "1"
_OFF = "0"


class DetectiveUnavailableError(RuntimeError):
    """The environment does not offer detective mode (DETECTIVE_MODE is off)."""


class DetectiveSwitch:
    """Whether turns return their trace right now."""

    def __init__(self, available: bool, redis: Redis | None, key: str) -> None:
        self.available = available
        self._redis = redis
        self._key = key
        # Without a Redis (tests), the state lives in the process.
        self._local: bool | None = None

    async def enabled(self) -> bool:
        if not self.available:
            return False
        if self._redis is None:
            return self._local if self._local is not None else True
        try:
            value = await self._redis.get(self._key)
        except Exception as exc:
            logger.warning(
                "Detective switch unreadable (%s); on by default", type(exc).__name__
            )
            return True
        if isinstance(value, bytes):
            value = value.decode()
        return value != _OFF

    async def set(self, enabled: bool) -> bool:
        """Turn it on or off for every conversation. Returns the new state."""
        if not self.available:
            raise DetectiveUnavailableError("detective mode is not offered here")
        if self._redis is None:
            self._local = enabled
        else:
            await self._redis.set(self._key, _ON if enabled else _OFF)
        return enabled
