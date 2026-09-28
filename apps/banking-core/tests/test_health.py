"""Tests for banking-core health check endpoint."""

import banking_core.main as main
import pytest
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.knowledge.tools.kb_search import KbSearchUnavailableError
from banking_core.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    """Ensure GET /health returns status ok and service banking-core."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "banking-core"}


def test_readiness_reports_missing_knowledge_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "get_control_config_repository",
        lambda: InMemoryControlConfigRepository(),
    )

    def unavailable_searcher() -> None:
        raise KbSearchUnavailableError("test cache is empty")

    monkeypatch.setattr(main, "get_kb_searcher", unavailable_searcher)
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "KbSearchUnavailableError" in response.json()["reason"]
