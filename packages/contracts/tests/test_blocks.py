"""Tests for the message block contract."""

import pytest
from pydantic import ValidationError

from contracts import (
    BLOCK_TYPES,
    MESSAGE_BLOCK_ADAPTER,
    MODEL_EMITTABLE_BLOCK_TYPES,
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


def test_discriminated_union_parses_each_type():
    assert isinstance(
        MESSAGE_BLOCK_ADAPTER.validate_python({"type": "text", "text": "hola"}), TextBlock
    )
    block = MESSAGE_BLOCK_ADAPTER.validate_python({"type": "receipt", "receipt": RECEIPT})
    assert isinstance(block, ReceiptBlock)
    assert block.receipt.action == "card.block"


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
