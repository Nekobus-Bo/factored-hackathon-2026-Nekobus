"""Identity package for customer matching, OTP lifecycle, and document verification."""

from banking_core.identity.challenge_store import (
    OtpChallengeStore,
    get_challenge_store,
)
from banking_core.identity.config import (
    IdentityConfig,
    UnsupportedOtpChannelModeError,
    resolve_otp_channel_mode,
)
from banking_core.identity.ports import OtpDeliveryPort, get_delivery_port
from banking_core.identity.simulated_inbox import (
    SimulatedInbox,
    SimulatedInboxMessage,
    get_simulated_inbox,
    set_simulated_inbox,
)
from banking_core.identity.tools import (
    CustomerLockedError,
    CustomerMatchResult,
    NoOtpChannelError,
    OtpResendLimitError,
    OtpVerifyResult,
    execute_customer_match,
    execute_identity_verify_document,
    execute_limited_customer_match,
    execute_otp_send,
    execute_otp_verify,
)

__all__ = [
    "CustomerLockedError",
    "CustomerMatchResult",
    "IdentityConfig",
    "NoOtpChannelError",
    "OtpChallengeStore",
    "OtpDeliveryPort",
    "OtpResendLimitError",
    "OtpVerifyResult",
    "SimulatedInbox",
    "SimulatedInboxMessage",
    "UnsupportedOtpChannelModeError",
    "execute_customer_match",
    "execute_identity_verify_document",
    "execute_limited_customer_match",
    "execute_otp_send",
    "execute_otp_verify",
    "get_challenge_store",
    "get_delivery_port",
    "get_simulated_inbox",
    "resolve_otp_channel_mode",
    "set_simulated_inbox",
]
