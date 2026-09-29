"""Customer-facing chat API.

POST /v1/conversations                 open a conversation (and a banking-core session);
                                       limited per client address (429 + Retry-After)
POST /v1/conversations/{id}/messages   run one turn, return the blocks; while a human
                                       agent holds the conversation, store the message
                                       for the agent and return no blocks
GET  /v1/conversations/{id}            masked transcript only, agent messages included,
                                       and whether an agent holds the conversation
GET  /v1/conversations/{id}/inbox      the simulated OTP messages of this conversation
                                       (ADR-0007): the code shown to the browser
                                       that types it, never stored or sent to the LLM

While a takeover is active (agent API) the LLM, the encoder and the banking-core
tools are out of the loop: the customer's message is masked and stored, and the
answer is an empty block list. The customer sees the agent's replies by reading
the transcript.

A message may carry a `client_message_id`. It makes the request safe to retry:
the writes of a re-run turn reuse their idempotency keys, and a retry of the
last completed turn gets its stored outcome back without running again. A
message without one is not deduplicated.

The inbox is a pass-through to banking-core for the conversation's own banking
session. It reads the conversation only for that id and saves nothing: the code
never enters the LLM history, the transcript, the turn metadata or the logs.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from contracts import MESSAGE_BLOCK_ADAPTER
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from orchestrator.chat.client_ip import client_ip
from orchestrator.chat.handler import TurnHandler, derive_turn_id
from orchestrator.chat.transcript import (
    TRANSCRIPT_MASKER,
    TranscriptMessage,
    mask_for_transcript,
    transcript_messages,
)
from orchestrator.conversation.engine import mask_bare_otps, otp_challenge_pending
from orchestrator.conversation.models import TurnEvalData
from orchestrator.llm.replay import ReplayMissError
from orchestrator.session.models import (
    CompletedTurn,
    ConversationState,
    Lang,
    Message,
    MessageRole,
)
from orchestrator.session.rate_limit import ConversationRateLimiter
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import (
    BankingCoreClient,
    InboxUnavailableError,
    SessionCreationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["chat"])


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: Lang | None = None


class CreateConversationResponse(BaseModel):
    conversation_id: str
    language: Lang


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=2000)
    lang: Lang | None = None
    client_message_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Unique per message, repeated unchanged when the same message is "
            "sent again. Without it a retry is treated as a new message"
        ),
    )


class SendMessageResponse(BaseModel):
    conversation_id: str
    blocks: list[dict[str, Any]]
    eval: TurnEvalData | None = None


class TakeoverStatus(BaseModel):
    """What the customer may know: that an agent is attending, and since when."""

    active: bool
    since: datetime | None


class TranscriptResponse(BaseModel):
    conversation_id: str
    language: Lang
    messages: list[TranscriptMessage]
    takeover: TakeoverStatus


class InboxMessageResponse(BaseModel):
    """One simulated OTP delivery. It carries the clear code by design (ADR-0007)."""

    channel: str
    destination_masked: str
    code: str = Field(repr=False)
    received_at: datetime
    expires_at: datetime


class InboxResponse(BaseModel):
    messages: list[InboxMessageResponse]


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.session_store
    return store


def _banking(request: Request) -> BankingCoreClient:
    banking: BankingCoreClient = request.app.state.banking_client
    return banking


async def _enforce_conversation_limit(request: Request) -> None:
    """429 before any banking-core session exists; 503 if the limit cannot be read.

    Fails closed: without redis-edge the limit cannot be enforced, and the
    conversation itself could not be stored anyway.
    """
    limiter: ConversationRateLimiter = request.app.state.conversation_limiter
    address = client_ip(request, request.app.state.trusted_proxy_hops)
    try:
        decision = await limiter.hit(address)
    except RedisError as exc:
        logger.error("Conversation rate limiter unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversations are temporarily unavailable",
        ) from exc
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many conversations opened from this address; try again later",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _handler(request: Request) -> TurnHandler:
    handler: TurnHandler | None = request.app.state.turn_handler
    if handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Turn handler is unavailable",
        )
    return handler


def _validate_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        validated = [MESSAGE_BLOCK_ADAPTER.validate_python(block) for block in blocks]
    except ValidationError as exc:
        logger.error("Turn handler returned a block outside the message contract")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Turn output violates the message block contract",
        ) from exc
    return [block.model_dump(mode="json") for block in validated]


async def _load(store: SessionStore, conversation_id: str) -> ConversationState:
    state = await store.get(conversation_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return state


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateConversationResponse,
)
async def create_conversation(
    request: Request, body: CreateConversationRequest | None = None
) -> CreateConversationResponse:
    await _enforce_conversation_limit(request)
    try:
        banking_session_id = await _banking(request).create_session()
    except SessionCreationError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Could not open a banking session"
        ) from exc

    lang = (body.lang if body else None) or request.app.state.default_lang
    state = ConversationState(banking_session_id=banking_session_id, language=lang)
    await _store(request).save(state)
    return CreateConversationResponse(
        conversation_id=state.conversation_id, language=state.language
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    response_model_exclude_none=True,
)
async def send_message(
    request: Request, conversation_id: str, body: SendMessageRequest
) -> SendMessageResponse:
    store = _store(request)
    handler = _handler(request)
    known = await _load(store, conversation_id)

    # A conversation an agent holds is not a turn: the agent API may be writing
    # to it at the same moment, so wait a moment for the lock instead of failing.
    token = await store.acquire_turn_lock(
        conversation_id,
        wait_seconds=(
            request.app.state.agent_lock_wait_seconds if known.takeover.active else 0.0
        ),
    )
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A turn is already in progress"
        )
    try:
        state = await _load(store, conversation_id)
        completed = state.last_turn
        if (
            body.client_message_id is not None
            and completed is not None
            and completed.client_message_id == body.client_message_id
        ):
            # The client is retrying the turn that just completed: answer from
            # the stored outcome. No LLM call, no tool call, nothing appended.
            logger.info("Retried message answered from the stored outcome")
            return SendMessageResponse(
                conversation_id=conversation_id,
                blocks=_validate_blocks(
                    [
                        _unmask_block_values(block, state.placeholder_map)
                        for block in completed.blocks
                    ]
                ),
            )
        if body.lang:
            state.language = body.lang
        if state.takeover.active:
            # Read under the lock, so a takeover that just landed is seen. The
            # handler is never reached: no LLM, no encoder, no tool.
            _append_customer_message(state, body.text)
            state.last_turn = _completed_turn(state, body.client_message_id, [])
            state.updated_at = datetime.now(UTC)
            if not await store.save_fenced(state, token):
                logger.error("Message lost its lock before saving; state not saved")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The message took too long and was not saved",
                )
            return SendMessageResponse(
                conversation_id=conversation_id,
                blocks=[],
                # There is no turn, so no provider evidence: an empty record.
                eval=TurnEvalData() if request.app.state.eval_expose_turn else None,
            )
        turn_id = (
            derive_turn_id(conversation_id, body.client_message_id)
            if body.client_message_id is not None
            else None
        )
        try:
            outcome = await handler.handle_turn(state, body.text, turn_id=turn_id)
        except ReplayMissError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail="replay_miss"
            ) from exc
        except Exception as exc:
            logger.exception("Turn failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The turn could not run",
            ) from exc

        blocks = _validate_blocks(outcome.blocks)
        _append_transcript(state, body.text, blocks, outcome.metadata)
        state.last_turn = _completed_turn(state, body.client_message_id, blocks)
        state.updated_at = datetime.now(UTC)
        if not await store.save_fenced(state, token):
            logger.error("Turn lost its lock before saving; state not saved")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The turn took too long and was not saved",
            )
    finally:
        await store.release_turn_lock(conversation_id, token)

    return SendMessageResponse(
        conversation_id=conversation_id,
        blocks=blocks,
        eval=outcome.eval if request.app.state.eval_expose_turn else None,
    )


@router.get("/{conversation_id}", response_model=TranscriptResponse)
async def get_transcript(request: Request, conversation_id: str) -> TranscriptResponse:
    state = await _load(_store(request), conversation_id)
    return TranscriptResponse(
        conversation_id=state.conversation_id,
        language=state.language,
        messages=transcript_messages(state),
        takeover=TakeoverStatus(
            active=state.takeover.active, since=state.takeover.since
        ),
    )


@router.get("/{conversation_id}/inbox", response_model=InboxResponse)
async def get_inbox(
    request: Request, response: Response, conversation_id: str
) -> InboxResponse:
    """Simulated OTP messages of this conversation's banking session, newest first.

    The web client shows them as "you got an email with the code". The
    conversation is loaded only to find its own banking session, so no other
    session's code can be asked for. Nothing is saved or logged from the answer.
    """
    state = await _load(_store(request), conversation_id)
    try:
        messages = await _banking(request).simulated_inbox(state.banking_session_id)
    except InboxUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The inbox is temporarily unavailable",
        ) from exc
    # The body holds a live code: no cache, in the browser or on the way.
    response.headers["Cache-Control"] = "no-store"
    return InboxResponse(
        messages=[
            InboxMessageResponse(
                channel=message.channel,
                destination_masked=message.destination_masked,
                code=message.code,
                received_at=message.received_at,
                expires_at=message.expires_at,
            )
            for message in messages
        ]
    )


def _mask_block_values(value: Any, placeholder_map: dict[str, str]) -> Any:
    """Mask recursive JSON values; Any represents nested MessageBlock payloads."""
    if isinstance(value, str):
        return mask_for_transcript(value, placeholder_map, TRANSCRIPT_MASKER)
    if isinstance(value, list):
        return [_mask_block_values(item, placeholder_map) for item in value]
    if isinstance(value, dict):
        return {
            key: _mask_block_values(item, placeholder_map)
            for key, item in value.items()
        }
    return value


def _unmask_block_values(value: Any, placeholder_map: dict[str, str]) -> Any:
    """Inverse of _mask_block_values: put the customer's own values back."""
    if isinstance(value, str):
        return TRANSCRIPT_MASKER.unmask(value, placeholder_map)
    if isinstance(value, list):
        return [_unmask_block_values(item, placeholder_map) for item in value]
    if isinstance(value, dict):
        return {
            key: _unmask_block_values(item, placeholder_map)
            for key, item in value.items()
        }
    return value


def _completed_turn(
    state: ConversationState,
    client_message_id: str | None,
    blocks: list[dict[str, Any]],
) -> CompletedTurn | None:
    """What a retry of this turn gets back; None if the client did not tag it.

    The blocks reach the customer with their own values in the text, so they are
    stored masked like the transcript and unmasked again on replay: Redis never
    holds them in clear.
    """
    if client_message_id is None:
        return None
    return CompletedTurn(
        client_message_id=client_message_id,
        blocks=[_mask_block_values(block, state.placeholder_map) for block in blocks],
    )


def _append_customer_message(state: ConversationState, user_text: str) -> None:
    """Store a customer message masked, with nothing after it: an agent answers.

    The assistant is not reading, so a code the customer types into a challenge
    that was pending when the agent took over is masked here, as the engine
    would: an OTP never enters the transcript.
    """
    text = user_text
    if otp_challenge_pending(state.llm_history):
        text = mask_bare_otps(text, state.placeholder_map)
    state.messages.append(
        Message(
            role=MessageRole.USER,
            content=mask_for_transcript(text, state.placeholder_map, TRANSCRIPT_MASKER),
        )
    )


def _append_transcript(
    state: ConversationState,
    user_text: str,
    blocks: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> None:
    """Store the turn masked: texts re-masked here, non-text blocks kept."""
    pm = state.placeholder_map
    state.messages.append(
        Message(
            role=MessageRole.USER,
            content=mask_for_transcript(user_text, pm, TRANSCRIPT_MASKER),
        )
    )
    reply = "\n".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    state.messages.append(
        Message(
            role=MessageRole.ASSISTANT,
            content=mask_for_transcript(reply, pm, TRANSCRIPT_MASKER) if reply else "",
            blocks=[
                _mask_block_values(block, pm)
                for block in blocks
                if block.get("type") != "text"
            ],
            metadata=metadata,
        )
    )
