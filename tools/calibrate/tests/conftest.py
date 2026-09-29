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


# --- Builders for artifact fragments (plain dicts, as the harness writes them) ---

SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture
def make_backend():
    """A valid ``tfidf_lr`` backend spec as a plain dict."""

    def make(
        sha: str = SHA_A,
        label_map: dict[str, str] | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        from encoder.registry import tfidf_model_id

        train: dict = {"path": "data/train.jsonl", "sha256": sha}
        if label_map:
            train["label_map"] = label_map
        spec: dict = {
            "kind": "tfidf_lr",
            "model_id": tfidf_model_id(sha, label_map),
            "train": train,
            "probability_kind": "distribution",
            "local_only": True,
            "cost_class": "low",
            "timeout_ms": 200,
            "params": {},
        }
        if labels:
            spec["labels"] = labels
        return spec

    return make


@pytest.fixture
def make_entry():
    """A valid decision-point entry as a plain dict."""

    def make(
        backend: str = "intent",
        labels: tuple[str, ...] = ("a", "b"),
        tau: float | None = 0.5,
        run_id: str = "run000000001",
    ) -> dict:
        return {
            "backend": backend,
            "view": {"kind": "labels", "labels": list(labels)},
            "enabled": True,
            "always_on": True,
            "calibrator": {"kind": "temperature", "by_lang": {"es": {"T": 0.5}}},
            "thresholds": {"es": tau, "pt": None},
            "status": "calibrated",
            "evidence": {"run_id": run_id, "report": f"reports/{run_id}.md"},
        }

    return make
