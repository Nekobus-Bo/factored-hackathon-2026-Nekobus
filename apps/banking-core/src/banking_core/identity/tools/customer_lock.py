"""Refusal shared by otp.send and otp.verify while a customer is locked.

A customer is locked across sessions after too many failed otp.verify (see
control/attempt_limits.py). The decision is taken BEFORE anything is generated,
delivered or evaluated, so a locked customer never gets a working code and a
correct code is never compared.
"""

from banking_core.control.attempt_limits import AttemptLimits
from banking_core.control.fsm import VerificationFSM
from banking_core.control.session import SessionState


class CustomerLockedError(Exception):
    """Raised when the pinned customer is locked out of OTP.

    Nothing was delivered, stored or evaluated. Carries the LOCKED session for the
    caller to persist once the refusal is audited, and the customer id (an
    internal UUID, not PII) for that audit row.
    """

    def __init__(self, locked_session: SessionState, customer_id: str) -> None:
        super().__init__("Customer is locked out of OTP; session locked")
        self.locked_session = locked_session
        self.customer_id = customer_id


def ensure_customer_not_locked(
    session: SessionState, fsm: VerificationFSM, limits: AttemptLimits
) -> None:
    """Raise CustomerLockedError if the session's pinned customer is locked."""
    customer_id = session.pinned_holder_id
    if customer_id and limits.customer_locked(customer_id):
        raise CustomerLockedError(
            fsm.on_customer_locked(session.model_copy()), customer_id
        )
