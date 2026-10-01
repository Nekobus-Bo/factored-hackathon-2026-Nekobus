"""Decision state kept with the conversation between turns (ADR-0012, E.1-E.2).

Small and free of PII by construction: a turn counter, the state of each gated
tool, and one label per sticky ledger. The engine works on a copy during the
turn and hands it back only when the turn completes, like the LLM history, so a
retried turn re-runs from the same state.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TRACKED = 16  # gated tools and ledgers; the effects file names a handful
MAX_LABEL_LENGTH = 64


class GateStatus(StrEnum):
    PENDING = "pending"  # the write was withheld and the customer was asked
    CONSENTED = "consented"  # the customer agreed, or asked for it outright


class ConsentSource(StrEnum):
    EXPLICIT_REQUEST = "explicit_request"  # a decided request, no extra turn
    CONFIRMATION = "confirmation"  # a decided `confirm` while a question was open


class GateState(BaseModel):
    """State of one gated tool. Absent from `DecisionState.gates` means closed."""

    model_config = ConfigDict(extra="forbid")

    status: GateStatus
    since_turn: int = Field(ge=0, description="Turn number when it was entered")
    source: ConsentSource | None = None

    @model_validator(mode="after")
    def _source_iff_consented(self) -> "GateState":
        if (self.status is GateStatus.CONSENTED) != (self.source is not None):
            raise ValueError("source must be set if and only if status is consented")
        return self


class DecisionState(BaseModel):
    """Everything the effects remember about a conversation."""

    model_config = ConfigDict(extra="forbid")

    turn: int = Field(default=0, ge=0, description="Completed turns")
    gates: dict[str, GateState] = Field(
        default_factory=dict, description="Tool name -> state, only while not closed"
    )
    ledgers: dict[str, str] = Field(
        default_factory=dict, description="Decision point id -> sticky label"
    )
    canned_turns: int = Field(
        default=0,
        ge=0,
        description=(
            "Turns answered by the canned clarification (ADR-0014). While it equals "
            "`turn`, the LLM has not answered this conversation yet"
        ),
    )

    @model_validator(mode="after")
    def _bounded(self) -> "DecisionState":
        if len(self.gates) > MAX_TRACKED or len(self.ledgers) > MAX_TRACKED:
            raise ValueError("decision state holds more entries than any config names")
        if any(len(label) > MAX_LABEL_LENGTH for label in self.ledgers.values()):
            raise ValueError("ledger label too long")
        return self
