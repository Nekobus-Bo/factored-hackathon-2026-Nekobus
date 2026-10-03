"""Session endpoints for banking-core.

POST /v1/sessions                        open an anonymous session, with its
                                         flow hint (ADR-0016)
GET  /v1/sessions/{id}/simulated-inbox   the session's simulated OTP messages
                                         (only while OTP_CHANNEL_MODE=simulated)
POST /v1/sessions/{id}/feedback          the customer's answer to "did the assistant
                                         help?", for the session's handoff (ADR-0017)
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from contracts.envelope import FlowHint, VerificationState
from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from banking_core.control.config import get_control_config_repository
from banking_core.control.flow import flow_hint
from banking_core.control.session import RedisSessionStore, SessionState
from banking_core.db import get_session_maker
from banking_core.handoff.feedback import (
    AlreadyAnsweredError,
    NoHandoffError,
    read_feedback,
    record_feedback,
)
from banking_core.identity.config import simulated_inbox_enabled
from banking_core.identity.simulated_inbox import SimulatedInbox, get_simulated_inbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

_session_store: RedisSessionStore | None = None


def configured_session_ttl_seconds() -> int:
    """session_ttl_seconds of the active policy config (ADR-0002)."""
    return get_control_config_repository().get_policy_config().session_ttl_seconds


def get_session_store() -> RedisSessionStore:
    """Dependency to provide RedisSessionStore instance."""
    global _session_store
    if _session_store is None:
        _session_store = RedisSessionStore(ttl_provider=configured_session_ttl_seconds)
    return _session_store


def set_session_store(store: RedisSessionStore) -> None:
    """Override session store (for tests)."""
    global _session_store
    _session_store = store


class CreateSessionResponse(BaseModel):
    """Response returned upon session creation."""

    session_id: str = Field(..., description="Opaque session identifier")
    flow: FlowHint | None = Field(
        default=None,
        description=(
            "The flow hint of the new ANONYMOUS session, as every tool result "
            "carries it (ADR-0016 amendment 2026-10-02); absent if the "
            "configuration could not be read"
        ),
    )


def _opening_flow(state: VerificationState) -> FlowHint | None:
    """The new session's flow hint; like every hint, it never fails the call."""
    try:
        config_repo = get_control_config_repository()
    except Exception as exc:
        logger.warning("Flow hint skipped on session creation: %s", type(exc).__name__)
        return None
    return flow_hint(state, config_repo)


@router.post("", response_model=CreateSessionResponse, status_code=201)
def create_session(
    store: Annotated[RedisSessionStore, Depends(get_session_store)],
) -> CreateSessionResponse:
    """Create a new anonymous session with pinned state in Redis."""
    session_id = f"sess_{uuid.uuid4().hex}"
    session = SessionState(
        session_id=session_id,
        state=VerificationState.ANONYMOUS,
    )
    store.save(session)
    return CreateSessionResponse(
        session_id=session_id,
        flow=_opening_flow(session.state),
    )


class SimulatedInboxMessageResponse(BaseModel):
    """One simulated OTP delivery. It carries the clear code by design (ADR-0007)."""

    challenge_id: str
    channel: str
    destination_masked: str
    code: str = Field(repr=False)
    created_at: datetime
    expires_at: datetime


class SimulatedInboxResponse(BaseModel):
    messages: list[SimulatedInboxMessageResponse]


@router.get("/{session_id}/simulated-inbox", response_model=SimulatedInboxResponse)
def read_simulated_inbox(
    session_id: str,
    response: Response,
    store: Annotated[RedisSessionStore, Depends(get_session_store)],
    inbox: Annotated[SimulatedInbox, Depends(get_simulated_inbox)],
) -> SimulatedInboxResponse:
    """Unexpired simulated OTP messages of this session, newest first.

    The session id in the path scopes every read: there is no way to ask for
    another session's messages, and an unknown or expired session is a 404. The
    endpoint exists only while OTP_CHANNEL_MODE=simulated. It is for the
    orchestrator, which relays it to the browser of the same conversation.
    """
    if not simulated_inbox_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulated inbox is not available: OTP_CHANNEL_MODE is not "
            "'simulated'",
        )
    if store.get(session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired",
        )
    # The body holds a live code: no cache, in the browser or on the way.
    response.headers["Cache-Control"] = "no-store"
    return SimulatedInboxResponse(
        messages=[
            SimulatedInboxMessageResponse(
                challenge_id=message.challenge_id,
                channel=message.channel,
                destination_masked=message.destination_masked,
                code=message.code,
                created_at=message.created_at,
                expires_at=message.expires_at,
            )
            for message in inbox.messages(session_id)
        ]
    )


class AssistantFeedbackRequest(BaseModel):
    """The customer's answer, as the orchestrator relays it."""

    model_config = ConfigDict(extra="forbid")

    helpful: StrictBool


class AssistantFeedbackResponse(BaseModel):
    """The answer as stored, re-read after the commit."""

    handoff_ref: str
    helpful: bool
    recorded_at: datetime


@router.post("/{session_id}/feedback", response_model=AssistantFeedbackResponse)
def record_assistant_feedback(
    request: AssistantFeedbackRequest,
    session_id: Annotated[str, Path(max_length=128, pattern=r"^sess_[0-9a-f]{32}$")],
) -> AssistantFeedbackResponse:
    """Store the answer for the session's newest handoff, once (ADR-0017).

    The handoff decides, not the session in Redis: the answer may come after the
    session has expired. 409 `no_handoff` when the session has none, 409
    `already_answered` when it holds the other answer; the same answer again is a
    200 with the stored row and no second write.
    """
    with get_session_maker()() as db_session:
        try:
            result = record_feedback(db_session, session_id, request.helpful)
        except NoHandoffError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "no_handoff") from exc
        except AlreadyAnsweredError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "already_answered") from exc
        db_session.commit()
        db_session.expire_all()
        stored = read_feedback(db_session, result.handoff_ref)
    # Committed above: only a handoff deleted in between lands here.
    if stored is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_handoff")
    return AssistantFeedbackResponse(
        handoff_ref=stored.handoff_ref,
        helpful=stored.helpful,
        recorded_at=stored.recorded_at,
    )
