"""Tests for orchestrator health check endpoint."""

from fastapi.testclient import TestClient
from orchestrator.main import app

client = TestClient(app)


def test_health() -> None:
    """Ensure GET /health returns status ok and service orchestrator."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "orchestrator"}
