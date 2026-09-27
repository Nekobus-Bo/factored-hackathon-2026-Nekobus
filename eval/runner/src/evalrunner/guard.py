"""Safety guards for evaluation runner outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class BaselineSystem:
    """Baseline system under test (pending implementation)."""

    name: str = "baseline"


class ProposedSystem:
    """Proposed Pattern Blue system under test (pending implementation)."""

    name: str = "proposed"


REAL_SYSTEM_CLASSES: tuple[type, ...] = (BaselineSystem, ProposedSystem)


def is_real_system(system: Any) -> bool:
    """Check if the system under test is an instance or subclass of a real system."""
    if isinstance(system, type):
        return any(issubclass(system, cls) for cls in REAL_SYSTEM_CLASSES)
    return isinstance(system, REAL_SYSTEM_CLASSES)


def guard_fakesystem_output(
    system: Any = None,
    out_path: str | Path = "",
    repo_root: str | Path | None = None,
    *,
    system_name: Any = None,
) -> None:
    """Refuse to write reports into reports/ when system is not allowlisted."""
    target_system = system if system is not None else system_name
    if is_real_system(target_system):
        return

    out_resolved = Path(out_path).resolve()
    if repo_root is None:
        # Resolve repo root from __file__
        # (eval/runner/src/evalrunner/guard.py -> parents[4])
        repo_root = Path(__file__).resolve().parents[4]

    reports_dir = (Path(repo_root) / "reports").resolve()
    if out_resolved == reports_dir or reports_dir in out_resolved.parents:
        raise ValueError(
            "Refusing to write fake evaluation report into repository reports/ "
            f"directory ({out_resolved}). "
            "FakeSystem evaluation must write to /tmp or another external path."
        )
