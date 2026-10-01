"""Shared fixtures for the encoder package tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_ARTIFACT = FIXTURES / "decision_points.fixture.json"


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Artifact paths (train data) are relative to the repo root, as in the service."""
    monkeypatch.chdir(REPO_ROOT)
    yield
