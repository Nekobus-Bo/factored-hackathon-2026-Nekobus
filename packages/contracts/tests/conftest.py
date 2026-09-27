"""Pytest configuration for contracts tests."""

import pytest


@pytest.fixture
def sample_audit_id() -> str:
    return "audit-evt-2026-09-26-abc12345"


@pytest.fixture
def sample_card_ref() -> str:
    return "card-token-49298371-abc"
