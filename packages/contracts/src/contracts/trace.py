"""Detective mode: what one chat turn did, step by step (ADR-0019).

A `TurnTrace` is the timeline of one customer turn: the encoder, the masking, the decision points,
every LLM call and every banking-core tool call, and what was kept of the model's reply. It is
returned with the turn only where the orchestrator offers detective mode, and it holds masked
values only: what the LLM was sent and what it answered, never the placeholder map, the raw
customer values or the rehydrated tool arguments.

Each event carries exactly one detail, in the field named after its kind (`encoder` for an
`encoder` event...); `canned_reply` and `takeover` events carry only a `note`. Every field is
required, nullable where a value may be missing, so the Zod mirror can be checked field by field
(packages/contracts/ts/trace.ts, ts/tests/drift.test.ts).
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.envelope import ReasonCode, ToolResultStatus, VerificationState

TRACE_VERSION = "1"


class TraceEventKind(str, Enum):
    """What a trace event records."""

    ENCODER = "encoder"
    MASKING = "masking"
    DECISIONS = "decisions"
    CANNED_REPLY = "canned_reply"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    ENGINE_HANDOFF = "engine_handoff"
    BLOCKS = "blocks"
    TAKEOVER = "takeover"


class TraceEventStatus(str, Enum):
    """How the step ended."""

    OK = "ok"
    REFUSED = "refused"
    ERROR = "error"
    SKIPPED = "skipped"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TraceCount(_Strict):
    """A category and how many times it occurred (PII spans by type)."""

    type: str = Field(min_length=1)
    count: int = Field(ge=0)


class TraceDecisionPoint(_Strict):
    """One decision point as the encoder decided it."""

    dp_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    label: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    raw_confidence: float | None
    runner_up_label: str | None
    runner_up_confidence: float | None
    tau: float | None


class EncoderDetail(_Strict):
    """The encoder's analysis of the customer text. Slot types only: values are customer data."""

    available: bool
    intent: str | None
    confidence: float | None
    abstain: bool | None
    model_id: str | None
    config_version: str | None
    server_latency_ms: float | None = Field(ge=0.0)
    slots: list[str]
    pii_spans: list[TraceCount]
    decision_points: list[TraceDecisionPoint]


class MaskingDetail(_Strict):
    """The customer text as the LLM receives it."""

    masked_text: str | None
    placeholders: list[str] = Field(description="Placeholders minted this turn, names only")
    regex_only: bool
    encoder_spans_added: int = Field(ge=0)
    otp_pending: bool
    failed: bool


class TraceDecision(_Strict):
    """What a decision point decided (ADR-0012)."""

    dp_id: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    label: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    unavailable_reason: str | None


class TraceEffect(_Strict):
    """What a decision point's effect did, or in shadow would have done."""

    dp_id: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    tool: str | None
    applied: bool
    would_apply: bool


class DecisionsDetail(_Strict):
    """The turn's decision records and effects."""

    config_version: str | None
    decisions: list[TraceDecision]
    effects: list[TraceEffect]


class TraceMessage(_Strict):
    """One message of a completion request, masked."""

    role: str = Field(min_length=1)
    content: str | None
    tool_calls: str | None = Field(description="The assistant's tool calls, as JSON")
    tool_call_id: str | None


class TraceToolRequest(_Strict):
    """A tool call the model asked for, with its masked arguments as JSON."""

    call_id: str
    name: str
    arguments: str


class LlmCallDetail(_Strict):
    """One completion: what was sent (masked) and what came back."""

    round: int = Field(ge=1)
    model: str | None
    prompt_version: str
    cached: bool
    recording_key: str | None
    tools_offered: list[str]
    messages_from: int = Field(
        ge=0, description="Index of the first message below: 0 on the first call, then the new ones"
    )
    messages: list[TraceMessage]
    response_content: str | None
    response_tool_calls: list[TraceToolRequest]
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None


class ToolCallDetail(_Strict):
    """One tool call: the masked arguments, banking-core's answer and what the LLM got back."""

    call_id: str | None
    llm_name: str | None
    tool: str
    arguments: str | None = Field(description="Masked arguments as JSON, as the model sent them")
    executed: bool = Field(description="False when refused before reaching banking-core")
    local_reason: str | None = Field(description="Why the engine refused it without calling")
    status: ToolResultStatus | None
    reason_code: ReasonCode | None
    flow_state: VerificationState | None
    flow_next: list[str]
    flow_allowed: list[str]
    feedback: str | None = Field(description="The masked result the LLM received, as JSON")


class BlocksDetail(_Strict):
    """What was kept of the model's reply for the customer."""

    kept: list[str]
    dropped: list[str]
    internal_lines_withheld: int = Field(ge=0)
    receipts: int = Field(ge=0)
    handoffs: int = Field(ge=0)
    fallback: bool


class TraceEvent(_Strict):
    """One step of the turn. Times are milliseconds from the start of the turn."""

    seq: int = Field(ge=0)
    kind: TraceEventKind
    label: str = Field(min_length=1, max_length=128)
    start_ms: float = Field(ge=0.0)
    duration_ms: float | None = Field(ge=0.0)
    status: TraceEventStatus
    note: str | None
    encoder: EncoderDetail | None
    masking: MaskingDetail | None
    decisions: DecisionsDetail | None
    llm_call: LlmCallDetail | None
    tool_call: ToolCallDetail | None
    blocks: BlocksDetail | None

    @model_validator(mode="after")
    def _detail_matches_kind(self) -> "TraceEvent":
        details = {
            "encoder": self.encoder,
            "masking": self.masking,
            "decisions": self.decisions,
            "llm_call": self.llm_call,
            "tool_call": self.tool_call,
            "blocks": self.blocks,
        }
        expected = {
            TraceEventKind.ENGINE_HANDOFF: "tool_call",
        }.get(self.kind, self.kind.value)
        present = [name for name, value in details.items() if value is not None]
        wanted = [expected] if expected in details else []
        if present != wanted:
            carries = wanted or "no detail"
            raise ValueError(f"a {self.kind.value} event carries {carries}, got {present}")
        return self


class TurnTrace(_Strict):
    """The timeline of one customer turn."""

    trace_version: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    total_ms: float = Field(ge=0.0)
    tool_rounds: int = Field(ge=0)
    events: list[TraceEvent]
