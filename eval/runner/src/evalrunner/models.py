"""Data models for evaluation scenarios, system interactions, and check outcomes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from contracts.envelope import ToolCall, ToolResult, ToolResultStatus, VerificationState
from contracts.tools import TOOL_CATALOG
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Language(StrEnum):
    ES = "es"
    PT = "pt"
    EN = "en"


class ScenarioGroup(StrEnum):
    HAPPY_PATH = "happy_path"
    AMBIGUITY = "ambiguity"
    OUT_OF_SCOPE = "out_of_scope"
    FAILED_IDENTITY = "failed_identity"
    NOT_THE_HOLDER = "not_the_holder"
    RISK_THRESHOLD = "risk_threshold"
    ADVERSARIAL = "adversarial"
    DEGRADATION = "degradation"
    MESSY_CONVERSATION = "messy_conversation"


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_threshold_minor: int | dict[str, int] = 50000
    mode: str = "flag"  # "flag" or "block"


class ToolPolicySetup(BaseModel):
    """Tools a scenario turns on or off in banking-core's versioned tool policy.

    Applied through the admin API after the fixture reset, which restores the
    seed policy: a scenario without this block runs on the seed.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known_and_disjoint(self) -> ToolPolicySetup:
        named = [*self.enabled, *self.disabled]
        unknown = sorted(set(named) - set(TOOL_CATALOG))
        if unknown:
            raise ValueError(f"tool_policy names unknown tool(s): {unknown}")
        both = sorted(set(self.enabled) & set(self.disabled))
        if both:
            raise ValueError(f"tool_policy both enables and disables: {both}")
        if not named:
            raise ValueError("tool_policy must enable or disable at least one tool")
        return self


class InitialState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer: str
    card_status: str
    registered_otp_channel: str
    policy: PolicyConfig
    tool_policy: ToolPolicySetup | None = None
    fault: str = "none"


class ScenarioExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_verification_state: str | list[str]
    tools_allowed: list[str] = Field(default_factory=list)
    tools_forbidden: list[str] = Field(default_factory=list)
    card_blocked: bool | None = None
    card_blocked_own: bool | None = None
    card_blocked_foreign: bool | None = None
    handoff: str = "optional"  # "required", "forbidden", "optional"
    handoff_priority: Literal["normal", "priority"] | None = None
    handoff_must_include: list[str] = Field(default_factory=list)
    must_ask_clarification: bool = False


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    lang: str
    group: str
    description: str
    initial_state: InitialState
    turns: list[str]
    expected: ScenarioExpected
    unsafe_outcomes_to_watch: list[str] = Field(default_factory=list)


class HandoffResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    created: bool = False
    priority: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolCallReport(BaseModel):
    """Execution report per tool call with pre-execution state for authorization."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    verification_state_before: VerificationState | str | None = None
    status: ToolResultStatus | str = ToolResultStatus.OK


class DecisionEvidence(BaseModel):
    """One decision point on one turn, as the orchestrator's eval hook reports it.

    ADR-0012: identifiers, enum values and numbers, never text. Read tolerantly
    (unknown fields ignored) so the runner does not break when the orchestrator
    records more.
    """

    model_config = ConfigDict(extra="ignore")

    dp_id: str
    effect: str = ""
    mode: str = ""
    outcome: str  # decided / abstained / unavailable / infeasible / off
    label: str | None = None
    confidence: float = 0.0
    tau: float | None = None
    model_id: str | None = None
    config_version: str | None = None
    unavailable_reason: str | None = None


class EffectEvidence(BaseModel):
    """What a gate or a select did to one call, or in shadow would have done."""

    model_config = ConfigDict(extra="ignore")

    dp_id: str
    effect: str  # gate / select
    mode: str = ""
    tool: str = ""
    applied: bool = False
    would_apply: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply_text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_call_reports: list[ToolCallReport] = Field(default_factory=list)
    masked_outbound_messages: list[str] = Field(default_factory=list)
    # Where masked_outbound_messages came from (U6 evidence provenance).
    outbound_provenance: list[str] = Field(default_factory=list)
    verification_state: VerificationState | str = VerificationState.ANONYMOUS
    handoff: HandoffResult = Field(default_factory=HandoffResult)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_used: int = 0
    asked_clarification: bool = False
    # Decision points (ADR-0012), from the orchestrator's eval hook. Untrusted-side
    # evidence like the masked outbound messages: a report input, never a check.
    decisions: list[DecisionEvidence] = Field(default_factory=list)
    effects: list[EffectEvidence] = Field(default_factory=list)
    # Records the hook sent that did not parse; counted so a gap is visible.
    decisions_unreadable: int = 0


class CheckDetail(BaseModel):
    check_name: str
    passed: bool
    expected: Any
    actual: Any
    message: str = ""


class UnsafeOutcome(BaseModel):
    code: str  # "U1" through "U8"
    detected: bool = False
    status: str = (
        "needs_human_review"  # "detected", "needs_human_review", "no_evidence", "clear"
    )
    description: str = ""
    turn_index: int | None = None


class ScenarioRunResult(BaseModel):
    scenario_id: str
    lang: str
    group: str
    passed: bool
    checks: list[CheckDetail] = Field(default_factory=list)
    unsafe_outcomes: list[UnsafeOutcome] = Field(default_factory=list)
    turns: list[TurnResult] = Field(default_factory=list)
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    automated_resolution: bool = False
    correct_abstention: bool = False
    unnecessary_escalation: bool = False
    handoff_quality_pass: bool | None = None
    error: str | None = None
    not_run_reason: str | None = None
