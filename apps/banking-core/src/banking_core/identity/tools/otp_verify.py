"""Implementation of otp.verify tool in banking-core.

Verifies customer-submitted 6-digit OTP code against active challenge.
Mutates FSM state to VERIFIED (on match) or LOCKED (on max failures).
Returns verified database receipt.

A customer locked across sessions (control/attempt_limits.py) is refused before
the code is compared, and every failed verification is counted toward that lock.
"""

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from contracts.envelope import Receipt, ResourceState
from contracts.tools.otp_verify import (
    OtpVerifyInput,
    OtpVerifyOutput,
)

from banking_core.control.attempt_limits import AttemptLimits
from banking_core.control.fsm import VerificationFSM
from banking_core.control.session import SessionState
from banking_core.identity.challenge_store import OtpChallengeStore, get_challenge_store
from banking_core.identity.tools.customer_lock import ensure_customer_not_locked


class OtpVerifyResult(NamedTuple):
    """Outcome of one otp.verify."""

    output: OtpVerifyOutput
    session: SessionState
    # This very failure reached the customer's failure maximum and locked the
    # customer across sessions: the caller audits the lock event.
    customer_locked: bool = False


def execute_otp_verify(
    args: OtpVerifyInput,
    session: SessionState,
    fsm: VerificationFSM,
    limits: AttemptLimits,
    challenge_store: OtpChallengeStore | None = None,
    audit_id: str | None = None,
) -> OtpVerifyResult:
    """Execute otp.verify tool against the active challenge in session.

    Raises:
        CustomerLockedError: the pinned customer is locked across sessions; the
            code was not compared and nothing was counted.
    """
    customer_id = session.pinned_holder_id
    if not customer_id:
        raise ValueError(
            "Session has no pinned customer; customer.match is required before "
            "otp.verify"
        )

    # Decide the lock BEFORE the code is compared: a locked customer's challenge
    # is never evaluated, so a correct code cannot verify while the lock holds.
    ensure_customer_not_locked(session, fsm, limits)

    resolved_store = challenge_store or get_challenge_store()
    state_before = session.state
    challenge_id = session.otp_challenge_id

    now = datetime.now(UTC)
    receipt_audit_id = audit_id or f"aud_{uuid.uuid4().hex[:16]}"
    target_masked = challenge_id if challenge_id else "chal_unknown"

    if challenge_id:
        is_valid, attempts_left, _ = resolved_store.verify_challenge(
            challenge_id=challenge_id,
            code=args.code,
        )
    else:
        # No challenge was active: count as failed verification
        is_valid, attempts_left = False, 0

    customer_locked = False
    if not is_valid:
        # Every failed verification counts toward the customer's lock, whichever
        # session it happens in. The failure that locks the customer also ends
        # this session: no attempts are left.
        customer_locked = limits.record_failed_verify(customer_id)
        if customer_locked:
            attempts_left = 0

    updated_session = fsm.on_otp_verify(
        session.model_copy(), valid=is_valid, customer_locked=customer_locked
    )
    receipt = Receipt(
        action="otp.verify",
        target_masked=target_masked,
        state_before=ResourceState(state_before.value),
        state_after=ResourceState(updated_session.state.value),
        verified_at=now,
        audit_id=receipt_audit_id,
    )
    output = OtpVerifyOutput(
        verified=is_valid,
        state=updated_session.state,
        attempts_remaining=attempts_left,
        receipt=receipt,
    )
    return OtpVerifyResult(output, updated_session, customer_locked)
