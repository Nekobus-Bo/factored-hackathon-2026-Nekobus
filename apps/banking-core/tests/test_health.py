"""Tests for banking-core health check endpoint."""

from banking_core.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    """Ensure GET /health returns status ok and service banking-core."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "banking-core"}
