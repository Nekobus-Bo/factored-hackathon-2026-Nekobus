"""Message blocks the orchestrator returns to the chat client.

The model may only emit blocks whose type is in MODEL_EMITTABLE_BLOCK_TYPES.
Receipt blocks are built exclusively by the orchestrator from real banking-core
ToolResults: a receipt proposed by the model is dropped, never rendered.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from contracts.envelope import Receipt


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


MessageBlock = Annotated[TextBlock | ReceiptBlock, Field(discriminator="type")]
MESSAGE_BLOCK_ADAPTER: TypeAdapter[TextBlock | ReceiptBlock] = TypeAdapter(MessageBlock)

BLOCK_TYPES: frozenset[str] = frozenset({"text", "receipt"})
# Block types the model is allowed to author. Everything else is engine-built.
MODEL_EMITTABLE_BLOCK_TYPES: frozenset[str] = frozenset({"text"})
