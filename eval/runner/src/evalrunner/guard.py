"""Safety guards for evaluation runner outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# A real system under test (the proposed one, the baseline once it exists) declares
# `real_system: ClassVar[bool] = True` on its class. Test doubles do not, so a fake
# never gets to write into reports/. It is read from the class, not the instance.
REAL_SYSTEM_MARKER = "real_system"


def is_real_system(system: Any) -> bool:
    """Check if the system under test (an instance or a class) is marked as real."""
    system_class = system if isinstance(system, type) else type(system)
    return getattr(system_class, REAL_SYSTEM_MARKER, False) is True


def guard_fakesystem_output(
    system: Any = None,
    out_path: str | Path = "",
    repo_root: str | Path | None = None,
    *,
    system_name: Any = None,
) -> None:
    """Refuse to write reports into reports/ unless the system is marked real."""
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
