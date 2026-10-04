"""Conversation turn engine: encoder -> mask -> LLM <-> tools -> blocks.

The encoder is optional; its PII spans widen the masking of the customer text,
which is otherwise done by the regexes alone.

The model proposes tool calls; banking-core decides (AGENTS rules 1 and 2).
The engine never retries a refused call and never alters model arguments
beyond rehydrating placeholders for the banking-core request and, when a
decision point is in `enforce` (ADR-0012), the bounded effects of
conversation/decisions: `select` overwrites an enum argument, `gate` withholds a
write until the customer consents. Neither can make banking-core allow anything.

One thing the engine does on its own, because the model cannot be trusted to
remember it (ADR-0003 amendment 2026-09-29): when a card.block comes back with
a REQUIRED handoff requirement and no handoff.create has succeeded yet, the
engine creates that handoff itself, with the requirement's reason, department
and priority, the same transaction_id and a fixed summary, no model text.
"""

import copy
import hashlib
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from contracts import (
    TOOL_CATALOG,
    AnalyzeResponse,
    HandoffBlock,
    Intent,
    PiiSpan,
    PiiType,
    ReasonCode,
    Receipt,
    ReceiptBlock,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from contracts.envelope import FlowHint, VerificationState
from contracts.locale import Locale, lang_of
from contracts.tools.handoff_create import (
    HandoffCreateOutput,
    HandoffPriority,
    HandoffRequirement,
    HandoffRequirementLevel,
)
from contracts.trace import TraceEventKind, TurnTrace
from pydantic import ValidationError

from orchestrator.config import Settings
from orchestrator.conversation.blocks import (
    MAX_TEXT_LENGTH,
    drop_repeated_lines,
    filter_model_blocks,
    withhold_internal_lines,
)
from orchestrator.conversation.dates import normalize_date_arguments
from orchestrator.conversation.decisions.catalog import RequestPlan
from orchestrator.conversation.decisions.effects import DecisionRuntime, TurnDecisions
from orchestrator.conversation.models import (
    ConversationContext,
    EncoderSignal,
    Lang,
    TakeoverActiveError,
    ToolOutcome,
    TurnEvalData,
    TurnMetadata,
    TurnResult,
)
from orchestrator.conversation.prompt import (
    FALLBACK_MESSAGES,
    FLOW_TEMPLATE,
    IDENTITY_REQUEST_ASK,
    IDENTITY_REQUEST_OPENINGS,
    PROMPT_VERSION,
    REPHRASE_MESSAGES,
    SYSTEM_PROMPT,
)
from orchestrator.conversation.tools import build_llm_tools, llm_tool_name
from orchestrator.conversation.trace import TraceRecorder
from orchestrator.encoder_client import EncoderClient, EncoderUnavailableError
from orchestrator.llm.provider import LLMProvider, LLMResponse
from orchestrator.privacy.masking import (
    Masker,
    MaskingError,
    RegexMasker,
    mask_json_string_values,
)
from orchestrator.privacy.spans import union_mask
from orchestrator.tools_client import BankingCoreClient

logger = logging.getLogger(__name__)

# Arguments that carry a secret or an identity claim, with the placeholder kind
# the masker gives that data. The model may only pass a placeholder of that kind
# the customer produced (present in the session mapping); a literal value would
# be a guess, and guessing burns attempts or enumerates. A placeholder of
# another kind (a `[DATE_1]` as OTP code) is a wrong value, not a secret.
SECRET_ARGS: dict[str, dict[str, PiiType]] = {
    "otp.verify": {"code": PiiType.OTP},
    "customer.match": {"document_number": PiiType.DOC},
}
# Tools that consume a limited attempt budget: at most one execution per turn.
ONCE_PER_TURN: frozenset[str] = frozenset({"otp.verify"})

# Output fields (dotted paths into `data`) the model is not shown. They differ on
# every run (random ids, audit sequence numbers, timestamps, queue length), so
# each LLM call after a write would get a new replay key, and the model does not
# need them to act. The customer-facing receipt and handoff blocks are built from
# the full ToolResult, so they keep everything. What stays is what the model acts
# on: card_ref, states, masked destination, verification outcome, department.
_RECEIPT_RUN_FIELDS = (
    "receipt.target_masked",
    "receipt.verified_at",
    "receipt.audit_id",
)
LLM_HIDDEN_FIELDS: dict[str, tuple[str, ...]] = {
    "otp.send": ("challenge_id", *_RECEIPT_RUN_FIELDS),
    "otp.verify": _RECEIPT_RUN_FIELDS,
    "card.block": _RECEIPT_RUN_FIELDS,
    "handoff.create": (
        "handoff_id",
        "queue_position",
        "created_at",
        "summary",
        *_RECEIPT_RUN_FIELDS,
    ),
}

# The summary of a handoff the engine creates itself: fixed text, so it says
# nothing the customer or the model could have steered and a retried turn asks
# banking-core for exactly the same write. The case facts (the disputed charge)
# are added server-side from the database.
ENGINE_HANDOFF_SUMMARY = (
    "Automatic escalation: policy requires a human to review this card block. "
    "The disputed charge, when one is linked, is in the verified facts."
)

# The opening of the fixed identity request names the customer's request: by the
# tool the model reached for or, when it reached for identification alone, by the
# intent of the enforced intent_hint (ADR-0014). Each topic comes with the tool that
# serves it, and a topic whose tool banking-core has not enabled is not named: the
# opening never offers what this bank does not do. Anything else opens neutrally.
# Identification steps (customer.match, otp.*) and helpers (card.list) name none.
IDENTITY_TOPIC_OF_TOOL: dict[str, str] = {
    "card.block": "card_block",
    "transaction.list_recent": "transactions",
    "account.get_summary": "balance",
}
IDENTITY_TOPIC_OF_INTENT: dict[str, tuple[str, str]] = {
    Intent.REQUEST_CARD_BLOCK: ("card_block", "card.block"),
    Intent.REPORT_LOST_CARD: ("card_block", "card.block"),
    Intent.REPORT_STOLEN_CARD: ("card_block", "card.block"),
    Intent.REPORT_SUSPICIOUS_ACTIVITY: ("card_block", "card.block"),
    Intent.REPORT_UNRECOGNIZED_CHARGE: ("charge", "handoff.create"),
    Intent.REQUEST_DISPUTE: ("charge", "handoff.create"),
    Intent.CHECK_RECENT_TRANSACTIONS: ("transactions", "transaction.list_recent"),
    Intent.CHECK_BALANCE: ("balance", "account.get_summary"),
}
_PRIORITY_ORDER = [
    HandoffPriority.LOW,
    HandoffPriority.NORMAL,
    HandoffPriority.HIGH,
    HandoffPriority.URGENT,
]

_OTP_PLACEHOLDER_RE = re.compile(r"^\[OTP_(\d+)\]$")
# A standalone 4-8 digit OTP, optionally with one internal space or dash.
_BARE_OTP_RE = re.compile(r"(?<![\w\[\]])\d+(?:[ -]\d+)?(?![\w\]])(?![ -]\d)")


@dataclass
class _TurnGuard:
    """Per-turn execution record enforced by the engine, not the prompt."""

    refused: dict[str, ReasonCode] = field(default_factory=dict)
    executed: set[str] = field(default_factory=set)
    # Writes banking-core acknowledged (status ok), per tool: the ordinal the
    # next write of that tool takes in its idempotency key.
    written: dict[str, int] = field(default_factory=dict)
    # The engine tries a required handoff at most once per turn; a failure is
    # retried on the next turn, not in a loop.
    required_handoff_tried: bool = False
    # The decision-point effects of the turn (ADR-0012); none in a bare guard.
    decisions: TurnDecisions | None = None
    # Tools banking-core's latest flow hint says are enabled somewhere (ADR-0016).
    enabled: list[str] | None = None
    # The session state of banking-core's latest flow hint: a tool result's, else
    # the one of session creation. None when banking-core has stated none.
    state: VerificationState | None = None


@dataclass(frozen=True)
class _RequiredHandoff:
    """A REQUIRED handoff a card.block decided and no handoff.create has answered."""

    requirement: HandoffRequirement
    transaction_id: str | None


class CompletionProvider(Protocol):
    """What the engine needs from the LLM layer (LLMProvider satisfies it)."""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = ...,
        tools: list[dict[str, Any]] | None = ...,
    ) -> LLMResponse: ...


class ToolCaller(Protocol):
    """What the engine needs from banking-core (BankingCoreClient satisfies it)."""

    async def call_tool(self, session_id: str, tool_call: ToolCall) -> ToolResult: ...


class Analyzer(Protocol):
    """What the engine needs from the encoder (EncoderClient satisfies it)."""

    async def analyze(
        self,
        text: str,
        lang: Lang | None = ...,
        decision_points: list[str] | None = ...,
        locale: Locale | None = ...,
    ) -> AnalyzeResponse: ...


class TurnEngine:
    """Runs one customer turn against a ConversationContext."""

    def __init__(
        self,
        llm: CompletionProvider,
        banking: ToolCaller,
        encoder: Analyzer | None = None,
        masker: Masker | None = None,
        max_tool_rounds: int = 5,
        collect_eval: bool = False,
        decisions: DecisionRuntime | None = None,
        collect_trace: bool = False,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be >= 1")
        self.llm = llm
        self.banking = banking
        self.encoder = encoder
        self.masker = masker or RegexMasker()
        self.max_tool_rounds = max_tool_rounds
        self.collect_eval = collect_eval
        # Detective mode (ADR-0019): each turn returns its timeline. Read-only.
        self.collect_trace = collect_trace
        # Without one, no decision point is configured: the engine is what it was.
        self.decisions = decisions or DecisionRuntime.empty()
        self.tools, self._tool_names = build_llm_tools()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        banking: ToolCaller | None = None,
        collect_eval: bool = False,
        collect_trace: bool = False,
    ) -> "TurnEngine":
        """Wire the engine from configuration and an optional shared client.

        Raises EffectsConfigError when the decision effects file is invalid: the
        service must not start with a gate it cannot read.
        """
        return cls(
            llm=LLMProvider(settings=settings),
            banking=banking or BankingCoreClient(settings=settings),
            encoder=EncoderClient(settings=settings)
            if settings.encoder_enabled
            else None,
            max_tool_rounds=settings.max_tool_rounds,
            collect_eval=collect_eval,
            decisions=DecisionRuntime.from_settings(settings),
            collect_trace=collect_trace,
        )

    async def run_turn(
        self,
        context: ConversationContext,
        user_text: str,
        lang: Lang | None = None,
        turn_id: str | None = None,
    ) -> TurnResult:
        """Run a turn. `context` is updated only if the turn completes.

        LLM errors (including a replay miss) propagate and leave `context`
        untouched, so a failed turn never persists a half-built transcript.

        `turn_id` names the customer request and seeds the idempotency keys of
        its writes. A caller that derives it from something the client repeats
        on a retry (the client message id) makes a retried request reuse the
        keys of the failed attempt, so banking-core answers from what it already
        did instead of acting twice. Without it the id is random and a retry is
        a new request.

        Raises TakeoverActiveError, before anything else happens, when a human
        agent holds the conversation: this is the one door to the LLM, the
        encoder and the tools, and it stays shut for a taken-over conversation.
        """
        if context.human_takeover:
            raise TakeoverActiveError(
                "A human agent holds this conversation; the engine does not run"
            )
        lang = lang or context.language
        metadata = TurnMetadata(turn_id=turn_id or uuid4().hex)
        eval_data = TurnEvalData()
        trace = (
            TraceRecorder(metadata.turn_id)
            if self.collect_trace
            else TraceRecorder.off()
        )
        mapping = dict(context.placeholder_map)
        previous = frozenset(mapping)
        history = copy.deepcopy(context.history)

        # 1. The encoder reads the raw text first (a local service on the edge
        # network, see docs/limitations.md): its intent goes to the metadata, its
        # decisions feed the decision-point effects (ADR-0012) and its PII spans
        # widen the masking below. It is optional: on any failure the turn goes
        # on masked by the regexes alone, never by less, and every decision point
        # counts as unavailable.
        turn_decisions = self.decisions.begin_turn(
            context.decisions.model_copy(deep=True), metadata
        )
        # The market rides along only while it agrees with the turn's language.
        locale = (
            context.locale
            if context.locale and lang_of(context.locale) == lang
            else None
        )
        metadata.locale = locale
        pii_spans = await self._analyze(
            user_text, lang, metadata, turn_decisions, locale, trace=trace
        )

        # 2. Mask the user text: the union of the regexes and the encoder's spans
        # (fail closed: nothing goes out if it fails). While an OTP challenge is
        # pending, a bare digit run is the code.
        mask_started = trace.now()
        text_to_mask = user_text
        otp_pending = otp_challenge_pending(history)
        if otp_pending:
            text_to_mask = self._mask_bare_otps(user_text, mapping)
        try:
            masked_user = self._mask_user_text(
                user_text, text_to_mask, mapping, previous, pii_spans, metadata
            )
        except MaskingError:
            logger.warning("Turn %s: user text failed masking", metadata.turn_id)
            metadata.masking_failed = True
            trace.masking(
                mask_started, None, [], metadata.masking_regex_only, 0, otp_pending
            )
            self._copy_decisions(eval_data, metadata)
            return TurnResult(
                blocks=[TextBlock(text=REPHRASE_MESSAGES[lang])],
                metadata=metadata,
                eval=eval_data,
                trace=self._finish_trace(trace, metadata),
            )
        trace.masking(
            mask_started,
            masked_user,
            [placeholder for placeholder in mapping if placeholder not in previous],
            metadata.masking_regex_only,
            metadata.encoder_spans_added,
            otp_pending,
        )

        history.append({"role": "user", "content": masked_user})

        # 3. An ambiguous opening may be answered by the canned clarification instead
        # of the LLM (ADR-0014): only in `enforce`, only before the LLM has answered
        # this conversation, never while a flow is in progress. In `shadow` it only
        # records what it would have done.
        canned = turn_decisions.canned_reply(
            lang,
            otp_pending=otp_pending,
            tool_seen=any(message.get("role") == "tool" for message in history),
        )
        if canned is not None:
            history.append({"role": "assistant", "content": canned})
            metadata.canned_reply = True
            trace.canned_reply()
            context.history = history
            context.placeholder_map = mapping
            context.decisions = turn_decisions.commit()
            self._copy_decisions(eval_data, metadata)
            return TurnResult(
                blocks=[TextBlock(text=canned)],
                metadata=metadata,
                eval=eval_data,
                trace=self._finish_trace(trace, metadata),
            )
        # The classification as context for every completion of the turn; None in
        # `shadow`, so the messages (and the replay keys) stay as they were.
        hint = turn_decisions.hint()
        hint_messages = [{"role": "system", "content": hint}] if hint else []

        # 4-5. LLM <-> tools loop, bounded
        receipts: list[ReceiptBlock] = []
        handoffs: list[HandoffBlock] = []
        guard = _TurnGuard(
            decisions=turn_decisions,
            enabled=context.enabled_tools,
            state=context.opening_flow.state if context.opening_flow else None,
        )
        final: LLMResponse | None = None
        identity_request: str | None = None
        while True:
            # Before every completion: a card.block of the last round, or of an
            # earlier turn whose handoff failed, may have left one required.
            await self._enforce_required_handoff(
                context.session_id,
                history,
                mapping,
                metadata,
                handoffs,
                guard,
                trace=trace,
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *hint_messages,
                *_opening_flow_messages(context.opening_flow, history),
                *history,
            ]
            context.enabled_tools = guard.enabled
            offered = self._offered(guard.enabled)
            llm_started = trace.now()
            response = await self.llm.complete(
                messages=messages,
                prompt_version=PROMPT_VERSION,
                tools=offered,
            )
            trace.llm_call(llm_started, messages, offered, response, PROMPT_VERSION)
            metadata.llm_recording_keys.append(response.recording_key)
            if self.collect_eval:
                outbound = response.masked_messages or messages
                eval_data.masked_outbound.append(
                    json.dumps(outbound, sort_keys=True, ensure_ascii=False)
                )
                eval_data.recording_keys.append(response.recording_key)
                eval_data.tokens += _usage_token_count(response.usage)
                if response.cost is not None:
                    eval_data.cost_usd += response.cost
            if not response.tool_calls:
                final = response
                break
            if metadata.tool_rounds >= self.max_tool_rounds:
                # Unexecuted tool calls are not added to history: no dangling calls.
                metadata.max_tool_rounds_reached = True
                logger.warning(
                    "Turn %s: max tool rounds (%d) reached",
                    metadata.turn_id,
                    self.max_tool_rounds,
                )
                break
            metadata.tool_rounds += 1
            round_start = len(metadata.tool_outcomes)
            await self._run_tool_round(
                context.session_id,
                response,
                history,
                mapping,
                metadata,
                receipts,
                handoffs,
                guard,
                lang,
                trace=trace,
            )
            round_outcomes = metadata.tool_outcomes[round_start:]
            if _needs_a_document(round_outcomes, mapping, history, guard.state):
                # Nothing was checked: ask for the document instead of letting the
                # model relay the refusal, which reads as a failed verification.
                topic = _identity_topic(
                    round_outcomes, turn_decisions.hinted_intent(), guard.enabled
                )
                identity_request = (
                    f"{IDENTITY_REQUEST_OPENINGS[topic][lang]} "
                    f"{IDENTITY_REQUEST_ASK[lang]}"
                )
                history.append({"role": "assistant", "content": identity_request})
                metadata.identity_requested = True
                trace.canned_reply(
                    note=f"asked for the document with the fixed identity request "
                    f"({topic} opening): the customer has given none yet, so "
                    "nothing was checked"
                )
                break

        # 6. Final reply through the block allowlist
        blocks_started = trace.now()
        blocks: list[TextBlock | ReceiptBlock | HandoffBlock] = (
            [TextBlock(text=identity_request)]
            if identity_request is not None
            else self._final_blocks(final, history, mapping, metadata, lang)
        )
        blocks.extend(receipts)
        blocks.extend(handoffs)
        if not blocks:
            blocks.append(TextBlock(text=FALLBACK_MESSAGES[lang]))
        trace.blocks(
            blocks_started,
            kept=[block.type for block in blocks],
            dropped=list(metadata.dropped_block_types),
            internal_lines_withheld=metadata.internal_lines_withheld,
            receipts=len(receipts),
            handoffs=len(handoffs),
            fallback=any(
                isinstance(block, TextBlock) and block.text == FALLBACK_MESSAGES[lang]
                for block in blocks
            ),
        )

        context.history = history
        context.placeholder_map = mapping
        context.decisions = turn_decisions.commit()
        self._copy_decisions(eval_data, metadata)
        return TurnResult(
            blocks=blocks,
            metadata=metadata,
            eval=eval_data,
            trace=self._finish_trace(trace, metadata),
        )

    # ------------------------------------------------------------------ steps

    async def _analyze(
        self,
        text: str,
        lang: Lang,
        metadata: TurnMetadata,
        decisions: TurnDecisions,
        locale: Locale | None = None,
        *,
        trace: TraceRecorder | None = None,
    ) -> list[PiiSpan]:
        """Record the encoder signal; return its PII spans (none if it failed).

        The decision points ride on the same call. Asking for them must never
        cost the PII spans, so only ids the encoder lists are named, and a 422
        (the listing went stale) is asked again for the service's default set.
        """
        trace = trace or TraceRecorder.off()
        started = trace.now()
        if self.encoder is None:
            self._observe(decisions, RequestPlan(), None, metadata)
            trace.encoder(started, None)
            return []
        plan = await self.decisions.plan(self.encoder)
        try:
            analysis = await self._ask_encoder(text, lang, plan, locale)
        except Exception as exc:
            # Any failure degrades the same way. Only the error type is logged
            # for an unexpected one: its message could quote the customer text.
            reason = (
                str(exc)
                if isinstance(exc, EncoderUnavailableError)
                else type(exc).__name__
            )
            logger.warning(
                "Turn %s: encoder unavailable (%s), masking with regexes only",
                metadata.turn_id,
                reason,
            )
            metadata.encoder_unavailable = True
            metadata.masking_regex_only = True
            self._observe(decisions, plan, None, metadata)
            trace.encoder(
                started,
                None,
                failure=f"encoder unavailable ({reason}): masking by the regexes alone",
            )
            return []
        trace.encoder(started, analysis)
        self._observe(decisions, plan, analysis, metadata)
        metadata.encoder = EncoderSignal(
            intent=analysis.intent,
            confidence=analysis.confidence,
            abstain=analysis.abstain,
            model_id=analysis.model_id,
        )
        metadata.encoder_pii_spans = len(analysis.pii_spans)
        return list(analysis.pii_spans)

    async def _ask_encoder(
        self, text: str, lang: Lang, plan: RequestPlan, locale: Locale | None = None
    ) -> AnalyzeResponse:
        assert self.encoder is not None
        # Only when set: an analyzer that predates locales keeps working.
        market: dict[str, Any] = {"locale": locale} if locale else {}
        if plan.ids is None:
            return await self.encoder.analyze(text, lang, **market)
        try:
            return await self.encoder.analyze(
                text, lang, decision_points=plan.ids, **market
            )
        except EncoderUnavailableError as exc:
            if exc.status_code != 422:
                raise
            logger.warning("Encoder refused the decision point ids; asking again")
            self.decisions.catalog.invalidate()
            return await self.encoder.analyze(text, lang, **market)

    @staticmethod
    def _observe(
        decisions: TurnDecisions,
        plan: RequestPlan,
        analysis: AnalyzeResponse | None,
        metadata: TurnMetadata,
    ) -> None:
        """Feed the decisions to the effects; a defect there never costs the turn.

        Nothing is lost in the safe direction: an effect that did not update its
        state leaves the gate closed and the LLM's arguments as they were.
        """
        try:
            decisions.observe(plan, analysis)
        except Exception as exc:
            logger.error(
                "Turn %s: decision effects failed (%s)",
                metadata.turn_id,
                type(exc).__name__,
            )

    @staticmethod
    def _copy_decisions(eval_data: TurnEvalData, metadata: TurnMetadata) -> None:
        """Hand the eval hook the turn's decision records (no text in them)."""
        eval_data.decisions = list(metadata.decisions)
        eval_data.effects = list(metadata.effects)

    @staticmethod
    def _finish_trace(trace: TraceRecorder, metadata: TurnMetadata) -> TurnTrace | None:
        """Close the timeline with the turn's decision records; None when it is off."""
        trace.decisions(
            metadata.decisions_config_version,
            list(metadata.decisions),
            list(metadata.effects),
        )
        return trace.build(PROMPT_VERSION, metadata.tool_rounds)

    async def _run_tool_round(
        self,
        session_id: str,
        response: LLMResponse,
        history: list[dict[str, Any]],
        mapping: dict[str, str],
        metadata: TurnMetadata,
        receipts: list[ReceiptBlock],
        handoffs: list[HandoffBlock],
        guard: _TurnGuard,
        lang: Lang,
        *,
        trace: TraceRecorder | None = None,
    ) -> None:
        trace = trace or TraceRecorder.off()
        parsed = [
            self._parse_tool_call(i, tc) for i, tc in enumerate(response.tool_calls)
        ]

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": self._mask_or_withhold(response.masked_content, mapping),
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": self._mask_args(args, mapping),
                    },
                }
                for call_id, name, args in parsed
            ],
        }
        history.append(assistant_msg)

        for (call_id, name, args), sent in zip(
            parsed, assistant_msg["tool_calls"], strict=True
        ):
            started = trace.now()
            result = await self._execute(
                session_id,
                name,
                args,
                mapping,
                history,
                metadata,
                guard,
                lang,
                trace=trace,
            )
            if result is not None:
                handoff = self._handoff_block_of(result)
                if handoff is not None:
                    handoffs.append(handoff)
                else:
                    receipt = self._receipt_of(result)
                    if receipt is not None:
                        receipts.append(ReceiptBlock(receipt=receipt))
            feedback = self._tool_feedback(name, result, mapping)
            history.append(
                {"role": "tool", "tool_call_id": call_id, "content": feedback}
            )
            # The strings the history already holds: the trace never masks again.
            trace.tool_call(
                started, call_id, name, sent["function"]["arguments"], result, feedback
            )

    async def _execute(
        self,
        session_id: str,
        name: str,
        args: dict[str, Any] | None,
        mapping: dict[str, str],
        history: list[dict[str, Any]],
        metadata: TurnMetadata,
        guard: _TurnGuard,
        lang: Lang,
        *,
        trace: TraceRecorder | None = None,
    ) -> ToolResult | None:
        trace = trace or TraceRecorder.off()
        tool = self._tool_names.get(name)
        if tool is None or args is None:
            trace.tool_outcome(
                tool or name,
                executed=False,
                local_reason="the model named a tool that does not exist"
                if tool is None
                else "the arguments were not valid JSON",
            )
            metadata.tool_outcomes.append(
                ToolOutcome(
                    tool=tool or name,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INVALID_ARGUMENTS,
                    executed=False,
                )
            )
            if tool is None:
                return None
            return self._local_error(tool)

        local = self._local_rejection(tool, args, mapping, history, guard)
        gated = False
        if local is None and guard.decisions is not None:
            # A write the customer has not consented to waits for the question the
            # model is about to ask. Nothing reaches banking-core, and the call
            # takes no idempotency ordinal.
            withheld = guard.decisions.gate(tool)
            if withheld is not None:
                guard.refused[tool] = withheld
                gated = True
                local = ToolResult(
                    tool=tool, status=ToolResultStatus.REFUSED, reason_code=withheld
                )
        if local is not None:
            reason = local.reason_code.value if local.reason_code else "unknown"
            trace.tool_outcome(
                tool,
                executed=False,
                local_reason=f"withheld by a decision gate until consent ({reason})"
                if gated
                else f"refused by the engine before banking-core ({reason})",
            )
            logger.warning(
                "Turn %s: %s rejected locally (%s)",
                metadata.turn_id,
                tool,
                local.reason_code.value if local.reason_code else None,
            )
            metadata.tool_outcomes.append(
                ToolOutcome(
                    tool=tool,
                    status=local.status,
                    reason_code=local.reason_code,
                    executed=False,
                )
            )
            return local

        definition = TOOL_CATALOG[tool]
        key = (
            self._idempotency_key(
                session_id, metadata.turn_id, tool, guard.written.get(tool, 0)
            )
            if definition.mutates_state
            else None
        )
        # Rehydrated values exist only in this request, never in history.
        try:
            tool_args = self._rehydrate(args, mapping)
            if tool == "otp.verify" and isinstance(tool_args, dict):
                code = tool_args.get("code")
                if isinstance(code, str):
                    tool_args["code"] = re.sub(r"[ -]", "", code)
            if isinstance(tool_args, dict):
                normalize_date_arguments(tool, tool_args, lang)
                if guard.decisions is not None:
                    tool_args = guard.decisions.select(tool, tool_args)
            tool_call = ToolCall(
                tool=tool,
                args=tool_args,
                idempotency_key=key,
            )
        except ValidationError:
            result = self._local_error(tool)
            executed = False
            trace.tool_outcome(
                tool,
                executed=False,
                local_reason="the arguments do not fit the tool contract",
            )
        else:
            result = await self.banking.call_tool(session_id, tool_call)
            executed = True
            trace.tool_outcome(tool, executed=True)
            guard.executed.add(tool)
            if result.flow is not None:
                guard.enabled = list(result.flow.enabled)
                guard.state = result.flow.state
            if result.status is ToolResultStatus.OK and definition.mutates_state:
                guard.written[tool] = guard.written.get(tool, 0) + 1
            elif result.status is ToolResultStatus.REFUSED:
                guard.refused[tool] = result.reason_code or ReasonCode.POLICY_BLOCKED
            if guard.decisions is not None:
                guard.decisions.after_result(tool, result)

        metadata.tool_outcomes.append(
            ToolOutcome(
                tool=tool,
                status=result.status,
                reason_code=result.reason_code,
                executed=executed,
            )
        )
        return result

    async def _enforce_required_handoff(
        self,
        session_id: str,
        history: list[dict[str, Any]],
        mapping: dict[str, str],
        metadata: TurnMetadata,
        handoffs: list[HandoffBlock],
        guard: _TurnGuard,
        *,
        trace: TraceRecorder | None = None,
    ) -> None:
        """Create the handoff a card.block required, if the model has not.

        Nothing here comes from the model's words: the reason, department and
        priority are the requirement banking-core returned, the transaction id
        is the one banking-core already accepted on the card.block, and the
        summary is fixed. The write takes the ordinal-based idempotency key of
        any other write, so a retried turn replays it instead of queueing twice.

        The call and its result go into the history like any tool round, success
        or failure, so the model's reply can only claim what happened. A failure
        is recorded (outcome and log) and, since the history still holds a
        required card.block and no successful handoff, tried again on the next
        turn.
        """
        if guard.required_handoff_tried:
            return
        pending = self._pending_required_handoff(history, mapping)
        if pending is None:
            return
        guard.required_handoff_tried = True

        tool = "handoff.create"
        requirement = pending.requirement
        # A REQUIRED requirement always carries all three (contract validator).
        if not (requirement.reason and requirement.priority and requirement.department):
            raise ValueError("a REQUIRED handoff requirement is missing its details")
        args: dict[str, Any] = {
            "reason": requirement.reason.value,
            "summary": ENGINE_HANDOFF_SUMMARY,
            "priority": requirement.priority.value,
            "department": requirement.department.value,
        }
        key = self._idempotency_key(
            session_id, metadata.turn_id, tool, guard.written.get(tool, 0)
        )
        try:
            call = ToolCall(
                tool=tool,
                args={**args, "transaction_id": pending.transaction_id}
                if pending.transaction_id
                else args,
                idempotency_key=key,
            )
        except ValidationError:
            # A transaction id that no longer fits the contract must not stop a
            # required escalation: banking-core still routes and prioritizes it.
            call = ToolCall(tool=tool, args=args, idempotency_key=key)

        trace = trace or TraceRecorder.off()
        started = trace.now()
        result = await self.banking.call_tool(session_id, call)
        trace.tool_outcome(tool, executed=True)
        guard.executed.add(tool)
        if result.status is ToolResultStatus.OK:
            guard.written[tool] = guard.written.get(tool, 0) + 1
        else:
            logger.warning(
                "Turn %s: required handoff failed (%s %s); retried next turn",
                metadata.turn_id,
                result.status.value,
                result.reason_code.value if result.reason_code else None,
            )
        metadata.tool_outcomes.append(
            ToolOutcome(
                tool=tool,
                status=result.status,
                reason_code=result.reason_code,
                executed=True,
            )
        )

        llm_name = next(n for n, t in self._tool_names.items() if t == tool)
        call_id = f"call_engine_{key[3:15]}"
        history.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": llm_name,
                            "arguments": self._mask_args(call.args, mapping),
                        },
                    }
                ],
            }
        )
        history.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": self._tool_feedback(llm_name, result, mapping),
            }
        )
        trace.tool_call(
            started,
            call_id,
            llm_name,
            history[-2]["tool_calls"][0]["function"]["arguments"],
            result,
            history[-1]["content"],
            kind=TraceEventKind.ENGINE_HANDOFF,
        )
        block = self._handoff_block_of(result)
        if block is not None:
            handoffs.append(block)

    def _pending_required_handoff(
        self, history: list[dict[str, Any]], mapping: dict[str, str]
    ) -> _RequiredHandoff | None:
        """The strongest REQUIRED card.block in the history, if no handoff succeeded.

        Read from the history so a retried turn and the next turn after a
        failed attempt see the same thing the first attempt did.
        """
        if any(
            result.get("tool") == "handoff.create" and result.get("status") == "ok"
            for _, result in _tool_results(history)
        ):
            return None

        calls: dict[str, dict[str, Any]] = {}
        best: tuple[int, _RequiredHandoff] | None = None
        for message in history:
            if message.get("role") == "assistant":
                for tool_call in message.get("tool_calls") or []:
                    calls[str(tool_call.get("id"))] = tool_call
                continue
            if message.get("role") != "tool":
                continue
            try:
                result = json.loads(message.get("content") or "")
            except ValueError:
                continue
            if (
                not isinstance(result, dict)
                or result.get("tool") != "card.block"
                or result.get("status") != "ok"
            ):
                continue
            requirement = _requirement_of(result)
            if requirement is None or requirement.level is not (
                HandoffRequirementLevel.REQUIRED
            ):
                continue
            rank = _PRIORITY_ORDER.index(requirement.priority or HandoffPriority.LOW)
            if best is None or rank > best[0]:
                transaction_id = self._transaction_id_of(
                    calls.get(str(message.get("tool_call_id"))), mapping
                )
                best = (rank, _RequiredHandoff(requirement, transaction_id))
        return best[1] if best is not None else None

    def _transaction_id_of(
        self, tool_call: dict[str, Any] | None, mapping: dict[str, str]
    ) -> str | None:
        """The transaction_id of a recorded tool call, placeholders restored."""
        function = (tool_call or {}).get("function")
        if not isinstance(function, dict):
            return None
        try:
            args = json.loads(function.get("arguments") or "")
        except ValueError:
            return None
        value = args.get("transaction_id") if isinstance(args, dict) else None
        if not isinstance(value, str):
            return None
        return self._rehydrate(value, mapping) or None

    def _final_blocks(
        self,
        final: LLMResponse | None,
        history: list[dict[str, Any]],
        mapping: dict[str, str],
        metadata: TurnMetadata,
        lang: Lang,
    ) -> list[TextBlock | ReceiptBlock | HandoffBlock]:
        if final is None:
            text = FALLBACK_MESSAGES[lang]
            history.append({"role": "assistant", "content": text})
            return [TextBlock(text=text)]

        try:
            masked_reply = self._mask_or_none(final.masked_content, mapping)
        except MaskingError:
            logger.warning("Turn %s: model reply failed masking", metadata.turn_id)
            text = FALLBACK_MESSAGES[lang]
            history.append({"role": "assistant", "content": text})
            return [TextBlock(text=text)]

        kept, dropped = filter_model_blocks(masked_reply)
        metadata.dropped_block_types.extend(dropped)
        # A line naming the model's context (the flow line, a state, a tool) never
        # reaches the customer, nor the history the next completion reads.
        texts: list[str] = []
        for block in kept:
            text, withheld = withhold_internal_lines(block.text)
            metadata.internal_lines_withheld += withheld
            if text:
                texts.append(text)
        # The same answer written twice in one completion reaches the customer once.
        texts, repeated = drop_repeated_lines(texts)
        if metadata.internal_lines_withheld or repeated:
            masked_reply = "\n\n".join(texts) or FALLBACK_MESSAGES[lang]
            texts = texts or [FALLBACK_MESSAGES[lang]]
        history.append({"role": "assistant", "content": masked_reply})
        # The customer sees their own values back, never placeholders.
        return [
            TextBlock(text=self.masker.unmask(text, mapping)[:MAX_TEXT_LENGTH])
            for text in texts
        ]

    # ---------------------------------------------------------------- guards

    @staticmethod
    def _local_rejection(
        tool: str,
        args: dict[str, Any],
        mapping: dict[str, str],
        history: list[dict[str, Any]],
        guard: _TurnGuard,
    ) -> ToolResult | None:
        """Engine-enforced limits; the prompt only explains them to the model."""
        if tool in guard.refused:
            # Refused earlier this turn: relay the same refusal, never re-run.
            return ToolResult(
                tool=tool,
                status=ToolResultStatus.REFUSED,
                reason_code=guard.refused[tool],
            )
        if tool in ONCE_PER_TURN and tool in guard.executed:
            return ToolResult(
                tool=tool,
                status=ToolResultStatus.REFUSED,
                reason_code=ReasonCode.RATE_LIMITED,
            )
        for arg, kind in SECRET_ARGS.get(tool, {}).items():
            value = args.get(arg)
            if not (
                isinstance(value, str)
                and _is_placeholder(value, kind)
                and value in mapping
                # Tool results are masked into the same mapping: a number in a
                # knowledge-base snippet must not pass for the customer's own.
                and _customer_wrote(value, history)
            ):
                return ToolResult(
                    tool=tool,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INVALID_ARGUMENTS,
                )
        if tool == "otp.verify" and _otp_code_is_stale(args["code"], history):
            return ToolResult(
                tool=tool,
                status=ToolResultStatus.ERROR,
                reason_code=ReasonCode.INVALID_ARGUMENTS,
            )
        return None

    @staticmethod
    def _mask_bare_otps(text: str, mapping: dict[str, str]) -> str:
        return mask_bare_otps(text, mapping)

    # ---------------------------------------------------------------- helpers

    def _mask(self, text: str, mapping: dict[str, str]) -> str:
        result = self.masker.mask(text, state=mapping)
        mapping.update(result.mapping)
        if not self.masker.verify_safe(result.masked_text):
            raise MaskingError("residual PII after masking")
        return result.masked_text

    def _mask_user_text(
        self,
        raw_text: str,
        text_to_mask: str,
        mapping: dict[str, str],
        previous: frozenset[str],
        pii_spans: list[PiiSpan],
        metadata: TurnMetadata,
    ) -> str:
        """Regex masking of the customer text, widened by the encoder's PII spans.

        `raw_text` is what the encoder saw (its offsets refer to it);
        `text_to_mask` is the same text after the pending-OTP pre-pass. With no
        spans the result is exactly the regex masking.
        """
        masked = self._mask(text_to_mask, mapping)
        if not pii_spans:
            return masked
        union = union_mask(self.masker, raw_text, masked, mapping, previous, pii_spans)
        metadata.encoder_spans_added = union.spans_added
        return union.masked_text

    def _mask_or_none(self, text: str | None, mapping: dict[str, str]) -> str | None:
        return self._mask(text, mapping) if text else text

    def _mask_or_withhold(
        self, text: str | None, mapping: dict[str, str]
    ) -> str | None:
        try:
            return self._mask_or_none(text, mapping)
        except MaskingError:
            logger.warning("Assistant text failed masking; withheld from history")
            return None

    def _mask_args(self, args: dict[str, Any] | None, mapping: dict[str, str]) -> str:
        if args is None:
            return "{}"
        try:
            return self._mask(
                json.dumps(args, sort_keys=True, ensure_ascii=False), mapping
            )
        except MaskingError:
            logger.warning("Tool call arguments failed masking; withheld from history")
            return "{}"

    def _parse_tool_call(
        self, index: int, raw: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Return (call id, llm tool name, args or None if unparseable)."""
        call_id = str(raw.get("id") or f"call_{index}")
        fn = raw.get("function")
        fn = fn if isinstance(fn, dict) else {}
        name = str(fn.get("name") or "")
        raw_args = fn.get("arguments")
        args: Any
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except ValueError:
                args = None
        elif raw_args is None:
            args = {}
        else:
            args = raw_args
        return call_id, name, args if isinstance(args, dict) else None

    def _rehydrate(self, value: Any, mapping: dict[str, str]) -> Any:
        if isinstance(value, str):
            return self.masker.unmask(value, mapping)
        if isinstance(value, list):
            return [self._rehydrate(v, mapping) for v in value]
        if isinstance(value, dict):
            return {k: self._rehydrate(v, mapping) for k, v in value.items()}
        return value

    def _offered(self, enabled: list[str] | None) -> list[dict[str, Any]]:
        """The tool schemas to offer: all of them until banking-core has said which
        tools the configuration enables, then only those (ADR-0016). A tool
        disabled everywhere is one the model could only be refused."""
        if enabled is None:
            return self.tools
        allowed = set(enabled)
        return [
            tool
            for tool in self.tools
            if self._tool_names.get(tool["function"]["name"]) in allowed
        ]

    def _tool_feedback(
        self, name: str, result: ToolResult | None, mapping: dict[str, str]
    ) -> str:
        if result is None:
            payload: dict[str, Any] = {
                "tool": name,
                "status": ToolResultStatus.ERROR.value,
                "reason_code": ReasonCode.INVALID_ARGUMENTS.value,
                "data": None,
            }
        else:
            payload = result.model_dump(mode="json")
            for path in LLM_HIDDEN_FIELDS.get(result.tool, ()):
                _drop_field(payload.get("data"), path)
            _name_flow_tools(payload)
        try:
            masked = mask_json_string_values(payload, self.masker, mapping)
            return json.dumps(masked, sort_keys=True, ensure_ascii=False)
        except MaskingError:
            logger.warning("Tool result for %s failed masking; data withheld", name)
            # The requirement is three enum values and no customer data: it stays,
            # or a required handoff would vanish with the rest of the data.
            payload["data"] = _requirement_only(result)
            masked = mask_json_string_values(payload, self.masker, mapping)
            return json.dumps(masked, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _receipt_of(result: ToolResult) -> Receipt | None:
        if result.status is not ToolResultStatus.OK or not result.data:
            return None
        if not TOOL_CATALOG[result.tool].mutates_state:
            return None
        raw = result.data.get("receipt")
        return Receipt.model_validate(raw) if raw is not None else None

    @staticmethod
    def _handoff_block_of(result: ToolResult | None) -> HandoffBlock | None:
        if (
            result is None
            or result.tool != "handoff.create"
            or result.status is not ToolResultStatus.OK
            or result.data is None
        ):
            return None
        try:
            output = HandoffCreateOutput.model_validate(result.data)
            receipt = TurnEngine._receipt_of(result)
        except ValidationError:
            return None
        if receipt is None:
            return None
        return HandoffBlock(
            handoff_id=output.handoff_id,
            summary=output.summary,
            status=output.status,
            department=output.department,
            priority=output.priority,
            queue_position=output.queue_position,
            receipt=receipt,
        )

    @staticmethod
    def _local_error(tool: str) -> ToolResult:
        return ToolResult(
            tool=tool,
            status=ToolResultStatus.ERROR,
            reason_code=ReasonCode.INVALID_ARGUMENTS,
        )

    @staticmethod
    def _idempotency_key(session_id: str, turn_id: str, tool: str, ordinal: int) -> str:
        """Stable per (session, turn, tool, ordinal): a retried turn cannot act twice.

        The ordinal counts the tool's acknowledged writes so far in the turn. It
        replaces the model's call id, which is random on every completion, so a
        re-run of the turn asks banking-core for the same thing under the same
        key. A call that failed without an acknowledgement keeps its ordinal:
        the retry is the same write, and banking-core answers from its record if
        the first attempt got through, or does it now.
        """
        digest = hashlib.sha256(
            f"{session_id}|{turn_id}|{tool}|{ordinal}".encode()
        ).hexdigest()
        return f"pb-{digest[:40]}"


def _needs_a_document(
    outcomes: list[ToolOutcome],
    mapping: dict[str, str],
    history: list[dict[str, Any]],
    state: VerificationState | None,
) -> bool:
    """True when a tool round only reached for identification before the customer
    gave a document: banking-core last stated the session ANONYMOUS, no customer
    message holds a `[DOC_n]` (one masked out of a tool result does not count),
    and every call was refused for that, either
    customer.match by the engine (no document placeholder) or a tool by
    banking-core's state check. Nothing ran, so the session is where it was."""
    if state is not VerificationState.ANONYMOUS or not outcomes:
        return False
    if any(
        _is_placeholder(placeholder, PiiType.DOC)
        and _customer_wrote(placeholder, history)
        for placeholder in mapping
    ):
        return False
    return all(
        (
            outcome.tool == "customer.match"
            and not outcome.executed
            and outcome.reason_code is ReasonCode.INVALID_ARGUMENTS
        )
        or outcome.reason_code is ReasonCode.STATE_NOT_ALLOWED
        for outcome in outcomes
    )


def _identity_topic(
    outcomes: list[ToolOutcome],
    hinted_intent: str | None,
    enabled: list[str] | None,
) -> str:
    """The opening of the fixed identity request: the topic of the first tool the
    model reached for that serves a request, else the topic of the hinted intent,
    as long as banking-core has enabled the tool that serves it; else neutral."""
    candidates = [
        (IDENTITY_TOPIC_OF_TOOL[outcome.tool], outcome.tool)
        for outcome in outcomes
        if outcome.tool in IDENTITY_TOPIC_OF_TOOL
    ]
    if hinted_intent is not None and hinted_intent in IDENTITY_TOPIC_OF_INTENT:
        candidates.append(IDENTITY_TOPIC_OF_INTENT[hinted_intent])
    for topic, tool in candidates:
        if enabled is not None and tool in enabled:
            return topic
    return "neutral"


def _is_placeholder(value: str, kind: PiiType) -> bool:
    """True if `value` is exactly one placeholder of `kind`, e.g. `[OTP_3]`."""
    return re.fullmatch(rf"\[{kind.value}_\d+\]", value) is not None


def _requirement_only(result: ToolResult | None) -> dict[str, Any] | None:
    """The handoff_requirement of an ok card.block result, on its own, else None."""
    if (
        result is None
        or result.tool != "card.block"
        or result.status is not ToolResultStatus.OK
        or not result.data
    ):
        return None
    raw = result.data.get("handoff_requirement")
    if raw is None:
        return None
    try:
        return {
            "handoff_requirement": HandoffRequirement.model_validate(raw).model_dump(
                mode="json"
            )
        }
    except ValidationError:
        return None


def _requirement_of(result: dict[str, Any]) -> HandoffRequirement | None:
    """The handoff_requirement of a card.block result; none if it has none."""
    data = result.get("data")
    raw = data.get("handoff_requirement") if isinstance(data, dict) else None
    if raw is None:
        return None
    try:
        return HandoffRequirement.model_validate(raw)
    except ValidationError:
        logger.warning("card.block returned a handoff_requirement that does not parse")
        return None


def _drop_field(data: Any, path: str) -> None:
    """Remove the dotted `path` from nested dicts, if present."""
    *parents, leaf = path.split(".")
    for key in parents:
        data = data.get(key) if isinstance(data, dict) else None
    if isinstance(data, dict):
        data.pop(leaf, None)


def _tool_results(
    history: list[dict[str, Any]],
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (index, result) for every tool message that holds a JSON object."""
    for index, message in enumerate(history):
        if message.get("role") != "tool":
            continue
        try:
            result = json.loads(message.get("content") or "")
        except ValueError:
            continue
        if isinstance(result, dict):
            yield index, result


def _opening_flow_messages(
    flow: FlowHint | None, history: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """The session-creation flow hint as one system line, until a tool result is in
    the history and carries the hint itself (ADR-0016 amendment 2026-10-02)."""
    if flow is None or not flow.next:
        return []
    if any(message.get("role") == "tool" for message in history):
        return []
    line = FLOW_TEMPLATE.format(
        state=flow.state.value,
        next=" or ".join(f"`{llm_tool_name(tool)}`" for tool in flow.next),
    )
    return [{"role": "system", "content": line}]


def _name_flow_tools(payload: dict[str, Any]) -> None:
    """banking-core's flow hint (ADR-0016) names catalog tools (`otp.send`); the
    model was offered function names (`otp_send`). Rename, and drop the hint's
    empty fields so the model reads only what is there."""
    flow = payload.get("flow")
    if not isinstance(flow, dict):
        payload.pop("flow", None)
        return
    # `enabled` shapes the offered tools; the model need not read it.
    flow.pop("enabled", None)
    for key in ("next", "allowed"):
        if isinstance(flow.get(key), list):
            flow[key] = [llm_tool_name(str(tool)) for tool in flow[key]]
    if flow.get("required_states") is None:
        flow.pop("required_states", None)


def mask_bare_otps(text: str, mapping: dict[str, str]) -> str:
    """Mask standalone 4-8 digit OTPs with one optional separator when pending.

    `mapping` (placeholder -> raw) gains the new `[OTP_n]` placeholders.
    """
    # Reuse only OTP placeholders: a code equal to an earlier value of
    # another kind (a 6-digit document) must not resolve to that one.
    reverse = {raw: ph for ph, raw in mapping.items() if _OTP_PLACEHOLDER_RE.match(ph)}
    next_index = max(
        (int(m.group(1)) for ph in mapping if (m := _OTP_PLACEHOLDER_RE.match(ph))),
        default=0,
    )

    def repl(match: re.Match[str]) -> str:
        nonlocal next_index
        raw = match.group(0)
        digits = raw.replace(" ", "").replace("-", "")
        if not 4 <= len(digits) <= 8:
            return raw
        if raw in reverse:
            return reverse[raw]
        next_index += 1
        placeholder = f"[OTP_{next_index}]"
        mapping[placeholder] = raw
        reverse[raw] = placeholder
        return placeholder

    return _BARE_OTP_RE.sub(repl, text)


def otp_challenge_pending(history: list[dict[str, Any]]) -> bool:
    """True if an otp.send succeeded and no otp.verify has closed it since."""
    pending = False
    for _, result in _tool_results(history):
        if result.get("status") != "ok":
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if result.get("tool") == "otp.send":
            pending = True
        elif result.get("tool") == "otp.verify":
            pending = data.get("state") == "OTP_PENDING"
    return pending


def _customer_wrote(placeholder: str, history: list[dict[str, Any]]) -> bool:
    """True if the placeholder is in one of the customer's own messages."""
    return any(
        message.get("role") == "user"
        and placeholder in str(message.get("content") or "")
        for message in history
    )


def _otp_code_is_stale(placeholder: str, history: list[dict[str, Any]]) -> bool:
    """True if the customer last typed this code before the latest otp.send.

    A code typed before the current challenge belongs to an older one. With no
    successful otp.send in the history there is nothing to compare against, and
    the FSM in banking-core refuses the call.
    """
    last_send = max(
        (
            index
            for index, result in _tool_results(history)
            if result.get("tool") == "otp.send" and result.get("status") == "ok"
        ),
        default=None,
    )
    if last_send is None:
        return False
    return not any(
        message.get("role") == "user"
        and placeholder in str(message.get("content") or "")
        for message in history[last_send + 1 :]
    )


def _usage_token_count(usage: dict[str, Any]) -> int:
    total = usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    return sum(
        value
        for value in (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )
