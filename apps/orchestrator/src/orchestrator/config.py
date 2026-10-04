"""Configuration settings for orchestrator service."""

from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Orchestrator configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # Banking Core Tool Service
    banking_core_url: str = Field(
        default="http://banking-core:8081", alias="BANKING_CORE_URL"
    )
    banking_core_timeout_seconds: float = Field(
        default=10.0, alias="BANKING_CORE_TIMEOUT_SECONDS"
    )

    # Encoder (optional signal; the turn degrades to LLM-only when unavailable)
    encoder_enabled: bool = Field(default=True, alias="ENCODER_ENABLED")
    encoder_url: str = Field(default="http://encoder:8090", alias="ENCODER_URL")
    encoder_timeout_seconds: float = Field(default=2.0, alias="ENCODER_TIMEOUT_SECONDS")

    # Decision points (ADR-0012): the effects file binds each decision point to an
    # engine effect; blank = the file shipped with the service. The mode override
    # is the kill switch: 'confirm_gate=shadow,block_reason=off' needs no redeploy.
    decision_effects_file: str | None = Field(
        default=None, alias="DECISION_EFFECTS_FILE"
    )
    decision_points_modes: str = Field(default="", alias="DECISION_POINTS_MODES")

    # Redis Edge (Edge trust zone session store & distributed locking)
    redis_edge_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_EDGE_URL", "REDIS_URL"),
    )
    redis_edge_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("REDIS_EDGE_HOST", "REDIS_HOST"),
    )
    redis_edge_port: int = Field(
        default=6379,
        validation_alias=AliasChoices("REDIS_EDGE_PORT", "REDIS_PORT"),
    )
    redis_edge_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_EDGE_PASSWORD", "REDIS_PASSWORD"),
    )
    redis_edge_key_prefix: str = Field(
        default="orch:conv:",
        validation_alias=AliasChoices("REDIS_EDGE_KEY_PREFIX"),
    )
    # Rate limit on POST /v1/conversations, per client address (see
    # session/rate_limit.py). Counters live on redis-edge under this prefix, which
    # the edge ACL (~orch:*) must cover.
    redis_edge_rate_limit_key_prefix: str = Field(
        default="orch:ratelimit:",
        validation_alias=AliasChoices("REDIS_EDGE_RATE_LIMIT_KEY_PREFIX"),
    )
    rate_limit_conversations_per_ip_hour: int = Field(
        default=30, ge=1, alias="RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR"
    )
    # Reverse index from a banking-core session id to the conversation id, for the
    # agent API (see session/store.py). Same redis-edge, so the edge ACL (~orch:*)
    # must cover the prefix.
    redis_edge_session_index_key_prefix: str = Field(
        default="orch:session:",
        validation_alias=AliasChoices("REDIS_EDGE_SESSION_INDEX_KEY_PREFIX"),
    )
    # How many reverse proxies stand in front of the orchestrator. 0 (default)
    # ignores X-Forwarded-For entirely; N strips N entries from its right.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=8, alias="TRUSTED_PROXY_HOPS")
    # No default on purpose: startup fails without it (see require_session_secret).
    session_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SESSION_SECRET"),
    )
    session_ttl_seconds: int = Field(
        default=3600,
        validation_alias=AliasChoices("SESSION_TTL_SECONDS"),
    )
    # Added on top of the slowest possible turn to get the turn-lock TTL.
    session_lock_margin_seconds: float = Field(
        default=60.0, ge=0, alias="SESSION_LOCK_MARGIN_SECONDS"
    )

    # Conversation turn engine
    max_tool_rounds: int = Field(default=5, ge=1, le=20, alias="MAX_TOOL_ROUNDS")

    eval_expose_turn: bool = Field(default=False, alias="EVAL_EXPOSE_TURN")

    # Detective mode (ADR-0019): each turn comes with its timeline (masked values
    # only) and the customer chat offers a switch to show it. Off unless an
    # environment sets it: the local compose does, Cloud Run through the
    # detective_mode variable. Unlike EVAL_EXPOSE_TURN it is allowed in production.
    # The back office turns it off and on at runtime; the state is this key on
    # redis-edge, which the edge ACL (~orch:*) must cover.
    detective_mode: bool = Field(default=False, alias="DETECTIVE_MODE")
    redis_edge_detective_key: str = Field(
        default="orch:detective:enabled",
        validation_alias=AliasChoices("REDIS_EDGE_DETECTIVE_KEY"),
    )

    # Agent API (/v1/agent): the back office reads a masked transcript and takes a
    # conversation over from the assistant (docs/adr/0013-front-ends-bff-takeover.md).
    # Off by default. When on it needs a bearer token; startup refuses the public
    # development token, and an empty one, under APP_ENV=production (agent/auth.py).
    agent_api_enabled: bool = Field(default=False, alias="AGENT_API_ENABLED")
    agent_api_token: SecretStr = Field(default=SecretStr(""), alias="AGENT_API_TOKEN")
    # How long a takeover or an agent message waits for a customer turn in flight
    # (the turn lock) before answering 503. Only the agent API waits.
    agent_lock_wait_seconds: float = Field(
        default=10.0, ge=0, le=120, alias="AGENT_LOCK_WAIT_SECONDS"
    )

    default_locale: Literal["es", "pt", "en"] = Field(
        default="es", alias="DEFAULT_LOCALE"
    )

    # LLM Settings
    llm_mode: Literal["replay", "live"] = Field(default="replay", alias="LLM_MODE")
    llm_model: str = Field(default="TODO", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    # Reasoning models reject temperature 0 unless reasoning is off ("none").
    # Blank = the parameter is not sent (non-reasoning models).
    llm_reasoning_effort: str | None = Field(default=None, alias="LLM_REASONING_EFFORT")
    # 0 is greedy decoding. A local model that thinks may ask for more in its
    # model card (Qwen3.6: 0.6), since greedy decoding with thinking can loop.
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0, alias="LLM_TEMPERATURE")
    llm_replay_on_miss: Literal["fail", "passthrough"] = Field(
        default="fail", alias="LLM_REPLAY_ON_MISS"
    )
    record: bool = Field(default=False, alias="RECORD")
    cost_tracking_enabled: bool = Field(default=True, alias="COST_TRACKING_ENABLED")

    # Replay Directory
    replay_dir: str = Field(
        default="eval/replay",
        alias="REPLAY_DIR",
        description="Path to store and read recordings",
    )

    @field_validator("record", mode="before")
    @classmethod
    def parse_record(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    @property
    def effective_agent_api_token(self) -> str:
        """The agent token as compared and validated: surrounding blanks dropped."""
        return self.agent_api_token.get_secret_value().strip()

    @property
    def turn_lock_seconds(self) -> float:
        """Turn-lock TTL: the slowest turn the config allows, plus a margin.

        Each of the (MAX_TOOL_ROUNDS + 1) LLM calls may take LLM_TIMEOUT_SECONDS
        per attempt, (1 + LLM_MAX_RETRIES) attempts. The save is also fenced on
        the lock token, so an expired lock can never overwrite a newer turn.
        """
        slowest_turn = (
            self.llm_timeout_seconds
            * (1 + self.llm_max_retries)
            * (self.max_tool_rounds + 1)
        )
        return slowest_turn + self.session_lock_margin_seconds

    def require_session_secret(self) -> str:
        if not self.session_secret or not self.session_secret.strip():
            raise ValueError(
                "SESSION_SECRET environment variable is required and cannot be empty"
            )
        return self.session_secret

    @property
    def effective_base_url(self) -> str | None:
        if not self.llm_base_url or self.llm_base_url.strip() in ("", "TODO"):
            return None
        return self.llm_base_url.strip()

    @property
    def effective_reasoning_effort(self) -> str | None:
        if not self.llm_reasoning_effort or not self.llm_reasoning_effort.strip():
            return None
        return self.llm_reasoning_effort.strip().lower()

    @property
    def effective_api_key(self) -> str | None:
        if not self.llm_api_key or self.llm_api_key.strip() in ("", "TODO"):
            return None
        return self.llm_api_key.strip()


def get_settings() -> Settings:
    """Return default settings instance."""
    return Settings()
