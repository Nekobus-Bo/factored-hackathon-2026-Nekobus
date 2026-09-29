"""Tests for encoder contracts: AnalyzeRequest, AnalyzeResponse, Slot, PiiSpan."""

import pytest
from pydantic import ValidationError

from contracts.encoder import (
    AnalyzeRequest,
    AnalyzeResponse,
    DecisionPointsResponse,
    DecisionResult,
    EmbedRequest,
    EmbedResponse,
    PiiSpan,
    Slot,
)


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


# --- Decision points (ADR-0012) ----------------------------------------------------


def _result(**overrides: object) -> DecisionResult:
    fields: dict[str, object] = {
        "dp_id": "confirm_gate",
        "outcome": "decided",
        "label": "confirm",
        "confidence": 0.97,
        "raw_confidence": 0.61,
        "runner_up": {"label": "other", "confidence": 0.02},
        "tau": 0.9,
        "tau_source": "artifact",
        "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
        "config_version": "0123456789ab",
        "latency_ms": 0.3,
    }
    fields.update(overrides)
    return DecisionResult.model_validate(fields)


def _response(**overrides: object) -> AnalyzeResponse:
    fields: dict[str, object] = {
        "intent": None,
        "confidence": 0.2,
        "abstain": True,
        "model_id": "test-model",
        "latency_ms": 1.0,
    }
    fields.update(overrides)
    return AnalyzeResponse.model_validate(fields)


def test_legacy_payloads_still_validate_without_decision_fields() -> None:
    """Backward compatibility: the current orchestrator and encoder omit every new field."""
    request = AnalyzeRequest.model_validate({"text": "hola", "lang": "es"})
    assert request.decision_points is None

    response = AnalyzeResponse.model_validate(
        {
            "intent": "request_card_block",
            "confidence": 0.9,
            "abstain": False,
            "slots": [],
            "pii_spans": [],
            "model_id": "m",
            "latency_ms": 1.0,
        }
    )
    assert response.decisions == {}
    assert response.config_version is None


def test_decision_points_request_accepts_valid_ids() -> None:
    req = AnalyzeRequest(text="sí", lang="es", decision_points=["confirm_gate", "turn_intent"])
    assert req.decision_points == ["confirm_gate", "turn_intent"]
    assert AnalyzeRequest(text="sí", decision_points=[]).decision_points == []


@pytest.mark.parametrize(
    "ids",
    [
        ["Confirm"],  # upper case
        ["ab"],  # too short
        ["1gate"],  # starts with a digit
        ["a" * 42],  # too long
        ["confirm-gate"],  # not snake case
        ["confirm_gate", "confirm_gate"],  # duplicate
        [f"dp_{n:02d}" for n in range(17)],  # more than 16
    ],
)
def test_decision_points_request_rejects_bad_ids(ids: list[str]) -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest(text="sí", decision_points=ids)


def test_decision_result_decided_carries_label_tau_and_provenance() -> None:
    result = _result()
    assert result.label == "confirm"
    assert result.tau_source == "artifact"
    assert result.config_version == "0123456789ab"
    assert result.runner_up is not None and result.runner_up.label == "other"


def test_decision_result_label_only_when_decided() -> None:
    with pytest.raises(ValidationError, match="label must be set if and only if"):
        _result(outcome="abstained")  # label present
    with pytest.raises(ValidationError, match="label must be set if and only if"):
        _result(label=None)  # decided without label


def test_decision_result_decided_must_pass_its_tau() -> None:
    with pytest.raises(ValidationError, match="confidence >= tau"):
        _result(confidence=0.5, tau=0.9)
    with pytest.raises(ValidationError, match="tau_source must be set"):
        _result(tau=None)  # tau_source alone is inconsistent
    with pytest.raises(ValidationError, match="must carry the tau"):
        _result(tau=None, tau_source=None)


def test_decision_result_abstained_may_lack_tau_when_the_language_is_infeasible() -> None:
    result = _result(
        outcome="abstained", label=None, confidence=0.4, tau=None, tau_source=None
    )
    assert result.tau is None
    with_tau = _result(outcome="abstained", label=None, confidence=0.4, tau=0.9)
    assert with_tau.label is None


@pytest.mark.parametrize("outcome", ["unavailable", "infeasible", "off"])
def test_decision_result_non_computed_outcomes_carry_nothing(outcome: str) -> None:
    result = _result(
        outcome=outcome,
        label=None,
        confidence=0.0,
        raw_confidence=None,
        runner_up=None,
        tau=None,
        tau_source=None,
    )
    assert result.outcome == outcome
    with pytest.raises(ValidationError, match="carries no confidence"):
        _result(outcome=outcome, label=None, confidence=0.4, runner_up=None, tau=None,
                tau_source=None)


def test_decision_result_is_strict_and_text_free() -> None:
    with pytest.raises(ValidationError):
        _result(text="me robaron la tarjeta")
    assert "text" not in DecisionResult.model_fields
    assert "spans" not in DecisionResult.model_fields
    with pytest.raises(ValidationError):
        _result(dp_id="Bad-Id")
    with pytest.raises(ValidationError):
        _result(model_id="m" * 129)


def test_response_carries_decisions_and_config_version() -> None:
    gate = _result()
    response = _response(decisions={"confirm_gate": gate}, config_version="0123456789ab")
    assert response.decisions["confirm_gate"].label == "confirm"
    assert response.config_version == "0123456789ab"
    # Round trip through JSON, as the orchestrator receives it.
    again = AnalyzeResponse.model_validate_json(response.model_dump_json())
    assert again == response


def test_response_decision_keys_must_match_dp_ids() -> None:
    with pytest.raises(ValidationError, match="does not match dp_id"):
        _response(decisions={"turn_intent": _result()})


def test_legacy_fields_follow_a_decided_turn_intent() -> None:
    decided = _result(dp_id="turn_intent", label="request_card_block")
    ok = _response(
        intent="request_card_block",
        confidence=0.97,
        abstain=False,
        decisions={"turn_intent": decided},
    )
    assert ok.intent == "request_card_block"
    with pytest.raises(ValidationError, match="legacy intent must equal"):
        _response(
            intent="report_lost_card",
            confidence=0.97,
            abstain=False,
            decisions={"turn_intent": decided},
        )
    with pytest.raises(ValidationError, match="legacy intent must equal"):
        _response(decisions={"turn_intent": decided})  # abstain=True


def test_legacy_abstain_follows_an_abstained_turn_intent() -> None:
    abstained = _result(
        dp_id="turn_intent", outcome="abstained", label=None, confidence=0.2, tau=0.4
    )
    assert _response(decisions={"turn_intent": abstained}).abstain is True
    with pytest.raises(ValidationError, match="legacy abstain must be true"):
        _response(
            intent="request_card_block",
            abstain=False,
            confidence=0.9,
            decisions={"turn_intent": abstained},
        )


def test_other_decision_points_do_not_constrain_the_legacy_fields() -> None:
    gate = _result(dp_id="confirm_gate")
    assert _response(decisions={"confirm_gate": gate}).abstain is True


def test_decision_points_response_contract() -> None:
    payload = {
        "config_version": None,
        "source": "legacy_seed",
        "decision_points": [
            {
                "id": "turn_intent",
                "labels": ["request_card_block", "confirm"],
                "backend_kind": "tfidf_lr",
                "backend_model_id": "tfidf_lr@train-sha256:a563c0c445d6",
                "probability_kind": "top1_only",
                "status": "uncalibrated_seed",
                "state": "ready",
                "enabled": True,
                "always_on": True,
                "languages_with_tau": ["*"],
            }
        ],
    }
    parsed = DecisionPointsResponse.model_validate(payload)
    assert parsed.decision_points[0].status == "uncalibrated_seed"
    payload["source"] = "somewhere"
    with pytest.raises(ValidationError):
        DecisionPointsResponse.model_validate(payload)


# --- Embeddings (ADR-0012, Appendix J) ---------------------------------------------


def test_embed_request_accepts_a_batch_of_texts() -> None:
    request = EmbedRequest(texts=["bloquear tarjeta", "card block"])
    assert request.texts == ["bloquear tarjeta", "card block"]


@pytest.mark.parametrize(
    "texts",
    [
        [],  # empty batch
        [""],  # empty text
        ["x" * 4001],  # too long
        ["ok"] * 257,  # over the contract ceiling
    ],
)
def test_embed_request_rejects_bad_batches(texts: list[str]) -> None:
    with pytest.raises(ValidationError):
        EmbedRequest(texts=texts)
    with pytest.raises(ValidationError):
        EmbedRequest(texts=["ok"], extra_field=1)  # type: ignore[call-arg]


def test_embed_response_carries_the_model_identity_and_no_text() -> None:
    response = EmbedResponse(
        model_id="org/model",
        revision="86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d",
        dim=3,
        vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )
    assert response.dim == 3 and len(response.vectors) == 2
    assert "texts" not in EmbedResponse.model_fields
    assert EmbedResponse.model_validate_json(response.model_dump_json()) == response


def test_embed_response_rejects_a_wrong_dimension_and_non_finite_values() -> None:
    base = {"model_id": "m", "revision": "r", "dim": 3}
    with pytest.raises(ValidationError, match="dim=3"):
        EmbedResponse(**base, vectors=[[1.0, 0.0]])
    with pytest.raises(ValidationError):
        EmbedResponse(**base, vectors=[[1.0, float("nan"), 0.0]])
    with pytest.raises(ValidationError):
        EmbedResponse(**base, vectors=[[1.0, float("inf"), 0.0]])
    with pytest.raises(ValidationError):
        EmbedResponse(model_id="", revision="r", dim=3, vectors=[])
