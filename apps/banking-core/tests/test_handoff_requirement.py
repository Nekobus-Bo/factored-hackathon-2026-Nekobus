"""From a card.block policy decision to the handoff requirement (ADR-0003 amendment)."""

import pytest
from banking_core.control.policy import Decision
from banking_core.handoff.requirement import requirement_for, stronger
from banking_core.handoff.tools import resolve_priority
from contracts.envelope import ReasonCode, VerificationState
from contracts.tools.card_block import BlockReason
from contracts.tools.handoff_create import (
    Department,
    HandoffPriority,
    HandoffReason,
    HandoffRequirement,
    HandoffRequirementLevel,
)

NONE = Decision(allowed=True)
RECOMMENDED = Decision(
    allowed=True,
    reason_code=ReasonCode.POLICY_FLAGGED,
    flags=["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"],
)
REQUIRED = Decision(
    allowed=True,
    reason_code=ReasonCode.POLICY_FLAGGED,
    flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
)


def _requirement(
    level: HandoffRequirementLevel, priority: HandoffPriority
) -> HandoffRequirement:
    return HandoffRequirement(
        level=level,
        priority=priority,
        department=Department.DISPUTES,
        reason=HandoffReason.UNRECOGNIZED_TRANSACTION,
    )


@pytest.mark.parametrize("reason", list(BlockReason))
def test_a_decision_without_flags_requires_nothing(reason: BlockReason) -> None:
    assert requirement_for(NONE, reason) == HandoffRequirement()


@pytest.mark.parametrize("reason", list(BlockReason))
def test_a_recommended_handoff_is_normal_priority(reason: BlockReason) -> None:
    requirement = requirement_for(RECOMMENDED, reason)

    assert requirement.level is HandoffRequirementLevel.RECOMMENDED
    assert requirement.priority is HandoffPriority.NORMAL


@pytest.mark.parametrize("reason", list(BlockReason))
def test_a_required_handoff_is_urgent(reason: BlockReason) -> None:
    requirement = requirement_for(REQUIRED, reason)

    assert requirement.level is HandoffRequirementLevel.REQUIRED
    assert requirement.priority is HandoffPriority.URGENT


def test_required_without_the_priority_flag_is_high() -> None:
    decision = Decision(
        allowed=True,
        reason_code=ReasonCode.POLICY_FLAGGED,
        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED"],
    )

    assert requirement_for(decision, BlockReason.LOST).priority is HandoffPriority.HIGH


@pytest.mark.parametrize("decision", [RECOMMENDED, REQUIRED])
def test_the_priority_is_what_handoff_create_maps_the_flags_to(
    decision: Decision,
) -> None:
    expected = resolve_priority(
        HandoffPriority.NORMAL, decision, VerificationState.VERIFIED
    )

    assert requirement_for(decision, BlockReason.LOST).priority is expected


@pytest.mark.parametrize(
    ("reason", "handoff_reason", "department"),
    [
        (
            BlockReason.UNRECOGNIZED_CHARGE,
            HandoffReason.UNRECOGNIZED_TRANSACTION,
            Department.DISPUTES,
        ),
        (
            BlockReason.SUSPICIOUS_ACTIVITY,
            HandoffReason.SUSPECTED_FRAUD,
            Department.FRAUD_OPERATIONS,
        ),
        (
            BlockReason.LOST,
            HandoffReason.SUSPECTED_FRAUD,
            Department.FRAUD_OPERATIONS,
        ),
        (
            BlockReason.STOLEN,
            HandoffReason.SUSPECTED_FRAUD,
            Department.FRAUD_OPERATIONS,
        ),
        (
            BlockReason.CUSTOMER_REQUEST,
            HandoffReason.DISPUTE_CLAIM,
            Department.DISPUTES,
        ),
    ],
)
def test_reason_and_department_follow_the_block_reason(
    reason: BlockReason, handoff_reason: HandoffReason, department: Department
) -> None:
    for decision in (RECOMMENDED, REQUIRED):
        requirement = requirement_for(decision, reason)
        assert requirement.reason is handoff_reason
        assert requirement.department is department


def test_every_block_reason_has_a_route() -> None:
    for reason in BlockReason:
        assert requirement_for(REQUIRED, reason).level is (
            HandoffRequirementLevel.REQUIRED
        )


# stronger(): what a session remembers


def test_none_remembers_nothing_new() -> None:
    kept = _requirement(HandoffRequirementLevel.RECOMMENDED, HandoffPriority.NORMAL)

    assert stronger(None, HandoffRequirement()) is None
    assert stronger(kept, HandoffRequirement()) == kept


def test_the_first_requirement_is_remembered() -> None:
    new = _requirement(HandoffRequirementLevel.RECOMMENDED, HandoffPriority.NORMAL)

    assert stronger(None, new) == new


def test_a_higher_level_replaces_and_a_lower_one_never_does() -> None:
    recommended = _requirement(
        HandoffRequirementLevel.RECOMMENDED, HandoffPriority.URGENT
    )
    required = _requirement(HandoffRequirementLevel.REQUIRED, HandoffPriority.HIGH)

    assert stronger(recommended, required) == required
    assert stronger(required, recommended) == required


def test_at_the_same_level_the_higher_priority_wins() -> None:
    high = _requirement(HandoffRequirementLevel.REQUIRED, HandoffPriority.HIGH)
    urgent = _requirement(HandoffRequirementLevel.REQUIRED, HandoffPriority.URGENT)

    assert stronger(high, urgent) == urgent
    assert stronger(urgent, high) == urgent
