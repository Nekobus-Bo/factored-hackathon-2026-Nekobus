"""LLM Replay Recorder and Player for deterministic evaluations.

Enforces ADR-0001:
Deterministic reproduction of reported evaluation metrics without API keys.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ReplayMissError(Exception):
    """Raised when a prompt/message recording is missing in replay mode."""


class RecordedResponse(BaseModel):
    """Model response payload stored in replay recordings."""

    model_config = ConfigDict(extra="ignore")

    content: str | None = Field(default=None, description="Assistant text response")
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tool calls proposed by the model",
    )
    usage: dict[str, Any] = Field(
        default_factory=dict,
        description="Token usage stats (prompt, completion, total)",
    )
    cost: float | None = Field(default=None, description="Estimated USD cost")


class Recording(BaseModel):
    """Complete replay recording persisted under eval/replay/<key>.json."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(..., description="SHA-256 recording key")
    model_id: str = Field(..., description="Model identifier")
    prompt_version: str = Field(..., description="Prompt schema/template version")
    masked_messages: list[dict[str, Any]] = Field(
        ...,
        description="Outbound messages with PII already masked",
    )
    tool_schema_hash: str = Field(
        default="",
        description="Hash of available tool definitions",
    )
    response: RecordedResponse = Field(..., description="Captured model response")
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Timestamp when recording was captured",
    )


def compute_tool_schema_hash(tools: list[dict[str, Any]] | None) -> str:
    """Compute deterministic SHA-256 digest of tools schema."""
    if not tools:
        return ""
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_recording_key(
    model_id: str,
    prompt_version: str,
    masked_messages: list[dict[str, Any]],
    tool_schema_hash: str = "",
) -> str:
    """Compute recording key as sha256 of:
    (model id, prompt_version, masked messages, tool schema hash).
    """
    canonical_obj = {
        "model_id": model_id,
        "prompt_version": prompt_version,
        "masked_messages": masked_messages,
        "tool_schema_hash": tool_schema_hash,
    }
    canonical_json = json.dumps(canonical_obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ReplayManager:
    """Manages reading and writing recordings for replay and live recording modes."""

    def __init__(
        self,
        replay_dir: str | Path = "eval/replay",
        mode: Literal["replay", "live"] = "replay",
        record: bool = False,
        replay_on_miss: Literal["fail", "passthrough"] = "fail",
    ) -> None:
        self.replay_dir = Path(replay_dir)
        self.mode = mode
        self.record = record
        self.replay_on_miss = replay_on_miss
        # Ensure replay directory exists if recording
        if self.record:
            self.replay_dir.mkdir(parents=True, exist_ok=True)

    def get_recording_path(self, key: str) -> Path:
        """Return the file path for a recording key."""
        return self.replay_dir / f"{key}.json"

    def has_recording(self, key: str) -> bool:
        """Check if a recording exists for the key."""
        return self.get_recording_path(key).is_file()

    def load_recording(self, key: str) -> Recording | None:
        """Load recording from disk if present."""
        path = self.get_recording_path(key)
        if not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return Recording.model_validate(data)
        except Exception as exc:
            logger.error("Failed to load recording '%s': %s", key, exc)
            return None

    def save_recording(
        self,
        key: str,
        model_id: str,
        prompt_version: str,
        masked_messages: list[dict[str, Any]],
        tool_schema_hash: str,
        response: RecordedResponse,
    ) -> Recording:
        """Save a new recording to eval/replay/<key>.json."""
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        rec = Recording(
            key=key,
            model_id=model_id,
            prompt_version=prompt_version,
            masked_messages=masked_messages,
            tool_schema_hash=tool_schema_hash,
            response=response,
        )
        path = self.get_recording_path(key)
        with open(path, "w", encoding="utf-8") as f:
            f.write(rec.model_dump_json(indent=2))
        logger.info("Saved replay recording: %s", path)
        return rec
