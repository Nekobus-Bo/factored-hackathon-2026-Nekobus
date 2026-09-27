"""Unit tests for PolicyEngine, Decision models, and risk rules (ADR-0002).

Verifies lead's exact policy-mode semantics:
- For card.block the threshold rule ALWAYS returns allowed=True
  (other rules: FSM state, code floor, rate limits on verification tools apply).
- thresholds_minor: dict[ISO currency, int] in PolicyConfig seeded from env.
- amount <= threshold(currency) -> allowed, no flags.
- above threshold, mode flag -> allowed + [POLICY_FLAGGED, HANDOFF_RECOMMENDED].
- above threshold, mode block -> allowed +
  [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
- unknown currency, or malformed/missing/negative amount ->
  treated as above threshold in block semantics:
  allowed + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
- Rate limiting per session applies ONLY to verification tools.
- handoff.create and kb.search are NEVER rate-limited.
- Authorizer integration with policy rules and FSM state enforcement.
"""

import os
from unittest.mock import patch

import pytest
from banking_core.control.authorize import Authorizer
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.policy import Decision, PolicyConfig, PolicyEngine
from banking_core.control.session import SessionState
from contracts.envelope import ReasonCode, ToolCall, VerificationState


def test_decision_model() -> None:
    decision_ok = Decision(allowed=True)
    assert decision_ok.allowed is True
    assert decision_ok.reason_code is None
    assert decision_ok.flags == []
    assert not decision_ok.is_flagged
    assert not decision_ok.requires_handoff
    assert not decision_ok.recommends_handoff
    assert not decision_ok.is_priority

    decision_flagged = Decision(
        allowed=True,
        reason_code=ReasonCode.POLICY_FLAGGED,
        flags=["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"],
    )
    assert decision_flagged.is_flagged
    assert decision_flagged.recommends_handoff
    assert not decision_flagged.requires_handoff
    assert not decision_flagged.is_priority

    decision_priority = Decision(
        allowed=True,
        reason_code=ReasonCode.POLICY_FLAGGED,
        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
    )
    assert decision_priority.is_flagged
    assert decision_priority.requires_handoff
    assert decision_priority.is_priority
    assert not decision_priority.recommends_handoff


def test_policy_config_validation() -> None:
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000, "COP": 20000000, "BRL": 25000},
        currency="USD",
        amount_mode="block",
        rate_limit_attempts_per_session=10,
        otp_max_resends=4,
    )
    assert cfg.thresholds_minor["USD"] == 5000
    assert cfg.thresholds_minor["COP"] == 20000000
    assert cfg.thresholds_minor["BRL"] == 25000
    assert cfg.amount_threshold_minor == 5000
    assert cfg.currency == "USD"
    assert cfg.amount_mode == "block"
    assert cfg.rate_limit_attempts_per_session == 10
    assert cfg.otp_max_resends == 4

    with pytest.raises(ValueError, match="Invalid amount_mode"):
        PolicyConfig(amount_mode="invalid_mode")  # type: ignore[arg-type]


def test_policy_config_from_env() -> None:
    env_vars = {
        "POLICY_SEED_THRESHOLDS_MINOR": '{"USD": 7500, "COP": 30000000}',
        "POLICY_SEED_THRESHOLD_MINOR_BRL": "40000",
        "POLICY_SEED_AMOUNT_MODE": "block",
        "DEFAULT_CURRENCY": "USD",
        "RATE_LIMIT_ATTEMPTS_PER_SESSION": "8",
        "OTP_MAX_ATTEMPTS": "4",
        "OTP_MAX_RESENDS": "4",
        "OTP_TTL_SECONDS": "600",
        "SESSION_TTL_SECONDS": "7200",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        cfg = PolicyConfig.from_env()
        assert cfg.thresholds_minor["USD"] == 7500
        assert cfg.thresholds_minor["COP"] == 30000000
        assert cfg.thresholds_minor["BRL"] == 40000
        assert cfg.amount_threshold_minor == 7500
        assert cfg.currency == "USD"
        assert cfg.amount_mode == "block"
        assert cfg.rate_limit_attempts_per_session == 8
        assert cfg.otp_max_attempts == 4
        assert cfg.otp_max_resends == 4
        assert cfg.otp_ttl_seconds == 600
        assert cfg.session_ttl_seconds == 7200


def test_policy_config_seed_defaults() -> None:
    """Verify seed default thresholds align with KB ~500 currency unit equivalents."""
    from banking_core.control.policy import DEFAULT_THRESHOLDS_MINOR

    assert DEFAULT_THRESHOLDS_MINOR["USD"] == 50000
    assert DEFAULT_THRESHOLDS_MINOR["EUR"] == 50000
    assert DEFAULT_THRESHOLDS_MINOR["BRL"] == 250000
    assert DEFAULT_THRESHOLDS_MINOR["COP"] == 200000000

    with patch.dict(os.environ, {}, clear=True):
        cfg = PolicyConfig.from_env()
        assert cfg.thresholds_minor["USD"] == 50000
        assert cfg.thresholds_minor["EUR"] == 50000
        assert cfg.thresholds_minor["BRL"] == 250000
        assert cfg.thresholds_minor["COP"] == 200000000
        assert cfg.currency == "COP"
        assert cfg.amount_threshold_minor == 200000000


def test_policy_config_from_env_malformed_json_raises_loudly() -> None:
    """from_env must fail loudly on malformed JSON, never silently fallback."""
    with patch.dict(
        os.environ,
        {"POLICY_SEED_THRESHOLDS_MINOR": '{"USD": 50000,'},
        clear=False,
    ):
        with pytest.raises(
            ValueError, match="Malformed JSON in POLICY_SEED_THRESHOLDS_MINOR"
        ):
            PolicyConfig.from_env()


def test_policy_config_from_env_non_dict_json_raises_loudly() -> None:
    """from_env must fail loudly if JSON is not an object."""
    with patch.dict(
        os.environ,
        {"POLICY_SEED_THRESHOLDS_MINOR": "[50000, 25000]"},
        clear=False,
    ):
        with pytest.raises(ValueError, match="must be a JSON object"):
            PolicyConfig.from_env()


def test_policy_config_from_env_non_integer_value_raises_loudly() -> None:
    """from_env must fail loudly if any threshold value is non-integer."""
    with patch.dict(
        os.environ,
        {"POLICY_SEED_THRESHOLDS_MINOR": '{"USD": "not-an-int"}'},
        clear=False,
    ):
        with pytest.raises(
            ValueError, match="Non-integer threshold value for currency 'USD'"
        ):
            PolicyConfig.from_env()


def test_policy_config_from_env_invalid_individual_threshold_raises_loudly() -> None:
    """from_env must fail loudly if individual currency threshold is not an int."""
    with patch.dict(
        os.environ,
        {"POLICY_SEED_THRESHOLD_MINOR_USD": "not-an-integer"},
        clear=False,
    ):
        with pytest.raises(
            ValueError,
            match="Invalid integer value for POLICY_SEED_THRESHOLD_MINOR_USD",
        ):
            PolicyConfig.from_env()


def test_policy_card_block_amount_rule_applies_regardless_of_reason() -> None:
    """The amount rule applies whenever amount context is present, regardless of reason.

    Model cannot dodge handoff by tagging a dispute as LOST.
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 50000},
        currency="USD",
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    # reason="LOST" but amount > threshold (60,000 > 50,000)
    # Mode "flag" -> allowed=True + [POLICY_FLAGGED, HANDOFF_RECOMMENDED]
    dec_lost_above = engine.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "LOST", "disputed_amount_minor": 60000, "currency": "USD"},
    )
    assert dec_lost_above.allowed is True
    assert dec_lost_above.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_lost_above.flags == ["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"]
    assert dec_lost_above.recommends_handoff is True

    # Mode "block" -> allowed=True + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY]
    cfg_block = PolicyConfig(
        thresholds_minor={"USD": 50000},
        currency="USD",
        amount_mode="block",
    )
    engine_block = PolicyEngine(config=cfg_block)
    dec_lost_block = engine_block.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "LOST", "disputed_amount_minor": 60000, "currency": "USD"},
    )
    assert dec_lost_block.allowed is True
    assert dec_lost_block.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_lost_block.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    assert dec_lost_block.requires_handoff is True
    assert dec_lost_block.is_priority is True

    # reason="LOST" with amount <= threshold (40,000 <= 50,000) -> allowed, no flags
    dec_lost_below = engine.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "LOST", "disputed_amount_minor": 40000, "currency": "USD"},
    )
    assert dec_lost_below.allowed is True
    assert dec_lost_below.reason_code is None
    assert dec_lost_below.flags == []


def test_policy_card_block_missing_amount_semantics() -> None:
    """Missing amount context preserves existing dispute/non-dispute semantics."""
    cfg = PolicyConfig(
        thresholds_minor={"USD": 50000},
        currency="USD",
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    # 1. Non-dispute reason without amount and without currency: no flags
    dec_lost_no_amount = engine.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "LOST"},
    )
    assert dec_lost_no_amount.allowed is True
    assert dec_lost_no_amount.reason_code is None
    assert dec_lost_no_amount.flags == []

    # 2. Dispute reason without amount: treated as above threshold in block semantics
    dec_dispute_no_amount = engine.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "UNRECOGNIZED_CHARGE"},
    )
    assert dec_dispute_no_amount.allowed is True
    assert dec_dispute_no_amount.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_dispute_no_amount.flags == [
        "POLICY_FLAGGED",
        "HANDOFF_REQUIRED",
        "PRIORITY",
    ]
    assert dec_dispute_no_amount.requires_handoff is True

    # 3. Non-dispute without amount but explicit currency: treated as above threshold
    dec_lost_with_curr = engine.evaluate(
        tool="card.block",
        session=session,
        context={"reason": "LOST", "currency": "USD"},
    )
    assert dec_lost_with_curr.allowed is True
    assert dec_lost_with_curr.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_lost_with_curr.flags == [
        "POLICY_FLAGGED",
        "HANDOFF_REQUIRED",
        "PRIORITY",
    ]


def test_policy_card_block_amount_le_threshold() -> None:
    """amount <= threshold(currency) -> allowed, no flags."""
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000},
        currency="USD",
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec_under = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 4000, "currency": "USD"},
    )
    assert dec_under.allowed is True
    assert dec_under.reason_code is None
    assert dec_under.flags == []
    assert not dec_under.is_flagged

    # Exact threshold equality
    dec_equal = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 5000, "currency": "USD"},
    )
    assert dec_equal.allowed is True
    assert dec_equal.reason_code is None
    assert dec_equal.flags == []


def test_policy_card_block_above_threshold_flag_mode() -> None:
    """above threshold, mode flag -> allowed + [POLICY_FLAGGED, HANDOFF_RECOMMENDED]."""
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000},
        currency="USD",
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 10000, "currency": "USD"},
    )
    assert dec.allowed is True
    assert dec.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec.flags == ["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"]
    assert dec.is_flagged is True
    assert dec.recommends_handoff is True
    assert dec.requires_handoff is False
    assert dec.is_priority is False


def test_policy_card_block_above_threshold_block_mode() -> None:
    """above threshold, mode block -> allowed + [FLAGGED, REQUIRED, PRIORITY].

    Notice: card.block is NEVER refused by amount, but requires priority handoff.
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000},
        currency="USD",
        amount_mode="block",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 15000, "currency": "USD"},
    )
    assert dec.allowed is True
    assert dec.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    assert dec.is_flagged is True
    assert dec.requires_handoff is True
    assert dec.is_priority is True


def test_policy_card_block_unknown_currency() -> None:
    """unknown currency -> treated as above threshold in block semantics:

    allowed + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000, "COP": 20000000},
        # Even in flag mode, unknown currency triggers block semantics
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec_unknown = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 1000, "currency": "JPY"},
    )
    assert dec_unknown.allowed is True
    assert dec_unknown.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_unknown.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    assert dec_unknown.requires_handoff is True
    assert dec_unknown.is_priority is True


def test_policy_card_block_malformed_amount() -> None:
    """malformed amount -> treated as above threshold in block semantics:

    allowed + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000}, currency="USD", amount_mode="flag"
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec_malformed = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": "not-a-number", "currency": "USD"},
    )
    assert dec_malformed.allowed is True
    assert dec_malformed.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_malformed.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    assert dec_malformed.requires_handoff is True
    assert dec_malformed.is_priority is True


def test_policy_card_block_missing_amount() -> None:
    """missing amount -> treated as above threshold in block semantics:

    allowed + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000}, currency="USD", amount_mode="flag"
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    # 1. Key present but None
    dec_none = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": None, "currency": "USD"},
    )
    assert dec_none.allowed is True
    assert dec_none.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_none.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]

    # 2. Key entirely missing
    dec_empty = engine.evaluate(
        tool="card.block",
        session=session,
        context={"currency": "USD"},
    )
    assert dec_empty.allowed is True
    assert dec_empty.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_empty.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]


def test_policy_card_block_negative_amount() -> None:
    """negative amount -> treated as above threshold in block semantics:

    allowed + [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
    """
    cfg = PolicyConfig(
        thresholds_minor={"USD": 5000}, currency="USD", amount_mode="flag"
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    dec_neg = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": -500, "currency": "USD"},
    )
    assert dec_neg.allowed is True
    assert dec_neg.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_neg.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]


def test_policy_card_block_multi_currency() -> None:
    """Multi-currency thresholds: USD vs BRL vs COP thresholds."""
    cfg = PolicyConfig(
        thresholds_minor={"COP": 20000000, "USD": 5000, "BRL": 25000},
        amount_mode="flag",
    )
    engine = PolicyEngine(config=cfg)
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)

    # 15,000 USD > 5,000 USD -> flagged
    dec_usd = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 15000, "currency": "USD"},
    )
    assert dec_usd.allowed is True
    assert dec_usd.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_usd.flags == ["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"]

    # 15,000 BRL <= 25,000 BRL -> allowed, no flags
    dec_brl = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 15000, "currency": "BRL"},
    )
    assert dec_brl.allowed is True
    assert dec_brl.reason_code is None
    assert dec_brl.flags == []

    # 10,000,000 COP <= 20,000,000 COP -> allowed, no flags
    dec_cop = engine.evaluate(
        tool="card.block",
        session=session,
        context={"disputed_amount_minor": 10000000, "currency": "COP"},
    )
    assert dec_cop.allowed is True
    assert dec_cop.reason_code is None
    assert dec_cop.flags == []


def test_policy_rate_limit_applies_only_to_verification_tools() -> None:
    """Rate limit per session applies ONLY to verification tools.

    handoff.create and kb.search must NEVER be rate-limited.
    """
    cfg = PolicyConfig(rate_limit_attempts_per_session=5)
    engine = PolicyEngine(config=cfg)

    # Session at or above limit (5 attempts)
    sess_limited = SessionState(
        session_id="s1",
        state=VerificationState.IDENTIFIED,
        attempts=5,
    )

    # Verification tools are rate-limited
    for v_tool in (
        "customer.match",
        "otp.send",
        "otp.verify",
        "identity.verify_document",
    ):
        dec = engine.evaluate(v_tool, sess_limited)
        assert dec.allowed is False, f"Expected {v_tool} to be rate-limited"
        assert dec.reason_code == ReasonCode.RATE_LIMITED

    # handoff.create and kb.search are NEVER rate-limited
    dec_handoff = engine.evaluate("handoff.create", sess_limited)
    assert dec_handoff.allowed is True
    assert dec_handoff.reason_code is None

    dec_kb = engine.evaluate("kb.search", sess_limited)
    assert dec_kb.allowed is True
    assert dec_kb.reason_code is None


def test_locked_and_rate_limited_session_can_reach_handoff() -> None:
    """A locked customer with 10 attempts can still reach handoff and search KB."""
    repo = InMemoryControlConfigRepository(
        policy_config=PolicyConfig(rate_limit_attempts_per_session=5)
    )
    authorizer = Authorizer(config_repo=repo)

    sess_locked = SessionState(
        session_id="s_locked",
        state=VerificationState.LOCKED,
        attempts=10,
    )

    handoff_call = ToolCall(
        tool="handoff.create",
        args={
            "reason": "CUSTOMER_LOCKED",
            "summary": "Customer locked out after failures",
        },
        idempotency_key="idem_handoff_locked_01",
    )
    dec_handoff = authorizer.authorize(handoff_call, sess_locked)
    assert dec_handoff.allowed is True
    assert dec_handoff.reason_code is None

    kb_call = ToolCall(
        tool="kb.search",
        args={"query": "how to unlock account"},
    )
    dec_kb = authorizer.authorize(kb_call, sess_locked)
    assert dec_kb.allowed is True
    assert dec_kb.reason_code is None


def test_authorizer_integrates_card_block_semantics() -> None:
    """Authorizer allows card.block when VERIFIED, propagating flags.

    When state is not VERIFIED, FSM / code floor still rejects card.block.
    """
    repo_block = InMemoryControlConfigRepository(
        policy_config=PolicyConfig(
            thresholds_minor={"USD": 5000},
            currency="USD",
            amount_mode="block",
        )
    )
    authorizer_block = Authorizer(config_repo=repo_block)

    tool_call = ToolCall(
        tool="card.block",
        args={"card_ref": "card_test_123", "reason": "UNRECOGNIZED_CHARGE"},
        idempotency_key="idem_key_xyz123",
    )

    # 1. VERIFIED session with amount exceeding threshold in block mode:
    # allowed=True, ReasonCode.POLICY_FLAGGED, PRIORITY handoff required!
    sess_verified = SessionState(session_id="s1", state=VerificationState.VERIFIED)
    dec_blocked = authorizer_block.authorize(
        tool_call,
        sess_verified,
        context={"disputed_amount_minor": 25000, "currency": "USD"},
    )
    assert dec_blocked.allowed is True
    assert dec_blocked.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_blocked.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    assert dec_blocked.requires_handoff is True
    assert dec_blocked.is_priority is True

    # 2. VERIFIED session with amount exceeding threshold in flag mode:
    # allowed=True, ReasonCode.POLICY_FLAGGED, HANDOFF_RECOMMENDED!
    repo_flag = InMemoryControlConfigRepository(
        policy_config=PolicyConfig(
            thresholds_minor={"USD": 5000},
            currency="USD",
            amount_mode="flag",
        )
    )
    authorizer_flag = Authorizer(config_repo=repo_flag)
    dec_flagged = authorizer_flag.authorize(
        tool_call,
        sess_verified,
        context={"disputed_amount_minor": 25000, "currency": "USD"},
    )
    assert dec_flagged.allowed is True
    assert dec_flagged.reason_code == ReasonCode.POLICY_FLAGGED
    assert dec_flagged.flags == ["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"]
    assert dec_flagged.recommends_handoff is True

    # 3. IDENTIFIED session:
    # FSM state / code floor blocks card.block (STATE_NOT_ALLOWED), regardless of amount
    sess_identified = SessionState(session_id="s2", state=VerificationState.IDENTIFIED)
    dec_not_verified = authorizer_block.authorize(
        tool_call,
        sess_identified,
        context={"disputed_amount_minor": 1000, "currency": "USD"},
    )
    assert dec_not_verified.allowed is False
    assert dec_not_verified.reason_code == ReasonCode.STATE_NOT_ALLOWED
