"""Fault injection for degradation scenarios (tool_down, timeout, slow_db).

Needs compose-level control of the stack (stop/pause containers, add latency),
which is not implemented yet: the default injector supports no fault, so those
scenarios are reported as not run.
"""

from __future__ import annotations

from typing import Protocol


class FaultInjector(Protocol):
    def supports(self, fault: str) -> bool: ...

    def apply(self, fault: str) -> None: ...

    def clear(self) -> None: ...


class NoFaultInjector:
    """Default: no fault can be injected."""

    def supports(self, fault: str) -> bool:
        return False

    def apply(self, fault: str) -> None:
        raise NotImplementedError("fault injection is not implemented")

    def clear(self) -> None:
        return None
