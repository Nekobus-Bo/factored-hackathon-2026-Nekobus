"""Configuration repository interface and in-memory implementation.

Enforces the non-negotiable architectural rule:
Runtime configuration can only RESTRICT tool permissions, NEVER widen them
beyond the non-configurable contracts.tools.CODE_FLOOR (ADR-0003 Appendix A).
"""

from typing import Protocol

from contracts.envelope import VerificationState
from contracts.tools import CODE_FLOOR, TOOL_CATALOG, get_effective_permitted_states

from banking_core.control.policy import PolicyConfig


class ControlConfigRepository(Protocol):
    """Protocol for accessing and updating control policies and tool matrices."""

    def get_policy_config(self) -> PolicyConfig:
        """Return active policy configuration."""
        ...

    def set_policy_config(self, config: PolicyConfig) -> None:
        """Update active policy configuration."""
        ...

    def get_tool_permitted_states(self, tool_name: str) -> frozenset[VerificationState]:
        """Return effective permitted states for a given tool."""
        ...

    def set_tool_permitted_states(
        self,
        tool_name: str,
        states: set[VerificationState] | frozenset[VerificationState],
    ) -> None:
        """Set permitted states for a tool, strictly validated against CODE_FLOOR."""
        ...


class InMemoryControlConfigRepository:
    """In-memory implementation of ControlConfigRepository.

    Used for unit testing and domain execution prior to DB storage in 2B-2b.
    """

    def __init__(
        self,
        policy_config: PolicyConfig | None = None,
        tool_matrix: dict[str, frozenset[VerificationState]] | None = None,
    ) -> None:
        self._policy_config = policy_config or PolicyConfig.from_env()
        self._tool_matrix: dict[str, frozenset[VerificationState]] = {}

        # Initialize with baseline TOOL_CATALOG permissions
        for tool_name, tool_def in TOOL_CATALOG.items():
            self._tool_matrix[tool_name] = tool_def.permitted_states

        # Apply any explicit overrides (each checked against CODE_FLOOR)
        if tool_matrix is not None:
            for tool_name, states in tool_matrix.items():
                self.set_tool_permitted_states(tool_name, states)

    def get_policy_config(self) -> PolicyConfig:
        return self._policy_config

    def set_policy_config(self, config: PolicyConfig) -> None:
        self._policy_config = config

    def get_tool_permitted_states(self, tool_name: str) -> frozenset[VerificationState]:
        """Return the effective permitted states for tool_name.

        Falls back to CODE_FLOOR if not in matrix, or raises ValueError if unknown tool.
        """
        if tool_name not in self._tool_matrix:
            if tool_name in CODE_FLOOR:
                return CODE_FLOOR[tool_name]
            raise ValueError(f"Unknown tool '{tool_name}'")
        return self._tool_matrix[tool_name]

    def set_tool_permitted_states(
        self,
        tool_name: str,
        states: set[VerificationState] | frozenset[VerificationState],
    ) -> None:
        """Configure permitted states for a tool.

        Strictly enforces that configuration can NEVER widen beyond CODE_FLOOR.
        Raises ValueError via get_effective_permitted_states if invalid.
        """
        effective = get_effective_permitted_states(tool_name, states)
        self._tool_matrix[tool_name] = effective
