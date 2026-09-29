"""Tool invocation dispatcher endpoint for banking-core."""

from typing import Annotated

from contracts.envelope import ToolCall, ToolResult
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from banking_core.api.dispatcher import SessionNotFoundError, ToolDispatcher
from banking_core.api.routes_sessions import get_session_store
from banking_core.control.session import RedisSessionStore
from banking_core.db import get_db

router = APIRouter(prefix="/v1/tools", tags=["tools"])

_dispatcher: ToolDispatcher | None = None


def get_dispatcher(
    session_store: Annotated[RedisSessionStore, Depends(get_session_store)],
) -> ToolDispatcher:
    """Dependency to provide ToolDispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ToolDispatcher(session_store=session_store)
    return _dispatcher


def set_dispatcher(dispatcher: ToolDispatcher) -> None:
    """Override dispatcher (for tests)."""
    global _dispatcher
    _dispatcher = dispatcher


@router.post("/call", response_model=ToolResult)
def call_tool(
    tool_call: ToolCall,
    x_session_id: Annotated[str | None, Header(alias="X-Session-Id")] = None,
    dispatcher: Annotated[ToolDispatcher, Depends(get_dispatcher)] = None,
    db_session: Annotated[Session, Depends(get_db)] = None,
) -> ToolResult:
    """Execute a tool call within an established customer verification session.

    Rate limits are per session (policy engine) and, across sessions, per
    customer (failed OTP verifications) and per claimed document (failed
    matches): see control/attempt_limits.py. Per-IP limiting belongs at the
    edge (the orchestrator limits conversation creation): the only client here
    is the orchestrator, and client-supplied forwarding headers are never
    trusted.
    """
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required 'X-Session-Id' header",
        )

    try:
        return dispatcher.dispatch_in_session(
            tool_call=tool_call,
            session_id=x_session_id,
            db_session=db_session,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{x_session_id}' not found or expired",
        ) from exc
