"""Test double FakeSystem implementing SystemUnderTest protocol."""

from __future__ import annotations

from collections.abc import Callable

from contracts.envelope import VerificationState

from evalrunner.models import Scenario, TurnResult


class FakeSession:
    """Session handle for FakeSystem."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.turn_index = 0
        self.card_blocked: bool | None = None
        self.card_blocked_own: bool | None = None
        self.card_blocked_foreign: bool | None = None
        self.amount_above_threshold: bool = False


class FakeSystem:
    """Configurable test double for SystemUnderTest."""

    def __init__(
        self,
        name: str = "FakeSystem",
        turn_results: list[TurnResult] | None = None,
        turn_fn: Callable[[FakeSession, str], TurnResult] | None = None,
    ) -> None:
        self.name = name
        self.turn_results = list(turn_results) if turn_results else []
        self.turn_fn = turn_fn
        self.sessions: list[FakeSession] = []

    def start(self, scenario: Scenario) -> FakeSession:
        session = FakeSession(scenario)
        self.sessions.append(session)
        return session

    def send(self, session: FakeSession, message: str) -> TurnResult:
        if self.turn_fn:
            result = self.turn_fn(session, message)
        elif session.turn_index < len(self.turn_results):
            result = self.turn_results[session.turn_index]
        else:
            result = TurnResult(
                reply_text="Default response",
                verification_state=VerificationState.ANONYMOUS,
            )
        session.turn_index += 1
        return result

    def teardown(self, session: FakeSession) -> None:
        pass
