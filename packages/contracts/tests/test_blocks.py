"""Tests for the message block contract."""

import pytest
from pydantic import ValidationError

from contracts import (
    BLOCK_TYPES,
    MESSAGE_BLOCK_ADAPTER,
    MODEL_EMITTABLE_BLOCK_TYPES,
    HandoffBlock,
    ReceiptBlock,
    TextBlock,
)

RECEIPT = {
    "action": "card.block",
    "target_masked": "card_ab12cd34",
    "state_before": "ACTIVE",
    "state_after": "BLOCKED",
    "verified_at": "2026-09-27T12:00:00Z",
    "audit_id": "aud_0001abcd",
}

HANDOFF_RECEIPT = {
    **RECEIPT,
    "action": "handoff.create",
    "target_masked": "hnd_abcd1234",
    "state_before": "NONE",
    "state_after": "QUEUED",
}


def test_discriminated_union_parses_each_type():
    assert isinstance(
        MESSAGE_BLOCK_ADAPTER.validate_python({"type": "text", "text": "hola"}), TextBlock
    )
    block = MESSAGE_BLOCK_ADAPTER.validate_python({"type": "receipt", "receipt": RECEIPT})
    assert isinstance(block, ReceiptBlock)
    assert block.receipt.action == "card.block"


def test_handoff_block_contract_and_exported_schema() -> None:
    raw = {
        "type": "handoff",
        "handoff_id": "hnd_abcd1234",
        "status": "QUEUED",
        "department": "DISPUTES",
        "priority": "HIGH",
        "queue_position": 4,
        "summary": {
            "verified_facts": {
                "verification_state": "VERIFIED",
                "customer_identified": True,
                "policy_flags": [],
            },
            "actions_taken": [],
            "verification_method": "document_match_and_otp",
            "open_questions": [{"source": "model_unverified", "text": "Stored question."}],
        },
        "receipt": HANDOFF_RECEIPT,
    }

    block = MESSAGE_BLOCK_ADAPTER.validate_python(raw)

    assert isinstance(block, HandoffBlock)
    assert block.handoff_id == "hnd_abcd1234"
    assert block.priority == "HIGH"
    assert block.queue_position == 4
    assert block.receipt.action == "handoff.create"
    assert block.summary.verified_facts["verification_state"] == "VERIFIED"
    assert block.summary.actions_taken == []
    assert block.summary.verification_method == "document_match_and_otp"
    assert block.summary.open_questions[0].text == "Stored question."
    handoff_schema = MESSAGE_BLOCK_ADAPTER.json_schema()["$defs"]["HandoffBlock"]
    assert {"handoff_id", "summary", "priority", "queue_position"} <= set(
        handoff_schema["properties"]
    )
    assert "HandoffSummary" in MESSAGE_BLOCK_ADAPTER.json_schema()["$defs"]
    assert "handoff" in BLOCK_TYPES
    assert "handoff" not in MODEL_EMITTABLE_BLOCK_TYPES


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "button", "label": "x"},
        {"type": "text", "text": ""},
        {"type": "text", "text": "x", "html": "<b>x</b>"},
        {"type": "receipt", "receipt": {**RECEIPT, "target_masked": "4532123456789012"}},
    ],
)
def test_rejects_unknown_types_extras_and_unmasked_targets(raw):
    with pytest.raises(ValidationError):
        MESSAGE_BLOCK_ADAPTER.validate_python(raw)


def test_model_may_only_emit_text():
    assert MODEL_EMITTABLE_BLOCK_TYPES == frozenset({"text"})
    assert MODEL_EMITTABLE_BLOCK_TYPES <= BLOCK_TYPES
    assert "receipt" not in MODEL_EMITTABLE_BLOCK_TYPES
    assert "handoff" not in MODEL_EMITTABLE_BLOCK_TYPES
