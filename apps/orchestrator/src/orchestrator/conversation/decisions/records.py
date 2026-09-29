"""What a turn records about its decisions (ADR-0012, E.3, invariant I5).

Never text, spans or free-form model output: identifiers, enum values, numbers.
"""

from enum import StrEnum
from typing import Any, Literal

from contracts import DecisionOutcome, TauSource
from pydantic import BaseModel, ConfigDict, Field


class Mode(StrEnum):
    """What an effect may do. `off` ignores the decision point."""

    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


# Why a decision point has no result of its own this turn.
UnavailableReason = Literal[
    "encoder_unavailable",  # encoder down, timed out, disabled or unreadable answer
    "not_served",  # the encoder does not serve this id (no artifact, legacy seed mode)
    "config_mismatch",  # the encoder serves it, without the labels the effect needs
    "not_returned",  # the encoder answered but left it out
]


class DecisionRecord(BaseModel):
    """One decision point, one turn."""

    model_config = ConfigDict(extra="forbid")

    dp_id: str
    effect: str
    mode: Mode
    outcome: DecisionOutcome
    label: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tau: float | None = None
    tau_source: TauSource | None = None
    model_id: str | None = None
    config_version: str | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    unavailable_reason: UnavailableReason | None = None

    @property
    def decided(self) -> bool:
        return self.outcome is DecisionOutcome.DECIDED


class EffectRecord(BaseModel):
    """What an effect did, or in `shadow` would have done, to one call.

    `would_apply` is what the effect wants given this turn's decisions;
    `applied` is whether it did it (only in `enforce`). `detail` holds
    `{event, state_before, state_after, consent_source}` for a gate and
    `{arg, llm_value, dp_value}` for a select: enum values, never text.
    """

    model_config = ConfigDict(extra="forbid")

    dp_id: str
    effect: Literal["select", "gate"]
    mode: Mode
    tool: str
    applied: bool
    would_apply: bool
    detail: dict[str, Any] = Field(default_factory=dict)
