"""Temperature scaling: fitted on validation, applied as the service applies it."""

from __future__ import annotations

import math

import numpy as np
import pytest
from calibrate.calibrators import (
    ISOTONIC_PENDING,
    T_MAX,
    CalibratorError,
    TemperatureScaler,
    require_supported,
)
from encoder.decision_points import apply_temperature

LABELS = ["a", "b", "c", "d"]


def _sample(flattening: float, n: int, seed: int) -> tuple[list[dict], list[str]]:
    """Rows from a model that states softmax(logits / flattening).

    Labels are drawn from the true distribution softmax(logits), so the model is
    exactly ``flattening`` too flat (``> 1``) or too sharp (``< 1``). Applying
    ``p ** (1 / T)`` with ``T = 1 / flattening`` undoes it, so that is the T the fit
    must recover.
    """
    rng = np.random.default_rng(seed)
    logits = rng.normal(0.0, 2.0, size=(n, len(LABELS)))
    truth_p = np.exp(logits - logits.max(axis=1, keepdims=True))
    truth_p /= truth_p.sum(axis=1, keepdims=True)
    labels = [LABELS[rng.choice(len(LABELS), p=row)] for row in truth_p]
    scaled = logits / flattening
    stated = np.exp(scaled - scaled.max(axis=1, keepdims=True))
    stated /= stated.sum(axis=1, keepdims=True)
    rows = [dict(zip(LABELS, map(float, row), strict=True)) for row in stated]
    return rows, labels


@pytest.mark.parametrize("flattening", [0.25, 4.0])
def test_fit_recovers_the_temperature_that_undoes_the_distortion(
    flattening: float,
) -> None:
    rows, truth = _sample(flattening, n=4000, seed=7)
    scaler = TemperatureScaler()
    fit = scaler.fit(rows, truth)
    assert math.isclose(fit.temperature, 1.0 / flattening, rel_tol=0.15)
    assert fit.nll_after < fit.nll_before
    assert not fit.at_bound


def test_an_already_calibrated_model_keeps_temperature_near_one() -> None:
    rows, truth = _sample(1.0, n=4000, seed=11)
    fit = TemperatureScaler().fit(rows, truth)
    assert math.isclose(fit.temperature, 1.0, abs_tol=0.12)


def test_fit_is_deterministic() -> None:
    rows, truth = _sample(0.5, n=500, seed=3)
    first = TemperatureScaler().fit(rows, truth)
    second = TemperatureScaler().fit(rows, truth)
    assert first == second


def test_apply_is_the_service_function() -> None:
    scaler = TemperatureScaler(0.2)
    row = {"a": 0.6, "b": 0.3, "c": 0.07, "d": 0.03}
    assert scaler.apply(row) == apply_temperature(row, 0.2)
    assert math.isclose(sum(scaler.apply(row).values()), 1.0)


def test_a_perfectly_separated_model_reports_that_the_bound_was_hit() -> None:
    rows = [{"a": 0.999, "b": 0.001}] * 20 + [{"a": 0.001, "b": 0.999}] * 20
    truth = ["a"] * 20 + ["b"] * 20
    fit = TemperatureScaler().fit(rows, truth)
    assert fit.at_bound
    assert 0 < fit.temperature <= T_MAX


def test_fit_rejects_unusable_input() -> None:
    scaler = TemperatureScaler()
    with pytest.raises(CalibratorError, match="zero rows"):
        scaler.fit([], [])
    with pytest.raises(CalibratorError, match="equal length"):
        scaler.fit([{"a": 1.0}], ["a", "a"])
    with pytest.raises(CalibratorError, match="not in the backend"):
        scaler.fit([{"a": 0.5, "b": 0.5}], ["zzz"])
    with pytest.raises(CalibratorError):
        TemperatureScaler(0.0)


def test_isotonic_is_pending_and_says_so() -> None:
    with pytest.raises(NotImplementedError, match=r"pending: isotonic"):
        require_supported("isotonic")
    assert ISOTONIC_PENDING.startswith("pending:")
    require_supported("none")
    require_supported("temperature")
    with pytest.raises(CalibratorError, match="unknown calibrator"):
        require_supported("platt")
