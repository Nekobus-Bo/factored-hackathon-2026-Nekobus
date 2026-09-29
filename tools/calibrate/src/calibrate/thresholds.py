"""Choosing tau under a precision constraint (ADR-0012, Appendix F.2).

The objective is always the same: **maximum coverage subject to the constraint**,
evaluated on the calibration split (validation, never test). The constraint binds
only the labels the engine *acts on*, not every class of the model.

Two shapes, because tau can be one number or one number per label:

* ``fit_label_threshold``: tau for one label. The accepted rows of a label are the
  rows whose top label it is with confidence >= tau, so its precision depends on
  that tau alone. Labels are independent, which is what makes a per-label tau
  cheap to fit exactly.
* ``fit_scalar_threshold``: one tau for the whole DP in a language. Every label is
  accepted at that tau, and the constraint must hold for each acted label at once.

A tau is always the confidence of an observed row, rounded *down* to six decimals
(``round_tau_down``) so the row that defined it stays accepted at runtime.

The precision estimate is either the point estimate or the Wilson 95% lower bound
(``ci``). With ten rows per class, as today, the lower bound cannot reach 0.95 and
a fit under it reports infeasible; that is the honest answer, and why the seed run
selects with the point estimate and certifies (separately, on test) with Wilson.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from calibrate.metrics.decision import wilson_lower_bound

ConfidenceInterval = Literal["point", "wilson95_lower"]
CONFIDENCE_INTERVALS: tuple[str, ...] = ("point", "wilson95_lower")
TAU_DECIMALS = 6


def round_tau_down(confidence: float) -> float:
    """``confidence`` rounded down to ``TAU_DECIMALS``, never above it."""
    scale = 10**TAU_DECIMALS
    tau = math.floor(confidence * scale) / scale
    while tau > confidence:
        tau = math.nextafter(tau, 0.0)
    return max(0.0, tau)


@dataclass(frozen=True)
class ScoredRow:
    """One calibration row after the backend and the calibrator have spoken."""

    lang: str
    label: str  # the DP's top label for the row
    confidence: float  # its calibrated confidence
    truth: str | None  # the row's true DP label; None when outside the view


def precision_estimate(tp: int, n: int, ci: ConfidenceInterval) -> float | None:
    """Precision under ``ci``; ``None`` when nothing was accepted."""
    if n == 0:
        return None
    return tp / n if ci == "point" else wilson_lower_bound(tp, n)


def meets(tp: int, n: int, p_min: float, ci: ConfidenceInterval) -> bool:
    """Whether accepted decisions satisfy the constraint. Accepting nothing does:
    a label the model never decides cannot be a wrong decision."""
    estimate = precision_estimate(tp, n, ci)
    return estimate is None or estimate >= p_min


@dataclass(frozen=True)
class LabelFit:
    """The outcome of fitting tau for one label in one scope."""

    label: str
    tau: float | None
    scope: Literal["language", "pooled"]
    n_rows: int  # rows in the scope
    support: int  # rows whose truth is this label
    accepted: int = 0
    tp: int = 0
    precision: float | None = None  # point estimate at tau
    estimate: float | None = None  # the estimate the constraint used (per ci)
    best_estimate: float | None = None  # best any tau reached (for the report)
    reason: str | None = None  # why tau is None

    @property
    def feasible(self) -> bool:
        return self.tau is not None

    @property
    def coverage(self) -> float:
        return self.accepted / self.n_rows if self.n_rows else 0.0


def _infeasible(
    label: str,
    scope: Literal["language", "pooled"],
    n_rows: int,
    support: int,
    reason: str,
    best: float | None = None,
) -> LabelFit:
    return LabelFit(
        label=label,
        tau=None,
        scope=scope,
        n_rows=n_rows,
        support=support,
        best_estimate=best,
        reason=reason,
    )


def fit_label_threshold(
    rows: Sequence[ScoredRow],
    label: str,
    *,
    p_min: float,
    ci: ConfidenceInterval,
    n_min: int,
    scope: Literal["language", "pooled"] = "language",
) -> LabelFit:
    """Tau for ``label``: the most accepted rows whose precision meets ``p_min``.

    Ties go to the higher tau. ``n_min`` is the fewest rows of the label the scope
    must hold for a fit to mean anything.
    """
    support = sum(1 for r in rows if r.truth == label)
    if support < n_min:
        return _infeasible(
            label,
            scope,
            len(rows),
            support,
            f"only {support} validation rows of '{label}' in this scope, "
            f"n_min is {n_min}",
        )
    predicted = [r for r in rows if r.label == label]
    if not predicted:
        return _infeasible(
            label,
            scope,
            len(rows),
            support,
            f"the model never predicts '{label}' on validation",
        )

    best_fit: tuple[int, float, int] | None = None  # (accepted, tau, tp)
    best_estimate: float | None = None
    for tau in sorted({round_tau_down(r.confidence) for r in predicted}):
        accepted = [r for r in predicted if r.confidence >= tau]
        tp = sum(1 for r in accepted if r.truth == label)
        estimate = precision_estimate(tp, len(accepted), ci)
        if estimate is not None and (best_estimate is None or estimate > best_estimate):
            best_estimate = estimate
        if not meets(tp, len(accepted), p_min, ci):
            continue
        if best_fit is None or (len(accepted), tau) >= (best_fit[0], best_fit[1]):
            best_fit = (len(accepted), tau, tp)

    if best_fit is None:
        return _infeasible(
            label,
            scope,
            len(rows),
            support,
            f"no threshold reaches {ci} precision {p_min:.2f} for '{label}' "
            f"(best {best_estimate:.3f})"
            if best_estimate is not None
            else f"no threshold reaches {ci} precision {p_min:.2f} for '{label}'",
            best_estimate,
        )
    accepted_n, tau, tp = best_fit
    return LabelFit(
        label=label,
        tau=tau,
        scope=scope,
        n_rows=len(rows),
        support=support,
        accepted=accepted_n,
        tp=tp,
        precision=tp / accepted_n,
        estimate=precision_estimate(tp, accepted_n, ci),
        best_estimate=best_estimate,
    )


@dataclass(frozen=True)
class ScalarFit:
    """The outcome of fitting one tau for a whole DP in a language."""

    tau: float | None
    n_rows: int
    accepted: int = 0
    per_label: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    # For each acted label: (tp, accepted) at tau.
    supports: Mapping[str, int] = field(default_factory=dict)
    reason: str | None = None

    @property
    def feasible(self) -> bool:
        return self.tau is not None

    @property
    def coverage(self) -> float:
        return self.accepted / self.n_rows if self.n_rows else 0.0


def fit_scalar_threshold(
    rows: Sequence[ScoredRow],
    acted: Mapping[str, float],
    *,
    ci: ConfidenceInterval,
    n_min: int,
) -> ScalarFit:
    """One tau for the language: the most rows accepted such that **every acted
    label** with accepted decisions meets its own ``p_min`` (``acted`` maps label to
    ``p_min``). Labels outside ``acted`` are accepted at the same tau, unconstrained.
    At least one acted label must be decided: a tau that satisfies the constraint by
    accepting none of them is infeasible, not a fit.
    """
    supports = {label: sum(1 for r in rows if r.truth == label) for label in acted}
    short = {label: n for label, n in supports.items() if n < n_min}
    if short:
        listing = ", ".join(f"'{label}' has {n}" for label, n in sorted(short.items()))
        return ScalarFit(
            tau=None,
            n_rows=len(rows),
            supports=supports,
            reason=f"too few validation rows for the acted labels ({listing}; "
            f"n_min is {n_min})",
        )
    if not rows:
        return ScalarFit(tau=None, n_rows=0, supports=supports, reason="no rows")

    best: tuple[int, float, dict[str, tuple[int, int]]] | None = None
    for tau in sorted({round_tau_down(r.confidence) for r in rows}):
        accepted = [r for r in rows if r.confidence >= tau]
        per_label: dict[str, tuple[int, int]] = {}
        ok = True
        for label, p_min in acted.items():
            decided = [r for r in accepted if r.label == label]
            tp = sum(1 for r in decided if r.truth == label)
            per_label[label] = (tp, len(decided))
            if not meets(tp, len(decided), p_min, ci):
                ok = False
                break
        # Holding the constraint by never deciding an acted label is not a fit: the
        # DP would silently do nothing it exists to do.
        decides_something = any(n > 0 for _, n in per_label.values())
        if (
            ok
            and decides_something
            and (best is None or (len(accepted), tau) >= (best[0], best[1]))
        ):
            best = (len(accepted), tau, per_label)
    if best is None:
        return ScalarFit(
            tau=None,
            n_rows=len(rows),
            supports=supports,
            reason=f"no threshold satisfies {ci} precision on every acted label "
            f"({', '.join(f'{k} >= {v:.2f}' for k, v in sorted(acted.items()))})",
        )
    accepted_n, tau, per_label = best
    return ScalarFit(
        tau=tau,
        n_rows=len(rows),
        accepted=accepted_n,
        per_label=per_label,
        supports=supports,
    )
