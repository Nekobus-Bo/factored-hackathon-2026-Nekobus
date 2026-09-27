from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KBSnippet(BaseModel):
    """Knowledge base article or policy snippet."""

    id: str
    lang: Literal["es", "pt"] | str
    title: str
    text: str


class QueryExample(BaseModel):
    """Evaluation query matching the frozen embedding queries schema."""

    id: str
    text: str
    lang: Literal["es", "pt"] | str
    relevant_ids: list[str] = Field(default_factory=list)
    split: Literal["train", "validation", "test"] | str
    source: Literal["synthetic", "human"] | str = "synthetic"


class SearchResult(BaseModel):
    """Single retrieval result item."""

    snippet_id: str
    score: float
    rank: int
