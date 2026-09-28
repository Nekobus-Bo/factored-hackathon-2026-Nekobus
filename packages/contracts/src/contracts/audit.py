"""Typed payload shared by every banking-core tool audit event."""

from pydantic import BaseModel, ConfigDict, Field

from contracts.envelope import ToolResultStatus, VerificationState
from contracts.tools.card_list import CardStatus
from contracts.tools.handoff_create import HandoffPriority, HandoffStatus

AuditDetail = str | int | float | bool | list[str] | None


class AuditPayload(BaseModel):
    """Stable, typed audit shape for tool outcomes and resource transitions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verification_state_before: VerificationState
    verification_state_after: VerificationState
    status: ToolResultStatus
    reason: str | None
    card_state_before: CardStatus | None = None
    card_state_after: CardStatus | None = None
    handoff_status: HandoffStatus | None = None
    handoff_priority: HandoffPriority | None = None
    idempotency_scope: str | None = None
    details: dict[str, AuditDetail] = Field(default_factory=dict)
