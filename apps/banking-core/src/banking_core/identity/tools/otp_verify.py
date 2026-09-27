"""Implementation of otp.verify tool in banking-core.

Verifies customer-submitted 6-digit OTP code against active challenge.
Mutates FSM state to VERIFIED (on match) or LOCKED (on max failures).
Returns verified database receipt.
"""

import uuid
from datetime import UTC, datetime

from contracts.envelope import Receipt, ResourceState, VerificationState
from contracts.tools.otp_verify import (
    OtpVerifyInput,
    OtpVerifyOutput,
)

from banking_core.control.fsm import VerificationFSM
from banking_core.control.session import SessionState
from banking_core.identity.challenge_store import OtpChallengeStore, get_challenge_store


def execute_otp_verify(
    args: OtpVerifyInput,
    session: SessionState,
    fsm: VerificationFSM,
    challenge_store: OtpChallengeStore | None = None,
    audit_id: str | None = None,
) -> tuple[OtpVerifyOutput, SessionState]:
    """Execute otp.verify tool against the active challenge in session.

    Returns:
        tuple[OtpVerifyOutput, SessionState]: Output payload and updated session state.
    """
    resolved_store = challenge_store or get_challenge_store()
    state_before = session.state
    challenge_id = session.otp_challenge_id

    now = datetime.now(UTC)
    receipt_audit_id = audit_id or f"aud_{uuid.uuid4().hex[:16]}"
    target_masked = challenge_id if challenge_id else "chal_unknown"

    if not challenge_id:
        # No challenge was active: count as failed verification
        updated_session = fsm.on_otp_verify(session, valid=False)
        receipt = Receipt(
            action="otp.verify",
            target_masked=target_masked,
            state_before=ResourceState(state_before.value),
            state_after=ResourceState(updated_session.state.value),
            verified_at=now,
            audit_id=receipt_audit_id,
        )
        return (
            OtpVerifyOutput(
                verified=False,
                state=updated_session.state,
                attempts_remaining=0,
                receipt=receipt,
            ),
            updated_session,
        )

    # Verify code against challenge store
    is_valid, attempts_left, _ = resolved_store.verify_challenge(
        challenge_id=challenge_id,
        code=args.code,
    )

    if is_valid:
        updated_session = fsm.on_otp_verify(session, valid=True)
        receipt = Receipt(
            action="otp.verify",
            target_masked=target_masked,
            state_before=ResourceState(state_before.value),
            state_after=ResourceState.VERIFIED,
            verified_at=now,
            audit_id=receipt_audit_id,
        )
        output = OtpVerifyOutput(
            verified=True,
            state=VerificationState.VERIFIED,
            attempts_remaining=attempts_left,
            receipt=receipt,
        )
    else:
        updated_session = fsm.on_otp_verify(session, valid=False)
        receipt = Receipt(
            action="otp.verify",
            target_masked=target_masked,
            state_before=ResourceState(state_before.value),
            state_after=ResourceState(updated_session.state.value),
            verified_at=now,
            audit_id=receipt_audit_id,
        )
        output = OtpVerifyOutput(
            verified=False,
            state=updated_session.state,
            attempts_remaining=attempts_left,
            receipt=receipt,
        )

    return output, updated_session
