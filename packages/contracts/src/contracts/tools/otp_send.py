"""Contract for otp.send tool."""

from enum import Enum

from pydantic import Field, StrictBool, StrictInt

from contracts.envelope import (
    MASKED_EMAIL_PATTERN,
    MASKED_PHONE_PATTERN,
    Receipt,
)
from contracts.tools.base import BaseToolInput, BaseToolOutput


class OtpChannel(str, Enum):
    """Delivery channels for one-time passcodes."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"
    SIMULATED = "SIMULATED"


OTP_DESTINATION_MASKED_PATTERN = (
    rf"^({MASKED_EMAIL_PATTERN}|{MASKED_PHONE_PATTERN}|"
    r"@[a-zA-Z0-9_.-]*\*+[a-zA-Z0-9_.-]*|simulated)$"
)


class OtpSendInput(BaseToolInput):
    """Input payload to trigger OTP dispatch.

    CRITICAL RULE (ADR-0004): destination phone/email and channel are NEVER model arguments.
    They are resolved strictly server-side from the pinned customer profile and deployment config.
    The model provides an empty payload; extra arguments are strictly forbidden.
    """

    pass


class OtpSendOutput(BaseToolOutput):
    """Result of OTP dispatch.

    Carries challenge_id and a verified receipt. A retry with the same key must
    not send a second code (idempotent); a legitimate resend uses a new key.
    """

    sent: StrictBool = Field(
        ...,
        description="True if the challenge was successfully generated and dispatched",
    )
    challenge_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Unique OTP challenge identifier",
    )
    channel: OtpChannel = Field(
        ...,
        description="Channel through which the OTP was dispatched",
    )
    destination_masked: str = Field(
        ...,
        min_length=4,
        max_length=64,
        pattern=OTP_DESTINATION_MASKED_PATTERN,
        description=(
            "Masked destination adhering to allowlist: masked email, phone, handle, or 'simulated'"
        ),
    )
    expires_in_seconds: StrictInt = Field(
        default=300,
        ge=30,
        le=900,
        description="Validity window of the issued OTP in seconds",
    )
    receipt: Receipt = Field(
        ...,
        description="Verified receipt for OTP challenge dispatch",
    )
