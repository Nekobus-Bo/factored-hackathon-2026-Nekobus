"""Orchestrator service entrypoint."""

from fastapi import FastAPI
from pydantic import BaseModel
from redis.asyncio import Redis

from orchestrator.chat.handler import TurnHandler
from orchestrator.chat.routes import router as chat_router
from orchestrator.config import Settings, get_settings
from orchestrator.log_redaction import install_redaction
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.store import SessionStore
from orchestrator.tools_client import BankingCoreClient


class HealthResponse(BaseModel):
    status: str
    service: str


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    banking_client: BankingCoreClient | None = None,
    turn_handler: TurnHandler | None = None,
) -> FastAPI:
    """Build the app. Dependencies are injectable for tests.

    Without a turn handler the chat routes answer 503 with an explicit
    message (the engine adapter is wired separately).
    """
    cfg = settings or get_settings()
    app = FastAPI(title="orchestrator")
    install_redaction(("uvicorn.access", "uvicorn.error"))

    # Redis connects lazily: building the client does not need redis-edge up.
    app.state.session_store = session_store or SessionStore(
        redis=Redis(
            host=cfg.redis_edge_host,
            port=cfg.redis_edge_port,
            password=cfg.redis_edge_password,
        ),
        encryptor=PlaceholderEncryptor(cfg.require_session_secret()),
        ttl_seconds=cfg.session_ttl_seconds,
        lock_timeout_seconds=cfg.turn_lock_seconds,
    )
    app.state.banking_client = banking_client or BankingCoreClient(settings=cfg)
    app.state.turn_handler = turn_handler
    app.state.default_lang = cfg.default_locale

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok", service="orchestrator")

    app.include_router(chat_router)
    return app


app = create_app()
