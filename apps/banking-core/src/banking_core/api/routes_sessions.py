"""Session endpoints for banking-core.

POST /v1/sessions                        open an anonymous session
GET  /v1/sessions/{id}/simulated-inbox   the session's simulated OTP messages
                                         (only while OTP_CHANNEL_MODE=simulated)
"""

import uuid
from datetime import datetime
from typing import Annotated

from contracts.envelope import VerificationState
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from banking_core.control.config import get_control_config_repository
from banking_core.control.session import RedisSessionStore, SessionState
from banking_core.identity.config import simulated_inbox_enabled
from banking_core.identity.simulated_inbox import SimulatedInbox, get_simulated_inbox

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
    return CreateSessionResponse(session_id=session_id)


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
