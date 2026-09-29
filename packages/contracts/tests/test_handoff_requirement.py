"""The disputed transaction link and the policy outcome (ADR-0003 amendment 2026-09-29)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.envelope import (
    Receipt,
    ResourceState,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from contracts.tools import (
    BlockReason,
    CardBlockInput,
    CardBlockOutput,
    CardStatus,
    Department,
    HandoffCreateInput,
    HandoffPriority,
    HandoffReason,
    HandoffRequirement,
    HandoffRequirementLevel,
    TransactionItem,
)

TX_ID = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"


def _receipt() -> Receipt:
    return Receipt(
        action="card.block",
        target_masked="**** **** **** 4321",
        state_before=ResourceState.ACTIVE,
        state_after=ResourceState.BLOCKED,
        verified_at=datetime.now(timezone.utc),
        audit_id="aud_00000001",
    )


def _required() -> HandoffRequirement:
    return HandoffRequirement(
        level=HandoffRequirementLevel.REQUIRED,
        priority=HandoffPriority.URGENT,
        department=Department.DISPUTES,
        reason=HandoffReason.UNRECOGNIZED_TRANSACTION,
    )


# transaction_id on the two inputs


def test_transaction_id_is_optional_on_card_block_and_handoff_create():
    block = CardBlockInput(card_ref="card_demo_es", reason=BlockReason.LOST)
    handoff = HandoffCreateInput(
        reason=HandoffReason.CUSTOMER_REQUEST, summary="Customer asked for a person."
    )
    assert block.transaction_id is None
    assert handoff.transaction_id is None


def test_transaction_id_is_accepted_on_card_block_and_handoff_create():
    block = CardBlockInput(
        card_ref="card_demo_es",
        reason=BlockReason.UNRECOGNIZED_CHARGE,
        transaction_id=TX_ID,
    )
    handoff = HandoffCreateInput(
        reason=HandoffReason.UNRECOGNIZED_TRANSACTION,
        summary="Customer disputes a charge.",
        transaction_id=TX_ID,
    )
    assert block.transaction_id == TX_ID
    assert handoff.transaction_id == TX_ID


@pytest.mark.parametrize("bad_id", ["short", "x" * 65, ""])
def test_transaction_id_keeps_the_transaction_item_length_limits(bad_id: str):
    with pytest.raises(ValidationError):
        CardBlockInput(
            card_ref="card_demo_es",
            reason=BlockReason.UNRECOGNIZED_CHARGE,
            transaction_id=bad_id,
        )
    with pytest.raises(ValidationError):
        HandoffCreateInput(
            reason=HandoffReason.UNRECOGNIZED_TRANSACTION,
            summary="Customer disputes a charge.",
            transaction_id=bad_id,
        )


def test_transaction_id_limits_are_the_ones_of_the_listed_item():
    def limits(model: type, field: str) -> set[tuple[str, int]]:
        found = {
            (type(meta).__name__, getattr(meta, name))
            for meta in model.model_fields[field].metadata
            for name in ("min_length", "max_length")
            if hasattr(meta, name)
        }
        return found

    listed = limits(TransactionItem, "transaction_id")
    assert listed
    assert limits(CardBlockInput, "transaction_id") == listed
    assert limits(HandoffCreateInput, "transaction_id") == listed


@pytest.mark.parametrize(
    "amount_arg", ["amount_minor", "disputed_amount_minor", "amount", "currency"]
)
def test_card_block_has_no_amount_argument(amount_arg: str):
    """The amount comes from the database, so no tool call can carry one."""
    args = {"card_ref": "card_demo_es", "reason": "UNRECOGNIZED_CHARGE", amount_arg: 1}
    with pytest.raises(ValidationError):
        CardBlockInput.model_validate(args)
    with pytest.raises(ValueError):
        ToolCall(tool="card.block", args=args, idempotency_key="key-amount-0001")


# HandoffRequirement


def test_requirement_defaults_to_none_with_nothing_else_set():
    requirement = HandoffRequirement()
    assert requirement.level is HandoffRequirementLevel.NONE
    assert (requirement.priority, requirement.department, requirement.reason) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "level", [HandoffRequirementLevel.RECOMMENDED, HandoffRequirementLevel.REQUIRED]
)
def test_requirement_above_none_carries_priority_department_and_reason(
    level: HandoffRequirementLevel,
):
    requirement = HandoffRequirement(
        level=level,
        priority=HandoffPriority.NORMAL,
        department=Department.FRAUD_OPERATIONS,
        reason=HandoffReason.SUSPECTED_FRAUD,
    )
    assert requirement.level is level
    for missing in ("priority", "department", "reason"):
        fields = requirement.model_dump()
        fields[missing] = None
        with pytest.raises(ValidationError):
            HandoffRequirement.model_validate(fields)


def test_requirement_none_refuses_details():
    with pytest.raises(ValidationError):
        HandoffRequirement(level=HandoffRequirementLevel.NONE, priority=HandoffPriority.HIGH)


def test_requirement_refuses_unknown_fields_and_is_frozen():
    with pytest.raises(ValidationError):
        HandoffRequirement.model_validate({"level": "NONE", "note": "free text"})
    with pytest.raises(ValidationError):
        _required().level = HandoffRequirementLevel.NONE  # type: ignore[misc]


# CardBlockOutput


def test_card_block_output_carries_the_requirement():
    output = CardBlockOutput(
        card_ref="card_demo_es",
        status=CardStatus.BLOCKED,
        receipt=_receipt(),
        handoff_requirement=_required(),
    )
    restored = CardBlockOutput.model_validate(output.model_dump(mode="json"))
    assert restored.handoff_requirement == _required()


def test_card_block_output_defaults_to_no_requirement_for_older_payloads():
    """A response stored before the field existed still validates on replay."""
    payload = CardBlockOutput(
        card_ref="card_demo_es", status=CardStatus.BLOCKED, receipt=_receipt()
    ).model_dump(mode="json")
    del payload["handoff_requirement"]
    restored = CardBlockOutput.model_validate(payload)
    assert restored.handoff_requirement.level is HandoffRequirementLevel.NONE


def test_tool_result_validates_a_card_block_requirement():
    output = CardBlockOutput(
        card_ref="card_demo_es",
        status=CardStatus.BLOCKED,
        receipt=_receipt(),
        handoff_requirement=_required(),
    )
    result = ToolResult(
        tool="card.block",
        status=ToolResultStatus.OK,
        data=output.model_dump(mode="json"),
    )
    assert result.data is not None
    assert result.data["handoff_requirement"]["level"] == "REQUIRED"
    assert result.data["handoff_requirement"]["priority"] == "URGENT"

    forged = output.model_dump(mode="json")
    forged["handoff_requirement"]["priority"] = None
    with pytest.raises(ValueError):
        ToolResult(tool="card.block", status=ToolResultStatus.OK, data=forged)
