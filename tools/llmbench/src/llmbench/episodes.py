"""Episodes: eval/scenarios conversations through the sandbox, scored by evalrunner.

`SandboxSystem` is an evalrunner SystemUnderTest (eval/runner protocol.py), so a
scenario runs through evalrunner's own `run_scenario` and is judged by its own
checks and unsafe-outcome hooks (U1-U8). The evidence is the sandbox bank's call
log, not banking-core's audit trail: it is evidence for choosing a model, not
for the system, and `real_system` stays False so evalrunner's guard keeps it
out of reports/.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from contracts import ToolCall, ToolResultStatus
from contracts.tools.card_list import CardStatus
from evalrunner.loader import load_scenarios_from_directory
from evalrunner.models import (
    HandoffResult,
    Scenario,
    ScenarioRunResult,
    ToolCallReport,
    TurnResult,
)
from evalrunner.protocol import TurnFailedError
from evalrunner.runner import run_scenario

from llmbench.harness import OTP_TOKEN, Conversation, TurnRecord
from llmbench.provider import BenchProvider
from llmbench.sandbox import BankSetup, SandboxBank

SCENARIOS_DIR = Path("eval/scenarios")
PRIORITY_HANDOFF = {"HIGH", "URGENT"}


def bank_setup(scenario: Scenario) -> BankSetup:
    """The scenario's initial_state as sandbox setup."""
    state = scenario.initial_state
    raw = state.policy.amount_threshold_minor
    thresholds = (
        {c: raw for c in ("USD", "EUR", "BRL", "COP")}
        if isinstance(raw, int)
        else dict(raw)
    )
    tool_policy = state.tool_policy
    return BankSetup(
        customer=state.customer,
        card_status=CardStatus(state.card_status),
        otp_channel_present=state.registered_otp_channel == "present",
        thresholds_minor=thresholds,
        amount_mode="block" if state.policy.mode == "block" else "flag",
        enabled_tools=frozenset(tool_policy.enabled) if tool_policy else frozenset(),
        disabled_tools=frozenset(tool_policy.disabled) if tool_policy else frozenset(),
        fault=state.fault,  # type: ignore[arg-type]
    )


@dataclass
class EpisodeSession:
    """The session handle evalrunner passes back; the checks read its attributes."""

    scenario: Scenario
    bank: SandboxBank
    conversation: Conversation
    llm: BenchProvider
    records: list[TurnRecord] = field(default_factory=list)
    card_blocked: bool | None = None
    card_blocked_own: bool | None = None
    card_blocked_foreign: bool | None = None
    masked_outbound_messages: list[str] = field(default_factory=list)


class SandboxSystem:
    """evalrunner SystemUnderTest: TurnEngine + SandboxBank + the model under test."""

    real_system: ClassVar[bool] = False

    def __init__(
        self,
        name: str,
        make_llm: Callable[[Conversation], BenchProvider],
        loop: asyncio.AbstractEventLoop,
        max_tool_rounds: int = 5,
    ) -> None:
        self.name = name
        self.make_llm = make_llm
        self.loop = loop
        self.max_tool_rounds = max_tool_rounds
        self.sessions: list[EpisodeSession] = []

    def start(self, scenario: Scenario) -> EpisodeSession:
        bank = SandboxBank(bank_setup(scenario))
        conversation = Conversation(
            bank, scenario.lang, max_tool_rounds=self.max_tool_rounds
        )
        session = EpisodeSession(
            scenario=scenario,
            bank=bank,
            conversation=conversation,
            llm=self.make_llm(conversation),
        )
        self.sessions.append(session)
        return session

    def send(self, session: EpisodeSession, message: str) -> TurnResult:
        conversation = session.conversation
        if (
            OTP_TOKEN in message
            and session.bank.otp_code(conversation.session_id) is None
        ):
            # The model never sent a code, so the customer has none to type. The
            # scenario fails here, and the turns so far still go through the checks.
            raise TurnFailedError(
                "no OTP challenge was issued before an {{otp}} turn",
                TurnResult(
                    verification_state=session.bank.state(conversation.session_id)
                ),
            )
        record = self.loop.run_until_complete(
            session.conversation.turn(message, session.llm)
        )
        session.records.append(record)
        self._update_cards(session)
        result = turn_result(record)
        if record.error is not None:
            raise TurnFailedError(record.error, result)
        return result

    def teardown(self, session: EpisodeSession) -> None:
        pass

    @staticmethod
    def _update_cards(session: EpisodeSession) -> None:
        customer = session.bank.case_customer()
        changed = session.bank.cards_blocked_since_start()
        own = [c for c in changed if customer and c.customer_id == customer.customer_id]
        session.card_blocked = bool(changed)
        session.card_blocked_own = bool(own)
        session.card_blocked_foreign = len(changed) > len(own)


def turn_result(record: TurnRecord) -> TurnResult:
    """evalrunner's TurnResult from what the bank and the engine recorded."""
    handoffs = [
        c
        for c in record.bank_calls
        if c.tool == "handoff.create" and c.result.status is ToolResultStatus.OK
    ]
    handoff = HandoffResult()
    if handoffs:
        data: dict[str, Any] = handoffs[-1].result.data or {}
        handoff = HandoffResult(
            created=True,
            priority=str(data.get("priority", "")).upper() in PRIORITY_HANDOFF,
            payload={
                **(data.get("summary") or {}),
                "department": data.get("department"),
                "handoff_priority": data.get("priority"),
            },
        )
    outbound = record.result.eval.masked_outbound if record.result else []
    return TurnResult.model_construct(
        reply_text=record.reply_text,
        tool_calls=[
            ToolCall.model_construct(tool=c.tool, args=c.args, idempotency_key=None)
            for c in record.bank_calls
        ],
        tool_results=[c.result for c in record.bank_calls],
        tool_call_reports=[
            ToolCallReport(
                tool=c.tool,
                verification_state_before=c.state_before,
                status=c.result.status,
            )
            for c in record.bank_calls
        ],
        masked_outbound_messages=list(outbound),
        outbound_provenance=["sandbox_engine"] if outbound else [],
        verification_state=record.state_after,
        handoff=handoff,
        latency_ms=record.latency_ms,
        cost_usd=0.0,
        tokens_used=sum(
            s.prompt_tokens + s.completion_tokens for s in record.llm_calls
        ),
        asked_clarification=False,
        decisions=[],
        effects=[],
        decisions_unreadable=0,
    )


def load_episodes(
    ids: list[str], scenarios_dir: Path = SCENARIOS_DIR
) -> list[Scenario]:
    by_id = {s.id: s for s in load_scenarios_from_directory(scenarios_dir)}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"episode ids not found in {scenarios_dir}: {missing}")
    return [by_id[i] for i in ids]


def run_episodes(
    system: SandboxSystem, scenarios: list[Scenario]
) -> list[tuple[ScenarioRunResult, EpisodeSession]]:
    """Each scenario through evalrunner, paired with its session for transcripts."""
    out: list[tuple[ScenarioRunResult, EpisodeSession]] = []
    for scenario in scenarios:
        result = run_scenario(system, scenario)
        out.append((result, system.sessions[-1]))
    return out


def read_episode_ids(path: Path) -> list[str]:
    """Scenario ids from a list file: one per line, # comments ignored."""
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.append(line)
    return ids
