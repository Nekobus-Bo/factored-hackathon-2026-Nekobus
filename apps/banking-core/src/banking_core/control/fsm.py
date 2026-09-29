"""Finite State Machine for customer identity verification in banking-core.

States and transitions conform strictly to ADR-0003 Appendix A (Approved 2026-09-26):
- ANONYMOUS -> IDENTIFIED on customer.match success (requires pinned holder_id)
- ANONYMOUS / IDENTIFIED -> LOCKED after N failed match attempts
- IDENTIFIED -> OTP_PENDING on otp.send
- OTP_PENDING -> VERIFIED on valid otp.verify
- OTP_PENDING -> LOCKED after N failed otp.verify attempts or max resends
- re-match in IDENTIFIED with a DIFFERENT holder replaces the pinned holder,
  discards the active OTP challenge, and counts as an attempt
- Any state -> HANDED_OFF on handoff.create

N comes strictly from configuration (OTP_MAX_ATTEMPTS, RATE_LIMIT_ATTEMPTS_PER_SESSION,
OTP_MAX_RESENDS), never hardcoded constants.
"""

from typing import TYPE_CHECKING

from contracts.envelope import VerificationState

if TYPE_CHECKING:
    from banking_core.control.policy import PolicyConfig
    from banking_core.control.session import SessionState


class FSMError(Exception):
    """Base exception for verification FSM errors."""


class InvalidFSMTransitionError(FSMError):
    """Raised when an illegal state transition is attempted."""

    def __init__(
        self,
        current_state: VerificationState,
        action: str,
        reason: str = "",
    ) -> None:
        self.current_state = current_state
        self.action = action
        self.reason = reason
        msg = f"Cannot execute '{action}' in state '{current_state.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class VerificationFSM:
    """Deterministic verification state machine.

    All attempt thresholds (N) are injected via configuration, never hardcoded.
    """

    def __init__(
        self,
        max_failed_matches: int,
        max_failed_verifies: int,
        max_otp_resends: int,
    ) -> None:
        if max_failed_matches < 1:
            raise ValueError("max_failed_matches must be at least 1")
        if max_failed_verifies < 1:
            raise ValueError("max_failed_verifies must be at least 1")
        if max_otp_resends < 1:
            raise ValueError("max_otp_resends must be at least 1")
        self.max_failed_matches = max_failed_matches
        self.max_failed_verifies = max_failed_verifies
        self.max_otp_resends = max_otp_resends

    @classmethod
    def from_config(cls, config: "PolicyConfig") -> "VerificationFSM":
        """Build VerificationFSM from validated PolicyConfig."""
        return cls(
            max_failed_matches=config.rate_limit_attempts_per_session,
            max_failed_verifies=config.otp_max_attempts,
            max_otp_resends=config.otp_max_resends,
        )

    def on_customer_match(
        self,
        session: "SessionState",
        matched: bool,
        holder_id: str | None = None,
        max_failed_matches: int | None = None,
    ) -> "SessionState":
        """Process customer.match result against current session state.

        - Permitted only in ANONYMOUS or IDENTIFIED.
        - On matched=True:
            - Requires non-empty holder_id (ADR-0004: requires pinned holder).
            - From ANONYMOUS: transitions to IDENTIFIED, pins holder_id.
            - From IDENTIFIED with same holder: stays IDENTIFIED.
            - From IDENTIFIED with different holder: replaces pinned holder,
              discards active OTP challenge, counts as an attempt.
        - On matched=False:
            - Increments failed match attempts and total attempts.
            - If failed matches >= N: transitions to LOCKED.
        """
        limit = (
            max_failed_matches
            if max_failed_matches is not None
            else self.max_failed_matches
        )

        if session.state not in (
            VerificationState.ANONYMOUS,
            VerificationState.IDENTIFIED,
        ):
            raise InvalidFSMTransitionError(
                current_state=session.state,
                action="customer.match",
                reason=(
                    "customer.match is only allowed in ANONYMOUS or IDENTIFIED states"
                ),
            )

        if matched:
            if not holder_id or not str(holder_id).strip():
                raise ValueError(
                    "holder_id is required when customer match succeeds "
                    "(ADR-0004 invariant: IDENTIFIED requires pinned holder)"
                )

            if session.state == VerificationState.ANONYMOUS:
                session.state = VerificationState.IDENTIFIED
                session.pinned_holder_id = holder_id
                session.otp_challenge_id = None
                session.failed_matches = 0
            elif session.state == VerificationState.IDENTIFIED:
                if holder_id != session.pinned_holder_id:
                    # Re-match with a DIFFERENT holder replaces the pinned holder,
                    # discards the OTP challenge, and counts as an attempt.
                    session.pinned_holder_id = holder_id
                    session.otp_challenge_id = None
                    session.attempts += 1
                    # If total attempts reach limit, lock
                    if session.attempts >= limit:
                        session.state = VerificationState.LOCKED
        else:
            session.attempts += 1
            session.failed_matches += 1
            if session.failed_matches >= limit or session.attempts >= limit:
                session.state = VerificationState.LOCKED

        return session

    def _otp_send_limit_reached(self, resends: int, attempts: int) -> bool:
        return resends >= self.max_otp_resends or attempts >= self.max_failed_matches

    def otp_send_would_lock(self, session: "SessionState") -> bool:
        """Whether an otp.send now would trip the resend or attempt limit.

        Lets the caller decide BEFORE generating or delivering a code: a resend
        that locks the session must not deliver a working one. Only a resend
        (OTP_PENDING) counts; the first send from IDENTIFIED never locks.
        Reads the session, never changes it.
        """
        return session.state == VerificationState.OTP_PENDING and (
            self._otp_send_limit_reached(session.otp_resends + 1, session.attempts + 1)
        )

    def on_otp_send_limit_exceeded(self, session: "SessionState") -> "SessionState":
        """Lock a session whose resend exceeded the limit; nothing was delivered.

        Counts the resend and the attempt like a locking otp.send does, and
        leaves otp_challenge_id as it was: no new challenge was created.
        """
        if not self.otp_send_would_lock(session):
            raise InvalidFSMTransitionError(
                current_state=session.state,
                action="otp.send",
                reason="the resend limit has not been reached",
            )
        session.otp_resends += 1
        session.attempts += 1
        session.state = VerificationState.LOCKED
        return session

    def on_otp_send(
        self,
        session: "SessionState",
        challenge_id: str,
    ) -> "SessionState":
        """Process otp.send result against current session state.

        - Permitted in IDENTIFIED or OTP_PENDING (resend).
        - If OTP_PENDING (resend): counts resend attempt. If resends >= max_otp_resends,
          transitions to LOCKED.
        - Transitions to OTP_PENDING.
        - Sets/updates active otp_challenge_id.
        - Does NOT reset failed_verifies (failed_verifies resets only on VERIFIED).
        """
        if session.state not in (
            VerificationState.IDENTIFIED,
            VerificationState.OTP_PENDING,
        ):
            raise InvalidFSMTransitionError(
                current_state=session.state,
                action="otp.send",
                reason="otp.send is only allowed in IDENTIFIED or OTP_PENDING states",
            )

        if self.otp_send_would_lock(session):
            return self.on_otp_send_limit_exceeded(session)

        if session.state == VerificationState.OTP_PENDING:
            session.otp_resends += 1
            session.attempts += 1

        session.state = VerificationState.OTP_PENDING
        session.otp_challenge_id = challenge_id
        return session

    def on_otp_verify(
        self,
        session: "SessionState",
        valid: bool,
        max_failed_verifies: int | None = None,
    ) -> "SessionState":
        """Process otp.verify result against current session state.

        - Permitted only in OTP_PENDING.
        - On valid=True: transitions to VERIFIED, clears active challenge,
          resets failed_verifies and otp_resends.
        - On valid=False: increments verify failures and attempts.
          If failed verifies >= N: transitions to LOCKED.
        """
        limit = (
            max_failed_verifies
            if max_failed_verifies is not None
            else self.max_failed_verifies
        )

        if session.state != VerificationState.OTP_PENDING:
            raise InvalidFSMTransitionError(
                current_state=session.state,
                action="otp.verify",
                reason="otp.verify is only allowed in OTP_PENDING state",
            )

        if valid:
            session.state = VerificationState.VERIFIED
            session.otp_challenge_id = None
            session.failed_verifies = 0
            session.otp_resends = 0
        else:
            session.attempts += 1
            session.failed_verifies += 1
            if session.failed_verifies >= limit:
                session.state = VerificationState.LOCKED

        return session

    def on_handoff_create(
        self,
        session: "SessionState",
    ) -> "SessionState":
        """Process handoff.create against current session state.

        - Permitted in all states (ANONYMOUS, IDENTIFIED, OTP_PENDING,
          VERIFIED, LOCKED, HANDED_OFF).
        - Transitions to HANDED_OFF.
        """
        session.state = VerificationState.HANDED_OFF
        return session
