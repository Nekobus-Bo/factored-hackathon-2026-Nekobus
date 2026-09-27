"""SystemUnderTest protocol for evaluation harness."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from evalrunner.models import Scenario, TurnResult


@runtime_checkable
class SystemUnderTest(Protocol):
    """Protocol for a system under evaluation (baseline, proposed, or test fake)."""

    name: str

    def start(self, scenario: Scenario) -> Any:
        """Initialize session for the given scenario and return a session handle."""
        ...

    def send(self, session: Any, message: str) -> TurnResult:
        """Send a single customer turn to the system and return the turn result."""
        ...

    def teardown(self, session: Any) -> None:
        """Clean up the session and any allocated resources."""
        ...
