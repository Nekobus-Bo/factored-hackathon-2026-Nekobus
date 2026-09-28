"""Configuration for kb.search, seeded from environment (ADR-0002, AGENTS rule 6)."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from retrieval import DEFAULT_KB_PATH

# Contract ceiling for KbSearchInput.limit; configuration can only lower it.
KB_SEARCH_HARD_CAP = 20
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

Backend = Literal["vector", "bm25", "hybrid"]


class KbSearchConfig(BaseModel):
    """Retrieval settings for the knowledge base."""

    kb_path: Path = Field(default=DEFAULT_KB_PATH)
    backend: Backend = Field(
        default="vector",
        description="vector is the default (ADR-0006); bm25/hybrid only if set",
    )
    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL,
        description="Hub id resolved from the local cache only, or a local path",
    )
    max_k: int = Field(default=5, ge=1, le=KB_SEARCH_HARD_CAP)
    score_floor: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum normalized score; below it SAME falls back to CROSS",
    )

    @classmethod
    def from_env(cls) -> "KbSearchConfig":
        """Build from env; invalid values fail loudly via validation."""
        values: dict[str, object] = {}
        if kb_path := os.getenv("KB_PATH"):
            values["kb_path"] = Path(kb_path)
        if backend := os.getenv("RETRIEVAL_MODE"):
            values["backend"] = backend.strip().lower()
        if model := os.getenv("EMBEDDING_MODEL"):
            values["embedding_model"] = model.strip()
        if max_k := os.getenv("RETRIEVAL_TOP_K"):
            values["max_k"] = max_k
        if floor := os.getenv("RETRIEVAL_SCORE_FLOOR"):
            values["score_floor"] = floor
        return cls.model_validate(values)
