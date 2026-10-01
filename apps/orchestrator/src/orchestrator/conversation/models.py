"""State and result models for the conversation turn engine."""

from typing import Any, Literal

from contracts import (
    HandoffBlock,
    ReasonCode,
    ReceiptBlock,
    TextBlock,
    ToolResultStatus,
)
from contracts.locale import Locale
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.conversation.decisions.records import DecisionRecord, EffectRecord
from orchestrator.conversation.decisions.state import DecisionState

Lang = Literal["es", "pt", "en"]


class TakeoverActiveError(RuntimeError):
    """A turn was requested on a conversation a human agent has taken over.

    The engine raises it before it reads, masks, sends or calls anything: once a
    takeover is active the conversation is closed to the LLM, the encoder and
    the banking-core tools for good.
    """


class ConversationContext(BaseModel):
    """What the engine needs to run a turn. Persisted by the session store.

    `history` is the masked LLM transcript (OpenAI message shape, including
    assistant tool_calls and tool results). Raw PII never enters it; the raw
    values live only in `placeholder_map`, which stays server-side.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="banking-core session id")
    language: Lang = Field(default="es")
    locale: Locale | None = Field(
        default=None, description="Market (ADR-0014): per-market thresholds, metrics"
    )
    history: list[dict[str, Any]] = Field(default_factory=list)
    placeholder_map: dict[str, str] = Field(
        default_factory=dict,
        description="Placeholder -> raw value. Server-side only, never sent out",
    )
    decisions: DecisionState = Field(
        default_factory=DecisionState,
        description="What the decision-point effects remember (ADR-0012); no PII",
    )
    human_takeover: bool = Field(
        default=False,
        description=(
            "A human agent holds this conversation. The engine refuses to run a "
            "turn on it (TakeoverActiveError): the history never reaches the LLM"
        ),
    )


class EncoderSignal(BaseModel):
    """Encoder analysis recorded in the turn metadata (no text, no spans)."""

    model_config = ConfigDict(extra="forbid")

    intent: str | None
    confidence: float
    abstain: bool
    model_id: str


class ToolOutcome(BaseModel):
    """One executed (or locally rejected) tool call within a turn."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    status: ToolResultStatus
    reason_code: ReasonCode | None = None
    executed: bool = Field(
        description="False when rejected before reaching banking-core"
    )


class TurnMetadata(BaseModel):
    """Observable facts about a turn, for the transcript, eval and metrics."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    # The market the encoder was asked for (ADR-0014); None: language only.
    locale: Locale | None = None
    # The turn was answered by the canned clarification, without the LLM (ADR-0014).
    canned_reply: bool = False
    encoder: EncoderSignal | None = None
    encoder_unavailable: bool = False
    # The encoder was configured but gave no PII spans this turn (unavailable,
    # timed out, invalid payload): the text was masked by the regexes alone.
    masking_regex_only: bool = False
    # Counts only, never offsets or text: spans the encoder returned, and how
    # many of them masked characters the regexes had left in clear.
    encoder_pii_spans: int = Field(default=0, ge=0)
    encoder_spans_added: int = Field(default=0, ge=0)
    masking_failed: bool = False
    tool_rounds: int = 0
    max_tool_rounds_reached: bool = False
    tool_outcomes: list[ToolOutcome] = Field(default_factory=list)
    dropped_block_types: list[str] = Field(default_factory=list)
    llm_recording_keys: list[str] = Field(default_factory=list)
    # Decision points (ADR-0012, I5): what each one decided and what its effect did
    # or, in shadow, would have done. Identifiers, enum values and numbers; never text.
    decisions: list[DecisionRecord] = Field(default_factory=list)
    effects: list[EffectRecord] = Field(default_factory=list)
    decisions_config_version: str | None = None
    # Decision points whose effects file labels the encoder does not serve: their
    # effects are off for the turn (a gate keeps withholding).
    dp_config_mismatch: list[str] = Field(default_factory=list)


class TurnEvalData(BaseModel):
    """Safe provider evidence returned only by the eval-only chat hook."""

    model_config = ConfigDict(extra="forbid")

    masked_outbound: list[str] = Field(default_factory=list)
    recording_keys: list[str] = Field(default_factory=list)
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    # The turn's decision records (no text), so the runner can report on them.
    decisions: list[DecisionRecord] = Field(default_factory=list)
    effects: list[EffectRecord] = Field(default_factory=list)


class TurnResult(BaseModel):
    """Blocks for the client plus the turn metadata."""

    model_config = ConfigDict(extra="forbid")

    blocks: list[TextBlock | ReceiptBlock | HandoffBlock]
    metadata: TurnMetadata
    eval: TurnEvalData = Field(default_factory=TurnEvalData)
