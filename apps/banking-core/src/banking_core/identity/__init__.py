"""Identity package for customer matching, OTP lifecycle, and document verification."""

from banking_core.identity.challenge_store import (
    OtpChallengeStore,
    get_challenge_store,
)
from banking_core.identity.config import IdentityConfig
from banking_core.identity.ports import (
    DevOtpSink,
    OtpDeliveryPort,
    get_delivery_port,
    get_dev_sink,
)
from banking_core.identity.tools import (
    NoOtpChannelError,
    execute_customer_match,
    execute_identity_verify_document,
    execute_otp_send,
    execute_otp_verify,
)

__all__ = [
    "DevOtpSink",
    "IdentityConfig",
    "NoOtpChannelError",
    "OtpChallengeStore",
    "OtpDeliveryPort",
    "execute_customer_match",
    "execute_identity_verify_document",
    "execute_otp_send",
    "execute_otp_verify",
    "get_challenge_store",
    "get_delivery_port",
    "get_dev_sink",
]
