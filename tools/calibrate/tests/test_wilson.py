"""Wilson interval, the zero-error sample size and reliability bins."""

from __future__ import annotations

import math

import pytest
from calibrate.metrics.decision import (
    expected_calibration_error,
    reliability_bins,
    wilson_interval,
    wilson_lower_bound,
    zero_error_sample_size,
)


def test_wilson_matches_a_hand_computed_case() -> None:
    # 8 of 10 at z = 1.96: centre 0.7361, half-width 0.1951 -> [0.4902, 0.9433].
    low, high = wilson_interval(8, 10, z=1.96)
    assert math.isclose(low, 0.4902, abs_tol=5e-4)
    assert math.isclose(high, 0.9433, abs_tol=5e-4)


def test_perfect_small_sample_is_not_a_certificate() -> None:
    # The probe of ADR-0012: 22 correct of 22 accepted has a lower bound of 0.85.
    assert math.isclose(wilson_lower_bound(22, 22), 0.85, abs_tol=0.005)
    assert wilson_lower_bound(10, 10) < 0.75


def test_no_evidence_gives_no_lower_bound() -> None:
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_bounds_stay_in_unit_interval_and_order() -> None:
    for n in (1, 2, 7, 30, 500):
        for k in {0, 1, n // 2, n - 1, n}:
            low, high = wilson_interval(k, n)
            assert 0.0 <= low <= k / n <= high <= 1.0


def test_lower_bound_grows_with_evidence_and_falls_with_errors() -> None:
    assert wilson_lower_bound(30, 30) > wilson_lower_bound(10, 10)
    assert wilson_lower_bound(29, 30) < wilson_lower_bound(30, 30)


def test_invalid_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        wilson_interval(5, 4)
    with pytest.raises(ValueError):
        wilson_interval(-1, 4)


def test_zero_error_sample_sizes_match_the_adr() -> None:
    # ADR-0012, context item 5 and F.1.
    assert zero_error_sample_size(0.95) == 73
    assert zero_error_sample_size(0.90) == 35
    assert wilson_lower_bound(73, 73) >= 0.95 > wilson_lower_bound(72, 72)


def test_no_sample_certifies_a_precision_of_one() -> None:
    with pytest.raises(ValueError, match="p_min"):
        zero_error_sample_size(1.0)


def test_reliability_bins_partition_the_rows_and_agree_with_ece() -> None:
    confidences = [0.05, 0.15, 0.55, 0.65, 0.95, 1.0]
    correct = [False, False, True, False, True, True]
    bins = reliability_bins(correct, confidences, n_bins=10)
    assert sum(b.n for b in bins) == len(confidences)
    assert bins[-1].n == 2  # 0.95 and 1.0 (the last bin is closed)
    ece = sum(
        b.n / len(confidences) * abs(b.accuracy - b.mean_confidence)
        for b in bins
        if b.n
    )
    # expected_calibration_error compares y_true == y_pred, so build them to match.
    y_pred = ["A"] * len(correct)
    y_true = ["A" if c else "B" for c in correct]
    reference = expected_calibration_error(y_true, y_pred, confidences)
    assert math.isclose(ece, reference, abs_tol=1e-9)
