"""Common envelope models for Pattern Blue tool invocation and results."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VerificationState(str, Enum):
    """Customer identity verification state in banking-core state machine."""

    ANONYMOUS = "ANONYMOUS"
    IDENTIFIED = "IDENTIFIED"
    OTP_PENDING = "OTP_PENDING"
    VERIFIED = "VERIFIED"
    LOCKED = "LOCKED"
    HANDED_OFF = "HANDED_OFF"


class ToolResultStatus(str, Enum):
    """Execution status returned by banking-core."""

    OK = "ok"
    REFUSED = "refused"
    ERROR = "error"


class ReasonCode(str, Enum):
    """Standard refusal and error reason codes."""

    STATE_NOT_ALLOWED = "STATE_NOT_ALLOWED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    POLICY_FLAGGED = "POLICY_FLAGGED"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_MATCHED = "NOT_MATCHED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    CODE_FLOOR_VIOLATION = "CODE_FLOOR_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ResourceState(str, Enum):
    """Resource state prior to and following execution of a state-mutating tool."""

    NONE = "NONE"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    FROZEN = "FROZEN"
    ISSUED = "ISSUED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    ANONYMOUS = "ANONYMOUS"
    IDENTIFIED = "IDENTIFIED"
    OTP_PENDING = "OTP_PENDING"
    HANDED_OFF = "HANDED_OFF"


# Mutating tools that require idempotency keys and return database-verified receipts
WRITE_TOOLS: frozenset[str] = frozenset({"card.block", "handoff.create", "otp.send", "otp.verify"})
MUTATING_TOOLS: frozenset[str] = WRITE_TOOLS

# Reusable masked identifier patterns:
# 1. Masked PAN (last 4 digits only)
MASKED_PAN_PATTERN = r"(\*{4}[\s-]?\*{4}[\s-]?\*{4}[\s-]?\d{4}|\*{4,12}\d{4})"
# 2. Masked Email (first char + asterisks + @domain)
MASKED_EMAIL_PATTERN = r"[a-zA-Z0-9]\*+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
# 3. Masked Phone (optional country code + optional area code + asterisks + last 2-4 digits)
MASKED_PHONE_PATTERN = r"(\+?\d{1,3}[-\s]?)?(\d{1,4}[-\s]?)?(\*+[-\s]?)+\d{2,4}"
# 4. Opaque reference with PAN guard (reject >=12 digits in opaque ref)
_OPAQUE_REF_PATTERN = r"(card|hnd|otp|chal|ticket|handoff)[_-][A-Za-z0-9*_-]{6,50}"

TARGET_MASKED_PATTERN = (
    rf"^({MASKED_PAN_PATTERN}|{MASKED_EMAIL_PATTERN}|{MASKED_PHONE_PATTERN}|{_OPAQUE_REF_PATTERN})$"
)


class Receipt(BaseModel):
    """Database-verified receipt returned on state-mutating actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Action executed (e.g. card.block)",
    )
    target_masked: str = Field(
        ...,
        min_length=6,
        max_length=64,
        pattern=TARGET_MASKED_PATTERN,
        description=(
            "Masked target identifier adhering to allowlist: "
            "masked PAN, email, phone, or opaque ref"
        ),
    )
    state_before: ResourceState = Field(
        ...,
        description="Resource state prior to action execution",
    )
    state_after: ResourceState = Field(
        ...,
        description="Resource state following action execution",
    )
    verified_at: datetime = Field(
        ...,
        description="Timestamp of verified execution in database",
    )
    audit_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Cryptographic/audit reference ID",
    )

    @field_validator("target_masked")
    @classmethod
    def validate_pan_guard(cls, v: str) -> str:
        """PAN guard: reject 12 or more digits in opaque reference branch (ignoring separators)."""
        prefixes = ("card", "hnd", "otp", "chal", "ticket", "handoff")
        for p in prefixes:
            if v.startswith(f"{p}_") or v.startswith(f"{p}-"):
                ref_part = v[len(p) + 1 :]
                digits_count = sum(1 for c in ref_part if c.isdigit())
                if digits_count >= 12:
                    raise ValueError(
                        "Opaque reference cannot contain 12 or more digits (PAN guard)"
                    )
                break
        return v


class ToolCall(BaseModel):
    """Common envelope for tool calls proposed by orchestrator to banking-core."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(
        ...,
        min_length=1,
        description="Exact registered tool identifier (e.g. card.block)",
    )
    version: str = Field(default="1.0", description="Contract schema version")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool input arguments")
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]{8,128}$",
        description="Client idempotency key. Required for state-mutating tools.",
    )

    @model_validator(mode="after")
    def validate_tool_call(self) -> "ToolCall":
        """Strictly validate tool existence, idempotency requirement, and tool input arguments."""
        from contracts.tools import TOOL_CATALOG

        # 1. Exact match against TOOL_CATALOG (no normalization, reject "Card.Block", "card.block ")
        if self.tool not in TOOL_CATALOG:
            raise ValueError(
                f"Unknown tool '{self.tool}'. Tool must match registered catalog exactly."
            )

        tool_def = TOOL_CATALOG[self.tool]

        # 2. Derive idempotency requirement from catalog entry
        if tool_def.mutates_state:
            if not self.idempotency_key or not self.idempotency_key.strip():
                raise ValueError(
                    f"State-mutating tool '{self.tool}' requires a non-empty idempotency_key"
                )

        # 3. Validate arguments against tool's input model (extra=forbid enforced)
        try:
            validated_args = tool_def.input_model.model_validate(self.args)
        except Exception as exc:
            raise ValueError(f"Invalid arguments for tool '{self.tool}': {exc}") from exc

        # 4. Store validated model dump in JSON mode, not raw unvalidated dict
        self.args = validated_args.model_dump(mode="json")

        return self


class ToolResult(BaseModel):
    """Common envelope for results returned by banking-core."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(
        ...,
        min_length=1,
        description="Exact registered tool identifier (e.g. card.block)",
    )
    status: ToolResultStatus = Field(..., description="Status of tool execution")
    reason_code: ReasonCode | None = Field(
        default=None,
        description="Standardized reason code when status is refused or error",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Payload returned by the tool when status is ok; None on refused/error",
    )

    @model_validator(mode="after")
    def validate_tool_result(self) -> "ToolResult":
        """Validate tool existence, non-ok payload restrictions, and output schema."""
        from contracts.tools import TOOL_CATALOG

        # 1. Exact match against TOOL_CATALOG
        if self.tool not in TOOL_CATALOG:
            raise ValueError(
                f"Unknown tool '{self.tool}'. Tool must match registered catalog exactly."
            )

        tool_def = TOOL_CATALOG[self.tool]

        # 2. Enforce reason_code present and payload absent when status != ok
        if self.status != ToolResultStatus.OK:
            if self.reason_code is None:
                raise ValueError(f"reason_code is required when status is '{self.status.value}'")
            if self.data is not None:
                raise ValueError(f"data must be None when status is '{self.status.value}'")
        else:
            if self.reason_code is not None:
                raise ValueError("reason_code must be None when status is 'ok'")

            # 3. Validate data with tool's output model
            if self.data is None:
                raise ValueError(
                    f"data payload is required when status is 'ok' for tool '{self.tool}'"
                )

            try:
                validated_output = tool_def.output_model.model_validate(self.data)
            except Exception as exc:
                raise ValueError(f"Invalid output data for tool '{self.tool}': {exc}") from exc

            # 4. Single source for receipts: verified receipt inside output model of mutating tools
            if tool_def.mutates_state:
                if not hasattr(validated_output, "receipt") or validated_output.receipt is None:
                    raise ValueError(
                        f"State-mutating tool '{self.tool}' output must include a receipt"
                    )
                if validated_output.receipt.action != self.tool:
                    raise ValueError(
                        f"Receipt action '{validated_output.receipt.action}' "
                        f"must match tool name '{self.tool}'"
                    )

        return self
