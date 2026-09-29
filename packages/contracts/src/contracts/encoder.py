"""Typed contracts for the encoder service (the model server): /v1/analyze and
/v1/decision-points (ADR-0012)."""

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from contracts.labels import PiiType, SlotType

# A decision point id is data, written by the calibration harness (ADR-0012).
DECISION_POINT_ID_PATTERN = r"^[a-z][a-z0-9_]{2,40}$"
# Contract ceiling on the decision points one request may name.
MAX_DECISION_POINTS_PER_REQUEST = 16
# Contract ceilings for POST /v1/embed. The model server's configured batch limit
# (EMBEDDING_MAX_BATCH) can only lower the first.
EMBED_MAX_BATCH = 256
EMBED_MAX_TEXT_CHARS = 4000


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


class DecisionOutcome(StrEnum):
    """What a decision point did with one utterance."""

    DECIDED = "decided"
    ABSTAINED = "abstained"
    UNAVAILABLE = "unavailable"
    INFEASIBLE = "infeasible"
    OFF = "off"


class TauSource(StrEnum):
    """Where the threshold applied to a decision came from."""

    ARTIFACT = "artifact"
    OVERRIDE = "override"
    SEED = "seed"


class RunnerUp(BaseModel):
    """The second label of a decision, for a targeted clarification later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)


class DecisionResult(BaseModel):
    """Outcome of one decision point (DP) for one utterance (ADR-0012, Appendix D).

    Carries no text and no spans: the orchestrator stores it as is. Only a
    `decided` result carries a label; every other outcome falls back to the
    LLM's own argument or a withheld write (invariant I2).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dp_id: str = Field(pattern=DECISION_POINT_ID_PATTERN, description="Decision point id")
    outcome: DecisionOutcome = Field(
        description=(
            "decided: top label has calibrated confidence >= its tau; abstained: below tau "
            "or no tau for the language; unavailable: backend timeout, error or not ready; "
            "infeasible: artifact status, never decides; off: disabled in the artifact"
        ),
    )
    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Top view label; set if and only if outcome is decided",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Calibrated confidence of the top view label; 0.0 when nothing was computed",
    )
    raw_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence before calibration, for drift debugging",
    )
    runner_up: RunnerUp | None = Field(default=None, description="Second label, if known")
    tau: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Threshold applied; null when none applies",
    )
    tau_source: TauSource | None = Field(
        default=None,
        description="Where tau came from; set if and only if tau is",
    )
    model_id: str = Field(
        min_length=1,
        max_length=128,
        description="Backend model id, including revision or hash",
    )
    config_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Calibration artifact id; null in legacy seed mode",
    )
    latency_ms: float = Field(
        ge=0.0,
        description="Time in this decision point's backend (a shared backend reports once)",
    )

    @model_validator(mode="after")
    def validate_outcome(self) -> "DecisionResult":
        decided = self.outcome is DecisionOutcome.DECIDED
        if decided != (self.label is not None):
            raise ValueError("label must be set if and only if outcome is decided")
        if (self.tau is None) != (self.tau_source is None):
            raise ValueError("tau_source must be set if and only if tau is set")
        if decided:
            if self.tau is None:
                raise ValueError("a decided result must carry the tau it passed")
            if self.confidence < self.tau:
                raise ValueError("a decided result must have confidence >= tau")
        elif self.outcome is not DecisionOutcome.ABSTAINED:
            if self.confidence != 0.0 or self.tau is not None or self.runner_up is not None:
                raise ValueError(
                    f"outcome '{self.outcome.value}' carries no confidence, tau or runner_up"
                )
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
    decision_points: list[str] | None = Field(
        default=None,
        max_length=MAX_DECISION_POINTS_PER_REQUEST,
        description=(
            "Decision point ids to evaluate. null = every enabled, always-on decision point; "
            "an unknown id is a 422. [] evaluates none"
        ),
    )

    @field_validator("decision_points")
    @classmethod
    def validate_decision_points(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        pattern = re.compile(DECISION_POINT_ID_PATTERN)
        for dp_id in value:
            if not pattern.match(dp_id):
                raise ValueError(f"invalid decision point id {dp_id!r}")
        if len(set(value)) != len(value):
            raise ValueError("decision_points must not repeat an id")
        return value


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
    decisions: dict[str, DecisionResult] = Field(
        default_factory=dict,
        description="One entry per evaluated decision point, keyed by its id",
    )
    config_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Calibration artifact id; null in legacy seed mode",
    )

    @model_validator(mode="after")
    def validate_abstention(self) -> "AnalyzeResponse":
        if self.abstain and self.intent is not None:
            raise ValueError("intent must be None (null) when abstain is True")
        if not self.abstain and self.intent is None:
            raise ValueError("intent must not be None when abstain is False")
        return self

    @model_validator(mode="after")
    def validate_decisions(self) -> "AnalyzeResponse":
        """Keys match ids, and the legacy fields follow `turn_intent` when it decided."""
        for key, result in self.decisions.items():
            if key != result.dp_id:
                raise ValueError(f"decisions key '{key}' does not match dp_id '{result.dp_id}'")
        turn_intent = self.decisions.get("turn_intent")
        if turn_intent is not None:
            if turn_intent.outcome is DecisionOutcome.DECIDED:
                if self.abstain or self.intent != turn_intent.label:
                    raise ValueError("legacy intent must equal the decided turn_intent label")
            elif turn_intent.outcome is DecisionOutcome.ABSTAINED and not self.abstain:
                raise ValueError("legacy abstain must be true when turn_intent abstained")
        return self


class DecisionPointInfo(BaseModel):
    """One decision point as served by GET /v1/decision-points."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=DECISION_POINT_ID_PATTERN)
    labels: list[str] = Field(description="Labels of the decision point's view")
    backend_kind: str = Field(min_length=1, max_length=64)
    backend_model_id: str = Field(min_length=1, max_length=128)
    probability_kind: Literal["distribution", "top1_only"]
    status: Literal["calibrated", "infeasible", "uncalibrated_seed"]
    state: Literal["ready", "unavailable", "infeasible", "off"]
    enabled: bool
    always_on: bool
    languages_with_tau: list[str] = Field(
        description="Languages (and '*') that have a threshold; others abstain",
    )


class DecisionPointsResponse(BaseModel):
    """Output contract for GET /v1/decision-points (used to cross-check the effects file)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Calibration artifact id; null in legacy seed mode",
    )
    source: Literal["artifact", "legacy_seed"] = Field(
        description=(
            "legacy_seed: no artifact file, one uncalibrated turn_intent "
            "derived from ABSTENTION_THRESHOLD"
        ),
    )
    decision_points: list[DecisionPointInfo] = Field(default_factory=list)


EmbedText = Annotated[str, StringConstraints(min_length=1, max_length=EMBED_MAX_TEXT_CHARS)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class EmbedRequest(BaseModel):
    """Input contract for POST /v1/embed (ADR-0012, Appendix J).

    The texts are search queries and public knowledge-base text, never a customer
    record; the model server still receives them only inside the private network.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    texts: list[EmbedText] = Field(
        min_length=1,
        max_length=EMBED_MAX_BATCH,
        description="Texts to embed, in order",
    )


class EmbedResponse(BaseModel):
    """Output contract for POST /v1/embed.

    `model_id` and `revision` say which pinned model produced the vectors; the caller
    compares them with what it expects on every response and refuses a mismatch.
    Carries no text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1, max_length=200, description="Configured model id")
    revision: str = Field(
        min_length=1,
        max_length=128,
        description="Pinned revision: a full commit for a hub model, a label for a directory",
    )
    dim: int = Field(ge=1, le=4096, description="Length of every vector")
    vectors: list[list[Finite]] = Field(description="One unit-length vector per text, in order")

    @model_validator(mode="after")
    def validate_dimensions(self) -> "EmbedResponse":
        for vector in self.vectors:
            if len(vector) != self.dim:
                raise ValueError(f"every vector must have dim={self.dim} values")
        return self
