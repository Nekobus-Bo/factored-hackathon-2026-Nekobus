"""SystemUnderTest protocol for evaluation harness."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from evalrunner.models import Scenario, TurnResult


class ScenarioNotRunError(Exception):
    """The scenario could not be run (setup precondition, replay miss).

    Reported as "not run" with its reason, and excluded from the metrics:
    never counted as a pass.
    """


class TurnFailedError(RuntimeError):
    """A turn failed after the system may already have acted.

    Carries the evidence collected for that turn so the checks (U1-U8) still
    run over it: the scenario FAILS, it is never "not run".
    """

    def __init__(self, message: str, turn: TurnResult) -> None:
        super().__init__(message)
        self.turn = turn


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
