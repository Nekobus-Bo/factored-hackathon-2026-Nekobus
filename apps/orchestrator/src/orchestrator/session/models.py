"""Domain models for customer conversation session state."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

Lang = Literal["es", "pt", "en"]


class MessageRole(StrEnum):
    """Role in a conversation turn."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """A single message turn in the conversation history."""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str = Field(..., description="Masked message text")
    blocks: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Non-text message blocks (e.g. receipts). Text lives masked in content"
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Turn metadata (intent, state, confidence)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Message timestamp in UTC",
    )


class CompletedTurn(BaseModel):
    """The last completed turn, kept so a retried request is answered, not re-run."""

    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(
        ..., description="Id the client sent with the message (its retry handle)"
    )
    blocks: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Blocks returned to the customer, masked like the transcript (never "
            "raw PII); unmasked with the placeholder map when replayed"
        ),
    )


class ConversationState(BaseModel):
    """State for an ongoing customer conversation session on redis-edge.

    Maintains:
    - Opaque conversation_id exposed to the web client
    - banking_session_id mapped server-side to banking-core tools (ADR-0001, ADR-0004)
    - Session language (stored as given)
    - Masked message history
    - Sensitive placeholder map (encrypted at rest in Redis, never returned to client)
    - The last completed turn's masked outcome, for client retries
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(
        default_factory=lambda: f"conv_{uuid4().hex}",
        description="Opaque conversation identifier exposed to client",
    )
    banking_session_id: str = Field(
        ...,
        description="Downstream banking-core session identifier",
    )
    language: Lang = Field(
        default="es",
        description="Conversation language (es, pt, en), stored as given",
    )
    messages: list[Message] = Field(
        default_factory=list,
        description="Masked transcript shown by GET /v1/conversations/{id}",
    )
    llm_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Masked LLM transcript (tool calls and tool results included). "
            "Owned by the turn handler; never returned to the client"
        ),
    )
    placeholder_map: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Placeholder to raw PII mapping (encrypted at rest, server-side only)"
        ),
    )
    last_turn: CompletedTurn | None = Field(
        default=None,
        description=(
            "Outcome of the last completed turn that carried a client_message_id; "
            "None if the last turn had none"
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Session creation timestamp in UTC",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Session last update timestamp in UTC",
    )
