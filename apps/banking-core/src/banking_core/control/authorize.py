"""Deterministic tool authorization engine for banking-core.

Core principle (ADR-0003, ADR-0004):
The model proposes, banking-core disposes.

Pipeline:
1. Typed contract enforcement: accepts only validated ToolCall
2. Catalog check: tool must exist in registered TOOL_CATALOG
3. Effective matrix check: config restricted by CODE_FLOOR
   via get_effective_permitted_states
4. FSM state check: session.state must be in effective permitted states
5. Policy evaluation: rate limits (verification tools only),
   risk thresholds (fail-closed)
-> Decision(allowed: bool, reason_code: ReasonCode | None, flags: list)
"""

from typing import Any

from contracts.envelope import ReasonCode, ToolCall
from contracts.tools import TOOL_CATALOG, get_effective_permitted_states

from banking_core.control.config import (
    ControlConfigRepository,
    InMemoryControlConfigRepository,
)
from banking_core.control.policy import Decision, PolicyEngine
from banking_core.control.session import SessionState


class Authorizer:
    """Authorizer evaluating deterministic access controls on tool calls."""

    def __init__(self, config_repo: ControlConfigRepository | None = None) -> None:
        self.config_repo = config_repo or InMemoryControlConfigRepository()

    def authorize(
        self,
        tool_call: ToolCall,
        session: SessionState,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        """Evaluate authorization pipeline for a proposed ToolCall."""
        if not isinstance(tool_call, ToolCall):
            raise TypeError(
                f"authorize requires a contracts.envelope.ToolCall instance, "
                f"got '{type(tool_call).__name__}'"
            )

        context = context or {}
        tool_name = tool_call.tool
        args = tool_call.args

        # 1. Catalog check
        if tool_name not in TOOL_CATALOG:
            return Decision(
                allowed=False,
                reason_code=ReasonCode.INVALID_ARGUMENTS,
                flags=["UNKNOWN_TOOL"],
            )

        # 2. Effective matrix check (config restricted by contracts CODE_FLOOR)
        configured_states = self.config_repo.get_tool_permitted_states(tool_name)
        try:
            effective_states = get_effective_permitted_states(
                tool_name, configured_states
            )
        except ValueError as exc:
            # Illegal configuration attempting to widen beyond code floor
            return Decision(
                allowed=False,
                reason_code=ReasonCode.STATE_NOT_ALLOWED,
                flags=["CODE_FLOOR_VIOLATION", str(exc)],
            )

        # 3. FSM state check
        if session.state not in effective_states:
            return Decision(
                allowed=False,
                reason_code=ReasonCode.STATE_NOT_ALLOWED,
                flags=[f"STATE_{session.state.value}_NOT_PERMITTED"],
            )

        # 4. Policy engine check (rate limits, thresholds)
        policy_config = self.config_repo.get_policy_config()
        policy_engine = PolicyEngine(config=policy_config)
        return policy_engine.evaluate(
            tool=tool_name,
            session=session,
            args=args,
            context=context,
        )


def authorize(
    tool_call: ToolCall,
    session: SessionState,
    context: dict[str, Any] | None = None,
    config_repo: ControlConfigRepository | None = None,
) -> Decision:
    """Convenience function to authorize a tool call against a session."""
    return Authorizer(config_repo=config_repo).authorize(
        tool_call=tool_call,
        session=session,
        context=context,
    )
