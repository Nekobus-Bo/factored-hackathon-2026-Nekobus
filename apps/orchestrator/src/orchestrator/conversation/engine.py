"""Conversation turn engine: mask -> encoder (optional) -> LLM <-> tools -> blocks.

The model proposes tool calls; banking-core decides (AGENTS rules 1 and 2).
The engine never retries a refused call and never alters model arguments
beyond rehydrating placeholders for the banking-core request.
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
    PiiType,
    ReasonCode,
    Receipt,
    ReceiptBlock,
    TextBlock,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from contracts.tools.handoff_create import HandoffCreateOutput
from pydantic import ValidationError

from orchestrator.config import Settings
from orchestrator.conversation.blocks import MAX_TEXT_LENGTH, filter_model_blocks
from orchestrator.conversation.dates import normalize_date_arguments
from orchestrator.conversation.models import (
    ConversationContext,
    EncoderSignal,
    Lang,
    ToolOutcome,
    TurnEvalData,
    TurnMetadata,
    TurnResult,
)
from orchestrator.conversation.prompt import (
    FALLBACK_MESSAGES,
    PROMPT_VERSION,
    REPHRASE_MESSAGES,
    SYSTEM_PROMPT,
)
from orchestrator.conversation.tools import build_llm_tools
from orchestrator.encoder_client import EncoderClient, EncoderUnavailableError
from orchestrator.llm.provider import LLMProvider, LLMResponse
from orchestrator.privacy.masking import (
    Masker,
    MaskingError,
    RegexMasker,
    mask_json_string_values,
)
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

    async def analyze(self, text: str, lang: Lang | None = ...) -> AnalyzeResponse: ...


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
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be >= 1")
        self.llm = llm
        self.banking = banking
        self.encoder = encoder
        self.masker = masker or RegexMasker()
        self.max_tool_rounds = max_tool_rounds
        self.collect_eval = collect_eval
        self.tools, self._tool_names = build_llm_tools()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        banking: ToolCaller | None = None,
        collect_eval: bool = False,
    ) -> "TurnEngine":
        """Wire the engine from configuration and an optional shared client."""
        return cls(
            llm=LLMProvider(settings=settings),
            banking=banking or BankingCoreClient(settings=settings),
            encoder=EncoderClient(settings=settings)
            if settings.encoder_enabled
            else None,
            max_tool_rounds=settings.max_tool_rounds,
            collect_eval=collect_eval,
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
        """
        lang = lang or context.language
        metadata = TurnMetadata(turn_id=turn_id or uuid4().hex)
        eval_data = TurnEvalData()
        mapping = dict(context.placeholder_map)
        history = copy.deepcopy(context.history)

        # 1. Mask the user text (fail closed: nothing goes out if it fails).
        # While an OTP challenge is pending, a bare digit run is the code.
        text_to_mask = user_text
        if _otp_challenge_pending(history):
            text_to_mask = self._mask_bare_otps(user_text, mapping)
        try:
            masked_user = self._mask(text_to_mask, mapping)
        except MaskingError:
            logger.warning("Turn %s: user text failed masking", metadata.turn_id)
            metadata.masking_failed = True
            return TurnResult(
                blocks=[TextBlock(text=REPHRASE_MESSAGES[lang])], metadata=metadata
            )

        # 2. Optional encoder signal; degrade to LLM-only on any failure
        await self._analyze(user_text, lang, metadata)

        history.append({"role": "user", "content": masked_user})

        # 3-4. LLM <-> tools loop, bounded
        receipts: list[ReceiptBlock] = []
        handoffs: list[HandoffBlock] = []
        guard = _TurnGuard()
        final: LLMResponse | None = None
        while True:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
            response = await self.llm.complete(
                messages=messages,
                prompt_version=PROMPT_VERSION,
                tools=self.tools,
            )
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
            )

        # 5. Final reply through the block allowlist
        blocks: list[TextBlock | ReceiptBlock | HandoffBlock] = self._final_blocks(
            final, history, mapping, metadata, lang
        )
        blocks.extend(receipts)
        blocks.extend(handoffs)
        if not blocks:
            blocks.append(TextBlock(text=FALLBACK_MESSAGES[lang]))

        context.history = history
        context.placeholder_map = mapping
        return TurnResult(blocks=blocks, metadata=metadata, eval=eval_data)

    # ------------------------------------------------------------------ steps

    async def _analyze(self, text: str, lang: Lang, metadata: TurnMetadata) -> None:
        if self.encoder is None:
            return
        try:
            analysis = await self.encoder.analyze(text, lang)
        except EncoderUnavailableError as exc:
            logger.warning(
                "Turn %s: encoder unavailable (%s), continuing LLM-only",
                metadata.turn_id,
                exc,
            )
            metadata.encoder_unavailable = True
            return
        metadata.encoder = EncoderSignal(
            intent=analysis.intent,
            confidence=analysis.confidence,
            abstain=analysis.abstain,
            model_id=analysis.model_id,
        )

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
    ) -> None:
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

        for call_id, name, args in parsed:
            result = await self._execute(
                session_id, name, args, mapping, history, metadata, guard, lang
            )
            if result is not None:
                handoff = self._handoff_block_of(result)
                if handoff is not None:
                    handoffs.append(handoff)
                else:
                    receipt = self._receipt_of(result)
                    if receipt is not None:
                        receipts.append(ReceiptBlock(receipt=receipt))
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": self._tool_feedback(name, result, mapping),
                }
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
    ) -> ToolResult | None:
        tool = self._tool_names.get(name)
        if tool is None or args is None:
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
        if local is not None:
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
            tool_call = ToolCall(
                tool=tool,
                args=tool_args,
                idempotency_key=key,
            )
        except ValidationError:
            result = self._local_error(tool)
            executed = False
        else:
            result = await self.banking.call_tool(session_id, tool_call)
            executed = True
            guard.executed.add(tool)
            if result.status is ToolResultStatus.OK and definition.mutates_state:
                guard.written[tool] = guard.written.get(tool, 0) + 1
            elif result.status is ToolResultStatus.REFUSED:
                guard.refused[tool] = result.reason_code or ReasonCode.POLICY_BLOCKED

        metadata.tool_outcomes.append(
            ToolOutcome(
                tool=tool,
                status=result.status,
                reason_code=result.reason_code,
                executed=executed,
            )
        )
        return result

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

        history.append({"role": "assistant", "content": masked_reply})
        kept, dropped = filter_model_blocks(masked_reply)
        metadata.dropped_block_types.extend(dropped)
        # The customer sees their own values back, never placeholders.
        return [
            TextBlock(text=self.masker.unmask(block.text, mapping)[:MAX_TEXT_LENGTH])
            for block in kept
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
        """Mask standalone 4-8 digit OTPs with one optional separator when pending."""
        # Reuse only OTP placeholders: a code equal to an earlier value of
        # another kind (a 6-digit document) must not resolve to that one.
        reverse = {
            raw: ph for ph, raw in mapping.items() if _OTP_PLACEHOLDER_RE.match(ph)
        }
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

    # ---------------------------------------------------------------- helpers

    def _mask(self, text: str, mapping: dict[str, str]) -> str:
        result = self.masker.mask(text, state=mapping)
        mapping.update(result.mapping)
        if not self.masker.verify_safe(result.masked_text):
            raise MaskingError("residual PII after masking")
        return result.masked_text

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
        try:
            masked = mask_json_string_values(payload, self.masker, mapping)
            return json.dumps(masked, sort_keys=True, ensure_ascii=False)
        except MaskingError:
            logger.warning("Tool result for %s failed masking; data withheld", name)
            payload["data"] = None
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


def _is_placeholder(value: str, kind: PiiType) -> bool:
    """True if `value` is exactly one placeholder of `kind`, e.g. `[OTP_3]`."""
    return re.fullmatch(rf"\[{kind.value}_\d+\]", value) is not None


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


def _otp_challenge_pending(history: list[dict[str, Any]]) -> bool:
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
