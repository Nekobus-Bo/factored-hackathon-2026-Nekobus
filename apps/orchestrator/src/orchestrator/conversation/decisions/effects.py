"""The effects, and the hooks the turn engine calls (ADR-0012, Appendix E).

Effects are a closed set, implemented once: `record`, `select` and `gate`. Which
decision point uses which is data (the effects file). None of them can authorize
anything (invariant I1): they record, choose among values banking-core already
accepts, or withhold a write until the customer consents. When a decision point
does not decide, the fallback is always the LLM's own argument or a withheld
write, never an action (I2).

The engine calls, per turn:

    turn = runtime.begin_turn(state_copy, metadata)
    turn.observe(plan, analysis, failure)   after the encoder answered (or not)
    turn.gate(tool)                         per proposed call, before banking-core
    turn.select(tool, args)                 per call that goes on, after rehydration
    turn.after_result(tool, result)         after banking-core answered
    state = turn.commit()                   when the turn completes

In `shadow` every effect computes and records what it WOULD do and changes
nothing; in `enforce` it applies. The state machines run the same either way, so
the records of a shadow run say what enforce would have done.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from contracts import (
    AnalyzeResponse,
    DecisionOutcome,
    ReasonCode,
    ToolResult,
    ToolResultStatus,
)

from orchestrator.config import Settings
from orchestrator.conversation.decisions.catalog import (
    RequestPlan,
    ServedCatalog,
    plan_request,
)
from orchestrator.conversation.decisions.config import (
    DecisionPointConfig,
    EffectsConfig,
    GateParams,
    SelectParams,
    SelectTarget,
    enum_values,
    load_effects,
    parse_mode_overrides,
)
from orchestrator.conversation.decisions.records import (
    DecisionRecord,
    EffectRecord,
    UnavailableReason,
)
from orchestrator.conversation.decisions.state import (
    ConsentSource,
    DecisionState,
    GateState,
    GateStatus,
)
from orchestrator.conversation.models import TurnMetadata

logger = logging.getLogger(__name__)


@dataclass
class PendingCall:
    """A tool call the LLM proposed, on its way to banking-core."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    withheld: ReasonCode | None = None


class Effect:
    """Base of the closed effect vocabulary. Every hook does nothing by default."""

    def __init__(self, config: DecisionPointConfig) -> None:
        self.config = config

    def observe(self, turn: "TurnDecisions") -> None:
        """This turn's decisions are in: update the state."""

    def gate(self, turn: "TurnDecisions", call: PendingCall) -> None:
        """May withhold the call (sets `call.withheld`)."""

    def select(self, turn: "TurnDecisions", call: PendingCall) -> None:
        """May overwrite an enum argument of the call."""

    def after_result(
        self, turn: "TurnDecisions", tool: str, result: ToolResult
    ) -> None:
        """banking-core answered a call that was sent."""

    def _record(
        self,
        turn: "TurnDecisions",
        effect: Literal["select", "gate"],
        tool: str,
        would_apply: bool,
        detail: dict[str, Any],
    ) -> None:
        turn.metadata.effects.append(
            EffectRecord(
                dp_id=self.config.id,
                effect=effect,
                mode=self.config.mode,
                tool=tool,
                applied=would_apply and self.config.enforcing,
                would_apply=would_apply,
                detail=detail,
            )
        )


class RecordEffect(Effect):
    """Stores the decision in the turn metadata, which `TurnDecisions` does for
    every active decision point. There is nothing further to do."""


class GateEffect(Effect):
    """Withholds an LLM-proposed write until the customer consents (E.2).

    Per gated tool the state is closed (absent), pending (the write was
    withheld and the LLM asked) or consented. A decided `confirm` only counts
    while a question is pending; a decided explicit request grants consent
    without the extra turn; a decided `deny` closes everything and beats any
    other signal of the same turn; consent and a pending question expire after
    `max_age_turns`. A successful write consumes the consent; a write banking-core
    refuses leaves it, so the verified retry needs no second question.
    """

    def __init__(self, config: DecisionPointConfig) -> None:
        super().__init__(config)
        assert isinstance(config.params, GateParams)
        self.params: GateParams = config.params

    def observe(self, turn: "TurnDecisions") -> None:
        tool = self.params.tool
        gates = turn.state.gates
        current = gates.get(tool)

        if (
            current is not None
            and turn.number - current.since_turn > self.params.max_age_turns
        ):
            event = (
                "consent_expired"
                if current.status is GateStatus.CONSENTED
                else "question_expired"
            )
            del gates[tool]
            self._transition(turn, event, current, None)
            current = None

        own = turn.results.get(self.config.id)
        label = own.label if own is not None and own.decided else None

        if label is not None and label in self.params.revoke_labels:
            if current is not None:
                del gates[tool]
                self._transition(turn, "consent_revoked", current, None)
            return

        request = self.params.explicit_request
        if request is not None and (
            current is None or current.status is GateStatus.PENDING
        ):
            asked = turn.results.get(request.dp)
            if asked is not None and asked.decided and asked.label in request.labels:
                self._grant(turn, current, ConsentSource.EXPLICIT_REQUEST)
                return

        if (
            label is not None
            and label in self.params.consent_labels
            and current is not None
            and current.status is GateStatus.PENDING
        ):
            self._grant(turn, current, ConsentSource.CONFIRMATION)

    def gate(self, turn: "TurnDecisions", call: PendingCall) -> None:
        tool = self.params.tool
        if call.tool != tool:
            return
        current = turn.state.gates.get(tool)
        own = turn.results.get(self.config.id)
        context = {"dp_outcome": own.outcome.value if own is not None else None}
        if current is not None and current.status is GateStatus.CONSENTED:
            self._record(
                turn,
                "gate",
                tool,
                False,
                {
                    "event": "released",
                    "state_before": "consented",
                    "state_after": "consented",
                    "consent_source": current.source.value if current.source else None,
                    **context,
                },
            )
            return
        # No consent: the write waits for the question the LLM is about to ask.
        pending = GateState(status=GateStatus.PENDING, since_turn=turn.number)
        turn.state.gates[tool] = pending
        if self.config.enforcing:
            call.withheld = ReasonCode.CONFIRMATION_REQUIRED
        self._record(
            turn,
            "gate",
            tool,
            True,
            {
                "event": "withheld",
                "state_before": _status(current),
                "state_after": "pending",
                "consent_source": None,
                **context,
            },
        )

    def after_result(
        self, turn: "TurnDecisions", tool: str, result: ToolResult
    ) -> None:
        if tool == self.params.tool and result.status is ToolResultStatus.OK:
            turn.state.gates.pop(tool, None)

    def _grant(
        self, turn: "TurnDecisions", before: GateState | None, source: ConsentSource
    ) -> None:
        after = GateState(
            status=GateStatus.CONSENTED, since_turn=turn.number, source=source
        )
        turn.state.gates[self.params.tool] = after
        self._transition(turn, "consent_granted", before, after)

    def _transition(
        self,
        turn: "TurnDecisions",
        event: str,
        before: GateState | None,
        after: GateState | None,
    ) -> None:
        self._record(
            turn,
            "gate",
            self.params.tool,
            True,
            {
                "event": event,
                "state_before": _status(before),
                "state_after": _status(after),
                "consent_source": after.source.value
                if after and after.source
                else None,
            },
        )


class SelectEffect(Effect):
    """Overwrites an enum argument of an LLM-proposed call with a decided value.

    A sticky ledger keeps what the customer established over the session (the
    strongest reason, or the latest route), so a turn on which the decision
    point abstains does not erase it. With nothing decided the LLM's argument
    stands. Only what is sent to banking-core changes; the history keeps the
    LLM's own call, so replay keys do not move.
    """

    def __init__(self, config: DecisionPointConfig) -> None:
        super().__init__(config)
        assert isinstance(config.params, SelectParams)
        self.params: SelectParams = config.params
        self._accepted = {label for t in self.params.targets for label in t.map}

    def observe(self, turn: "TurnDecisions") -> None:
        own = turn.results.get(self.config.id)
        if own is None or not own.decided or own.label not in self._accepted:
            return
        assert own.label is not None
        ledger = self.params.ledger
        current = turn.state.ledgers.get(self.config.id)
        order = ledger.order or []
        if (
            ledger.policy == "priority"
            and current in order
            and order.index(current) <= order.index(own.label)
        ):
            return
        turn.state.ledgers[self.config.id] = own.label

    def select(self, turn: "TurnDecisions", call: PendingCall) -> None:
        label = turn.state.ledgers.get(self.config.id)
        for target in self.params.targets:
            if target.tool != call.tool:
                continue
            values = _assignments(target).get(label) if label is not None else None
            skipped = None
            if values is None:
                skipped = "no_decision"
            elif any(
                call.args.get(arg) in kept
                for arg, kept in target.keep_llm_call_when.items()
            ):
                skipped = "kept_llm_call"
            for arg in _assigned_args(target):
                dp_value = (
                    values[arg] if values is not None and skipped is None else None
                )
                llm_value = call.args.get(arg)
                if not (
                    isinstance(llm_value, str)
                    and llm_value in enum_values(call.tool, arg)
                ):
                    llm_value = None  # never copy free text into the record
                would_apply = dp_value is not None and dp_value != llm_value
                if would_apply and self.config.enforcing:
                    call.args[arg] = dp_value
                self._record(
                    turn,
                    "select",
                    call.tool,
                    would_apply,
                    {
                        "arg": arg,
                        "llm_value": llm_value,
                        "dp_value": dp_value,
                        "label": label,
                        "skipped": skipped,
                    },
                )

    def after_result(
        self, turn: "TurnDecisions", tool: str, result: ToolResult
    ) -> None:
        # What the customer established was spent on this write.
        if result.status is ToolResultStatus.OK and any(
            target.tool == tool for target in self.params.targets
        ):
            turn.state.ledgers.pop(self.config.id, None)


def _status(state: GateState | None) -> str:
    return state.status.value if state is not None else "none"


def _assignments(target: SelectTarget) -> dict[str, dict[str, str]]:
    """label -> {arg: value}; the loader has validated both shapes."""
    if target.arg is not None:
        return {label: {target.arg: str(value)} for label, value in target.map.items()}
    return {
        label: dict(value)
        for label, value in target.map.items()
        if isinstance(value, dict)
    }


def _assigned_args(target: SelectTarget) -> list[str]:
    return list(next(iter(_assignments(target).values())))


_EFFECTS: dict[str, type[Effect]] = {
    "record": RecordEffect,
    "gate": GateEffect,
    "select": SelectEffect,
}


class TurnDecisions:
    """The decision-point side of one turn, held by the engine."""

    def __init__(
        self,
        runtime: "DecisionRuntime",
        state: DecisionState,
        metadata: TurnMetadata,
    ) -> None:
        self.runtime = runtime
        self.state = state
        self.metadata = metadata
        self.number = state.turn
        self.results: dict[str, DecisionRecord] = {}

    def observe(
        self,
        plan: RequestPlan,
        analysis: AnalyzeResponse | None,
        failure: UnavailableReason = "encoder_unavailable",
    ) -> None:
        """Record every active decision point, then let the effects update state."""
        active = self.runtime.config.active()
        if not active:
            return
        for dp in active:
            record = self._record_of(dp, plan, analysis, failure)
            self.results[dp.id] = record
            self.metadata.decisions.append(record)
            logger.info(
                "Turn %s: decision dp=%s mode=%s outcome=%s label=%s "
                "confidence=%.3f tau=%s model=%s config=%s reason=%s",
                self.metadata.turn_id,
                record.dp_id,
                record.mode.value,
                record.outcome.value,
                record.label,
                record.confidence,
                record.tau,
                record.model_id,
                record.config_version,
                record.unavailable_reason,
            )
        if analysis is not None:
            self.metadata.decisions_config_version = analysis.config_version
        self.metadata.dp_config_mismatch = plan.mismatched
        for effect in self.runtime.effects:
            effect.observe(self)

    def gate(self, tool: str) -> ReasonCode | None:
        """The reason to refuse `tool` locally, or None to let it go on."""
        call = PendingCall(tool=tool)
        for effect in self.runtime.effects:
            effect.gate(self, call)
        return call.withheld

    def select(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """The arguments to send to banking-core (a copy; the input is untouched)."""
        call = PendingCall(tool=tool, args=dict(args))
        for effect in self.runtime.effects:
            effect.select(self, call)
        return call.args

    def after_result(self, tool: str, result: ToolResult) -> None:
        for effect in self.runtime.effects:
            effect.after_result(self, tool, result)

    def commit(self) -> DecisionState:
        """The state to keep, once the turn has completed."""
        gated = {
            e.params.tool for e in self.runtime.effects if isinstance(e, GateEffect)
        }
        ledgers = {
            e.config.id for e in self.runtime.effects if isinstance(e, SelectEffect)
        }
        self.state.gates = {k: v for k, v in self.state.gates.items() if k in gated}
        self.state.ledgers = {
            k: v for k, v in self.state.ledgers.items() if k in ledgers
        }
        self.state.turn += 1
        return self.state

    @staticmethod
    def _record_of(
        dp: DecisionPointConfig,
        plan: RequestPlan,
        analysis: AnalyzeResponse | None,
        failure: UnavailableReason,
    ) -> DecisionRecord:
        reason = plan.blocked.get(dp.id)
        if reason is None and analysis is None:
            reason = failure
        result = analysis.decisions.get(dp.id) if analysis is not None else None
        if reason is None and result is None:
            reason = "not_returned"
        if reason is not None or result is None:
            return DecisionRecord(
                dp_id=dp.id,
                effect=dp.effect,
                mode=dp.mode,
                outcome=DecisionOutcome.UNAVAILABLE,
                unavailable_reason=reason,
            )
        return DecisionRecord(
            dp_id=dp.id,
            effect=dp.effect,
            mode=dp.mode,
            outcome=result.outcome,
            label=result.label,
            confidence=result.confidence,
            tau=result.tau,
            tau_source=result.tau_source,
            model_id=result.model_id,
            config_version=result.config_version,
            latency_ms=result.latency_ms,
        )


class DecisionRuntime:
    """The validated effects file, its effects, and the catalog of served DPs."""

    def __init__(
        self, config: EffectsConfig, catalog: ServedCatalog | None = None
    ) -> None:
        self.config = config
        self.catalog = catalog or ServedCatalog()
        self._logged_blocked: dict[str, str] | None = None
        self.effects: list[Effect] = [_EFFECTS[dp.effect](dp) for dp in config.active()]

    @classmethod
    def empty(cls) -> "DecisionRuntime":
        """No decision points: the engine behaves as it did before ADR-0012."""
        return cls(EffectsConfig())

    @classmethod
    def from_settings(cls, settings: Settings) -> "DecisionRuntime":
        """Load and validate the effects file. Raises EffectsConfigError."""
        config = load_effects(
            settings.decision_effects_file,
            parse_mode_overrides(settings.decision_points_modes),
        )
        logger.info(
            "Decision points from %s: %s",
            config.source,
            ", ".join(f"{k}={v}" for k, v in config.modes().items()),
        )
        return cls(config)

    async def plan(self, encoder: Any) -> RequestPlan:
        """What to ask the encoder for this turn. Never raises."""
        active = self.config.active()
        if not active:
            return RequestPlan()
        plan = plan_request(active, await self.catalog.get(encoder))
        if plan.blocked != (self._logged_blocked or {}):
            # Once per change, not once per turn.
            self._logged_blocked = dict(plan.blocked)
            if plan.blocked:
                logger.warning(
                    "Decision points not requested: %s",
                    ", ".join(f"{k} ({v})" for k, v in plan.blocked.items()),
                )
        return plan

    def begin_turn(self, state: DecisionState, metadata: TurnMetadata) -> TurnDecisions:
        """`state` must be a copy: the caller keeps the original until commit."""
        return TurnDecisions(self, state, metadata)
