"""Contract for otp.verify tool."""

from pydantic import Field, StrictBool, StrictInt

from contracts.envelope import Receipt, VerificationState
from contracts.tools.base import BaseToolInput, BaseToolOutput


class OtpVerifyInput(BaseToolInput):
    """Input payload to verify a customer-submitted OTP code."""

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-digit numeric verification code",
    )


class OtpVerifyOutput(BaseToolOutput):
    """Result of OTP verification.

    Mutates FSM state (OTP_PENDING -> VERIFIED or LOCKED) and returns a verified receipt.
    """

    verified: StrictBool = Field(
        ...,
        description="True if the provided code matched the active challenge",
    )
    state: VerificationState = Field(
        ...,
        description="Current verification state following the check (e.g. VERIFIED or LOCKED)",
    )
    attempts_remaining: StrictInt = Field(
        ...,
        ge=0,
        description="Remaining verification attempts before session lockout",
    )
    receipt: Receipt = Field(
        ...,
        description="Verified receipt recording FSM verification state transition",
    )
