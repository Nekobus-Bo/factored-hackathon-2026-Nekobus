"""Session creation endpoint for banking-core."""

import uuid
from typing import Annotated

from contracts.envelope import VerificationState
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from banking_core.control.config import get_control_config_repository
from banking_core.control.session import RedisSessionStore, SessionState

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
