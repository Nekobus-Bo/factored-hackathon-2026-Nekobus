"""Seam between the chat API and the turn engine."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.session.models import ConversationState


class TurnOutcome(BaseModel):
    """What a turn produced.

    `blocks` go to the client as returned (text may carry the customer's own
    values back). The chat layer builds the stored transcript from them and
    re-masks every text, so a handler cannot leak raw PII into the transcript.
    """

    model_config = ConfigDict(extra="forbid")

    blocks: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnHandler(Protocol):
    """Runs one customer turn.

    The handler owns `conversation.llm_history` and
    `conversation.placeholder_map` and may update them in place; the chat
    layer persists the state only if the turn returns normally.
    """

    async def handle_turn(
        self, conversation: ConversationState, user_text: str
    ) -> TurnOutcome: ...
