"""Contract for handoff.create tool."""

from datetime import datetime
from enum import Enum

from pydantic import Field, StrictInt

from contracts.envelope import Receipt
from contracts.tools.base import BaseToolInput, BaseToolOutput


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
