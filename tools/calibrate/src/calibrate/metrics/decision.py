from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, NamedTuple

# Two-sided 95% normal quantile, for the Wilson score interval.
Z_95 = 1.959963984540054


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    """Calculate Macro-averaged F1 score across all classes."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have identical lengths")
    if not y_true:
        return 0.0

    classes = sorted(set(y_true) | set(y_pred))
    if not classes:
        return 0.0

    f1_scores: list[float] = []
    for cls in classes:
        tp = sum(
            1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == cls and yp == cls
        )
        fp = sum(
            1 for yt, yp in zip(y_true, y_pred, strict=True) if yt != cls and yp == cls
        )
        fn = sum(
            1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == cls and yp != cls
        )

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        f1_scores.append(f1)

    return float(sum(f1_scores) / len(f1_scores))


def per_class_precision(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    classes: Sequence[str] | None = None,
) -> dict[str, float]:
    """Calculate precision per class."""
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have identical lengths")

    target_classes = sorted(set(classes or (set(y_true) | set(y_pred))))
    precisions: dict[str, float] = {}

    for cls in target_classes:
        tp = sum(
            1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == cls and yp == cls
        )
        fp = sum(
            1 for yt, yp in zip(y_true, y_pred, strict=True) if yt != cls and yp == cls
        )
        precisions[cls] = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0

    return precisions


def expected_calibration_error(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    confidences: Sequence[float],
    n_bins: int = 10,
) -> float:
    """Calculate Expected Calibration Error (ECE) with equal-width binning."""
    n = len(y_true)
    if n == 0:
        return 0.0
    if len(y_pred) != n or len(confidences) != n:
        raise ValueError("Inputs to expected_calibration_error must have equal length")

    bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
    ece = 0.0

    for b in range(n_bins):
        low = bin_boundaries[b]
        high = bin_boundaries[b + 1]

        # Include upper boundary in the final bin
        if b == n_bins - 1:
            indices = [i for i, c in enumerate(confidences) if low <= c <= high]
        else:
            indices = [i for i, c in enumerate(confidences) if low <= c < high]

        count = len(indices)
        if count == 0:
            continue

        bin_acc = sum(1 for i in indices if y_true[i] == y_pred[i]) / count
        bin_conf = sum(confidences[i] for i in indices) / count

        ece += (count / n) * abs(bin_acc - bin_conf)

    return float(ece)


class TauCalibrationResult(NamedTuple):
    """Result of threshold tau calibration on validation split."""

    tau: float | None
    coverage: float
    is_feasible: bool
    best_min_precision: float


def calibrate_tau(
    y_true_val: Sequence[str],
    y_pred_val: Sequence[str],
    confidences_val: Sequence[float],
    p_min: float = 0.9,
) -> TauCalibrationResult:
    """Select threshold tau on validation split.

    Chooses tau to maximize coverage subject to per-class precision >= p_min
    for all classes predicted in the accepted subset.
    Returns TauCalibrationResult with explicit feasibility flag.
    """
    n = len(y_true_val)
    if n == 0 or len(confidences_val) == 0:
        return TauCalibrationResult(
            tau=None,
            coverage=0.0,
            is_feasible=False,
            best_min_precision=0.0,
        )

    candidate_taus = sorted(
        set([0.0, 1.0] + [round(float(c), 6) for c in confidences_val])
    )

    best_tau: float | None = None
    best_coverage = -1.0
    best_min_precision = 0.0

    for tau in candidate_taus:
        accepted_indices = [i for i, c in enumerate(confidences_val) if c >= tau]
        if not accepted_indices:
            continue

        coverage = len(accepted_indices) / n
        sub_true = [y_true_val[i] for i in accepted_indices]
        sub_pred = [y_pred_val[i] for i in accepted_indices]
        predicted_classes = set(sub_pred)

        precisions = per_class_precision(
            sub_true, sub_pred, classes=list(predicted_classes)
        )
        min_prec = min(precisions.values()) if precisions else 0.0

        if min_prec > best_min_precision:
            best_min_precision = min_prec

        if min_prec >= p_min:
            # Maximizing coverage corresponds to smallest tau meeting constraint
            if coverage > best_coverage:
                best_coverage = coverage
                best_tau = tau

    if best_tau is None or best_coverage < 0.0:
        return TauCalibrationResult(
            tau=None,
            coverage=0.0,
            is_feasible=False,
            best_min_precision=best_min_precision,
        )

    return TauCalibrationResult(
        tau=best_tau,
        coverage=best_coverage,
        is_feasible=True,
        best_min_precision=best_min_precision,
    )


def evaluate_at_tau(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    confidences: Sequence[float],
    tau: float | None,
) -> tuple[float, dict[str, float], float]:
    """Evaluate performance of calibrated threshold on test split.

    Returns (coverage, per_class_precision, macro_f1).
    If tau is None (infeasible calibration), returns (0.0, {}, 0.0).
    """
    n = len(y_true)
    if n == 0 or tau is None:
        return 0.0, {}, 0.0

    accepted = [i for i, c in enumerate(confidences) if c >= tau]
    coverage = len(accepted) / n

    if not accepted:
        return coverage, {}, 0.0

    sub_true = [y_true[i] for i in accepted]
    sub_pred = [y_pred[i] for i in accepted]

    precisions = per_class_precision(sub_true, sub_pred)
    f1 = macro_f1(sub_true, sub_pred)

    return coverage, precisions, f1


def slot_f1(
    true_slots_list: Sequence[Sequence[Any]],
    pred_slots_list: Sequence[Sequence[Any]],
) -> float:
    """Calculate micro F1 score across extracted slot entities."""
    if len(true_slots_list) != len(pred_slots_list):
        raise ValueError("True and predicted slot lists must have identical lengths")

    total_tp = 0
    total_fp = 0
    total_fn = 0

    has_any_slots = False

    for true_slots, pred_slots in zip(true_slots_list, pred_slots_list, strict=True):

        def _to_tuple(item: Any) -> tuple[str, str]:
            if hasattr(item, "type") and hasattr(item, "value"):
                return (str(item.type).lower(), str(item.value).strip().lower())
            if isinstance(item, dict):
                return (
                    str(item.get("type", "")).lower(),
                    str(item.get("value", "")).strip().lower(),
                )
            return (str(item), "")

        t_set = [_to_tuple(s) for s in true_slots]
        p_set = [_to_tuple(s) for s in pred_slots]

        if t_set or p_set:
            has_any_slots = True

        # Multiset matching
        remaining_pred = list(p_set)
        for t in t_set:
            if t in remaining_pred:
                total_tp += 1
                remaining_pred.remove(t)
            else:
                total_fn += 1
        total_fp += len(remaining_pred)

    if not has_any_slots:
        return 1.0

    prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    return float((2 * prec * rec) / (prec + rec)) if (prec + rec) > 0 else 0.0


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion. ``(0.0, 1.0)`` when ``n == 0``.

    Unlike the point estimate it does not call 10 of 10 "100% precise": 10 of 10
    has a lower bound near 0.72. That is why a precision claim is made on the lower
    bound (ADR-0012, Appendix F).
    """
    if n < 0 or not 0 <= successes <= n:
        raise ValueError(f"need 0 <= successes <= n, got {successes} of {n}")
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denominator
    # The exact ends are known; do not let float error move them off 0 and 1.
    low = 0.0 if successes == 0 else min(p, max(0.0, centre - margin))
    high = 1.0 if successes == n else max(p, min(1.0, centre + margin))
    return low, high


def wilson_lower_bound(successes: int, n: int, z: float = Z_95) -> float:
    """Lower end of the Wilson interval; 0.0 when there is no evidence (``n == 0``)."""
    if n == 0:
        return 0.0
    return wilson_interval(successes, n, z)[0]


def zero_error_sample_size(p_min: float, z: float = Z_95) -> int:
    """Fewest accepted decisions, all correct, whose Wilson lower bound reaches
    ``p_min``. 73 for 0.95 and 35 for 0.90 (ADR-0012, context item 5)."""
    if not 0.0 <= p_min < 1.0:
        raise ValueError(
            "p_min must be in [0, 1): no sample certifies a precision of 1"
        )
    n = max(1, math.ceil(p_min * z * z / (1.0 - p_min)))
    # The closed form can be off by one at the float boundary.
    while wilson_lower_bound(n, n, z) < p_min:
        n += 1
    while n > 1 and wilson_lower_bound(n - 1, n - 1, z) >= p_min:
        n -= 1
    return n


class ReliabilityBin(NamedTuple):
    """One equal-width confidence bin of a reliability diagram."""

    low: float
    high: float
    n: int
    mean_confidence: float
    accuracy: float


def reliability_bins(
    correct: Sequence[bool],
    confidences: Sequence[float],
    n_bins: int = 10,
) -> list[ReliabilityBin]:
    """Reliability diagram data, binned as ``expected_calibration_error`` bins."""
    if len(correct) != len(confidences):
        raise ValueError("correct and confidences must have identical lengths")
    bins: list[ReliabilityBin] = []
    for b in range(n_bins):
        low, high = b / n_bins, (b + 1) / n_bins
        members = [
            i
            for i, c in enumerate(confidences)
            if low <= c < high or (b == n_bins - 1 and c == high)
        ]
        n = len(members)
        bins.append(
            ReliabilityBin(
                low=low,
                high=high,
                n=n,
                mean_confidence=(
                    sum(confidences[i] for i in members) / n if n else 0.0
                ),
                accuracy=sum(1 for i in members if correct[i]) / n if n else 0.0,
            )
        )
    return bins
