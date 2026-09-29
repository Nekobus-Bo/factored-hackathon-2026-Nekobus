"""Unit tests for VerificationFSM transitions and security rules (ADR-0003 Appendix A).

Verifies:
- ANONYMOUS -> IDENTIFIED on customer.match success (requires pinned holder)
- ANONYMOUS -> LOCKED after N failed match attempts
- IDENTIFIED -> LOCKED after N failed match attempts
- Re-match in IDENTIFIED with DIFFERENT holder replaces pinned holder,
  discards challenge, increments attempts
- Re-match with same holder keeps pinned holder and state
- IDENTIFIED -> OTP_PENDING on otp.send
- OTP_PENDING -> OTP_PENDING on otp.send (resend)
- OTP_PENDING -> LOCKED when max OTP resends exceeded
- OTP resends do NOT reset failed_verifies; resend loop ends in LOCKED
- OTP_PENDING -> VERIFIED on valid otp.verify (resets failures and resends)
- OTP_PENDING -> LOCKED after N failed otp.verify attempts
- Any state -> HANDED_OFF on handoff.create
- N is configurable and never hardcoded
- Illegal transitions raise InvalidFSMTransitionError
- matched=True with missing holder_id raises ValueError
"""

import pytest
from banking_core.control.fsm import InvalidFSMTransitionError, VerificationFSM
from banking_core.control.policy import PolicyConfig
from banking_core.control.session import SessionState
from contracts.envelope import VerificationState


def test_anonymous_to_identified_on_successful_match() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(session_id="s1", state=VerificationState.ANONYMOUS)

    fsm.on_customer_match(session, matched=True, holder_id="holder_123")

    assert session.state == VerificationState.IDENTIFIED
    assert session.pinned_holder_id == "holder_123"
    assert session.otp_challenge_id is None
    assert session.failed_matches == 0


def test_match_success_requires_holder_id() -> None:
    """ADR-0004 invariant: IDENTIFIED requires pinned holder.

    matched=True without holder_id must raise ValueError.
    """
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(session_id="s1", state=VerificationState.ANONYMOUS)

    with pytest.raises(ValueError, match="holder_id is required"):
        fsm.on_customer_match(session, matched=True, holder_id=None)

    with pytest.raises(ValueError, match="holder_id is required"):
        fsm.on_customer_match(session, matched=True, holder_id="")


def test_fsm_from_config_factory() -> None:
    """Verify FSM can be built from PolicyConfig."""
    cfg = PolicyConfig(
        rate_limit_attempts_per_session=4,
        otp_max_attempts=2,
        otp_max_resends=2,
    )
    fsm = VerificationFSM.from_config(cfg)
    assert fsm.max_failed_matches == 4
    assert fsm.max_failed_verifies == 2
    assert fsm.max_otp_resends == 2


def test_anonymous_to_locked_after_n_failed_matches() -> None:
    fsm = VerificationFSM(
        max_failed_matches=3, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(session_id="s1", state=VerificationState.ANONYMOUS)

    # 1st failure
    fsm.on_customer_match(session, matched=False)
    assert session.state == VerificationState.ANONYMOUS
    assert session.failed_matches == 1

    # 2nd failure
    fsm.on_customer_match(session, matched=False)
    assert session.state == VerificationState.ANONYMOUS
    assert session.failed_matches == 2

    # 3rd failure -> LOCKED
    fsm.on_customer_match(session, matched=False)
    assert session.state == VerificationState.LOCKED
    assert session.failed_matches == 3


def test_identified_to_locked_after_n_failed_matches() -> None:
    fsm = VerificationFSM(
        max_failed_matches=2, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.IDENTIFIED,
        pinned_holder_id="holder_123",
    )

    fsm.on_customer_match(session, matched=False)
    assert session.state == VerificationState.IDENTIFIED

    fsm.on_customer_match(session, matched=False)
    assert session.state == VerificationState.LOCKED


def test_identified_rematch_with_same_holder() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.IDENTIFIED,
        pinned_holder_id="holder_123",
        attempts=1,
    )

    fsm.on_customer_match(session, matched=True, holder_id="holder_123")
    assert session.state == VerificationState.IDENTIFIED
    assert session.pinned_holder_id == "holder_123"
    assert session.attempts == 1


def test_identified_rematch_with_different_holder_rule() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.IDENTIFIED,
        pinned_holder_id="holder_old",
        otp_challenge_id="chal_xyz",
        attempts=1,
    )

    fsm.on_customer_match(session, matched=True, holder_id="holder_new")

    assert session.state == VerificationState.IDENTIFIED
    assert session.pinned_holder_id == "holder_new"
    assert session.otp_challenge_id is None
    assert session.attempts == 2


def test_identified_to_otp_pending_on_send() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.IDENTIFIED,
        pinned_holder_id="holder_123",
    )

    fsm.on_otp_send(session, challenge_id="chal_001")
    assert session.state == VerificationState.OTP_PENDING
    assert session.otp_challenge_id == "chal_001"
    assert session.failed_verifies == 0


def test_otp_resend_increments_resends_and_locks_on_limit() -> None:
    """Verify OTP resends are counted and session locks after max resends."""
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=2
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_old",
    )

    # 1st resend
    fsm.on_otp_send(session, challenge_id="chal_new1")
    assert session.state == VerificationState.OTP_PENDING
    assert session.otp_resends == 1

    # 2nd resend -> reaches max_otp_resends=2 -> LOCKED
    fsm.on_otp_send(session, challenge_id="chal_new2")
    assert session.state == VerificationState.LOCKED
    assert session.otp_resends == 2


@pytest.mark.parametrize(
    ("state", "resends", "attempts", "would_lock"),
    [
        (VerificationState.IDENTIFIED, 0, 0, False),
        # The first send never locks, whatever the counters say.
        (VerificationState.IDENTIFIED, 5, 9, False),
        (VerificationState.OTP_PENDING, 0, 0, False),
        # max_otp_resends=3: the third resend locks, so two is the last free one.
        (VerificationState.OTP_PENDING, 1, 1, False),
        (VerificationState.OTP_PENDING, 2, 2, True),
        # max_failed_matches=5: the fifth attempt locks even with resends to spare.
        (VerificationState.OTP_PENDING, 0, 3, False),
        (VerificationState.OTP_PENDING, 0, 4, True),
    ],
)
def test_otp_send_would_lock_decides_before_delivery(
    state: VerificationState, resends: int, attempts: int, would_lock: bool
) -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=state,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_old",
        otp_resends=resends,
        attempts=attempts,
    )
    before = session.model_copy()

    assert fsm.otp_send_would_lock(session) is would_lock

    assert session == before  # a decision, not a transition


@pytest.mark.parametrize(
    ("resends", "attempts"),
    [(2, 2), (0, 4)],
)
def test_on_otp_send_agrees_with_the_decision_and_keeps_the_old_challenge(
    resends: int, attempts: int
) -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_old",
        otp_resends=resends,
        attempts=attempts,
    )
    assert fsm.otp_send_would_lock(session)

    locked = fsm.on_otp_send_limit_exceeded(session.model_copy())
    via_send = fsm.on_otp_send(session.model_copy(), challenge_id="chal_new")

    assert locked == via_send
    assert locked.state == VerificationState.LOCKED
    assert locked.otp_challenge_id == "chal_old"
    assert (locked.otp_resends, locked.attempts) == (resends + 1, attempts + 1)


def test_on_otp_send_limit_exceeded_refuses_when_the_limit_is_not_reached() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_old",
    )

    with pytest.raises(InvalidFSMTransitionError, match="limit has not been reached"):
        fsm.on_otp_send_limit_exceeded(session)

    assert session.state == VerificationState.OTP_PENDING


def test_otp_resend_probe_does_not_reset_failed_verifies() -> None:
    """Security probe: otp.send must NOT reset failed_verifies.

    A sequence of wrong codes followed by resends must still lock when limits are hit.
    """
    fsm = VerificationFSM(
        max_failed_matches=10, max_failed_verifies=3, max_otp_resends=5
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_1",
    )

    # 2 wrong codes
    fsm.on_otp_verify(session, valid=False)
    fsm.on_otp_verify(session, valid=False)
    assert session.failed_verifies == 2

    # Resend code
    fsm.on_otp_send(session, challenge_id="chal_2")
    # failed_verifies must NOT be reset to 0
    assert session.failed_verifies == 2

    # 3rd wrong code -> reaches max_failed_verifies=3 -> LOCKED
    fsm.on_otp_verify(session, valid=False)
    assert session.state == VerificationState.LOCKED
    assert session.failed_verifies == 3


def test_otp_pending_to_verified_on_valid_code() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_001",
        failed_verifies=2,
        otp_resends=1,
    )

    fsm.on_otp_verify(session, valid=True)
    assert session.state == VerificationState.VERIFIED
    assert session.otp_challenge_id is None
    assert session.failed_verifies == 0
    assert session.otp_resends == 0


def test_otp_pending_to_locked_after_n_failed_verifies() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=2, max_otp_resends=3
    )
    session = SessionState(
        session_id="s1",
        state=VerificationState.OTP_PENDING,
        pinned_holder_id="holder_123",
        otp_challenge_id="chal_001",
    )

    # 1st failure
    fsm.on_otp_verify(session, valid=False)
    assert session.state == VerificationState.OTP_PENDING
    assert session.failed_verifies == 1

    # 2nd failure -> LOCKED
    fsm.on_otp_verify(session, valid=False)
    assert session.state == VerificationState.LOCKED
    assert session.failed_verifies == 2


@pytest.mark.parametrize(
    "initial_state",
    [
        VerificationState.ANONYMOUS,
        VerificationState.IDENTIFIED,
        VerificationState.OTP_PENDING,
        VerificationState.VERIFIED,
        VerificationState.LOCKED,
        VerificationState.HANDED_OFF,
    ],
)
def test_any_state_to_handed_off_on_handoff_create(
    initial_state: VerificationState,
) -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )
    session = SessionState(session_id="s1", state=initial_state)

    fsm.on_handoff_create(session)
    assert session.state == VerificationState.HANDED_OFF


def test_illegal_fsm_transitions_raise() -> None:
    fsm = VerificationFSM(
        max_failed_matches=5, max_failed_verifies=3, max_otp_resends=3
    )

    # customer.match in VERIFIED
    sess_verified = SessionState(session_id="s1", state=VerificationState.VERIFIED)
    with pytest.raises(InvalidFSMTransitionError):
        fsm.on_customer_match(sess_verified, matched=True, holder_id="h1")

    # otp.send in ANONYMOUS
    sess_anon = SessionState(session_id="s2", state=VerificationState.ANONYMOUS)
    with pytest.raises(InvalidFSMTransitionError):
        fsm.on_otp_send(sess_anon, challenge_id="chal_1")

    # otp.verify in ANONYMOUS
    with pytest.raises(InvalidFSMTransitionError):
        fsm.on_otp_verify(sess_anon, valid=True)
