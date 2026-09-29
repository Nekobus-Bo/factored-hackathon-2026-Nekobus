"""Hermetic defaults for the encoder service tests."""

from collections.abc import Generator
from pathlib import Path

import pytest
from encoder_service.decisions import set_runtime


@pytest.fixture(autouse=True)
def no_artifact_and_clean_decision_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    """No calibration artifact unless a test asks for one.

    A committed packages/encoder/calibration/decision_points.json must not change what
    the legacy seed tests see, so the file is pointed at a path that does not exist.
    """
    monkeypatch.setenv("DECISION_POINTS_FILE", str(tmp_path / "no-artifact.json"))
    for name in (
        "DECISION_POINTS_ALLOW_STALE",
        "DECISION_POINTS_TAU_RAISE",
        "DECISION_POINTS_MAX_WORKERS",
        "APP_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    set_runtime(None)
    yield
    set_runtime(None)
