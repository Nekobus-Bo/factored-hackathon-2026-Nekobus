"""Seam between the chat API and the turn engine."""

import hashlib
from typing import Any, Protocol

from contracts.trace import TurnTrace
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.conversation.models import TurnEvalData
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
    eval: TurnEvalData | None = None
    # Detective mode (ADR-0019): the turn's timeline, masked values only.
    trace: TurnTrace | None = None


def derive_turn_id(conversation_id: str, client_message_id: str) -> str:
    """Turn id of a client-identified request: the same on every retry of it.

    The engine seeds the idempotency keys of its writes with the turn id, so a
    retry that carries the same client message id reuses the keys of the failed
    attempt and banking-core does not act twice.
    """
    digest = hashlib.sha256(f"{conversation_id}|{client_message_id}".encode())
    return digest.hexdigest()[:32]


class TurnHandler(Protocol):
    """Runs one customer turn.

    The handler owns `conversation.llm_history` and
    `conversation.placeholder_map` and may update them in place; the chat
    layer persists the state only if the turn returns normally.

    `turn_id` is set (see derive_turn_id) when the client identified the
    message; a request without it is not deduplicated, so a retry of it is a
    new turn.
    """

    async def handle_turn(
        self,
        conversation: ConversationState,
        user_text: str,
        turn_id: str | None = None,
    ) -> TurnOutcome: ...
