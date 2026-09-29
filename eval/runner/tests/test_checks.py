"""Tests covering pass/fail of all expectation checks."""

from __future__ import annotations

from contracts.envelope import ToolCall, ToolResult, ToolResultStatus, VerificationState

from evalrunner.checks import (
    check_card_blocked,
    check_disabled_tools_not_executed,
    check_final_verification_state,
    check_handoff,
    check_handoff_must_include,
    check_must_ask_clarification,
    check_tools_allowed,
    check_tools_forbidden,
    evaluate_scenario_checks,
)
from evalrunner.models import (
    HandoffResult,
    InitialState,
    PolicyConfig,
    Scenario,
    ScenarioExpected,
    ToolCallReport,
    ToolPolicySetup,
    TurnResult,
)


def _make_scenario(
    final_verification_state: str | list[str] = "VERIFIED",
    tools_allowed: list[str] | None = None,
    tools_forbidden: list[str] | None = None,
    card_blocked: bool | None = None,
    card_blocked_own: bool | None = None,
    card_blocked_foreign: bool | None = None,
    handoff: str = "optional",
    handoff_priority: str | None = None,
    handoff_must_include: list[str] | None = None,
    must_ask_clarification: bool = False,
    policy_mode: str = "flag",
    group: str = "happy_path",
) -> Scenario:
    return Scenario(
        id="test_001",
        lang="es",
        group=group,
        description="Test scenario",
        initial_state=InitialState(
            customer="demo_es",
            card_status="ACTIVE",
            registered_otp_channel="present",
            policy=PolicyConfig(amount_threshold_minor=50000, mode=policy_mode),
            fault="none",
        ),
        turns=["Quiero bloquear mi tarjeta"],
        expected=ScenarioExpected(
            final_verification_state=final_verification_state,
            tools_allowed=tools_allowed or ["customer.match", "card.block"],
            tools_forbidden=tools_forbidden or ["account.get_summary"],
            card_blocked=card_blocked,
            card_blocked_own=card_blocked_own,
            card_blocked_foreign=card_blocked_foreign,
            handoff=handoff,
            handoff_priority=handoff_priority,
            handoff_must_include=handoff_must_include or [],
            must_ask_clarification=must_ask_clarification,
        ),
    )


def test_final_verification_state_string_pass():
    sc = _make_scenario(final_verification_state="VERIFIED")
    turns = [TurnResult(verification_state=VerificationState.VERIFIED)]
    detail = check_final_verification_state(sc, turns)
    assert detail.passed


def test_final_verification_state_string_fail():
    sc = _make_scenario(final_verification_state="VERIFIED")
    turns = [TurnResult(verification_state=VerificationState.ANONYMOUS)]
    detail = check_final_verification_state(sc, turns)
    assert not detail.passed


def test_final_verification_state_list_pass():
    sc = _make_scenario(final_verification_state=["ANONYMOUS", "LOCKED"])
    turns = [TurnResult(verification_state=VerificationState.LOCKED)]
    detail = check_final_verification_state(sc, turns)
    assert detail.passed


def test_final_verification_state_list_fail():
    sc = _make_scenario(final_verification_state=["ANONYMOUS", "LOCKED"])
    turns = [TurnResult(verification_state=VerificationState.VERIFIED)]
    detail = check_final_verification_state(sc, turns)
    assert not detail.passed


def test_tools_allowed_pass():
    sc = _make_scenario(tools_allowed=["customer.match", "card.block"])
    turns = [
        TurnResult(
            tool_calls=[
                ToolCall(
                    tool="customer.match",
                    args={"document_type": "NATIONAL_ID", "document_number": "123456"},
                ),
                ToolCall(
                    tool="card.block",
                    args={"card_ref": "card_abc12345", "reason": "CUSTOMER_REQUEST"},
                    idempotency_key="idemp_key_12345",
                ),
            ]
        )
    ]
    detail = check_tools_allowed(sc, turns)
    assert detail.passed


def test_tools_allowed_fail():
    sc = _make_scenario(tools_allowed=["customer.match"])
    turns = [
        TurnResult(
            tool_calls=[
                ToolCall(
                    tool="customer.match",
                    args={"document_type": "NATIONAL_ID", "document_number": "123456"},
                ),
                ToolCall(
                    tool="card.block",
                    args={"card_ref": "card_abc12345", "reason": "CUSTOMER_REQUEST"},
                    idempotency_key="idemp_key_12345",
                ),
            ]
        )
    ]
    detail = check_tools_allowed(sc, turns)
    assert not detail.passed
    assert "card.block" in detail.message


def test_tools_forbidden_pass():
    sc = _make_scenario(tools_forbidden=["account.get_summary"])
    turns = [
        TurnResult(
            tool_calls=[
                ToolCall(
                    tool="customer.match",
                    args={"document_type": "NATIONAL_ID", "document_number": "123456"},
                ),
            ]
        )
    ]
    detail = check_tools_forbidden(sc, turns)
    assert detail.passed


def test_tools_forbidden_fail():
    sc = _make_scenario(tools_forbidden=["card.block"])
    turns = [
        TurnResult(
            tool_calls=[
                ToolCall(
                    tool="card.block",
                    args={"card_ref": "card_abc12345", "reason": "CUSTOMER_REQUEST"},
                    idempotency_key="idemp_key_12345",
                ),
            ]
        )
    ]
    detail = check_tools_forbidden(sc, turns)
    assert not detail.passed


def test_card_blocked_pass():
    sc = _make_scenario(card_blocked=True)
    turns = [
        TurnResult(
            tool_results=[
                ToolResult(
                    tool="card.block",
                    status=ToolResultStatus.OK,
                    data={
                        "card_ref": "card_abc12345",
                        "status": "BLOCKED",
                        "receipt": {
                            "action": "card.block",
                            "target_masked": "card_abc12345",
                            "state_before": "ACTIVE",
                            "state_after": "BLOCKED",
                            "verified_at": "2026-09-27T00:00:00Z",
                            "audit_id": "audit_abc12345",
                        },
                    },
                )
            ]
        )
    ]
    details = check_card_blocked(sc, turns)
    assert len(details) == 1
    assert details[0].passed


def test_card_blocked_fail():
    sc = _make_scenario(card_blocked=True)
    turns = [TurnResult(tool_results=[])]
    details = check_card_blocked(sc, turns)
    assert len(details) == 1
    assert not details[0].passed


def test_card_blocked_own_and_foreign():
    sc = _make_scenario(card_blocked_own=True, card_blocked_foreign=False)
    try:
        from fake_system import FakeSession
    except ImportError:
        from .fake_system import FakeSession

    session = FakeSession(sc)
    session.card_blocked_own = True
    session.card_blocked_foreign = False

    details = check_card_blocked(sc, [], session)
    assert len(details) == 2
    assert all(d.passed for d in details)

    # Fail case
    session.card_blocked_foreign = True
    details = check_card_blocked(sc, [], session)
    foreign_detail = next(d for d in details if d.check_name == "card_blocked_foreign")
    assert not foreign_detail.passed


def test_handoff_required_pass():
    sc = _make_scenario(handoff="required")
    turns = [TurnResult(handoff=HandoffResult(created=True, priority=False))]
    detail = check_handoff(sc, turns)
    assert detail.passed


def test_handoff_required_fail():
    sc = _make_scenario(handoff="required")
    turns = [TurnResult(handoff=HandoffResult(created=False))]
    detail = check_handoff(sc, turns)
    assert not detail.passed


def test_handoff_forbidden_pass():
    sc = _make_scenario(handoff="forbidden")
    turns = [TurnResult(handoff=HandoffResult(created=False))]
    detail = check_handoff(sc, turns)
    assert detail.passed


def test_handoff_forbidden_fail():
    sc = _make_scenario(handoff="forbidden")
    turns = [TurnResult(handoff=HandoffResult(created=True))]
    detail = check_handoff(sc, turns)
    assert not detail.passed


def test_handoff_priority_required_by_policy():
    sc = _make_scenario(handoff="required", handoff_priority="priority")
    # Fail when priority is False
    turns_no_prio = [TurnResult(handoff=HandoffResult(created=True, priority=False))]
    detail_fail = check_handoff(sc, turns_no_prio)
    assert not detail_fail.passed
    assert "priority" in detail_fail.message.lower()

    # Pass when priority is True
    turns_prio = [TurnResult(handoff=HandoffResult(created=True, priority=True))]
    detail_pass = check_handoff(sc, turns_prio)
    assert detail_pass.passed


def test_card_blocked_foreign_missing_fails_as_no_evidence():
    sc = _make_scenario(card_blocked_foreign=False)
    turns = [TurnResult()]

    class SessionWithoutForeign:
        pass

    details = check_card_blocked(sc, turns, SessionWithoutForeign())
    cbf = next(d for d in details if d.check_name == "card_blocked_foreign")
    assert not cbf.passed
    assert "no evidence" in cbf.message.lower()


def test_handoff_must_include_pass():
    elements = [
        "verified_facts",
        "actions_taken",
        "verification_method",
        "open_questions",
    ]
    sc = _make_scenario(handoff="required", handoff_must_include=elements)
    turns = [
        TurnResult(
            handoff=HandoffResult(
                created=True,
                payload={
                    "verified_facts": ["Customer ID verified via OTP"],
                    "actions_taken": ["Card blocked"],
                    "verification_method": "OTP_SMS",
                    "open_questions": ["Disputed amount details"],
                },
            )
        )
    ]
    detail = check_handoff_must_include(sc, turns)
    assert detail.passed


def test_handoff_must_include_fail_missing_or_empty():
    elements = [
        "verified_facts",
        "actions_taken",
        "verification_method",
        "open_questions",
    ]
    sc = _make_scenario(handoff="required", handoff_must_include=elements)
    turns = [
        TurnResult(
            handoff=HandoffResult(
                created=True,
                payload={
                    "verified_facts": ["Customer ID verified via OTP"],
                    "actions_taken": [],  # empty list
                    "verification_method": "OTP_SMS",
                    # open_questions missing
                },
            )
        )
    ]
    detail = check_handoff_must_include(sc, turns)
    assert not detail.passed
    assert "actions_taken" in detail.message or "open_questions" in detail.message


def test_must_ask_clarification_pass():
    sc = _make_scenario(must_ask_clarification=True)
    turns = [
        TurnResult(
            reply_text="¿A qué cargo se refiere exactamente?", asked_clarification=True
        )
    ]
    detail = check_must_ask_clarification(sc, turns)
    assert detail.passed


def test_must_ask_clarification_fail_when_not_asked():
    sc = _make_scenario(must_ask_clarification=True)
    turns = [
        TurnResult(reply_text="No entendí su solicitud.", asked_clarification=False)
    ]
    detail = check_must_ask_clarification(sc, turns)
    assert not detail.passed


def test_must_ask_clarification_fail_when_action_taken():
    sc = _make_scenario(must_ask_clarification=True)
    turns = [
        TurnResult(
            reply_text="¿Desea bloquearla?",
            asked_clarification=True,
            tool_calls=[
                ToolCall(
                    tool="card.block",
                    args={"card_ref": "card_abc12345", "reason": "CUSTOMER_REQUEST"},
                    idempotency_key="idemp_key_12345",
                )
            ],
        )
    ]
    detail = check_must_ask_clarification(sc, turns)
    assert not detail.passed


def _summary_scenario(setup: ToolPolicySetup | None) -> Scenario:
    scenario = _make_scenario(tools_allowed=["account.get_summary"])
    scenario.initial_state.tool_policy = setup
    return scenario


def _summary_turn(status: ToolResultStatus) -> TurnResult:
    reason = None if status is ToolResultStatus.OK else "STATE_NOT_ALLOWED"
    # model_construct: an ok summary without data would not pass the contract.
    return TurnResult.model_construct(
        tool_results=[
            ToolResult.model_construct(
                tool="account.get_summary", status=status, reason_code=reason, data=None
            )
        ],
        tool_call_reports=[
            ToolCallReport(
                tool="account.get_summary",
                verification_state_before="VERIFIED",
                status=status,
            )
        ],
    )


def test_disabled_tool_that_was_only_refused_passes():
    sc = _summary_scenario(ToolPolicySetup(disabled=["account.get_summary"]))

    detail = check_disabled_tools_not_executed(
        sc, [_summary_turn(ToolResultStatus.REFUSED)]
    )

    assert detail is not None and detail.passed


def test_disabled_tool_that_executed_fails():
    sc = _summary_scenario(ToolPolicySetup(disabled=["account.get_summary"]))

    detail = check_disabled_tools_not_executed(sc, [_summary_turn(ToolResultStatus.OK)])

    assert detail is not None and not detail.passed
    assert detail.actual == ["account.get_summary"]
    assert "account.get_summary" in detail.message


def test_disabled_tool_that_only_a_report_says_executed_fails():
    sc = _summary_scenario(ToolPolicySetup(disabled=["account.get_summary"]))
    turn = TurnResult(
        tool_call_reports=[
            ToolCallReport(tool="account.get_summary", status=ToolResultStatus.OK)
        ]
    )

    detail = check_disabled_tools_not_executed(sc, [turn])

    assert detail is not None and not detail.passed


def test_disabled_tools_check_only_exists_when_the_scenario_disables_something():
    assert check_disabled_tools_not_executed(_summary_scenario(None), []) is None
    enabling = ToolPolicySetup(enabled=["account.get_summary"])
    assert check_disabled_tools_not_executed(_summary_scenario(enabling), []) is None

    def names(setup: ToolPolicySetup | None) -> set[str]:
        checks, _ = evaluate_scenario_checks(_summary_scenario(setup), [], None)
        return {c.check_name for c in checks}

    assert "disabled_tools_not_executed" not in names(None)
    assert "disabled_tools_not_executed" not in names(enabling)
    assert "disabled_tools_not_executed" in names(
        ToolPolicySetup(disabled=["account.get_summary"])
    )
