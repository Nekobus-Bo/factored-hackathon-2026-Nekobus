"""Configuration repository interface and in-memory implementation.

Enforces the non-negotiable architectural rule:
Runtime configuration can only RESTRICT tool permissions, NEVER widen them
beyond the non-configurable contracts.tools.CODE_FLOOR (ADR-0003 Appendix A).
"""

from typing import Protocol

from contracts.envelope import VerificationState
from contracts.tools import CODE_FLOOR, TOOL_CATALOG, get_effective_permitted_states
from sqlalchemy.orm import Session, sessionmaker

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

    Tests only, via explicit injection. Never a runtime fallback for the DB.
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


class DatabaseControlConfigRepository:
    """PostgreSQL-backed implementation of ControlConfigRepository.

    Reads policy configuration and tool authorization matrices from the DB,
    seeded from environment on first run if empty (ADR-0002).
    Strictly validates against CODE_FLOOR on reads and writes (ADR-0003 Appendix A).
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()
        from banking_core.db.session import get_session_maker

        return get_session_maker()()

    def get_policy_config(self) -> PolicyConfig:
        from banking_core.control.loader import load_policy_config

        with self._get_session() as session:
            return load_policy_config(session=session)

    def set_policy_config(self, config: PolicyConfig) -> None:
        from banking_core.control.loader import save_policy_config

        with self._get_session() as session:
            save_policy_config(config, session=session)

    def get_tool_permitted_states(self, tool_name: str) -> frozenset[VerificationState]:
        if tool_name not in TOOL_CATALOG and tool_name not in CODE_FLOOR:
            raise ValueError(f"Unknown tool '{tool_name}'")

        from banking_core.models.config import ToolPolicyRecord

        with self._get_session() as session:
            record = session.get(ToolPolicyRecord, tool_name)
            # An empty list is an operator disabling the tool, not a missing row.
            if record is not None:
                configured = {VerificationState(s) for s in record.permitted_states}
                return get_effective_permitted_states(tool_name, configured)

        # Baseline fallback from catalog or code floor
        if tool_name in TOOL_CATALOG:
            return TOOL_CATALOG[tool_name].permitted_states
        return CODE_FLOOR[tool_name]

    def set_tool_permitted_states(
        self,
        tool_name: str,
        states: set[VerificationState] | frozenset[VerificationState],
    ) -> None:
        effective = get_effective_permitted_states(tool_name, states)
        from banking_core.models.config import ToolPolicyRecord

        state_values = sorted([s.value for s in effective])
        with self._get_session() as session:
            record = session.get(ToolPolicyRecord, tool_name)
            if record is None:
                record = ToolPolicyRecord(
                    tool_name=tool_name,
                    permitted_states=state_values,
                )
                session.add(record)
            else:
                record.permitted_states = state_values
            session.commit()


def get_control_config_repository(
    session_factory: sessionmaker[Session] | None = None,
) -> ControlConfigRepository:
    """Return active ControlConfigRepository backed by PostgreSQL.

    Fails loudly if database is unreachable (no silent InMemory fallback).
    InMemoryControlConfigRepository is allowed only in tests via explicit injection.
    """
    return DatabaseControlConfigRepository(session_factory=session_factory)
