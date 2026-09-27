"""Tests for encoder health check endpoint."""

from encoder_service.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    """Ensure GET /health returns status ok and service encoder."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "encoder"}
