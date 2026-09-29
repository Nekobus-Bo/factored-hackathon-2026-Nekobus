"""Implementation of otp.send tool in banking-core.

Dispatches a one-time passcode to the pinned customer's registered channel.
Generates an opaque challenge ID and database-verified receipt.
Mutates FSM state to OTP_PENDING.

Everything that can refuse the call (resend limit, channel, contract output)
is decided before the challenge is stored or the code is delivered: a refused
call delivers nothing.
"""

import secrets
import string
import uuid
from datetime import UTC, datetime

from contracts.envelope import (
    Receipt,
    ResourceState,
)
from contracts.tools.otp_send import (
    OtpChannel,
    OtpSendInput,
    OtpSendOutput,
)
from sqlalchemy.orm import Session

from banking_core.control.fsm import VerificationFSM
from banking_core.control.session import SessionState
from banking_core.crypto import RecordEncryptor, get_master_key
from banking_core.identity.challenge_store import OtpChallengeStore, get_challenge_store
from banking_core.identity.ports import OtpDeliveryPort, get_delivery_port
from banking_core.models.core_bank import Customer


class NoOtpChannelError(ValueError):
    """Raised when there is no usable OTP channel on file.

    Either the NONE sentinel or a value this service does not recognize: in both
    cases nothing is delivered and the customer goes to a human.
    """

    def __init__(
        self, message: str, audit_reason: str = "no_registered_otp_channel"
    ) -> None:
        super().__init__(message)
        self.audit_reason = audit_reason


class OtpResendLimitError(Exception):
    """Raised when a resend would exceed the configured limit.

    Nothing was delivered or stored. Carries the LOCKED session for the caller to
    persist once the refusal is audited.
    """

    def __init__(self, locked_session: SessionState) -> None:
        super().__init__("OTP resend limit exceeded; session locked")
        self.locked_session = locked_session


def _mask_phone(phone: str) -> str:
    digits = [c for c in phone if c.isdigit()]
    last4 = "".join(digits[-4:]) if len(digits) >= 4 else "".join(digits)
    prefix = ""
    if phone.startswith("+"):
        prefix = phone[:3] + " " if len(phone) >= 3 else "+ "
    return f"{prefix}*** *** {last4}".strip()


def _mask_email(email: str) -> str:
    if "@" in email:
        user, domain = email.split("@", 1)
        first = user[0] if user else "u"
        return f"{first}***@{domain}"
    return "u***@domain.com"


def execute_otp_send(
    db_session: Session,
    args: OtpSendInput,
    session: SessionState,
    fsm: VerificationFSM,
    delivery_port: OtpDeliveryPort | None = None,
    challenge_store: OtpChallengeStore | None = None,
    master_key: str | bytes | None = None,
    ttl_seconds: int = 300,
    audit_id: str | None = None,
) -> tuple[OtpSendOutput, SessionState]:
    """Execute otp.send tool, generating challenge and delivering to registered channel.

    Returns:
        tuple[OtpSendOutput, SessionState]: Output payload and updated session state.
    """
    if not session.pinned_holder_id:
        raise ValueError(
            "Session has no pinned customer; customer.match is required before otp.send"
        )

    # 1. Decide the resend limit BEFORE generating or delivering anything: a
    # resend that locks the session must not deliver a working code.
    if fsm.otp_send_would_lock(session):
        raise OtpResendLimitError(fsm.on_otp_send_limit_exceeded(session.model_copy()))

    resolved_port = delivery_port or get_delivery_port()
    resolved_store = challenge_store or get_challenge_store()
    resolved_key = get_master_key(master_key)

    # 2. Fetch customer from DB
    cust_uuid = uuid.UUID(session.pinned_holder_id)
    customer = db_session.get(Customer, cust_uuid)
    if customer is None:
        raise ValueError(f"Pinned customer '{session.pinned_holder_id}' not found")

    # 3. Resolve the registered channel; anything but a known channel fails closed
    channel_str = customer.registered_otp_channel.strip().upper()
    if channel_str == "NONE":
        raise NoOtpChannelError(
            "Customer has no registered OTP channel on file (sentinel NONE). "
            "Cannot send OTP; handoff required."
        )
    try:
        otp_channel = OtpChannel(channel_str)
    except ValueError:
        # Never guess a channel: sending to the wrong one would deliver the code
        # somewhere the customer did not register.
        raise NoOtpChannelError(
            "Customer's registered OTP channel is not recognized. "
            "Cannot send OTP; handoff required.",
            audit_reason="unrecognized_otp_channel",
        ) from None

    # 4. Decrypt contact details and produce masked destination
    encryptor = RecordEncryptor(
        schema="core_bank",
        table="customer",
        record_id=customer.id,
        master_key=resolved_key,
    )

    if otp_channel == OtpChannel.EMAIL:
        raw_contact = encryptor.decrypt("email_enc", customer.email_enc)
        destination_masked = _mask_email(raw_contact)
    else:
        raw_contact = encryptor.decrypt("phone_enc", customer.phone_enc)
        destination_masked = _mask_phone(raw_contact)

    # 5. Generate random 6-digit code and unique challenge ID
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    challenge_suffix = "".join(
        secrets.choice(string.ascii_lowercase) for _ in range(16)
    )
    challenge_id = f"chal_{challenge_suffix}"

    # 6. Compute the transition on a copy and build the contract output, so any
    # invalid state or output fails here, before the challenge exists or a code
    # leaves. The caller's session is left untouched.
    state_before = session.state
    updated_session = fsm.on_otp_send(session.model_copy(), challenge_id=challenge_id)
    now = datetime.now(UTC)
    receipt_audit_id = audit_id or f"aud_{uuid.uuid4().hex[:16]}"
    receipt = Receipt(
        action="otp.send",
        target_masked=destination_masked,
        state_before=ResourceState(state_before.value),
        state_after=ResourceState(updated_session.state.value),
        verified_at=now,
        audit_id=receipt_audit_id,
    )
    output = OtpSendOutput(
        sent=True,
        challenge_id=challenge_id,
        channel=otp_channel,
        destination_masked=destination_masked,
        expires_in_seconds=ttl_seconds,
        receipt=receipt,
    )

    # 7. Store the challenge, then deliver: a code is never sent without a
    # challenge that can verify it.
    resolved_store.create_challenge(
        challenge_id=challenge_id,
        customer_id=str(customer.id),
        code=code,
        channel=otp_channel.value,
        destination_masked=destination_masked,
        ttl_seconds=ttl_seconds,
        max_attempts=fsm.max_failed_verifies,
    )
    resolved_port.deliver(
        challenge_id=challenge_id,
        channel=otp_channel.value,
        destination_masked=destination_masked,
        code=code,
    )
    return output, updated_session
