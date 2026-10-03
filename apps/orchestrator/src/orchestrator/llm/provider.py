"""LLM Provider layer using LiteLLM (ADR-0001, ADR-0004).

Enforces:
- Outbound PII masking on EVERY message (no raw emails/phones/PANs/docs reach LLM).
- Every string field is inspected/verified (content, tool arguments, list parts).
- Server-side tool_call placeholder rehydration for banking-core execution.
- Deterministic replay check via ReplayManager before making network calls.
- Telemetry and third-party callbacks explicitly disabled.
- Token and USD cost tracking logging (without logging any PII).
- Response rehydration (unmasking) for caller consumption.
"""

import copy
import json
import logging
from typing import Any

import litellm
from contracts import TOOL_CATALOG, ToolResult
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from orchestrator.config import Settings, get_settings
from orchestrator.llm.replay import (
    RecordedResponse,
    ReplayManager,
    ReplayMissError,
    compute_recording_key,
    compute_tool_schema_hash,
)
from orchestrator.privacy.masking import (
    PLACEHOLDER_RE,
    Masker,
    MaskingError,
    RegexMasker,
    mask_json_string_values,
)

logger = logging.getLogger(__name__)


class LLMResponse(BaseModel):
    """Response returned by LLMProvider."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, description="Rehydrated text for caller")
    masked_content: str | None = Field(
        default=None, description="Raw masked text from LLM"
    )
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list, description="Tool calls proposed by the model (masked)"
    )
    rehydrated_tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Tool calls with placeholders rehydrated for banking-core execution"
        ),
    )

    masked_messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Exact outbound messages after PII masking",
    )
    usage: dict[str, Any] = Field(
        default_factory=dict, description="Token usage statistics"
    )
    cost: float | None = Field(default=None, description="Calculated USD cost")
    model: str = Field(..., description="Model identifier used")
    recording_key: str = Field(..., description="Deterministic replay key")
    cached: bool = Field(default=False, description="True if served from replay")


def _reserve_placeholders(messages: list[Any]) -> dict[str, str]:
    """Reserve the placeholders the engine already put in the messages.

    The engine masks with the conversation's mapping, which this provider does
    not hold. A placeholder minted here must not reuse one of those indexes: the
    engine would unmask the model's echo of it to a different value (a balance
    shown as the customer's document number). Each placeholder maps to itself,
    so the masker's counters start past it and unmasking leaves it unchanged.
    """
    try:
        text = json.dumps(messages, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {}
    return {m.group(0): m.group(0) for m in PLACEHOLDER_RE.finditer(text)}


class LLMProvider:
    """LiteLLM wrapper providing fail-closed PII masking and replay capabilities."""

    def __init__(
        self,
        settings: Settings | None = None,
        masker: Masker | None = None,
        replay_manager: ReplayManager | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.llm_model
        self.base_url = self.settings.effective_base_url
        self.api_key = self.settings.effective_api_key
        self.timeout = self.settings.llm_timeout_seconds
        self.retries = self.settings.llm_max_retries
        self.reasoning_effort = self.settings.effective_reasoning_effort
        self.temperature = self.settings.llm_temperature
        self.mode = self.settings.llm_mode
        self.replay_on_miss = self.settings.llm_replay_on_miss
        self.record = self.settings.record

        # Explicitly disable litellm telemetry and third-party callbacks (P2)
        litellm.telemetry = False
        litellm.success_callback = []
        litellm.failure_callback = []

        self.masker = masker or RegexMasker()
        self.replay_manager = replay_manager or ReplayManager(
            replay_dir=self.settings.replay_dir,
            mode=self.mode,
            record=self.record,
            replay_on_miss=self.replay_on_miss,
        )

    def _mask_and_verify_string(
        self,
        text: str,
        state: dict[str, str],
        field_desc: str,
    ) -> str:
        """Mask a single string and verify it is safe.

        Raises MaskingError on failure.
        """
        if not text:
            return text
        mask_res = self.masker.mask(text, state=state)
        state.update(mask_res.mapping)
        if not self.masker.verify_safe(mask_res.masked_text):
            raise MaskingError(
                f"Outbound field '{field_desc}' failed PII safety check after masking"
            )
        return mask_res.masked_text

    @staticmethod
    def _is_tool_result_envelope(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        # The engine renames the flow hint's tools to function names (`otp_send`),
        # so the hint fails ToolResult validation; it is still part of the envelope.
        # Without it, the result is masked as text and a COP balance in minor units
        # (7+ digits) reads as a document number.
        keys = set(payload)
        if keys - {"flow"} != {"tool", "status", "reason_code", "data"}:
            return False
        if not isinstance(payload.get("flow", {}), dict | None):
            return False
        tool = payload.get("tool")
        status = payload.get("status")
        data = payload.get("data")
        reason_code = payload.get("reason_code")
        if not isinstance(tool, str) or tool not in TOOL_CATALOG:
            return False
        if status == "ok":
            return reason_code is None and isinstance(data, dict)
        return (
            status in {"refused", "error"}
            and data is None
            and isinstance(reason_code, str)
        )

    def _mask_tool_result_content(self, text: str, state: dict[str, str]) -> str | None:
        """Mask tool-result string values and preserve contract-typed numbers.

        The engine already validates tool output before masking it. Revalidating
        the serialized result can reject short PII placeholders in constrained
        string fields, so a strict envelope check is the fallback after masking.
        """
        try:
            raw_result = json.loads(text)
        except json.JSONDecodeError:
            return None
        try:
            result = ToolResult.model_validate(raw_result)
        except ValidationError:
            if not self._is_tool_result_envelope(raw_result):
                return None
            payload = raw_result
        else:
            payload = result.model_dump(mode="json")
        masked = mask_json_string_values(payload, self.masker, state)
        return json.dumps(masked, sort_keys=True, ensure_ascii=False)

    def mask_outbound_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Mask PII in all outbound messages across every string field.

        Masks and verifies:
        - str `content`
        - list-shaped `content` parts (e.g. [{"type": "text", "text": "..."}])
        - assistant `tool_calls[].function.arguments`
        - tool messages (`role="tool"`, `content`)
        - `name` field if present
        Raises MaskingError on any unsupported shape that cannot be safely inspected.
        """
        if not isinstance(messages, list):
            raise MaskingError(
                f"Messages must be a list, got {type(messages).__name__}"
            )

        masked_messages: list[dict[str, Any]] = []
        accumulated_state = _reserve_placeholders(messages)

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise MaskingError(
                    f"Message at index {i} must be a dict, got {type(msg).__name__}"
                )
            msg_copy = copy.deepcopy(msg)
            role = msg_copy.get("role", "unknown")

            if "content" in msg_copy:
                raw_content = msg_copy["content"]
                if isinstance(raw_content, str):
                    masked_tool_result = (
                        self._mask_tool_result_content(raw_content, accumulated_state)
                        if role == "tool"
                        else None
                    )
                    msg_copy["content"] = (
                        masked_tool_result
                        or self._mask_and_verify_string(
                            raw_content,
                            accumulated_state,
                            f"message[{i}]({role}).content",
                        )
                    )
                elif isinstance(raw_content, list):
                    masked_parts: list[Any] = []
                    for p_idx, part in enumerate(raw_content):
                        if isinstance(part, str):
                            masked_part = self._mask_and_verify_string(
                                part,
                                accumulated_state,
                                f"message[{i}]({role}).content[{p_idx}]",
                            )
                            masked_parts.append(masked_part)
                        elif isinstance(part, dict):
                            part_copy = copy.deepcopy(part)
                            if "text" in part_copy and isinstance(
                                part_copy["text"], str
                            ):
                                part_copy["text"] = self._mask_and_verify_string(
                                    part_copy["text"],
                                    accumulated_state,
                                    f"message[{i}]({role}).content[{p_idx}].text",
                                )
                            elif "text" in part_copy:
                                raise MaskingError(
                                    f"Message[{i}] content part 'text' is not a string"
                                )
                            masked_parts.append(part_copy)
                        else:
                            raise MaskingError(
                                f"Unsupported content part type at index {p_idx}: "
                                f"{type(part).__name__}"
                            )
                    msg_copy["content"] = masked_parts
                elif raw_content is None:
                    pass
                else:
                    raise MaskingError(
                        f"Unsupported content type for role '{role}': "
                        f"{type(raw_content).__name__}"
                    )

            # 2. Inspect and mask tool_calls (assistant messages)
            if "tool_calls" in msg_copy:
                tool_calls = msg_copy["tool_calls"]
                if not isinstance(tool_calls, list):
                    raise MaskingError(
                        f"Message[{i}] tool_calls must be a list, got "
                        f"{type(tool_calls).__name__}"
                    )
                for tc_idx, tc in enumerate(tool_calls):
                    if not isinstance(tc, dict):
                        raise MaskingError(
                            f"Message[{i}] tool_call[{tc_idx}] must be a dict"
                        )
                    fn = tc.get("function")
                    if isinstance(fn, dict) and "arguments" in fn:
                        raw_args = fn["arguments"]
                        if isinstance(raw_args, str):
                            fn["arguments"] = self._mask_and_verify_string(
                                raw_args,
                                accumulated_state,
                                f"message[{i}]({role}).tool_calls[{tc_idx}].arguments",
                            )
                        elif isinstance(raw_args, dict):
                            args_json = json.dumps(raw_args)
                            masked_args_json = self._mask_and_verify_string(
                                args_json,
                                accumulated_state,
                                f"message[{i}]({role}).tool_calls[{tc_idx}].arguments",
                            )
                            fn["arguments"] = json.loads(masked_args_json)
                        else:
                            raise MaskingError(
                                f"Unsupported tool_call arguments type: "
                                f"{type(raw_args).__name__}"
                            )

            # 3. Inspect optional name field
            if "name" in msg_copy and isinstance(msg_copy["name"], str):
                msg_copy["name"] = self._mask_and_verify_string(
                    msg_copy["name"], accumulated_state, f"message[{i}]({role}).name"
                )

            masked_messages.append(msg_copy)

        return masked_messages, accumulated_state

    def rehydrate_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        mapping: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Rehydrate tool call arguments by replacing placeholders with original PII.

        Used strictly right before building the contracts ToolCall for banking-core.
        The rehydrated values must never re-enter the history sent to the provider.
        """
        if not tool_calls or not mapping:
            return copy.deepcopy(tool_calls)

        rehydrated = copy.deepcopy(tool_calls)
        for tc in rehydrated:
            fn = tc.get("function")
            if isinstance(fn, dict) and "arguments" in fn:
                args = fn["arguments"]
                if isinstance(args, str):
                    fn["arguments"] = self.masker.unmask(args, mapping)
                elif isinstance(args, dict):
                    fn["arguments"] = {
                        k: (self.masker.unmask(v, mapping) if isinstance(v, str) else v)
                        for k, v in args.items()
                    }
        return rehydrated

    async def complete(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = "1.0",
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute completion with mandatory masking, replay check, and unmasking."""
        # 1. Outbound masking (fail closed)
        masked_messages, mapping = self.mask_outbound_messages(messages)

        # 2. Compute deterministic recording key
        tool_hash = compute_tool_schema_hash(tools)
        key = compute_recording_key(
            model_id=self.model,
            prompt_version=prompt_version,
            masked_messages=masked_messages,
            tool_schema_hash=tool_hash,
        )

        # 3. Handle replay mode
        if self.mode == "replay":
            recording = self.replay_manager.load_recording(key)
            if recording is not None:
                raw_content = recording.response.content
                unmasked = (
                    self.masker.unmask(raw_content, mapping) if raw_content else None
                )
                rehydrated_tcs = self.rehydrate_tool_calls(
                    recording.response.tool_calls, mapping
                )
                return LLMResponse(
                    content=unmasked,
                    masked_content=raw_content,
                    tool_calls=recording.response.tool_calls,
                    rehydrated_tool_calls=rehydrated_tcs,
                    usage=recording.response.usage,
                    cost=recording.response.cost,
                    model=recording.model_id,
                    recording_key=key,
                    cached=True,
                    masked_messages=recording.masked_messages,
                )

            if self.replay_on_miss == "fail":
                raise ReplayMissError(
                    f"No recording found for key '{key}' in replay mode "
                    f"(model={self.model}, prompt_version={prompt_version})"
                )
            logger.warning("Replay miss for key=%s, falling back to live provider", key)

        # 4. Live provider call via LiteLLM
        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": masked_messages,
            "temperature": self.temperature if temperature is None else temperature,
            "timeout": self.timeout,
            "num_retries": self.retries,
            **kwargs,
        }
        if self.base_url:
            call_kwargs["api_base"] = self.base_url
        if self.api_key:
            call_kwargs["api_key"] = self.api_key
        if self.reasoning_effort:
            call_kwargs["reasoning_effort"] = self.reasoning_effort
        if tools:
            call_kwargs["tools"] = tools

        try:
            response = await litellm.acompletion(**call_kwargs)
        except Exception as exc:
            logger.error("LiteLLM completion error: %s", exc)
            raise

        # 5. Extract response payload
        choice = response.choices[0]
        message = choice.message
        raw_content = message.content
        raw_tool_calls: list[dict[str, Any]] = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                if isinstance(tc, dict):
                    raw_tool_calls.append(tc)
                elif hasattr(tc, "model_dump"):
                    raw_tool_calls.append(tc.model_dump())
                else:
                    raw_tool_calls.append(dict(tc))

        usage_dict: dict[str, Any] = {}
        if hasattr(response, "usage") and response.usage:
            if hasattr(response.usage, "model_dump"):
                usage_dict = response.usage.model_dump()
            elif isinstance(response.usage, dict):
                usage_dict = response.usage

        cost: float | None = None
        if self.settings.cost_tracking_enabled:
            try:
                cost = float(litellm.completion_cost(completion_response=response))
            except Exception:
                cost = None

        # Structured log (no PII)
        logger.info(
            "LLM live completion: model=%s prompt_tokens=%s completion_tokens=%s "
            "total_tokens=%s cost_usd=%s key=%s",
            self.model,
            usage_dict.get("prompt_tokens"),
            usage_dict.get("completion_tokens"),
            usage_dict.get("total_tokens"),
            cost,
            key,
        )

        # 6. Save recording if RECORD=1
        if self.record or self.settings.record:
            rec_response = RecordedResponse(
                content=raw_content,
                tool_calls=raw_tool_calls,
                usage=usage_dict,
                cost=cost,
            )
            self.replay_manager.save_recording(
                key=key,
                model_id=self.model,
                prompt_version=prompt_version,
                masked_messages=masked_messages,
                tool_schema_hash=tool_hash,
                response=rec_response,
            )

        # 7. Unmask response for consumer and rehydrate tool calls
        unmasked = self.masker.unmask(raw_content, mapping) if raw_content else None
        rehydrated_tcs = self.rehydrate_tool_calls(raw_tool_calls, mapping)

        return LLMResponse(
            content=unmasked,
            masked_content=raw_content,
            tool_calls=raw_tool_calls,
            rehydrated_tool_calls=rehydrated_tcs,
            usage=usage_dict,
            cost=cost,
            model=self.model,
            recording_key=key,
            cached=False,
            masked_messages=masked_messages,
        )

    def complete_sync(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = "1.0",
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous completion execution."""
        # 1. Outbound masking (fail closed)
        masked_messages, mapping = self.mask_outbound_messages(messages)

        # 2. Compute key
        tool_hash = compute_tool_schema_hash(tools)
        key = compute_recording_key(
            model_id=self.model,
            prompt_version=prompt_version,
            masked_messages=masked_messages,
            tool_schema_hash=tool_hash,
        )

        # 3. Handle replay mode
        if self.mode == "replay":
            recording = self.replay_manager.load_recording(key)
            if recording is not None:
                raw_content = recording.response.content
                unmasked = (
                    self.masker.unmask(raw_content, mapping) if raw_content else None
                )
                rehydrated_tcs = self.rehydrate_tool_calls(
                    recording.response.tool_calls, mapping
                )
                return LLMResponse(
                    content=unmasked,
                    masked_content=raw_content,
                    tool_calls=recording.response.tool_calls,
                    rehydrated_tool_calls=rehydrated_tcs,
                    usage=recording.response.usage,
                    cost=recording.response.cost,
                    model=recording.model_id,
                    recording_key=key,
                    cached=True,
                    masked_messages=recording.masked_messages,
                )

            if self.replay_on_miss == "fail":
                raise ReplayMissError(
                    f"No recording found for key '{key}' in replay mode "
                    f"(model={self.model}, prompt_version={prompt_version})"
                )

        # 4. Live provider call via LiteLLM
        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": masked_messages,
            "temperature": self.temperature if temperature is None else temperature,
            "timeout": self.timeout,
            "num_retries": self.retries,
            **kwargs,
        }
        if self.base_url:
            call_kwargs["api_base"] = self.base_url
        if self.api_key:
            call_kwargs["api_key"] = self.api_key
        if self.reasoning_effort:
            call_kwargs["reasoning_effort"] = self.reasoning_effort
        if tools:
            call_kwargs["tools"] = tools

        response = litellm.completion(**call_kwargs)

        # 5. Extract response payload
        choice = response.choices[0]
        message = choice.message
        raw_content = message.content
        raw_tool_calls: list[dict[str, Any]] = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                if isinstance(tc, dict):
                    raw_tool_calls.append(tc)
                elif hasattr(tc, "model_dump"):
                    raw_tool_calls.append(tc.model_dump())
                else:
                    raw_tool_calls.append(dict(tc))

        usage_dict: dict[str, Any] = {}
        if hasattr(response, "usage") and response.usage:
            if hasattr(response.usage, "model_dump"):
                usage_dict = response.usage.model_dump()
            elif isinstance(response.usage, dict):
                usage_dict = response.usage

        cost: float | None = None
        if self.settings.cost_tracking_enabled:
            try:
                cost = float(litellm.completion_cost(completion_response=response))
            except Exception:
                cost = None

        logger.info(
            "LLM live completion: model=%s prompt_tokens=%s completion_tokens=%s "
            "total_tokens=%s cost_usd=%s key=%s",
            self.model,
            usage_dict.get("prompt_tokens"),
            usage_dict.get("completion_tokens"),
            usage_dict.get("total_tokens"),
            cost,
            key,
        )

        if self.record or self.settings.record:
            rec_response = RecordedResponse(
                content=raw_content,
                tool_calls=raw_tool_calls,
                usage=usage_dict,
                cost=cost,
            )
            self.replay_manager.save_recording(
                key=key,
                model_id=self.model,
                prompt_version=prompt_version,
                masked_messages=masked_messages,
                tool_schema_hash=tool_hash,
                response=rec_response,
            )

        unmasked = self.masker.unmask(raw_content, mapping) if raw_content else None
        rehydrated_tcs = self.rehydrate_tool_calls(raw_tool_calls, mapping)

        return LLMResponse(
            content=unmasked,
            masked_content=raw_content,
            tool_calls=raw_tool_calls,
            rehydrated_tool_calls=rehydrated_tcs,
            usage=usage_dict,
            cost=cost,
            model=self.model,
            recording_key=key,
            cached=False,
            masked_messages=masked_messages,
        )
