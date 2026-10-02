"""The model under test, behind the orchestrator's real LLMProvider.

`live_provider` builds an LLMProvider in live mode against a local
OpenAI-compatible server, so the bench exercises the same outbound masking,
verification and tool-argument rehydration the service runs. `BenchProvider`
wraps any CompletionProvider (engine.py) to time each call, keep what the model
proposed, and optionally offer only the tools the session's state allows.
"""

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestrator.config import Settings
from orchestrator.llm.provider import LLMProvider, LLMResponse


def live_provider(
    model: str,
    base_url: str,
    api_key: str = "sk-local",
    timeout_seconds: float = 120.0,
) -> LLMProvider:
    """An LLMProvider in live mode; nothing is read from the environment or .env.

    `model` is the LiteLLM model string, e.g. `openai/qwen3.5-4b` for a llama.cpp
    server whose OpenAI API lives at `base_url` (http://127.0.0.1:8099/v1).
    """
    settings = Settings(
        _env_file=None,
        LLM_MODE="live",
        LLM_MODEL=model,
        LLM_BASE_URL=base_url,
        LLM_API_KEY=api_key,
        LLM_TIMEOUT_SECONDS=timeout_seconds,
        LLM_MAX_RETRIES=0,
        LLM_REASONING_EFFORT="",
        RECORD=False,
        COST_TRACKING_ENABLED=False,
        ENCODER_ENABLED=False,
    )
    return LLMProvider(settings=settings)


@dataclass
class CallStat:
    """One completion as the bench saw it. Tool calls are the model's own (masked)."""

    latency_ms: float
    tools_offered: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # Who answered: the model under test, or the oracle that builds a probe prefix.
    by_oracle: bool = False


class BenchProvider:
    """CompletionProvider wrapper: timing, model proposals and tool routing.

    `allowed_tools`, when given, returns the catalog names the session's state
    allows right now; only those schemas are offered (the `--route-tools`
    ablation). The engine itself is unchanged: it still checks every call, and
    banking-core still refuses what the state does not allow.
    """

    def __init__(
        self,
        inner: Any,
        llm_names: dict[str, str] | None = None,
        allowed_tools: Callable[[], frozenset[str]] | None = None,
        request_kwargs: dict[str, Any] | None = None,
        by_oracle: bool = False,
    ) -> None:
        self.inner = inner
        self.llm_names = llm_names or {}
        self.allowed_tools = allowed_tools
        self.request_kwargs = request_kwargs or {}
        self.by_oracle = by_oracle
        self.stats: list[CallStat] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = "1.0",
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        offered = self._route(tools)
        started = time.perf_counter()
        try:
            response = await self.inner.complete(
                messages=messages,
                prompt_version=prompt_version,
                tools=offered,
                **self.request_kwargs,
            )
        except Exception as exc:
            self.stats.append(
                CallStat(
                    latency_ms=(time.perf_counter() - started) * 1000,
                    tools_offered=len(offered or []),
                    error=type(exc).__name__,
                    by_oracle=self.by_oracle,
                )
            )
            raise
        usage = response.usage or {}
        self.stats.append(
            CallStat(
                latency_ms=(time.perf_counter() - started) * 1000,
                tools_offered=len(offered or []),
                prompt_tokens=_int(usage.get("prompt_tokens")),
                completion_tokens=_int(usage.get("completion_tokens")),
                content=response.masked_content,
                tool_calls=copy.deepcopy(response.tool_calls),
                by_oracle=self.by_oracle,
            )
        )
        return response

    def _route(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if self.allowed_tools is None or not tools:
            return tools
        allowed = self.allowed_tools()
        return [
            tool
            for tool in tools
            if self.llm_names.get(tool["function"]["name"]) in allowed
        ]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
