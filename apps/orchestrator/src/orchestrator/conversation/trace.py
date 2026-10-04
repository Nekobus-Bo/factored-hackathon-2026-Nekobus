"""Detective mode (ADR-0019): a turn's timeline, from what the engine already holds.

The recorder only reads. It is handed the values the engine computed anyway (the
masked text, the masked messages the provider sent, the masked tool arguments, the
feedback string the model receives), so a turn sends exactly the same things with
the trace on or off, and the LLM recording keys stay the same. It never sees the
placeholder map's values, the rehydrated tool arguments or a raw tool result's data.

A defect here never costs the turn: an event that cannot be built is dropped and
logged by type. With detective mode off the engine uses `TraceRecorder.off()`,
which records nothing.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from contracts import AnalyzeResponse, ToolResult, ToolResultStatus
from contracts.trace import (
    TRACE_VERSION,
    BlocksDetail,
    DecisionsDetail,
    EncoderDetail,
    LlmCallDetail,
    MaskingDetail,
    ToolCallDetail,
    TraceCount,
    TraceDecision,
    TraceDecisionPoint,
    TraceEffect,
    TraceEvent,
    TraceEventKind,
    TraceEventStatus,
    TraceMessage,
    TraceToolRequest,
    TurnTrace,
)

from orchestrator.conversation.decisions.records import DecisionRecord, EffectRecord
from orchestrator.llm.provider import LLMResponse

logger = logging.getLogger(__name__)

_DETAILS = ("encoder", "masking", "decisions", "llm_call", "tool_call", "blocks")
_STATUS_OF = {
    ToolResultStatus.OK: TraceEventStatus.OK,
    ToolResultStatus.REFUSED: TraceEventStatus.REFUSED,
    ToolResultStatus.ERROR: TraceEventStatus.ERROR,
}


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class TraceRecorder:
    """Collects the events of one turn. Not shared between turns."""

    def __init__(
        self,
        turn_id: str,
        enabled: bool = True,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.turn_id = turn_id
        self.enabled = enabled
        self._clock = clock
        self._start = clock()
        self._events: list[TraceEvent] = []
        self._llm_round = 0
        self._last_outbound: list[dict[str, Any]] = []
        # What `_execute` learned about the tool call in progress (see `tool_outcome`).
        self._pending_tool: dict[str, Any] = {}

    @classmethod
    def off(cls) -> "TraceRecorder":
        """A recorder that records nothing: detective mode is off."""
        return cls(turn_id="off", enabled=False)

    def now(self) -> float:
        return self._clock() if self.enabled else 0.0

    # ----------------------------------------------------------------- events

    def _add(
        self,
        kind: TraceEventKind,
        label: str,
        started: float | None,
        status: TraceEventStatus,
        note: str | None = None,
        **detail: Any,
    ) -> None:
        if not self.enabled:
            return
        try:
            now = self._clock()
            start = self._start if started is None else started
            self._events.append(
                TraceEvent(
                    seq=len(self._events),
                    kind=kind,
                    label=label[:128],
                    start_ms=round(max(0.0, (start - self._start) * 1000), 3),
                    duration_ms=None
                    if started is None
                    else round(max(0.0, (now - started) * 1000), 3),
                    status=status,
                    note=note,
                    **{name: detail.get(name) for name in _DETAILS},
                )
            )
        except Exception as exc:
            logger.error(
                "Turn %s: trace event %s dropped (%s)",
                self.turn_id,
                kind.value,
                type(exc).__name__,
            )

    def encoder(
        self,
        started: float,
        analysis: AnalyzeResponse | None,
        failure: str | None = None,
    ) -> None:
        """The encoder's answer, or why there was none (`failure`, or no encoder)."""
        if not self.enabled:
            return
        if analysis is None:
            self._add(
                TraceEventKind.ENCODER,
                "encoder",
                started,
                TraceEventStatus.ERROR if failure else TraceEventStatus.SKIPPED,
                note=failure or "no encoder configured: masking by the regexes alone",
                encoder=EncoderDetail(
                    available=False,
                    intent=None,
                    confidence=None,
                    abstain=None,
                    model_id=None,
                    config_version=None,
                    server_latency_ms=None,
                    slots=[],
                    pii_spans=[],
                    decision_points=[],
                ),
            )
            return
        spans = Counter(
            str(getattr(span.type, "value", span.type)) for span in analysis.pii_spans
        )
        self._add(
            TraceEventKind.ENCODER,
            "encoder",
            started,
            TraceEventStatus.OK,
            encoder=EncoderDetail(
                available=True,
                intent=analysis.intent,
                confidence=analysis.confidence,
                abstain=analysis.abstain,
                model_id=analysis.model_id,
                config_version=analysis.config_version,
                server_latency_ms=analysis.latency_ms,
                # Types only: a slot's value is the customer's text.
                slots=[
                    str(getattr(slot.type, "value", slot.type))
                    for slot in analysis.slots
                ],
                pii_spans=[
                    TraceCount(type=kind, count=n) for kind, n in sorted(spans.items())
                ],
                decision_points=[
                    TraceDecisionPoint(
                        dp_id=result.dp_id,
                        outcome=str(getattr(result.outcome, "value", result.outcome)),
                        label=result.label,
                        confidence=result.confidence,
                        raw_confidence=result.raw_confidence,
                        runner_up_label=result.runner_up.label
                        if result.runner_up
                        else None,
                        runner_up_confidence=result.runner_up.confidence
                        if result.runner_up
                        else None,
                        tau=result.tau,
                    )
                    for _, result in sorted(analysis.decisions.items())
                ],
            ),
        )

    def masking(
        self,
        started: float,
        masked_text: str | None,
        placeholders: list[str],
        regex_only: bool,
        encoder_spans_added: int,
        otp_pending: bool,
    ) -> None:
        failed = masked_text is None
        self._add(
            TraceEventKind.MASKING,
            "masking",
            started,
            TraceEventStatus.ERROR if failed else TraceEventStatus.OK,
            note="the text could not be masked safely: nothing was sent"
            if failed
            else None,
            masking=MaskingDetail(
                masked_text=masked_text,
                placeholders=sorted(placeholders),
                regex_only=regex_only,
                encoder_spans_added=encoder_spans_added,
                otp_pending=otp_pending,
                failed=failed,
            ),
        )

    def canned_reply(
        self,
        note: str = "answered by the canned clarification, without the LLM (ADR-0014)",
    ) -> None:
        self._add(
            TraceEventKind.CANNED_REPLY,
            "canned reply",
            None,
            TraceEventStatus.OK,
            note=note,
        )

    def llm_call(
        self,
        started: float,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response: LLMResponse,
        prompt_version: str,
    ) -> None:
        """One completion; after the first, only the messages added since the last."""
        if not self.enabled:
            return
        self._llm_round += 1
        outbound = response.masked_messages or messages
        previous = self._last_outbound
        start = len(previous) if outbound[: len(previous)] == previous else 0
        self._last_outbound = list(outbound)
        usage = response.usage or {}
        self._add(
            TraceEventKind.LLM_CALL,
            f"llm #{self._llm_round}",
            started,
            TraceEventStatus.OK,
            llm_call=LlmCallDetail(
                round=self._llm_round,
                model=response.model,
                prompt_version=prompt_version,
                cached=response.cached,
                recording_key=response.recording_key,
                tools_offered=[
                    str((tool.get("function") or {}).get("name") or "")
                    for tool in tools or []
                ],
                messages_from=start,
                messages=[
                    TraceMessage(
                        role=str(message.get("role") or "unknown"),
                        content=_text(message.get("content")),
                        tool_calls=_text(message.get("tool_calls")),
                        tool_call_id=_text(message.get("tool_call_id")),
                    )
                    for message in outbound[start:]
                ],
                response_content=response.masked_content,
                response_tool_calls=[
                    TraceToolRequest(
                        call_id=str(call.get("id") or ""),
                        name=str((call.get("function") or {}).get("name") or ""),
                        arguments=_text((call.get("function") or {}).get("arguments"))
                        or "",
                    )
                    for call in response.tool_calls
                ],
                prompt_tokens=_int(usage.get("prompt_tokens")),
                completion_tokens=_int(usage.get("completion_tokens")),
                total_tokens=_int(usage.get("total_tokens")),
                cost_usd=response.cost,
            ),
        )

    def tool_outcome(
        self, tool: str, executed: bool, local_reason: str | None = None
    ) -> None:
        """Called by the engine where a tool call ends; `tool_call` reads it back."""
        if self.enabled:
            self._pending_tool = {
                "tool": tool,
                "executed": executed,
                "local_reason": local_reason,
                "ended": self._clock(),
            }

    def tool_call(
        self,
        started: float,
        call_id: str | None,
        llm_name: str,
        arguments: str | None,
        result: ToolResult | None,
        feedback: str | None,
        kind: TraceEventKind = TraceEventKind.TOOL_CALL,
    ) -> None:
        if not self.enabled:
            return
        pending, self._pending_tool = self._pending_tool, {}
        tool = str(pending.get("tool") or (result.tool if result else llm_name))
        executed = bool(pending.get("executed", result is not None))
        if result is None:
            status = TraceEventStatus.ERROR
        elif not executed and result.status is ToolResultStatus.REFUSED:
            status = TraceEventStatus.REFUSED
        else:
            status = _STATUS_OF.get(result.status, TraceEventStatus.ERROR)
        flow = result.flow if result else None
        # The banking-core call is timed to where it returned, not past the feedback.
        ended = pending.get("ended")
        self._add(
            kind,
            tool,
            started,
            status,
            tool_call=ToolCallDetail(
                call_id=call_id,
                llm_name=llm_name,
                tool=tool,
                arguments=arguments,
                executed=executed,
                local_reason=pending.get("local_reason"),
                status=result.status if result else None,
                reason_code=result.reason_code if result else None,
                flow_state=flow.state if flow else None,
                flow_next=list(flow.next) if flow else [],
                flow_allowed=list(flow.allowed) if flow else [],
                feedback=feedback,
            ),
        )
        if ended is not None and self._events and self._events[-1].kind is kind:
            event = self._events[-1]
            event.duration_ms = round(max(0.0, (ended - started) * 1000), 3)

    def blocks(
        self,
        started: float,
        kept: list[str],
        dropped: list[str],
        internal_lines_withheld: int,
        receipts: int,
        handoffs: int,
        fallback: bool,
    ) -> None:
        self._add(
            TraceEventKind.BLOCKS,
            "reply",
            started,
            TraceEventStatus.OK,
            blocks=BlocksDetail(
                kept=kept,
                dropped=dropped,
                internal_lines_withheld=internal_lines_withheld,
                receipts=receipts,
                handoffs=handoffs,
                fallback=fallback,
            ),
        )

    def decisions(
        self,
        config_version: str | None,
        decisions: list[DecisionRecord],
        effects: list[EffectRecord],
    ) -> None:
        self._add(
            TraceEventKind.DECISIONS,
            "decision points",
            None,
            TraceEventStatus.OK if decisions or effects else TraceEventStatus.SKIPPED,
            decisions=DecisionsDetail(
                config_version=config_version,
                decisions=[
                    TraceDecision(
                        dp_id=record.dp_id,
                        effect=record.effect,
                        mode=record.mode.value,
                        outcome=str(getattr(record.outcome, "value", record.outcome)),
                        label=record.label,
                        confidence=record.confidence,
                        unavailable_reason=record.unavailable_reason,
                    )
                    for record in decisions
                ],
                effects=[
                    TraceEffect(
                        dp_id=effect.dp_id,
                        effect=effect.effect,
                        mode=effect.mode.value,
                        tool=effect.tool,
                        applied=effect.applied,
                        would_apply=effect.would_apply,
                    )
                    for effect in effects
                ],
            ),
        )

    def takeover(self) -> None:
        self._add(
            TraceEventKind.TAKEOVER,
            "takeover",
            None,
            TraceEventStatus.SKIPPED,
            note="an agent holds the conversation: the message was only stored",
        )

    # ------------------------------------------------------------------ build

    def build(self, prompt_version: str, tool_rounds: int = 0) -> TurnTrace | None:
        if not self.enabled:
            return None
        try:
            return TurnTrace(
                trace_version=TRACE_VERSION,
                turn_id=self.turn_id,
                prompt_version=prompt_version,
                total_ms=round(max(0.0, (self._clock() - self._start) * 1000), 3),
                tool_rounds=tool_rounds,
                events=list(self._events),
            )
        except Exception as exc:
            logger.error(
                "Turn %s: trace dropped (%s)", self.turn_id, type(exc).__name__
            )
            return None
