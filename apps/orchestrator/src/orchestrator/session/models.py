"""Domain models for customer conversation session state."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from contracts.locale import Locale
from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.conversation.decisions.state import DecisionState

Lang = Literal["es", "pt", "en"]


class MessageRole(StrEnum):
    """Role in a conversation turn."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    AGENT = "agent"


class Message(BaseModel):
    """A single message turn in the conversation history.

    `content` is always masked: it is what redis-edge holds in clear and the only
    text anything but a transcript reader may use. An agent message may also keep
    the text as the agent wrote it, encrypted, in `content_enc`.
    """

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str = Field(..., description="Masked message text")
    content_enc: str | None = Field(
        default=None,
        repr=False,
        description=(
            "Agent messages only: the text as the agent wrote it, encrypted "
            "(Fernet, keyed by SESSION_SECRET). Never in clear at rest, never "
            "read to build the LLM history, never returned as a field: a "
            "transcript reader decrypts it into `content` (chat/transcript.py). "
            "Absent on messages stored before it existed"
        ),
    )
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
    client_message_id: str | None = Field(
        default=None,
        description=(
            "Retry handle of an agent message (the agent API returns the stored "
            "message when it is repeated). Never shown in a transcript"
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Message timestamp in UTC",
    )

    @model_validator(mode="after")
    def _only_an_agent_keeps_its_text_as_written(self) -> "Message":
        if self.content_enc is not None and self.role is not MessageRole.AGENT:
            raise ValueError("only an agent message keeps its text as written")
        return self


class Takeover(BaseModel):
    """Whether a human agent has taken the conversation over from the assistant.

    Once active it stays active: there is no hand-back to the assistant. While
    active the LLM never sees the conversation again (see
    conversation/engine.py) and the customer's messages only reach the agent.

    An active takeover with no `agent_ref` was released by its agent when the
    case went back to the queue (ADR-0018): the assistant stays off, nobody may
    write, and the next agent's takeover picks it up.
    """

    model_config = ConfigDict(extra="forbid")

    active: bool = False
    since: datetime | None = Field(
        default=None, description="When the takeover started, in UTC"
    )
    agent_ref: str | None = Field(
        default=None,
        description=(
            "Who holds the conversation. Server-side and agent-side only: the "
            "customer's transcript never carries it"
        ),
    )

    @model_validator(mode="after")
    def _active_names_its_holder(self) -> "Takeover":
        if self.active and self.since is None:
            raise ValueError("an active takeover needs since")
        if self.active and self.agent_ref == "":
            raise ValueError("an active takeover names its agent, or None if released")
        if not self.active and (self.since is not None or self.agent_ref is not None):
            raise ValueError("an inactive takeover carries no since or agent_ref")
        return self


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
    - Masked message history (an agent's text also kept as written, encrypted)
    - Sensitive placeholder map (encrypted at rest in Redis, never returned to client)
    - The last completed turn's masked outcome, for client retries
    - The decision-point state (consent for a gated write, sticky ledgers)
    - Whether a human agent has taken the conversation over
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
    locale: Locale | None = Field(
        default=None,
        description=(
            "Market (pt-BR, es-MX, es-AR, es-CO, en-US; ADR-0014); dropped when the "
            "language switches away from it. States saved before it load as None"
        ),
    )
    messages: list[Message] = Field(
        default_factory=list,
        description=(
            "Masked transcript behind GET /v1/conversations/{id}; an agent "
            "message is shown as written (Message.content_enc)"
        ),
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
    decisions: DecisionState = Field(
        default_factory=DecisionState,
        description=(
            "State of the decision-point effects (consent, sticky ledgers, turn "
            "count; ADR-0012). No text; committed only when a turn completes"
        ),
    )
    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "Catalog tools banking-core's latest flow hint says the configuration "
            "enables (ADR-0016); None until the first tool result. Tool names only"
        ),
    )
    takeover: Takeover = Field(
        default_factory=Takeover,
        description="Human takeover of the conversation (agent API)",
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
