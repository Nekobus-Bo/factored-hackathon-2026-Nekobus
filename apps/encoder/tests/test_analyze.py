"""Tests for encoder service analyze, health, and readiness endpoints."""

from collections.abc import Generator

import pytest
from contracts.labels import Intent, PiiType, SlotType
from encoder_service.backend import (
    RawPiiSpan,
    RawSlot,
    UnavailableBackend,
    set_backend,
)
from encoder_service.config import get_abstention_threshold
from encoder_service.main import app
from fastapi.testclient import TestClient

from .fake_backend import FakeEncoderBackend


@pytest.fixture(autouse=True)
def reset_dependencies(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Ensure clean backend and environment for each test."""
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.75")
    set_backend(None)
    yield
    set_backend(None)


def test_tau_unset_boots_and_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Encoder boots with tau unset: /health 200, but /ready and /analyze return 503."""
    monkeypatch.delenv("ABSTENTION_THRESHOLD", raising=False)
    assert get_abstention_threshold() is None

    # Service boots without raising
    with TestClient(app) as client:
        # /health is 200 OK (alive)
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok", "service": "encoder"}

        # /ready is 503 uncalibrated
        ready_resp = client.get("/ready")
        assert ready_resp.status_code == 503
        ready_payload = ready_resp.json()
        assert ready_payload["ready"] is False
        assert ready_payload["reason"] == (
            "uncalibrated: ABSTENTION_THRESHOLD not set (ADR-0010)"
        )

        # /v1/analyze is 503 uncalibrated
        analyze_resp = client.post(
            "/v1/analyze",
            json={"text": "Bloquea mi tarjeta", "lang": "es"},
        )
        assert analyze_resp.status_code == 503
        assert "uncalibrated" in analyze_resp.json()["detail"].lower()


def test_startup_fails_with_invalid_tau(monkeypatch: pytest.MonkeyPatch) -> None:
    """Encoder fails loud at startup if ABSTENTION_THRESHOLD is present but invalid."""
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "invalid")
    with pytest.raises(ValueError, match="must be a valid float in"):
        with TestClient(app):
            pass

    monkeypatch.setenv("ABSTENTION_THRESHOLD", "1.5")
    with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
        with TestClient(app):
            pass

    monkeypatch.setenv("ABSTENTION_THRESHOLD", "-0.1")
    with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
        with TestClient(app):
            pass


def test_ready_unavailable_backend() -> None:
    """GET /ready returns 503 when model backend is unavailable."""
    set_backend(UnavailableBackend())
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["ready"] is False
    assert payload["status"] == "unavailable"
    assert "reason" in payload


def test_ready_active_backend() -> None:
    """GET /ready returns 200 when model backend is loaded and tau is set."""
    set_backend(FakeEncoderBackend(model_id="custom-model-v1"))
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["status"] == "ok"
    assert payload["backend"] == "custom-model-v1"


def test_analyze_unavailable_backend() -> None:
    """POST /v1/analyze returns 503 when backend is unavailable."""
    set_backend(UnavailableBackend())
    client = TestClient(app)
    response = client.post(
        "/v1/analyze",
        json={"text": "Bloquea mi tarjeta", "lang": "es"},
    )
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_analyze_fake_backend_confident() -> None:
    """POST /v1/analyze returns intent and extracted slots when confidence >= tau."""
    fake_backend = FakeEncoderBackend(
        intent=Intent.REQUEST_CARD_BLOCK,
        confidence=0.92,
        slots=[
            RawSlot(
                type=SlotType.CARD_LAST4,
                value="1234",
                start=10,
                end=14,
                normalized="1234",
            )
        ],
        pii_spans=[RawPiiSpan(type=PiiType.CARD, start=10, end=14)],
        model_id="fake-encoder-v1",
    )
    set_backend(fake_backend)

    client = TestClient(app)
    response = client.post(
        "/v1/analyze",
        json={"text": "Bloquea mi 1234 por favor", "lang": "es"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "request_card_block"
    assert data["confidence"] == 0.92
    assert data["abstain"] is False
    assert len(data["slots"]) == 1
    assert data["slots"][0]["type"] == "card_last4"
    assert data["slots"][0]["value"] == "1234"
    assert data["slots"][0]["normalized"] == "1234"
    assert len(data["pii_spans"]) == 1
    assert data["pii_spans"][0]["type"] == "CARD"
    assert data["model_id"] == "fake-encoder-v1"
    assert isinstance(data["latency_ms"], float)
    assert data["latency_ms"] >= 0.0


def test_analyze_abstains_below_tau() -> None:
    """When confidence < tau, abstain must be True and intent must be null."""
    fake_backend = FakeEncoderBackend(
        intent=Intent.REQUEST_CARD_BLOCK,
        confidence=0.60,  # tau is 0.75
        slots=[RawSlot(type=SlotType.CARD_LAST4, value="4321", start=5, end=9)],
        model_id="fake-encoder-v1",
    )
    set_backend(fake_backend)

    client = TestClient(app)
    response = client.post(
        "/v1/analyze",
        json={"text": "card 4321", "lang": "en"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["abstain"] is True
    assert data["intent"] is None
    assert data["confidence"] == 0.60
    assert len(data["slots"]) == 1
    assert data["slots"][0]["value"] == "4321"


def test_analyze_unknown_label_returns_500() -> None:
    """Return 500 when backend emits unknown intent, slot, or PII label."""
    # Unknown intent
    set_backend(FakeEncoderBackend(intent="unknown.intent", confidence=0.99))
    client = TestClient(app)
    resp = client.post("/v1/analyze", json={"text": "test", "lang": "es"})
    assert resp.status_code == 500
    assert "unknown intent" in resp.json()["detail"].lower()

    # Unknown slot type
    set_backend(
        FakeEncoderBackend(
            intent=Intent.REQUEST_CARD_BLOCK,
            confidence=0.99,
            slots=[RawSlot(type="unsupported_slot", value="x", start=0, end=1)],
        )
    )
    resp = client.post("/v1/analyze", json={"text": "test", "lang": "es"})
    assert resp.status_code == 500
    assert "unknown slot type" in resp.json()["detail"].lower()

    # Unknown PII type
    set_backend(
        FakeEncoderBackend(
            intent=Intent.REQUEST_CARD_BLOCK,
            confidence=0.99,
            pii_spans=[RawPiiSpan(type="INVALID_PII_TYPE", start=0, end=1)],
        )
    )
    resp = client.post("/v1/analyze", json={"text": "test", "lang": "es"})
    assert resp.status_code == 500
    assert "unknown pii type" in resp.json()["detail"].lower()


def test_every_1e_intent_validates() -> None:
    """Every real 1E intent passes validation without error."""
    client = TestClient(app)
    for intent in Intent:
        set_backend(FakeEncoderBackend(intent=intent.value, confidence=0.95))
        resp = client.post("/v1/analyze", json={"text": "test message", "lang": "es"})
        assert resp.status_code == 200
        assert resp.json()["intent"] == intent.value


def test_analyze_request_validation() -> None:
    """POST /v1/analyze validates length and language constraints."""
    client = TestClient(app)

    # Empty text fails validation (min_length=1)
    resp = client.post("/v1/analyze", json={"text": ""})
    assert resp.status_code == 422

    # Text > 2000 chars fails validation
    resp = client.post("/v1/analyze", json={"text": "a" * 2001})
    assert resp.status_code == 422

    # Unsupported language fails validation
    resp = client.post("/v1/analyze", json={"text": "Hello", "lang": "fr"})
    assert resp.status_code == 422
