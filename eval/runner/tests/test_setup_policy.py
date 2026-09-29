"""policy_differences: what the admin API has to change before a scenario runs."""

from __future__ import annotations

from evalrunner.systems.evidence import PolicySnapshot
from evalrunner.systems.setup import policy_differences

SEED = {"USD": 50000, "COP": 200000000, "BRL": 250000, "EUR": 50000}


def _policy(mode: str = "flag", **thresholds: int) -> PolicySnapshot:
    return PolicySnapshot(amount_mode=mode, thresholds_minor=thresholds or dict(SEED))


def test_identical_policy_has_no_differences() -> None:
    assert policy_differences(_policy(), _policy()) == []


def test_a_different_mode_or_threshold_is_reported() -> None:
    wanted = PolicySnapshot("block", {**SEED, "USD": 10000})

    diffs = policy_differences(_policy(), wanted)

    assert diffs == [
        "policy mode is 'flag', scenario needs 'block'",
        "policy thresholds differ for ['USD']",
    ]


def test_a_currency_the_scenario_leaves_out_is_a_difference() -> None:
    """An unmapped currency is set up by leaving it out: the PUT replaces the map."""
    wanted = _policy(COP=SEED["COP"], BRL=SEED["BRL"], EUR=SEED["EUR"])

    assert policy_differences(_policy(), wanted) == [
        "policy thresholds differ for ['USD']"
    ]
    assert policy_differences(wanted, wanted) == []


def test_a_scenario_without_a_threshold_map_leaves_the_live_map_alone() -> None:
    wanted = PolicySnapshot(amount_mode="flag", thresholds_minor={})

    assert policy_differences(_policy(), wanted) == []
