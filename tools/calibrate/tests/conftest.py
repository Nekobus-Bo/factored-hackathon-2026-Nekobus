"""Shared test setup for the calibration harness.

The decision-points task never imports PyTorch, so its tests must run anywhere. A few
older tests exercise the GLiNER and sentence-transformers adapters; where PyTorch is
not installed (a sandbox that cannot reach the PyTorch wheel index) they are skipped
here instead of failing at collection. CI installs PyTorch and runs all of them.
"""

from __future__ import annotations

import importlib.util

import pytest

HAS_TORCH = importlib.util.find_spec("torch") is not None

# Whole modules that import a PyTorch adapter at the top.
collect_ignore: list[str] = [] if HAS_TORCH else ["test_adapter_failures.py"]

# Individual tests whose candidates load a PyTorch model.
_NEEDS_TORCH = {
    "test_runner_smoke.py::test_runner_decision_smoke",
    "test_runner_smoke.py::test_runner_embedding_smoke",
}


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if HAS_TORCH:
        return
    skip = pytest.mark.skip(reason="needs PyTorch (not installed here)")
    for item in items:
        if any(item.nodeid.endswith(name) for name in _NEEDS_TORCH):
            item.add_marker(skip)
