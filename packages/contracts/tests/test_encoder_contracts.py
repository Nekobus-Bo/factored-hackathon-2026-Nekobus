"""Tests for encoder contracts: AnalyzeRequest, AnalyzeResponse, Slot, PiiSpan."""

import pytest
from pydantic import ValidationError

from contracts.encoder import AnalyzeRequest, AnalyzeResponse, PiiSpan, Slot


def test_analyze_request_valid() -> None:
    """Verify valid AnalyzeRequest instances."""
    req = AnalyzeRequest(text="Necesito bloquear mi tarjeta", lang="es")
    assert req.text == "Necesito bloquear mi tarjeta"
    assert req.lang == "es"

    req_no_lang = AnalyzeRequest(text="Block card")
    assert req_no_lang.lang is None


def test_analyze_request_invalid() -> None:
    """Verify AnalyzeRequest validation errors for bad lengths or languages."""
    # Empty text
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="")

    # Text > 2000 chars
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="a" * 2001)

    # Invalid language code
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="Hello", lang="fr")  # type: ignore[arg-type]

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="Hello", extra_field="bad")  # type: ignore[call-arg]


def test_slot_valid_and_invalid() -> None:
    """Verify Slot validation."""
    slot = Slot(type="card_last4", value="1234", start=0, end=4, normalized="1234")
    assert slot.type == "card_last4"
    assert slot.start == 0
    assert slot.end == 4

    # Case-insensitive resolution works
    slot_upper = Slot(type="CARD_LAST4", value="1234", start=0, end=4)
    assert slot_upper.type == "card_last4"

    # Invalid slot type raises
    with pytest.raises(ValidationError):
        Slot(type="invalid_slot_type", value="1234", start=0, end=4)

    # start > end raises
    with pytest.raises(ValidationError, match="start index .* must be <= end index"):
        Slot(type="card_last4", value="1234", start=5, end=2)


def test_pii_span_valid_and_invalid() -> None:
    """Verify PiiSpan validation."""
    span = PiiSpan(type="EMAIL", start=10, end=25)
    assert span.type == "EMAIL"
    assert span.start == 10
    assert span.end == 25

    # Case-insensitive resolution works
    span_lower = PiiSpan(type="card", start=0, end=4)
    assert span_lower.type == "CARD"

    # Invalid PII type raises
    with pytest.raises(ValidationError):
        PiiSpan(type="INVALID_PII", start=0, end=4)

    # start > end raises
    with pytest.raises(ValidationError, match="start index .* must be <= end index"):
        PiiSpan(type="EMAIL", start=25, end=10)


def test_analyze_response_valid() -> None:
    """Verify valid AnalyzeResponse."""
    resp = AnalyzeResponse(
        intent="request_card_block",
        confidence=0.92,
        abstain=False,
        slots=[Slot(type="card_last4", value="1234", start=0, end=4)],
        pii_spans=[],
        model_id="test-model",
        latency_ms=12.5,
    )
    assert resp.intent == "request_card_block"
    assert resp.confidence == 0.92
    assert resp.abstain is False


def test_analyze_response_abstention_enforces_null_intent() -> None:
    """Verify that when abstain=True, intent must be None."""
    # abstain=True with intent=None is valid
    resp = AnalyzeResponse(
        intent=None,
        confidence=0.35,
        abstain=True,
        slots=[],
        pii_spans=[],
        model_id="test-model",
        latency_ms=8.0,
    )
    assert resp.abstain is True
    assert resp.intent is None

    # abstain=True with a non-null intent raises validation error
    with pytest.raises(ValidationError, match="intent must be None"):
        AnalyzeResponse(
            intent="card.block",
            confidence=0.35,
            abstain=True,
            slots=[],
            pii_spans=[],
            model_id="test-model",
            latency_ms=8.0,
        )


def test_analyze_response_enforces_intent_when_not_abstaining() -> None:
    """Verify that when abstain=False, intent must not be None."""
    with pytest.raises(ValidationError, match="intent must not be None when abstain is False"):
        AnalyzeResponse(
            intent=None,
            confidence=0.85,
            abstain=False,
            slots=[],
            pii_spans=[],
            model_id="test-model",
            latency_ms=5.0,
        )
