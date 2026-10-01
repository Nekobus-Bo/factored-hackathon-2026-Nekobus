"""Confidence calibrators for decision-point backends (ADR-0012, Appendix F).

Only temperature scaling exists at the freeze. It is one parameter per language:
``p_i ** (1 / T)`` renormalized, the same function the encoder service applies at
runtime (``encoder.decision_points.apply_temperature``), so the number fitted here
is exactly the number served. ``T < 1`` sharpens an under-confident model.

``isotonic`` is promised by the ADR and not built; asking for it fails with the
same ``pending:`` message the artifact loader uses (AGENTS.md, rule 7).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from encoder.decision_points import apply_temperature

# The artifact schema accepts T in (0, 100]. A fit that lands on the lower bound
# means the model is (almost) perfectly separated on the rows it was fitted on.
T_MIN = 0.01
T_MAX = 100.0
# Same clamp as apply_temperature, so a zero probability costs the same in both.
_EPS = 1e-12
_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0

ISOTONIC_PENDING = "pending: isotonic calibrator is not implemented (ADR-0012)"


class CalibratorError(ValueError):
    """A calibrator cannot be fitted from the rows it was given."""


@dataclass(frozen=True)
class TemperatureFit:
    """What fitting one temperature found."""

    temperature: float
    n: int
    nll_before: float
    nll_after: float
    # True when T is at T_MIN or T_MAX: the optimum is outside the searched range.
    at_bound: bool


def _log_matrix(
    probabilities: Sequence[Mapping[str, float]], labels: Sequence[str]
) -> np.ndarray:
    rows = np.empty((len(probabilities), len(labels)), dtype=np.float64)
    for i, distribution in enumerate(probabilities):
        for j, label in enumerate(labels):
            rows[i, j] = math.log(max(float(distribution[label]), _EPS))
    return rows


def _nll(logs: np.ndarray, truth: np.ndarray, beta: float) -> float:
    """Mean negative log-likelihood of the true label when scaled by ``beta = 1/T``."""
    scaled = logs * beta
    top = scaled.max(axis=1, keepdims=True)
    log_norm = top[:, 0] + np.log(np.exp(scaled - top).sum(axis=1))
    return float(np.mean(log_norm - scaled[np.arange(len(truth)), truth]))


class TemperatureScaler:
    """One temperature, fitted by minimizing the log loss of the true label.

    The loss is convex in ``beta = 1 / T``, so a bounded golden-section search on
    ``log beta`` finds the one optimum with no dependency on a solver and gives the
    same answer on every run.
    """

    def __init__(self, temperature: float = 1.0) -> None:
        if not 0.0 < temperature <= T_MAX:
            raise CalibratorError(f"T must be in (0, {T_MAX:g}], got {temperature}")
        self.temperature = temperature

    def apply(self, probabilities: Mapping[str, float]) -> dict[str, float]:
        return apply_temperature(probabilities, self.temperature)

    def fit(
        self,
        probabilities: Sequence[Mapping[str, float]],
        truth: Sequence[str],
        *,
        iterations: int = 80,
    ) -> TemperatureFit:
        """Set ``self.temperature`` from validation rows and describe the fit.

        ``probabilities`` are the backend's raw distributions and ``truth`` the
        true label of each, drawn from the same label space.
        """
        if len(probabilities) != len(truth):
            raise CalibratorError("probabilities and truth must have equal length")
        if not probabilities:
            raise CalibratorError("cannot fit a temperature on zero rows")
        labels = sorted(probabilities[0])
        index = {label: i for i, label in enumerate(labels)}
        unknown = sorted({t for t in truth if t not in index})
        if unknown:
            raise CalibratorError(
                f"true labels {unknown} are not in the backend's label space"
            )
        logs = _log_matrix(probabilities, labels)
        y = np.array([index[t] for t in truth], dtype=np.int64)

        low, high = math.log(1.0 / T_MAX), math.log(1.0 / T_MIN)
        a, b = low, high
        c = b - _GOLDEN * (b - a)
        d = a + _GOLDEN * (b - a)
        fc, fd = _nll(logs, y, math.exp(c)), _nll(logs, y, math.exp(d))
        for _ in range(iterations):
            if fc < fd:
                b, d, fd = d, c, fc
                c = b - _GOLDEN * (b - a)
                fc = _nll(logs, y, math.exp(c))
            else:
                a, c, fc = c, d, fd
                d = a + _GOLDEN * (b - a)
                fd = _nll(logs, y, math.exp(d))
        beta = math.exp((a + b) / 2.0)
        temperature = min(T_MAX, max(T_MIN, 1.0 / beta))
        # Round as the artifact will store it, so the reported loss is the served one.
        temperature = round(temperature, 6)
        self.temperature = temperature
        return TemperatureFit(
            temperature=temperature,
            n=len(truth),
            nll_before=_nll(logs, y, 1.0),
            nll_after=_nll(logs, y, 1.0 / temperature),
            at_bound=temperature <= T_MIN * 1.001 or temperature >= T_MAX * 0.999,
        )


def require_supported(kind: str) -> None:
    """Fail explicitly for a calibrator the ADR names and the harness lacks."""
    if kind == "isotonic":
        raise NotImplementedError(ISOTONIC_PENDING)
    if kind not in {"none", "temperature"}:
        raise CalibratorError(
            f"unknown calibrator {kind!r}; expected none or temperature"
        )
