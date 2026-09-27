"""Typed contracts for the encoder service /v1/analyze endpoint."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.labels import PiiType, SlotType


class Slot(BaseModel):
    """Extracted named entity slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SlotType = Field(description="Slot entity type matching schema.yaml")
    value: str = Field(min_length=1, max_length=2000, description="Extracted slot value")
    start: int = Field(ge=0, description="Character start index in source text")
    end: int = Field(ge=0, description="Character end index in source text")
    normalized: str | None = Field(
        default=None,
        description="Optional normalized representation of the slot value",
    )

    @model_validator(mode="after")
    def validate_span(self) -> "Slot":
        if self.start > self.end:
            raise ValueError(f"start index ({self.start}) must be <= end index ({self.end})")
        return self


class PiiSpan(BaseModel):
    """Detected PII span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: PiiType = Field(description="PII category matching orchestrator placeholders")
    start: int = Field(ge=0, description="Character start index in source text")
    end: int = Field(ge=0, description="Character end index in source text")

    @model_validator(mode="after")
    def validate_span(self) -> "PiiSpan":
        if self.start > self.end:
            raise ValueError(f"start index ({self.start}) must be <= end index ({self.end})")
        return self


class AnalyzeRequest(BaseModel):
    """Input contract for POST /v1/analyze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(
        min_length=1,
        max_length=2000,
        description="Customer input text to analyze",
    )
    lang: Literal["es", "pt", "en"] | None = Field(
        default=None,
        description="Optional language code (es, pt, en)",
    )


class AnalyzeResponse(BaseModel):
    """Output contract for POST /v1/analyze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: str | None = Field(
        default=None,
        description="Predicted customer intent, or null if abstaining",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for the predicted intent",
    )
    abstain: bool = Field(
        description="True if confidence is below the abstention threshold",
    )
    slots: list[Slot] = Field(
        default_factory=list,
        description="List of extracted entity slots",
    )
    pii_spans: list[PiiSpan] = Field(
        default_factory=list,
        description="List of detected PII spans",
    )
    model_id: str = Field(
        min_length=1,
        max_length=128,
        description="Identifier of the model used for inference",
    )
    latency_ms: float = Field(
        ge=0.0,
        description="Processing latency in milliseconds",
    )

    @model_validator(mode="after")
    def validate_abstention(self) -> "AnalyzeResponse":
        if self.abstain and self.intent is not None:
            raise ValueError("intent must be None (null) when abstain is True")
        if not self.abstain and self.intent is None:
            raise ValueError("intent must not be None when abstain is False")
        return self
