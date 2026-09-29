"""Contract for handoff.create tool."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from contracts.envelope import Receipt
from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput
from contracts.tools.transaction_list_recent import (
    TRANSACTION_ID_MAX_LENGTH,
    TRANSACTION_ID_MIN_LENGTH,
)


class HandoffReason(str, Enum):
    """Reason for session escalation to a human agent."""

    SUSPECTED_FRAUD = "SUSPECTED_FRAUD"
    DISPUTE_CLAIM = "DISPUTE_CLAIM"
    CUSTOMER_LOCKED = "CUSTOMER_LOCKED"
    UNRECOGNIZED_TRANSACTION = "UNRECOGNIZED_TRANSACTION"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class HandoffPriority(str, Enum):
    """Queue priority for agent assignment."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Department(str, Enum):
    """Bank back-office specialized queues."""

    FRAUD_OPERATIONS = "FRAUD_OPERATIONS"
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    DISPUTES = "DISPUTES"


class HandoffStatus(str, Enum):
    """Status of handoff ticket."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    PENDING = "PENDING"


class HandoffRequirementLevel(str, Enum):
    """How strongly banking-core policy asks for a human on this case (ADR-0003).

    RECOMMENDED is advisory. REQUIRED is enforced: the turn engine creates the
    handoff itself when the model has not.
    """

    NONE = "NONE"
    RECOMMENDED = "RECOMMENDED"
    REQUIRED = "REQUIRED"


class HandoffRequirement(BaseToolModel):
    """Policy outcome for a case, decided by banking-core and never by the model.

    When the level is NONE nothing else is set; otherwise the priority,
    department and reason a handoff for this case must carry are all set.
    """

    level: HandoffRequirementLevel = Field(
        default=HandoffRequirementLevel.NONE,
        description="NONE, RECOMMENDED (advisory) or REQUIRED (enforced)",
    )
    priority: HandoffPriority | None = Field(
        default=None,
        description="Minimum queue priority of the handoff; unset when level is NONE",
    )
    department: Department | None = Field(
        default=None,
        description="Department the handoff must be routed to; unset when level is NONE",
    )
    reason: HandoffReason | None = Field(
        default=None,
        description="Categorized reason the handoff must carry; unset when level is NONE",
    )

    @model_validator(mode="after")
    def _details_match_level(self) -> "HandoffRequirement":
        details = (self.priority, self.department, self.reason)
        if self.level is HandoffRequirementLevel.NONE:
            if any(detail is not None for detail in details):
                raise ValueError("priority, department and reason must be unset when level is NONE")
        elif any(detail is None for detail in details):
            raise ValueError("priority, department and reason are required unless level is NONE")
        return self


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class HandoffOpenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    text: str


class HandoffSummary(BaseModel):
    """Server-built handoff context persisted with a queue ticket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verified_facts: dict[str, JsonValue]
    actions_taken: list[str | dict[str, JsonValue]]
    verification_method: str
    open_questions: list[HandoffOpenQuestion]


class HandoffCreateInput(BaseToolInput):
    """Input payload to create human agent handoff ticket.

    Permitted in every verification state, including LOCKED.
    """

    reason: HandoffReason = Field(
        ...,
        description="Categorized reason for human escalation",
    )
    summary: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Structured summary of facts established so far",
    )
    priority: HandoffPriority = Field(
        default=HandoffPriority.NORMAL,
        description="Operational priority level",
    )
    department: Department = Field(
        default=Department.FRAUD_OPERATIONS,
        description="Target specialized department queue",
    )
    transaction_id: str | None = Field(
        default=None,
        min_length=TRANSACTION_ID_MIN_LENGTH,
        max_length=TRANSACTION_ID_MAX_LENGTH,
        description=(
            "Opaque transaction id returned by transaction.list_recent for the "
            "charge the customer disputes. banking-core reads its details from "
            "the database. Never invent or guess one"
        ),
    )


class HandoffCreateOutput(BaseToolOutput):
    """Outcome of human agent handoff creation.

    Mutates queue state and returns a verified receipt referencing the handoff ticket.
    """

    handoff_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Unique handoff incident identifier",
    )
    status: HandoffStatus = Field(
        default=HandoffStatus.QUEUED,
        description="Current ticket queue status",
    )
    department: Department = Field(
        ...,
        description="Target department queue",
    )
    priority: HandoffPriority = Field(
        ..., description="Effective priority assigned after banking-core policy"
    )
    summary: HandoffSummary = Field(
        ..., description="Server-built context stored with the handoff ticket"
    )
    queue_position: StrictInt | None = Field(
        default=None,
        ge=1,
        description="Estimated queue position if known",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp of ticket creation",
    )
    receipt: Receipt = Field(
        ...,
        description="Verified receipt for handoff ticket creation",
    )
