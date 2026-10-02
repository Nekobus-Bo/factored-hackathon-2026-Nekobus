"""The flow hint (ADR-0016): what banking-core allows after each call."""

from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.flow import flow_hint, with_flow
from contracts.envelope import (
    ReasonCode,
    ToolResult,
    ToolResultStatus,
    VerificationState,
)

S = VerificationState


def _refused(tool: str, reason: ReasonCode) -> ToolResult:
    return ToolResult(tool=tool, status=ToolResultStatus.REFUSED, reason_code=reason)


def test_identified_names_the_code_as_next_and_lists_what_is_allowed():
    hint = flow_hint(S.IDENTIFIED, InMemoryControlConfigRepository())
    assert hint is not None
    assert hint.next == ["otp.send"]
    assert "card.list" not in hint.allowed
    assert {"otp.send", "handoff.create", "kb.search"} <= set(hint.allowed)
    assert hint.required_states is None


def test_a_state_refusal_says_which_state_the_tool_needs():
    refusal = _refused("card.list", ReasonCode.STATE_NOT_ALLOWED)
    hint = flow_hint(S.IDENTIFIED, InMemoryControlConfigRepository(), refusal)
    assert hint is not None
    assert hint.required_states == [S.VERIFIED]
    assert hint.next == ["otp.send"]


def test_a_refused_next_step_is_not_offered_again():
    # No OTP channel: otp.send is refused, so the way forward is a human.
    refusal = _refused("otp.send", ReasonCode.POLICY_BLOCKED)
    hint = flow_hint(S.IDENTIFIED, InMemoryControlConfigRepository(), refusal)
    assert hint is not None
    assert hint.next == ["handoff.create"]
    assert hint.required_states is None


def test_each_state_points_forward_along_the_fsm():
    repo = InMemoryControlConfigRepository()
    nexts = {state: flow_hint(state, repo).next for state in S}  # type: ignore[union-attr]
    assert nexts == {
        S.ANONYMOUS: ["customer.match"],
        S.IDENTIFIED: ["otp.send"],
        S.OTP_PENDING: ["otp.verify"],
        S.VERIFIED: [],
        S.LOCKED: ["handoff.create"],
        S.HANDED_OFF: [],
    }


def test_verified_allows_the_card_tools():
    hint = flow_hint(S.VERIFIED, InMemoryControlConfigRepository())
    assert hint is not None
    assert {"card.list", "card.block", "transaction.list_recent"} <= set(hint.allowed)


def test_a_tool_disabled_by_configuration_is_not_allowed_anywhere():
    repo = InMemoryControlConfigRepository(
        tool_matrix={"account.get_summary": frozenset()}
    )
    for state in S:
        hint = flow_hint(state, repo)
        assert hint is not None and "account.get_summary" not in hint.allowed


def test_a_configuration_outage_drops_the_hint_not_the_result():
    class Broken(InMemoryControlConfigRepository):
        def get_tool_permitted_states(self, tool_name):
            raise RuntimeError("db down")

    result = ToolResult(
        tool="customer.match", status=ToolResultStatus.OK, data={"matched": True}
    )
    assert flow_hint(S.IDENTIFIED, Broken()) is None
    assert with_flow(result, S.IDENTIFIED, Broken()) == result


def test_with_flow_keeps_the_result_and_adds_the_hint():
    result = ToolResult(
        tool="customer.match", status=ToolResultStatus.OK, data={"matched": True}
    )
    out = with_flow(result, S.IDENTIFIED, InMemoryControlConfigRepository())
    assert out.data == result.data and out.status is ToolResultStatus.OK
    assert out.flow is not None and out.flow.state is S.IDENTIFIED
    # The hint survives the contract's own validation (the wire format).
    assert ToolResult.model_validate(out.model_dump(mode="json")).flow == out.flow
