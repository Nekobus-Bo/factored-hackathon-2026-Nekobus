"""Tests for tool authorization matrix and non-configurable CODE_FLOOR.

Verifies:
1. Every matrix cell (10 tools x 6 states = 60 cells) conforms to ADR-0003 Appendix A.
2. Configuration can restrict permissions.
3. Configuration can NEVER widen permissions beyond CODE_FLOOR.
"""

import pytest
from banking_core.control.authorize import Authorizer
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.session import SessionState
from contracts.envelope import ReasonCode, ToolCall, VerificationState
from contracts.tools import TOOL_CATALOG, get_effective_permitted_states

# Expected authorization matrix from ADR-0003 Appendix A
EXPECTED_MATRIX: dict[str, dict[VerificationState, bool]] = {
    "customer.match": {
        VerificationState.ANONYMOUS: True,
        VerificationState.IDENTIFIED: True,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: False,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "otp.send": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: True,
        VerificationState.OTP_PENDING: True,
        VerificationState.VERIFIED: False,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "otp.verify": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: False,
        VerificationState.OTP_PENDING: True,
        VerificationState.VERIFIED: False,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "identity.verify_document": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: True,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: False,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "card.list": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: False,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "transaction.list_recent": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: False,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "account.get_summary": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: False,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "card.block": {
        VerificationState.ANONYMOUS: False,
        VerificationState.IDENTIFIED: False,
        VerificationState.OTP_PENDING: False,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: False,
        VerificationState.HANDED_OFF: False,
    },
    "handoff.create": {
        VerificationState.ANONYMOUS: True,
        VerificationState.IDENTIFIED: True,
        VerificationState.OTP_PENDING: True,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: True,
        VerificationState.HANDED_OFF: True,
    },
    "kb.search": {
        VerificationState.ANONYMOUS: True,
        VerificationState.IDENTIFIED: True,
        VerificationState.OTP_PENDING: True,
        VerificationState.VERIFIED: True,
        VerificationState.LOCKED: True,
        VerificationState.HANDED_OFF: True,
    },
}

SAMPLE_TOOL_CALLS: dict[str, ToolCall] = {
    "customer.match": ToolCall(
        tool="customer.match",
        args={"document_type": "NATIONAL_ID", "document_number": "12345678"},
    ),
    "otp.send": ToolCall(
        tool="otp.send",
        args={},
        idempotency_key="idem_otp_send_001",
    ),
    "otp.verify": ToolCall(
        tool="otp.verify",
        args={"code": "123456"},
        idempotency_key="idem_otp_verify_001",
    ),
    "identity.verify_document": ToolCall(
        tool="identity.verify_document",
        args={
            "document_type": "NATIONAL_ID",
            "document_front_ref": "doc_front_ref_01",
        },
    ),
    "card.list": ToolCall(
        tool="card.list",
        args={},
    ),
    "transaction.list_recent": ToolCall(
        tool="transaction.list_recent",
        args={},
    ),
    "account.get_summary": ToolCall(
        tool="account.get_summary",
        args={},
    ),
    "card.block": ToolCall(
        tool="card.block",
        args={"card_ref": "card_ref_001", "reason": "LOST"},
        idempotency_key="idem_card_block_001",
    ),
    "handoff.create": ToolCall(
        tool="handoff.create",
        args={"reason": "SUSPECTED_FRAUD", "summary": "Customer needs support"},
        idempotency_key="idem_handoff_create_001",
    ),
    "kb.search": ToolCall(
        tool="kb.search",
        args={"query": "how to report lost card"},
    ),
}

ALL_TOOLS = sorted(TOOL_CATALOG.keys())
ALL_STATES = [
    VerificationState.ANONYMOUS,
    VerificationState.IDENTIFIED,
    VerificationState.OTP_PENDING,
    VerificationState.VERIFIED,
    VerificationState.LOCKED,
    VerificationState.HANDED_OFF,
]


@pytest.mark.parametrize("tool_name", ALL_TOOLS)
@pytest.mark.parametrize("state", ALL_STATES)
def test_every_matrix_cell_authorization(
    tool_name: str,
    state: VerificationState,
) -> None:
    """Verify authorization decision for every tool x state matrix cell (60 cells)."""
    expected_allowed = EXPECTED_MATRIX[tool_name][state]
    session = SessionState(session_id="test_sess", state=state)
    authorizer = Authorizer()
    tool_call = SAMPLE_TOOL_CALLS[tool_name]

    decision = authorizer.authorize(tool_call, session)

    if expected_allowed:
        assert decision.allowed is True, (
            f"Expected {tool_name} to be ALLOWED in {state.value}, but was refused"
        )
        assert decision.reason_code is None
    else:
        assert decision.allowed is False, (
            f"Expected {tool_name} to be REFUSED in {state.value}, but was allowed"
        )
        assert decision.reason_code == ReasonCode.STATE_NOT_ALLOWED


def test_code_floor_cannot_be_widened_by_config_repo() -> None:
    """Verify InMemoryControlConfigRepository rejects widening beyond CODE_FLOOR."""
    repo = InMemoryControlConfigRepository()

    # Attempt to widen card.block to include IDENTIFIED state
    illegal_states = {VerificationState.VERIFIED, VerificationState.IDENTIFIED}
    with pytest.raises(ValueError, match="cannot widen tool 'card.block'"):
        repo.set_tool_permitted_states("card.block", illegal_states)

    # Attempt to widen customer.match to include VERIFIED state
    illegal_match_states = {
        VerificationState.ANONYMOUS,
        VerificationState.IDENTIFIED,
        VerificationState.VERIFIED,
    }
    with pytest.raises(ValueError, match="cannot widen tool 'customer.match'"):
        repo.set_tool_permitted_states("customer.match", illegal_match_states)


def test_code_floor_cannot_be_widened_via_contract_helper() -> None:
    """Verify get_effective_permitted_states rejects widening beyond CODE_FLOOR."""
    with pytest.raises(ValueError, match="cannot widen tool 'card.list'"):
        get_effective_permitted_states(
            "card.list",
            configured_states={
                VerificationState.VERIFIED,
                VerificationState.ANONYMOUS,
            },
        )


def test_config_can_restrict_permitted_states() -> None:
    """Verify that configuration can narrow permissions below the code floor."""
    repo = InMemoryControlConfigRepository()

    # Restrict customer.match to ONLY ANONYMOUS (removing IDENTIFIED)
    narrowed_states = {VerificationState.ANONYMOUS}
    repo.set_tool_permitted_states("customer.match", narrowed_states)

    authorizer = Authorizer(config_repo=repo)
    tool_call = SAMPLE_TOOL_CALLS["customer.match"]

    # In ANONYMOUS: still allowed
    sess_anon = SessionState(session_id="s1", state=VerificationState.ANONYMOUS)
    assert authorizer.authorize(tool_call, sess_anon).allowed is True

    # In IDENTIFIED: now refused because config narrowed it
    sess_ident = SessionState(session_id="s2", state=VerificationState.IDENTIFIED)
    decision = authorizer.authorize(tool_call, sess_ident)
    assert decision.allowed is False
    assert decision.reason_code == ReasonCode.STATE_NOT_ALLOWED


def test_authorizer_rejects_non_toolcall() -> None:
    """Verify authorizer strictly requires ToolCall instance."""
    authorizer = Authorizer()
    session = SessionState(session_id="s1", state=VerificationState.VERIFIED)
    with pytest.raises(TypeError, match="authorize requires a contracts"):
        authorizer.authorize("card.list", session)  # type: ignore[arg-type]
