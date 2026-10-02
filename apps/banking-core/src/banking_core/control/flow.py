"""The flow hint every tool result carries (ADR-0016).

banking-core leads the conversation by saying, after each call, what it allows
from the session's state: every tool the effective configuration permits there,
and the one that moves the session forward. It is advisory. The authorizer still
decides every call, and the hint never fails one: if the configuration cannot be
read, the result goes out without it.
"""

import logging

from contracts.envelope import (
    FlowHint,
    ReasonCode,
    ToolResult,
    ToolResultStatus,
    VerificationState,
)
from contracts.tools import (
    TOOL_CATALOG,
    VERIFICATION_PATH,
    get_effective_permitted_states,
)

from banking_core.control.config import ControlConfigRepository

logger = logging.getLogger(__name__)

# The FSM's forward edge from each state (control/fsm.py): the tool whose success
# moves the session one step towards VERIFIED (the contract's VERIFICATION_PATH,
# which the tool descriptions also read), or out of a dead end.
ADVANCE: dict[VerificationState, str] = {
    **dict(VERIFICATION_PATH),
    VerificationState.LOCKED: "handoff.create",
}
_NO_NEXT = frozenset({VerificationState.VERIFIED, VerificationState.HANDED_OFF})


def flow_hint(
    state: VerificationState,
    config_repo: ControlConfigRepository,
    result: ToolResult | None = None,
) -> FlowHint | None:
    """The hint for a session in `state`, after `result` (if any)."""
    try:
        effective = {
            tool: get_effective_permitted_states(
                tool, config_repo.get_tool_permitted_states(tool)
            )
            for tool in TOOL_CATALOG
        }
    except Exception as exc:
        logger.warning("Flow hint skipped: %s", type(exc).__name__)
        return None

    allowed = [tool for tool, states in effective.items() if state in states]
    refused = (
        result.tool
        if result is not None and result.status is not ToolResultStatus.OK
        else None
    )
    nexts = [
        tool
        for tool in (ADVANCE.get(state),)
        if tool is not None and tool in allowed and tool != refused
    ]
    if not nexts and state not in _NO_NEXT and "handoff.create" in allowed:
        nexts = ["handoff.create"]

    required = None
    if (
        result is not None
        and result.reason_code is ReasonCode.STATE_NOT_ALLOWED
        and result.tool in effective
    ):
        required = sorted(effective[result.tool], key=list(VerificationState).index)
    enabled = [tool for tool, states in effective.items() if states]
    return FlowHint(
        state=state,
        next=nexts,
        allowed=allowed,
        enabled=enabled,
        required_states=required,
    )


def with_flow(
    result: ToolResult, state: VerificationState, config_repo: ControlConfigRepository
) -> ToolResult:
    """`result` with its flow hint for the session's state after the call."""
    hint = flow_hint(state, config_repo, result)
    return result if hint is None else result.model_copy(update={"flow": hint})
