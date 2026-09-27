from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Slot(BaseModel):
    """Slot entity within a text utterance."""

    type: str
    value: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "value": self.value,
            "start": self.start,
            "end": self.end,
        }


class DecisionExample(BaseModel):
    """Linguistic and intent example matching the frozen decision format."""

    id: str
    text: str
    lang: Literal["es", "pt"] | str
    intent: str
    slots: list[Slot] = Field(default_factory=list)
    split: Literal["train", "validation", "test"] | str
    source: Literal["synthetic", "human"] | str = "synthetic"


class DecisionPrediction(BaseModel):
    """Output prediction for an utterance."""

    intent: str
    confidence: float
    slots: list[Slot] = Field(default_factory=list)
    probabilities: dict[str, float] = Field(default_factory=dict)
