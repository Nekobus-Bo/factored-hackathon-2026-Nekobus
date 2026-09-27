from __future__ import annotations

import math

from calibrate.metrics.decision import (
    calibrate_tau,
    evaluate_at_tau,
    expected_calibration_error,
    macro_f1,
    per_class_precision,
    slot_f1,
)


def test_macro_f1_hand_computed():
    """Verify macro-F1 against hand-computed reference case: 59/90 ~= 0.655556."""
    y_true = ["A", "A", "B", "B", "C", "C"]
    y_pred = ["A", "B", "B", "C", "C", "C"]

    score = macro_f1(y_true, y_pred)
    expected = 59.0 / 90.0

    assert math.isclose(score, expected, rel_tol=1e-5), (
        f"Expected {expected}, got {score}"
    )


def test_per_class_precision_hand_computed():
    """Verify per-class precision against hand-computed reference."""
    y_true = ["A", "A", "B", "B", "C", "C"]
    y_pred = ["A", "B", "B", "C", "C", "C"]

    precisions = per_class_precision(y_true, y_pred)
    assert math.isclose(precisions["A"], 1.0, rel_tol=1e-5)
    assert math.isclose(precisions["B"], 0.5, rel_tol=1e-5)
    assert math.isclose(precisions["C"], 2.0 / 3.0, rel_tol=1e-5)


def test_ece_hand_computed():
    """Verify ECE on hand-computed 2-bin case: exactly 0.16."""
    y_true = ["A", "A", "B", "B", "A"]
    y_pred = ["A", "B", "B", "A", "A"]
    confidences = [0.2, 0.4, 0.7, 0.8, 0.9]

    ece = expected_calibration_error(y_true, y_pred, confidences, n_bins=2)
    expected = 0.16

    assert math.isclose(ece, expected, rel_tol=1e-5), f"Expected {expected}, got {ece}"


def test_tau_selection_feasible():
    """Verify feasible threshold tau selection enforces
    per-class precision >= p_min while maximizing coverage.
    """
    # 4 validation samples
    y_true_val = ["A", "B", "A", "B"]
    y_pred_val = ["A", "B", "A", "A"]  # sample 3 has error: pred A, true B
    confidences_val = [0.95, 0.92, 0.85, 0.60]

    res = calibrate_tau(y_true_val, y_pred_val, confidences_val, p_min=0.90)

    assert res.is_feasible is True
    assert res.tau is not None
    assert res.tau >= 0.85
    assert math.isclose(res.coverage, 0.75, rel_tol=1e-5)
    assert res.best_min_precision >= 0.90

    # Evaluate on test samples using calibrated tau
    y_true_test = ["A", "B", "A"]
    y_pred_test = ["A", "B", "B"]
    conf_test = [0.95, 0.90, 0.50]  # sample 2 rejected by tau=0.85

    cov_test, prec_test, f1_test = evaluate_at_tau(
        y_true_test, y_pred_test, conf_test, res.tau
    )
    assert math.isclose(cov_test, 2.0 / 3.0, rel_tol=1e-5)
    assert math.isclose(prec_test["A"], 1.0, rel_tol=1e-5)
    assert math.isclose(prec_test["B"], 1.0, rel_tol=1e-5)
    assert math.isclose(f1_test, 1.0, rel_tol=1e-5)


def test_tau_selection_infeasible():
    """Verify infeasible case when no threshold meets p_min."""
    # 4 validation samples: at top confidence 0.95, 1 correct and 1 wrong
    # -> precision 0.50. At lower confidence 0.80, 1 correct and 1 wrong
    # -> precision 0.50. No subset achieves precision >= 0.90.
    y_true_val = ["A", "B", "A", "B"]
    y_pred_val = ["A", "A", "B", "B"]
    confidences_val = [0.95, 0.95, 0.80, 0.80]

    res = calibrate_tau(y_true_val, y_pred_val, confidences_val, p_min=0.90)

    assert res.is_feasible is False
    assert res.tau is None
    assert res.coverage == 0.0
    assert math.isclose(res.best_min_precision, 0.5, rel_tol=1e-5)

    # evaluate_at_tau with None tau returns zero coverage and safe defaults
    cov, prec, f1 = evaluate_at_tau(["A", "B"], ["A", "B"], [0.95, 0.90], res.tau)
    assert cov == 0.0
    assert prec == {}
    assert f1 == 0.0


def test_tau_selection_empty_accepted_set():
    """Verify edge cases with empty input or empty accepted sets."""
    # Empty inputs
    res_empty = calibrate_tau([], [], [], p_min=0.90)
    assert res_empty.is_feasible is False
    assert res_empty.tau is None
    assert res_empty.coverage == 0.0
    assert res_empty.best_min_precision == 0.0

    cov, prec, f1 = evaluate_at_tau([], [], [], tau=None)
    assert cov == 0.0
    assert prec == {}
    assert f1 == 0.0


def test_slot_f1_hand_computed():
    """Verify slot entity micro-F1 matches hand-computed case: 2/3 ~= 0.666667."""
    true_slots = [
        [{"type": "amount", "value": "$100"}, {"type": "merchant", "value": "Amazon"}],
        [{"type": "card_last4", "value": "1234"}],
    ]
    pred_slots = [
        [{"type": "amount", "value": "$100"}, {"type": "merchant", "value": "Ebay"}],
        [{"type": "card_last4", "value": "1234"}],
    ]

    f1 = slot_f1(true_slots, pred_slots)
    expected = 2.0 / 3.0

    assert math.isclose(f1, expected, rel_tol=1e-5), f"Expected {expected}, got {f1}"
