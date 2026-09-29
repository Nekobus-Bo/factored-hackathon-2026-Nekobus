"""tau selection: maximum coverage subject to the constraint on the acted labels."""

from __future__ import annotations

import pytest
from calibrate.thresholds import (
    ScoredRow,
    fit_label_threshold,
    fit_scalar_threshold,
    meets,
    precision_estimate,
    round_tau_down,
)


def row(
    label: str, confidence: float, truth: str | None, lang: str = "es"
) -> ScoredRow:
    return ScoredRow(lang=lang, label=label, confidence=confidence, truth=truth)


def test_round_tau_down_never_rises_above_the_confidence() -> None:
    for confidence in (0.0, 0.1234565, 0.999999999, 1.0, 0.3333333333333333):
        tau = round_tau_down(confidence)
        assert 0.0 <= tau <= confidence
        assert confidence - tau < 2e-6


def test_meets_accepts_nothing_and_rejects_an_imprecise_label() -> None:
    assert meets(0, 0, 0.95, "point")  # no decisions, no wrong decisions
    assert meets(19, 20, 0.95, "point")
    assert not meets(18, 20, 0.95, "point")
    # 19 of 20 is 0.95 by point estimate but its Wilson lower bound is far lower.
    assert not meets(19, 20, 0.95, "wilson95_lower")
    assert precision_estimate(0, 0, "point") is None


def test_scalar_tau_binds_only_the_acted_labels() -> None:
    rows = [
        row("A", 0.95, "A"),
        row("B", 0.92, "A"),  # an error on B, which the engine does not act on
        row("A", 0.90, "A"),
        row("A", 0.85, "A"),
        row("A", 0.60, "B"),  # an error on A, which it does
        row("B", 0.50, "B"),
    ]
    only_a = fit_scalar_threshold(rows, {"A": 0.9}, ci="point", n_min=1)
    assert only_a.tau == pytest.approx(0.85)
    assert only_a.accepted == 4  # the wrong B at 0.92 is accepted: B is unconstrained
    assert only_a.per_label["A"] == (3, 3)

    both = fit_scalar_threshold(rows, {"A": 0.9, "B": 0.9}, ci="point", n_min=1)
    assert both.tau == pytest.approx(0.95)  # the wrong B forces tau above 0.92
    assert both.accepted == 1
    assert only_a.coverage > both.coverage


def test_scalar_tau_is_not_assumed_monotone() -> None:
    # An error sits above two correct rows: the prefix precision dips and recovers.
    rows = [
        row("A", 0.99, "A"),
        row("A", 0.98, "A"),
        row("A", 0.90, "B"),
        row("A", 0.80, "A"),
        row("A", 0.79, "A"),
    ]
    fit = fit_scalar_threshold(rows, {"A": 0.75}, ci="point", n_min=1)
    assert fit.tau == pytest.approx(0.79)  # 4 of 5 = 0.8 beats the 2-of-3 prefix
    assert fit.accepted == 5


def test_scalar_infeasible_says_why() -> None:
    everything_wrong = [row("A", 0.9, "B"), row("A", 0.8, "B")]
    fit = fit_scalar_threshold(everything_wrong, {"A": 0.9}, ci="point", n_min=0)
    assert not fit.feasible
    assert fit.reason and "no threshold" in fit.reason


def test_scalar_does_not_pass_by_never_deciding_an_acted_label() -> None:
    # A is wrong at every confidence; B is right. A tau above every A row would
    # satisfy the constraint vacuously while still accepting B, but the DP would
    # then never do what it is calibrated for.
    rows = [row("A", 0.7, "B"), row("A", 0.6, "B"), row("B", 0.95, "B")]
    fit = fit_scalar_threshold(rows, {"A": 0.9}, ci="point", n_min=0)
    assert not fit.feasible


def test_scalar_needs_n_min_rows_of_every_acted_label() -> None:
    rows = [row("A", 0.9, "A")] * 5 + [row("B", 0.9, "B")] * 2
    fit = fit_scalar_threshold(rows, {"A": 0.9, "B": 0.9}, ci="point", n_min=3)
    assert not fit.feasible
    assert fit.reason and "'B' has 2" in fit.reason


def test_scalar_wilson_selection_is_stricter_than_the_point_estimate() -> None:
    rows = [row("A", 0.9 - i / 100, "A") for i in range(10)]
    point = fit_scalar_threshold(rows, {"A": 0.95}, ci="point", n_min=1)
    wilson = fit_scalar_threshold(rows, {"A": 0.95}, ci="wilson95_lower", n_min=1)
    assert point.feasible
    # Ten perfect rows have a lower bound near 0.72: nothing to accept at 0.95.
    assert wilson.tau is None or wilson.accepted == 0


def test_label_tau_maximizes_accepted_rows_under_the_constraint() -> None:
    rows = [
        row("confirm", 0.97, "confirm"),
        row("confirm", 0.94, "confirm"),
        row("confirm", 0.91, "confirm"),
        row("confirm", 0.70, "other"),  # a false confirm
        row("confirm", 0.65, "confirm"),
        row("other", 0.99, "other"),
    ] + [row("other", 0.9, "confirm")] * 4  # missed confirms: support only
    fit = fit_label_threshold(rows, "confirm", p_min=0.95, ci="point", n_min=5)
    assert fit.tau == pytest.approx(0.91)
    assert (fit.accepted, fit.tp, fit.precision) == (3, 3, 1.0)
    assert fit.support == 8
    assert fit.coverage == pytest.approx(3 / len(rows))


def test_label_tau_is_independent_of_other_labels() -> None:
    noisy = [row("deny", 0.99, "other")] * 5
    quiet: list[ScoredRow] = []
    base = [row("confirm", 0.9, "confirm")] * 6
    a = fit_label_threshold(base + noisy, "confirm", p_min=0.95, ci="point", n_min=1)
    b = fit_label_threshold(base + quiet, "confirm", p_min=0.95, ci="point", n_min=1)
    assert a.tau == b.tau and a.accepted == b.accepted


def test_label_tau_ties_go_to_the_higher_tau() -> None:
    # Two rows share one confidence: there is a single candidate and it is that one.
    rows = [row("A", 0.8, "A"), row("A", 0.8, "A")]
    assert fit_label_threshold(rows, "A", p_min=0.9, ci="point", n_min=1).tau == 0.8


def test_label_tau_infeasible_reports_the_best_reached() -> None:
    rows = [row("A", 0.9, "B"), row("A", 0.8, "A"), row("A", 0.7, "B")]
    fit = fit_label_threshold(rows, "A", p_min=0.95, ci="point", n_min=1)
    assert not fit.feasible
    assert fit.best_estimate == pytest.approx(0.5)
    assert fit.reason and "'A'" in fit.reason and "0.500" in fit.reason


def test_label_tau_needs_support_and_predictions() -> None:
    rows = [row("A", 0.9, "A")] * 3
    short = fit_label_threshold(rows, "A", p_min=0.9, ci="point", n_min=10)
    assert not short.feasible and "n_min is 10" in (short.reason or "")

    never = fit_label_threshold(
        [row("B", 0.9, "A")] * 4, "A", p_min=0.9, ci="point", n_min=1
    )
    assert not never.feasible and "never predicts" in (never.reason or "")


def test_outside_the_view_counts_as_a_wrong_decision() -> None:
    # truth None: the utterance belongs to no label of the view; deciding is an error.
    rows = [row("LOST", 0.9, "LOST"), row("LOST", 0.8, None), row("LOST", 0.7, "LOST")]
    fit = fit_label_threshold(rows, "LOST", p_min=0.9, ci="point", n_min=1)
    assert fit.tau == pytest.approx(0.9)
    assert fit.accepted == 1


def test_a_constraint_that_rejects_nothing_is_reported_as_not_binding() -> None:
    # Every prediction is right at every confidence: tau is only the lowest seen, and
    # validation says nothing about how low a confidence is still safe.
    easy = [row("A", 0.9 - i / 20, "A") for i in range(6)]
    fit = fit_label_threshold(easy, "A", p_min=0.9, ci="point", n_min=1)
    assert fit.feasible and not fit.binding
    assert fit.tau == pytest.approx(easy[-1].confidence, abs=1e-6)

    hard = [*easy, row("A", 0.3, "B")]
    binding = fit_label_threshold(hard, "A", p_min=0.9, ci="point", n_min=1)
    assert binding.feasible and binding.binding
    assert binding.n_predicted == 7 and binding.accepted == 6

    scalar = fit_scalar_threshold(easy, {"A": 0.9}, ci="point", n_min=1)
    assert scalar.feasible and not scalar.binding
    scalar_hard = fit_scalar_threshold(hard, {"A": 0.9}, ci="point", n_min=1)
    assert scalar_hard.binding
