"""Message blocks the orchestrator returns to the chat client.

The model may only emit blocks whose type is in MODEL_EMITTABLE_BLOCK_TYPES.
Receipt and handoff blocks are engine-built from real banking-core ToolResults.
Handoff summary and effective priority come from the stored result; model text
can only appear in the summary's `open_questions`.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from contracts.envelope import Receipt
from contracts.tools.handoff_create import (
    Department,
    HandoffPriority,
    HandoffStatus,
    HandoffSummary,
)


class TextBlock(BaseModel):
    """Plain assistant text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["text"] = "text"
    text: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Assistant text shown to the customer",
    )


class ReceiptBlock(BaseModel):
    """Verified receipt of a state-mutating action, re-read from the database."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["receipt"] = "receipt"
    receipt: Receipt = Field(..., description="Receipt returned by banking-core")


class HandoffBlock(BaseModel):
    """Engine-built handoff details backed by a banking-core ToolResult receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["handoff"] = "handoff"
    handoff_id: str = Field(..., min_length=8, max_length=64)
    status: HandoffStatus
    department: Department
    priority: HandoffPriority
    queue_position: StrictInt | None = Field(default=None, ge=1)
    summary: HandoffSummary
    receipt: Receipt = Field(..., description="Verified handoff creation receipt")


MessageBlock = Annotated[TextBlock | ReceiptBlock | HandoffBlock, Field(discriminator="type")]
MESSAGE_BLOCK_ADAPTER: TypeAdapter[TextBlock | ReceiptBlock | HandoffBlock] = TypeAdapter(
    MessageBlock
)

BLOCK_TYPES: frozenset[str] = frozenset({"text", "receipt", "handoff"})
# Block types the model is allowed to author. Everything else is engine-built.
MODEL_EMITTABLE_BLOCK_TYPES: frozenset[str] = frozenset({"text"})
