"""Agent API: what the back office needs to read and take over a conversation.

GET  /v1/agent/sessions/{session_ref}/conversation  banking session id -> conversation
GET  /v1/agent/conversations/{id}                    transcript and takeover
POST /v1/agent/conversations/{id}/takeover           an agent takes the conversation
POST /v1/agent/conversations/{id}/messages           an agent writes to the customer
POST /v1/agent/conversations/{id}/release            the holder lets it go (ADR-0018)
GET  /v1/agent/detective                             detective mode: offered, and on?
PUT  /v1/agent/detective                             turn it on or off (ADR-0019)

Mounted only when AGENT_API_ENABLED=true, behind a bearer token (agent/auth.py).
The caller is the back-office server, which authenticates the agent itself and
says who it is: `agent_ref` on takeover, `X-Agent-Ref` on every message. Both
routes write under the conversation's turn lock, so a takeover and a customer
turn in flight never overwrite each other. The design is in
docs/adr/0013-front-ends-bff-takeover.md.

The agent sees the transcript and nothing else: never the LLM history, never the
placeholder map. What an agent writes is stored twice: masked, like everything
else in the transcript (that is what redis-edge holds in clear), and as written,
encrypted, so the customer and the agent read it as written (ADR-0013, amendment
2026-09-29). The text as written is decrypted only to answer these routes and the
customer's transcript; it never reaches the LLM, the encoder, a tool or a log.
Once a takeover is active it stays so: there is no hand-back to the assistant.
Its agent can release it when the case goes back to the queue (ADR-0018); the
assistant stays off and the next agent's takeover picks the conversation up.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from redis.exceptions import RedisError

from orchestrator.agent.auth import require_agent
from orchestrator.chat.transcript import (
    TRANSCRIPT_MASKER,
    TranscriptMessage,
    mask_for_transcript,
    text_as_written,
    transcript_messages,
)
from orchestrator.detective import DetectiveSwitch, DetectiveUnavailableError
from orchestrator.session.crypto import CryptoError
from orchestrator.session.models import (
    ConversationState,
    Lang,
    Message,
    MessageRole,
    Takeover,
)
from orchestrator.session.store import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/agent", tags=["agent"], dependencies=[Depends(require_agent)]
)

# banking-core's ops.handoff.session_ref is a String(128).
_MAX_SESSION_REF = 128

AgentRef = Annotated[
    str, StringConstraints(min_length=3, max_length=254, pattern=r"^\S+$")
]


class DetectiveState(BaseModel):
    """Detective mode (ADR-0019): offered by the environment, and on right now."""

    available: bool
    enabled: bool


class DetectiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ConversationRefResponse(BaseModel):
    conversation_id: str


class AgentTakeoverState(BaseModel):
    """The takeover as the back office sees it: it does name the agent."""

    active: bool
    since: datetime | None
    agent_ref: str | None


class AgentTranscriptResponse(BaseModel):
    conversation_id: str
    language: Lang
    messages: list[TranscriptMessage]
    takeover: AgentTakeoverState


class TakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_ref: AgentRef
    handoff_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class TakeoverResponse(BaseModel):
    conversation_id: str
    takeover: AgentTakeoverState


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_ref: AgentRef
    handoff_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class AgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    client_message_id: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Unique per message, repeated unchanged on a retry",
    )


class AgentMessage(BaseModel):
    """The stored message. `content` is the text as the agent wrote it."""

    role: MessageRole
    content: str
    blocks: list[dict[str, Any]]
    created_at: datetime


class AgentMessageResponse(BaseModel):
    message: AgentMessage


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.session_store
    return store


async def _load(store: SessionStore, conversation_id: str) -> ConversationState:
    state = await store.get(conversation_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return state


def _takeover_view(takeover: Takeover) -> AgentTakeoverState:
    return AgentTakeoverState(
        active=takeover.active, since=takeover.since, agent_ref=takeover.agent_ref
    )


def _busy() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="turn_in_progress",
        headers={"Retry-After": "2"},
    )


def _not_saved() -> HTTPException:
    logger.error("Agent write lost its lock before saving; state not saved")
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, detail="The change was not saved"
    )


@router.get(
    "/sessions/{session_ref}/conversation", response_model=ConversationRefResponse
)
async def conversation_of_session(
    request: Request, session_ref: str
) -> ConversationRefResponse:
    """The conversation of a banking-core session id (what a handoff records)."""
    store = _store(request)
    conversation_id = (
        await store.conversation_id_for_session(session_ref)
        if 0 < len(session_ref) <= _MAX_SESSION_REF
        else None
    )
    state = await store.get(conversation_id) if conversation_id else None
    # The index and the conversation expire together; checking the conversation
    # still holds that session keeps a stale entry from answering.
    if state is None or state.banking_session_id != session_ref:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationRefResponse(conversation_id=state.conversation_id)


@router.get("/conversations/{conversation_id}", response_model=AgentTranscriptResponse)
async def get_conversation(
    request: Request, conversation_id: str
) -> AgentTranscriptResponse:
    store = _store(request)
    state = await _load(store, conversation_id)
    return AgentTranscriptResponse(
        conversation_id=state.conversation_id,
        language=state.language,
        messages=transcript_messages(state, store.encryptor),
        takeover=_takeover_view(state.takeover),
    )


@router.post(
    "/conversations/{conversation_id}/takeover", response_model=TakeoverResponse
)
async def take_over(
    request: Request, conversation_id: str, body: TakeoverRequest
) -> TakeoverResponse:
    """Close the conversation to the assistant and hand it to `agent_ref`.

    Idempotent for the agent who holds it; 409 for anyone else. It waits for a
    customer turn in flight (the assistant may be mid-reply): the takeover lands
    after that turn is saved, and every turn after it is refused by the engine.
    """
    store = _store(request)
    await _load(store, conversation_id)
    wait = request.app.state.agent_lock_wait_seconds
    async with store.turn_lock(conversation_id, wait_seconds=wait) as token:
        if token is None:
            raise _busy()
        state = await _load(store, conversation_id)
        holder = state.takeover.agent_ref
        if state.takeover.active and holder is not None:
            if holder != body.agent_ref:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, detail="taken_over_by_another_agent"
                )
            return TakeoverResponse(
                conversation_id=conversation_id,
                takeover=_takeover_view(state.takeover),
            )
        # Never taken, or released by its last agent: this agent holds it now.
        now = datetime.now(UTC)
        state.takeover = Takeover(active=True, since=now, agent_ref=body.agent_ref)
        state.updated_at = now
        if not await store.save_fenced(state, token):
            raise _not_saved()
    logger.info("Conversation taken over (handoff %s)", body.handoff_ref)
    return TakeoverResponse(
        conversation_id=conversation_id, takeover=_takeover_view(state.takeover)
    )


@router.post(
    "/conversations/{conversation_id}/release", response_model=TakeoverResponse
)
async def release(
    request: Request, conversation_id: str, body: ReleaseRequest
) -> TakeoverResponse:
    """Let the conversation go when its case goes back to the queue (ADR-0018).

    Only its holder may release it, and the assistant stays off: the takeover
    stays active with no agent until the next agent's takeover. A conversation
    that was never taken, or is already released, is answered as it is.
    """
    store = _store(request)
    await _load(store, conversation_id)
    wait = request.app.state.agent_lock_wait_seconds
    async with store.turn_lock(conversation_id, wait_seconds=wait) as token:
        if token is None:
            raise _busy()
        state = await _load(store, conversation_id)
        holder = state.takeover.agent_ref
        if state.takeover.active and holder is not None:
            if holder != body.agent_ref:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, detail="taken_over_by_another_agent"
                )
            state.takeover = Takeover(
                active=True, since=state.takeover.since, agent_ref=None
            )
            state.updated_at = datetime.now(UTC)
            if not await store.save_fenced(state, token):
                raise _not_saved()
            logger.info("Conversation released (handoff %s)", body.handoff_ref)
    return TakeoverResponse(
        conversation_id=conversation_id, takeover=_takeover_view(state.takeover)
    )


@router.post(
    "/conversations/{conversation_id}/messages", response_model=AgentMessageResponse
)
async def send_agent_message(
    request: Request,
    conversation_id: str,
    body: AgentMessageRequest,
    x_agent_ref: Annotated[AgentRef, Header()],
) -> AgentMessageResponse:
    """Store the agent's reply and answer with it as written.

    Stored masked in `content` and, encrypted, as written. A repeated
    `client_message_id` is a retry: it returns the stored message, not a new one.
    """
    store = _store(request)
    await _load(store, conversation_id)
    wait = request.app.state.agent_lock_wait_seconds
    async with store.turn_lock(conversation_id, wait_seconds=wait) as token:
        if token is None:
            raise _busy()
        state = await _load(store, conversation_id)
        if not state.takeover.active or state.takeover.agent_ref != x_agent_ref:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="no_active_takeover")
        stored = next(
            (
                m
                for m in state.messages
                if m.role is MessageRole.AGENT
                and m.client_message_id == body.client_message_id
            ),
            None,
        )
        if stored is None:
            try:
                as_written = store.encryptor.encrypt_text(body.text)
            except CryptoError as exc:
                logger.error("Agent text could not be encrypted; message not saved")
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The message was not saved",
                ) from exc
            stored = Message(
                role=MessageRole.AGENT,
                content=mask_for_transcript(
                    body.text, state.placeholder_map, TRANSCRIPT_MASKER
                ),
                content_enc=as_written,
                client_message_id=body.client_message_id,
            )
            state.messages.append(stored)
            state.updated_at = datetime.now(UTC)
            if not await store.save_fenced(state, token):
                raise _not_saved()
    return AgentMessageResponse(
        message=AgentMessage(
            role=stored.role,
            content=text_as_written(stored, store.encryptor),
            blocks=stored.blocks,
            created_at=stored.created_at,
        )
    )


@router.get("/detective", response_model=DetectiveState)
async def get_detective(request: Request) -> DetectiveState:
    """Whether customer turns come with their trace, for the back office's switch."""
    switch: DetectiveSwitch = request.app.state.detective
    return DetectiveState(available=switch.available, enabled=await switch.enabled())


@router.put("/detective", response_model=DetectiveState)
async def set_detective(request: Request, body: DetectiveRequest) -> DetectiveState:
    """Turn detective mode on or off for every conversation, at once (ADR-0019).

    409 where the environment does not offer it: the switch moves only within
    what DETECTIVE_MODE allows.
    """
    switch: DetectiveSwitch = request.app.state.detective
    try:
        enabled = await switch.set(body.enabled)
    except DetectiveUnavailableError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="detective_unavailable"
        ) from exc
    except RedisError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="The change was not saved"
        ) from exc
    logger.info("Detective mode switched %s", "on" if enabled else "off")
    return DetectiveState(available=True, enabled=enabled)
