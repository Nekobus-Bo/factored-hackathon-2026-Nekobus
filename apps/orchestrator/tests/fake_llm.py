"""Test-only scripted LLM. Lives in tests/ so src/ can never import it."""

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from orchestrator.llm.provider import LLMResponse


def tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI-shaped tool call as a model would emit it."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


@dataclass
class Step:
    """One scripted model answer: either text or tool calls."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ScriptedLLM:
    """Returns scripted steps in order and records every payload it receives.

    With `repeat_last`, the last step is returned forever (for loop bounds).
    """

    def __init__(self, steps: list[Step], repeat_last: bool = False) -> None:
        self.steps = list(steps)
        self.repeat_last = repeat_last
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = "1.0",
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "prompt_version": prompt_version,
                "tools": tools,
            }
        )
        index = len(self.calls) - 1
        if index >= len(self.steps):
            if not (self.repeat_last and self.steps):
                raise AssertionError(f"ScriptedLLM ran out of steps at call {index}")
            step = self.steps[-1]
        else:
            step = self.steps[index]
        return LLMResponse(
            content=step.content,
            masked_content=step.content,
            tool_calls=copy.deepcopy(step.tool_calls),
            rehydrated_tool_calls=copy.deepcopy(step.tool_calls),
            model="fake-llm",
            recording_key=f"fake-{index}",
        )

    def payload_dump(self) -> str:
        """Everything the provider was sent, as one string for PII assertions."""
        return json.dumps(self.calls, ensure_ascii=False)
