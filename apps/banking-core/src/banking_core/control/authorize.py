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

import logging
from typing import Any

from contracts.envelope import ReasonCode, ToolCall
from contracts.tools import (
    TOOL_CATALOG,
    CodeFloorViolation,
    get_effective_permitted_states,
)

from banking_core.control.config import (
    ControlConfigRepository,
    get_control_config_repository,
)
from banking_core.control.policy import Decision, PolicyEngine
from banking_core.control.session import SessionState

logger = logging.getLogger(__name__)

CONFIG_UNAVAILABLE_FLAG = "POLICY_CONFIG_UNAVAILABLE"
TOOL_DISABLED_FLAG = "TOOL_DISABLED"


def _config_unavailable(tool_name: str, exc: Exception) -> Decision:
    """Refuse closed when DB-backed configuration cannot be read.

    The exception detail goes to the log only: flags travel to the untrusted zone.
    """
    logger.error(
        "Policy configuration unavailable for tool '%s': %s: %s",
        tool_name,
        type(exc).__name__,
        exc,
    )
    return Decision(
        allowed=False,
        reason_code=ReasonCode.INTERNAL_ERROR,
        flags=[CONFIG_UNAVAILABLE_FLAG],
    )


class Authorizer:
    """Authorizer evaluating deterministic access controls on tool calls."""

    def __init__(self, config_repo: ControlConfigRepository | None = None) -> None:
        self.config_repo = config_repo or get_control_config_repository()

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
        try:
            configured_states = self.config_repo.get_tool_permitted_states(tool_name)
            effective_states = get_effective_permitted_states(
                tool_name, configured_states
            )
        except CodeFloorViolation as exc:
            # A stored row wider than CODE_FLOOR: refuse, never serve it.
            logger.error("Code floor violation for tool '%s': %s", tool_name, exc)
            return Decision(
                allowed=False,
                reason_code=ReasonCode.CODE_FLOOR_VIOLATION,
                flags=["CODE_FLOOR_VIOLATION"],
            )
        except Exception as exc:
            return _config_unavailable(tool_name, exc)

        # 3. FSM state check. A tool no state enables was disabled by configuration:
        # the refusal is the same STATE_NOT_ALLOWED, the audit flag says why.
        if session.state not in effective_states:
            return Decision(
                allowed=False,
                reason_code=ReasonCode.STATE_NOT_ALLOWED,
                flags=[
                    TOOL_DISABLED_FLAG
                    if not effective_states
                    else f"STATE_{session.state.value}_NOT_PERMITTED"
                ],
            )

        # 4. Policy engine check (rate limits, thresholds)
        try:
            policy_config = self.config_repo.get_policy_config()
        except Exception as exc:
            return _config_unavailable(tool_name, exc)

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
