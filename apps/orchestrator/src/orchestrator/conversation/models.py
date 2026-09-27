"""State and result models for the conversation turn engine."""

from typing import Any, Literal

from contracts import ReasonCode, ReceiptBlock, TextBlock, ToolResultStatus
from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["es", "pt", "en"]


class ConversationContext(BaseModel):
    """What the engine needs to run a turn. Persisted by the session store.

    `history` is the masked LLM transcript (OpenAI message shape, including
    assistant tool_calls and tool results). Raw PII never enters it; the raw
    values live only in `placeholder_map`, which stays server-side.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="banking-core session id")
    language: Lang = Field(default="es")
    history: list[dict[str, Any]] = Field(default_factory=list)
    placeholder_map: dict[str, str] = Field(
        default_factory=dict,
        description="Placeholder -> raw value. Server-side only, never sent out",
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
    encoder: EncoderSignal | None = None
    encoder_unavailable: bool = False
    masking_failed: bool = False
    tool_rounds: int = 0
    max_tool_rounds_reached: bool = False
    tool_outcomes: list[ToolOutcome] = Field(default_factory=list)
    dropped_block_types: list[str] = Field(default_factory=list)
    llm_recording_keys: list[str] = Field(default_factory=list)


class TurnResult(BaseModel):
    """Blocks for the client plus the turn metadata."""

    model_config = ConfigDict(extra="forbid")

    blocks: list[TextBlock | ReceiptBlock]
    metadata: TurnMetadata
