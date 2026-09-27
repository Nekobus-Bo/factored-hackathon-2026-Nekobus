"""Implementation of otp.send tool in banking-core.

Dispatches a one-time passcode to the pinned customer's registered channel.
Generates an opaque challenge ID and database-verified receipt.
Mutates FSM state to OTP_PENDING.
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
    """Raised when customer has no registered OTP channel on file (NONE)."""

    pass


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

    resolved_port = delivery_port or get_delivery_port()
    resolved_store = challenge_store or get_challenge_store()
    resolved_key = get_master_key(master_key)

    # 1. Fetch customer from DB
    cust_uuid = uuid.UUID(session.pinned_holder_id)
    customer = db_session.get(Customer, cust_uuid)
    if customer is None:
        raise ValueError(f"Pinned customer '{session.pinned_holder_id}' not found")

    # 2. Check registered channel
    channel_str = customer.registered_otp_channel.strip().upper()
    if channel_str == "NONE":
        raise NoOtpChannelError(
            "Customer has no registered OTP channel on file (sentinel NONE). "
            "Cannot send OTP; handoff required."
        )

    # Map to OtpChannel enum
    try:
        otp_channel = OtpChannel(channel_str)
    except ValueError:
        otp_channel = OtpChannel.SMS

    # 3. Decrypt contact details and produce masked destination
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

    # 4. Generate random 6-digit code and unique challenge ID
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    challenge_suffix = "".join(
        secrets.choice(string.ascii_lowercase) for _ in range(16)
    )
    challenge_id = f"chal_{challenge_suffix}"

    # 5. Deliver through port (trusted zone dev sink or external gateway)
    resolved_port.deliver(
        challenge_id=challenge_id,
        channel=otp_channel.value,
        destination_masked=destination_masked,
        code=code,
    )

    # 6. Store active challenge in challenge store
    resolved_store.create_challenge(
        challenge_id=challenge_id,
        customer_id=str(customer.id),
        code=code,
        channel=otp_channel.value,
        destination_masked=destination_masked,
        ttl_seconds=ttl_seconds,
        max_attempts=fsm.max_failed_verifies,
    )

    # 7. Update FSM state (transitions to OTP_PENDING)
    state_before = session.state
    updated_session = fsm.on_otp_send(session, challenge_id=challenge_id)

    # 8. Create verified receipt
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
    return output, updated_session
