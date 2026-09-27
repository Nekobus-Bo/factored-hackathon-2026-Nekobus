"""Configuration settings for orchestrator service."""

from typing import Any, Literal

from pydantic import Field, field_validator
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

    # Conversation turn engine
    max_tool_rounds: int = Field(default=5, ge=1, le=20, alias="MAX_TOOL_ROUNDS")

    # LLM Settings
    llm_mode: Literal["replay", "live"] = Field(default="replay", alias="LLM_MODE")
    llm_model: str = Field(default="TODO", alias="LLM_MODEL")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
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
    def effective_base_url(self) -> str | None:
        if not self.llm_base_url or self.llm_base_url.strip() in ("", "TODO"):
            return None
        return self.llm_base_url.strip()

    @property
    def effective_api_key(self) -> str | None:
        if not self.llm_api_key or self.llm_api_key.strip() in ("", "TODO"):
            return None
        return self.llm_api_key.strip()


def get_settings() -> Settings:
    """Return default settings instance."""
    return Settings()
