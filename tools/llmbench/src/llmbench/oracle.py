"""Scripted answers that walk a probe to the state it tests.

The oracle plays the gold tool calls of a probe's prefix through the real
engine and sandbox, so the history the model under test receives (masked user
turns, tool results, assistant turns) is what the service would have built,
not a hand-written transcript.

Arguments may hold templates, resolved when the call is made:
- `{{ph:DOC}}`: the latest placeholder of that kind in the masked messages
  (`[DOC_1]`), i.e. the value the customer just typed;
- `{{card}}` / `{{card:<last4>}}`: the case customer's first card, or the one
  ending in those digits;
- `{{tx:<merchant prefix>}}`: the case customer's transaction at that merchant.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from orchestrator.conversation.tools import llm_tool_name
from orchestrator.llm.provider import LLMResponse

from llmbench.sandbox import SandboxBank

_TEMPLATE = re.compile(r"\{\{([a-z]+)(?::([^}]*))?\}\}")


@dataclass
class OracleTurn:
    """The gold behavior for one customer turn: calls in order, then a reply."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reply: str = ""


class Resolver:
    """Resolves the templates above against the bank and the outbound messages."""

    def __init__(self, bank: SandboxBank) -> None:
        self.bank = bank

    def resolve(self, value: Any, messages: list[dict[str, Any]] | None = None) -> Any:
        if isinstance(value, dict):
            return {k: self.resolve(v, messages) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v, messages) for v in value]
        if not isinstance(value, str):
            return value
        match = _TEMPLATE.fullmatch(value)
        if match is None:
            return value
        kind, arg = match.group(1), match.group(2)
        if kind == "ph":
            return latest_placeholder(messages or [], arg or "")
        if kind == "card":
            return self.card_ref(arg)
        if kind == "tx":
            return self.transaction_id(arg or "")
        raise ValueError(f"unknown template {value!r}")

    def card_ref(self, last4: str | None = None) -> str:
        customer = self.bank.case_customer()
        if customer is None:
            raise ValueError("{{card}} needs a case customer")
        cards = self.bank.world.cards_of(customer.customer_id)
        for card in cards:
            if last4 is None or card.pan_last4 == last4:
                return card.card_ref
        raise ValueError(f"no card ending in {last4}")

    def transaction_id(self, merchant_prefix: str) -> str:
        customer = self.bank.case_customer()
        if customer is None:
            raise ValueError("{{tx}} needs a case customer")
        for tx in self.bank.world.transactions.values():
            if tx.customer_id == customer.customer_id and tx.merchant.startswith(
                merchant_prefix
            ):
                return tx.transaction_id
        raise ValueError(f"no transaction at {merchant_prefix!r}")


def latest_placeholder(messages: list[dict[str, Any]], kind: str) -> str:
    """The last `[KIND_n]` in the masked messages, newest message first."""
    pattern = re.compile(rf"\[{re.escape(kind)}_\d+\]")
    for message in reversed(messages):
        found = pattern.findall(str(message.get("content") or ""))
        if found:
            return found[-1]
    raise ValueError(f"no {kind} placeholder in the conversation yet")


class OracleLLM:
    """A CompletionProvider that answers one OracleTurn, one tool call per round."""

    def __init__(self, turn: OracleTurn, resolver: Resolver) -> None:
        self.turn = turn
        self.resolver = resolver
        self.index = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        prompt_version: str = "1.0",
        tools: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> LLMResponse:
        if self.index < len(self.turn.calls):
            tool, args = self.turn.calls[self.index]
            self.index += 1
            raw = {
                "id": f"call_oracle_{self.index}",
                "type": "function",
                "function": {
                    "name": llm_tool_name(tool),
                    "arguments": json.dumps(
                        self.resolver.resolve(args, messages), ensure_ascii=False
                    ),
                },
            }
            return _response(None, [raw])
        return _response(self.turn.reply or None, [])


def _response(content: str | None, tool_calls: list[dict[str, Any]]) -> LLMResponse:
    return LLMResponse(
        content=content,
        masked_content=content,
        tool_calls=tool_calls,
        rehydrated_tool_calls=tool_calls,
        model="oracle",
        recording_key="oracle",
    )
