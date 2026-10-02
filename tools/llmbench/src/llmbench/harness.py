"""One conversation: the real TurnEngine, a SandboxBank, and a model.

The engine runs as the service runs it, with one difference: no encoder. The
customer text is masked by the regexes alone, and the `intent_hint` and
`clarify_route` decision points do not act (docs/limitations.md). Every model
under test gets the same harness, so the comparison is fair, but it measures the
model with less help than production gives it.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from contracts.envelope import VerificationState
from contracts.tools import get_effective_permitted_states
from orchestrator.conversation.engine import TurnEngine
from orchestrator.conversation.models import ConversationContext, Lang, TurnResult
from orchestrator.conversation.tools import build_llm_tools

from llmbench.provider import BenchProvider, CallStat
from llmbench.sandbox import CallRecord, SandboxBank

OTP_TOKEN = "{{otp}}"


@dataclass
class TurnRecord:
    """What one customer turn produced, for the scorers and the transcript."""

    user_text: str
    reply_text: str = ""
    result: TurnResult | None = None
    bank_calls: list[CallRecord] = field(default_factory=list)
    llm_calls: list[CallStat] = field(default_factory=list)
    state_after: VerificationState = VerificationState.ANONYMOUS
    latency_ms: float = 0.0
    error: str | None = None
    by_oracle: bool = False

    @property
    def proposed_tools(self) -> list[str]:
        """Catalog names of every tool the model proposed in the turn, in order."""
        _, names = build_llm_tools()
        return [
            names.get(call["function"]["name"], call["function"]["name"])
            for stat in self.llm_calls
            for call in stat.tool_calls
            if isinstance(call.get("function"), dict)
        ]

    def transcript(self) -> dict[str, Any]:
        return {
            "user": self.user_text,
            "reply": self.reply_text,
            "by_oracle": self.by_oracle,
            "error": self.error,
            "state_after": self.state_after.value,
            "latency_ms": round(self.latency_ms, 1),
            "llm_calls": [
                {
                    "latency_ms": round(s.latency_ms, 1),
                    "tools_offered": s.tools_offered,
                    "prompt_tokens": s.prompt_tokens,
                    "completion_tokens": s.completion_tokens,
                    "content": s.content,
                    "tool_calls": s.tool_calls,
                    "error": s.error,
                }
                for s in self.llm_calls
            ],
            "bank_calls": [
                {
                    "tool": c.tool,
                    "state_before": c.state_before.value,
                    "status": c.result.status.value,
                    "reason_code": c.result.reason_code.value
                    if c.result.reason_code
                    else None,
                }
                for c in self.bank_calls
            ],
            "local_rejections": [
                {
                    "tool": o.tool,
                    "reason_code": o.reason_code.value if o.reason_code else None,
                }
                for o in (self.result.metadata.tool_outcomes if self.result else [])
                if not o.executed
            ],
        }


class Conversation:
    """A session on the bank plus the engine context, driven turn by turn."""

    def __init__(
        self,
        bank: SandboxBank,
        lang: Lang,
        max_tool_rounds: int = 5,
    ) -> None:
        self.bank = bank
        self.lang = lang
        self.session_id = bank.create_session()
        self.context = ConversationContext(session_id=self.session_id, language=lang)
        self.max_tool_rounds = max_tool_rounds
        self.turns: list[TurnRecord] = []
        _, self.llm_names = build_llm_tools()

    def allowed_tools(self) -> frozenset[str]:
        """Catalog tools the session's current state allows (the routing ablation)."""
        state = self.bank.state(self.session_id)
        return frozenset(
            tool
            for tool in self.llm_names.values()
            if state
            in get_effective_permitted_states(
                tool, self.bank.config.get_tool_permitted_states(tool)
            )
        )

    def render(self, text: str) -> str:
        if OTP_TOKEN not in text:
            return text
        code = self.bank.otp_code(self.session_id)
        if code is None:
            raise RuntimeError("no OTP challenge was issued before an {{otp}} turn")
        return text.replace(OTP_TOKEN, code)

    async def turn(self, text: str, llm: BenchProvider) -> TurnRecord:
        rendered = self.render(text)
        engine = TurnEngine(
            llm=llm,
            banking=self.bank,
            encoder=None,
            max_tool_rounds=self.max_tool_rounds,
            collect_eval=True,
        )
        calls_before = len(self.bank.calls(self.session_id))
        stats_before = len(llm.stats)
        record = TurnRecord(user_text=rendered, by_oracle=llm.by_oracle)
        started = time.perf_counter()
        try:
            result = await engine.run_turn(self.context, rendered, lang=self.lang)
        except Exception as exc:  # a failed completion: the context is untouched
            record.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        else:
            record.result = result
            record.reply_text = "\n".join(
                block.text for block in result.blocks if block.type == "text"
            )
        record.latency_ms = (time.perf_counter() - started) * 1000
        record.bank_calls = self.bank.calls(self.session_id)[calls_before:]
        record.llm_calls = llm.stats[stats_before:]
        record.state_after = self.bank.state(self.session_id)
        self.turns.append(record)
        return record
