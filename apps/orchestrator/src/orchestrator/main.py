"""Orchestrator service entrypoint."""

from fastapi import FastAPI
from pydantic import BaseModel
from redis.asyncio import Redis

from orchestrator.chat.engine_handler import EngineTurnHandler
from orchestrator.chat.handler import TurnHandler
from orchestrator.chat.routes import router as chat_router
from orchestrator.config import Settings, get_settings
from orchestrator.conversation import TurnEngine
from orchestrator.log_redaction import install_redaction
from orchestrator.session.crypto import PlaceholderEncryptor
from orchestrator.session.rate_limit import ConversationRateLimiter
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
    """Build an app. Dependencies are injectable for tests."""
    cfg = settings or get_settings()
    if cfg.eval_expose_turn and cfg.app_env.strip().casefold() == "production":
        raise ValueError("EVAL_EXPOSE_TURN cannot be enabled when APP_ENV=production")
    app = FastAPI(title="orchestrator")
    install_redaction(("uvicorn.access", "uvicorn.error"))

    # Redis connects lazily: building the client does not need redis-edge up.
    if session_store is None:
        redis_url = (
            cfg.redis_edge_url.get_secret_value()
            if cfg.redis_edge_url is not None
            else ""
        )
        redis_client = (
            Redis.from_url(redis_url)
            if redis_url
            else Redis(
                host=cfg.redis_edge_host,
                port=cfg.redis_edge_port,
                password=cfg.redis_edge_password,
            )
        )
        session_store = SessionStore(
            redis=redis_client,
            encryptor=PlaceholderEncryptor(cfg.require_session_secret()),
            ttl_seconds=cfg.session_ttl_seconds,
            lock_timeout_seconds=cfg.turn_lock_seconds,
            key_prefix=cfg.redis_edge_key_prefix,
        )
    app.state.session_store = session_store
    # Same redis-edge connection as the conversations, its own key prefix.
    app.state.conversation_limiter = ConversationRateLimiter(
        redis=session_store.redis,
        secret=cfg.require_session_secret(),
        limit=cfg.rate_limit_conversations_per_ip_hour,
        key_prefix=cfg.redis_edge_rate_limit_key_prefix,
    )
    app.state.trusted_proxy_hops = cfg.trusted_proxy_hops
    banking = banking_client or BankingCoreClient(settings=cfg)
    handler = turn_handler or EngineTurnHandler(
        TurnEngine.from_settings(
            cfg, banking=banking, collect_eval=cfg.eval_expose_turn
        )
    )
    app.state.banking_client = banking
    app.state.turn_handler = handler
    app.state.default_lang = cfg.default_locale
    app.state.eval_expose_turn = cfg.eval_expose_turn

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok", service="orchestrator")

    app.include_router(chat_router)
    return app


app = create_app()
