"""Delivery port and dev sink for Outbound One-Time Passcodes (OTP).

Core invariants:
1. Delivery channel is an open decision (ADR-0004, ADR-0007).
2. The dev sink stays strictly in the trusted zone.
3. OTP codes are never logged in clear text and never returned in ToolResult data.
4. Test/dev-only hook to retrieve code is disabled by default.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class OtpDeliveryPort(Protocol):
    """Port for outbound OTP delivery."""

    def deliver(
        self,
        challenge_id: str,
        channel: str,
        destination_masked: str,
        code: str,
    ) -> None:
        """Deliver the generated OTP code to the customer destination."""
        ...


class DevOtpSink:
    """In-memory dev sink for OTP delivery within the trusted zone."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def deliver(
        self,
        challenge_id: str,
        channel: str,
        destination_masked: str,
        code: str,
    ) -> None:
        """Deliver and store OTP in the trusted zone dev sink."""
        now = datetime.now(UTC)
        self._store[challenge_id] = {
            "challenge_id": challenge_id,
            "channel": channel,
            "destination_masked": destination_masked,
            "code": code,
            "delivered_at": now,
        }
        # Log delivery without cleartext code
        logger.info(
            "OTP delivered to dev sink: challenge_id=%s channel=%s destination=%s",
            challenge_id,
            channel,
            destination_masked,
        )

    def get_code(self, challenge_id: str, allow_hook: bool = False) -> str | None:
        """Retrieve cleartext code for evaluation runner only if hook is enabled."""
        if not allow_hook:
            raise PermissionError(
                "Dev OTP retrieval hook is disabled by default. "
                "Set ALLOW_DEV_OTP_HOOK=true in evaluation environments."
            )
        entry = self._store.get(challenge_id)
        return entry["code"] if entry else None

    def clear(self) -> None:
        """Clear sink state (useful between tests)."""
        self._store.clear()


_global_dev_sink = DevOtpSink()


def get_dev_sink() -> DevOtpSink:
    """Get the global dev OTP sink."""
    return _global_dev_sink


def get_delivery_port() -> OtpDeliveryPort:
    """Get configured OTP delivery port."""
    return _global_dev_sink
