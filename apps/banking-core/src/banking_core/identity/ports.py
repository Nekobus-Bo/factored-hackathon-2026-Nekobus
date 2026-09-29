"""Delivery port for outbound One-Time Passcodes (OTP).

Core invariants:
1. The delivery mode comes from OTP_CHANNEL_MODE. Only ``simulated`` is implemented
   (an in-app inbox on redis-core, ADR-0007 amendment 2026-09-29); any other value
   fails with an explicit message instead of pretending to send.
2. Delivery stays in the trusted zone: the model never sees the code and never
   chooses the channel or the destination.
3. OTP codes are never logged in clear text and never returned in ToolResult data.
4. A real provider plugs in by implementing ``OtpDeliveryPort``; none exists yet.
5. The test/dev-only hook that reads a code back is disabled by default.
"""

from typing import Protocol

from banking_core.identity.config import resolve_otp_channel_mode
from banking_core.identity.simulated_inbox import get_simulated_inbox


class OtpDeliveryPort(Protocol):
    """Port for outbound OTP delivery."""

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
        """Deliver the generated OTP code for the session's customer.

        ``destination_masked`` is the only form of the destination this port
        receives; ``ttl_seconds`` is how long the code stays valid.
        """
        ...


def get_delivery_port() -> OtpDeliveryPort:
    """Get the delivery port for the configured OTP_CHANNEL_MODE."""
    resolve_otp_channel_mode()  # raises for any mode that is not implemented
    return get_simulated_inbox()
