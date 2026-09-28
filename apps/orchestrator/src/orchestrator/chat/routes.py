"""Customer-facing chat API.

POST /v1/conversations                 open a conversation (and a banking-core session)
POST /v1/conversations/{id}/messages   run one turn, return the blocks
GET  /v1/conversations/{id}            masked transcript only
"""

import logging
from datetime import UTC, datetime
from typing import Any

from contracts import MESSAGE_BLOCK_ADAPTER
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from orchestrator.chat.handler import TurnHandler
from orchestrator.chat.transcript import mask_for_transcript
from orchestrator.conversation.models import TurnEvalData
from orchestrator.llm.replay import ReplayMissError
from orchestrator.privacy.masking import Masker, RegexMasker
from orchestrator.session.models import (
    ConversationState,
    Lang,
    Message,
    MessageRole,
)
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient, SessionCreationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/conversations", tags=["chat"])

_masker: Masker = RegexMasker()


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


class SendMessageResponse(BaseModel):
    conversation_id: str
    blocks: list[dict[str, Any]]
    eval: TurnEvalData | None = None


class TranscriptMessage(BaseModel):
    role: MessageRole
    content: str
    blocks: list[dict[str, Any]]
    created_at: datetime


class TranscriptResponse(BaseModel):
    conversation_id: str
    language: Lang
    messages: list[TranscriptMessage]


def _store(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.session_store
    return store


def _banking(request: Request) -> BankingCoreClient:
    banking: BankingCoreClient = request.app.state.banking_client
    return banking


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
    await _load(store, conversation_id)

    token = await store.acquire_turn_lock(conversation_id)
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A turn is already in progress"
        )
    try:
        state = await _load(store, conversation_id)
        if body.lang:
            state.language = body.lang
        try:
            outcome = await handler.handle_turn(state, body.text)
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
        messages=[
            TranscriptMessage(
                role=m.role, content=m.content, blocks=m.blocks, created_at=m.created_at
            )
            for m in state.messages
            if m.role is not MessageRole.SYSTEM
        ],
    )


def _mask_block_values(value: Any, placeholder_map: dict[str, str]) -> Any:
    """Mask recursive JSON values; Any represents nested MessageBlock payloads."""
    if isinstance(value, str):
        return mask_for_transcript(value, placeholder_map, _masker)
    if isinstance(value, list):
        return [_mask_block_values(item, placeholder_map) for item in value]
    if isinstance(value, dict):
        return {
            key: _mask_block_values(item, placeholder_map)
            for key, item in value.items()
        }
    return value


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
            role=MessageRole.USER, content=mask_for_transcript(user_text, pm, _masker)
        )
    )
    reply = "\n".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    state.messages.append(
        Message(
            role=MessageRole.ASSISTANT,
            content=mask_for_transcript(reply, pm, _masker) if reply else "",
            blocks=[
                _mask_block_values(block, pm)
                for block in blocks
                if block.get("type") != "text"
            ],
            metadata=metadata,
        )
    )
