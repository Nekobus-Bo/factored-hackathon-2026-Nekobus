"""The calibration artifact (schema, canonical id, loader) and `decide` (pure)."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from encoder.decision_points import (
    ArtifactError,
    DecisionPointsArtifact,
    DecisionPointSpec,
    apply_temperature,
    artifact_json_schema,
    artifact_to_json,
    check_tau_raise,
    compute_artifact_id,
    decide,
    load_artifact,
    parse_artifact,
    parse_tau_raise,
    resolve_threshold,
    seed_backend_and_dp,
    view_labels,
    with_artifact_id,
)

FIXTURE_ARTIFACT = (
    Path(__file__).resolve().parent / "fixtures" / "decision_points.fixture.json"
)
SCHEMA_FILE = (
    Path(__file__).resolve().parents[1] / "calibration" / "decision_points.schema.json"
)


def raw_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_ARTIFACT.read_text(encoding="utf-8"))


def dp(**overrides: Any) -> DecisionPointSpec:
    """A small labels-view DP for `decide`."""
    fields: dict[str, Any] = {
        "backend": "b",
        "view": {"kind": "labels", "labels": ["yes", "no", "other"]},
        "thresholds": {"*": 0.6},
        "status": "calibrated",
    }
    fields.update(overrides)
    return DecisionPointSpec.model_validate(fields)


# --- The committed fixture ---


def test_the_fixture_artifact_loads_and_is_current() -> None:
    artifact = load_artifact(FIXTURE_ARTIFACT)
    assert set(artifact.decision_points) == {
        "turn_intent",
        "confirm_gate",
        "block_reason",
        "smalltalk_route",
        "handoff_route",
    }
    assert artifact.artifact_id == compute_artifact_id(raw_fixture())
    train = Path(artifact.backends["intent_tfidf"].train.path)  # type: ignore[union-attr]
    assert train.is_file(), (
        "regenerate with packages/encoder/tests/fixtures/regenerate.py"
    )


def test_the_schema_file_next_to_the_artifact_is_current() -> None:
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == artifact_json_schema(), (
        "regenerate with: uv run python -m encoder.decision_points "
        "packages/encoder/calibration/decision_points.schema.json"
    )


# --- Canonical id ---


def test_artifact_id_ignores_key_order_whitespace_and_the_id_itself() -> None:
    raw = raw_fixture()
    shuffled = dict(reversed(list(raw.items())))
    assert compute_artifact_id(shuffled) == compute_artifact_id(raw)
    assert compute_artifact_id({**raw, "artifact_id": "0" * 12}) == compute_artifact_id(
        raw
    )
    assert len(compute_artifact_id(raw)) == 12


def test_artifact_id_changes_with_any_content_change() -> None:
    raw = raw_fixture()
    changed = copy.deepcopy(raw)
    changed["decision_points"]["confirm_gate"]["thresholds"]["*"] = 0.51
    assert compute_artifact_id(changed) != compute_artifact_id(raw)


def test_a_hand_edited_artifact_is_refused() -> None:
    raw = raw_fixture()
    raw["decision_points"]["confirm_gate"]["thresholds"]["*"] = (
        0.01  # lower tau by hand
    )
    with pytest.raises(ArtifactError, match="edited by hand"):
        parse_artifact(raw)


def test_writer_round_trips_through_the_loader(tmp_path: Path) -> None:
    artifact = load_artifact(FIXTURE_ARTIFACT)
    out = tmp_path / "decision_points.json"
    out.write_text(artifact_to_json(artifact), encoding="utf-8")
    again = load_artifact(out)
    # The id is over content: dumping the model adds its defaults, so it differs from
    # the hand-written fixture's. Everything else is the same.
    assert again.model_dump(exclude={"artifact_id"}) == artifact.model_dump(
        exclude={"artifact_id"}
    )
    # Deterministic bytes: a second write is identical, so git shows only real changes.
    assert artifact_to_json(again) == out.read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8").endswith("\n")


def test_with_artifact_id_recomputes_after_an_edit() -> None:
    raw = raw_fixture()
    raw["decision_points"]["confirm_gate"]["thresholds"]["*"] = 0.55
    fixed = with_artifact_id(raw)
    assert fixed["artifact_id"] != raw["artifact_id"]
    assert parse_artifact(fixed).decision_points["confirm_gate"].thresholds["*"] == 0.55


# --- Loader failures are loud and name the problem ---


def test_missing_and_malformed_files_name_the_path(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="cannot read"):
        load_artifact(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="broken.json: not valid JSON"):
        load_artifact(broken)
    listy = tmp_path / "list.json"
    listy.write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactError, match="top level must be a JSON object"):
        load_artifact(listy)


def broken(mutate: Any) -> dict[str, Any]:
    raw = raw_fixture()
    mutate(raw)
    return with_artifact_id(raw)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.update(schema_version=2), "schema_version"),
        (lambda r: r.update(surprise=1), "surprise"),
        (
            lambda r: r["decision_points"]["turn_intent"].update(backend="ghost"),
            "unknown backend 'ghost'",
        ),
        (
            lambda r: r["decision_points"].update(
                Bad_Id=r["decision_points"]["turn_intent"]
            ),
            "must match",
        ),
        (
            lambda r: r["backends"]["intent_tfidf"].update(local_only=False),
            "local_only must be true",
        ),
        (
            lambda r: r["decision_points"]["confirm_gate"].update(
                escalate_to="turn_intent"
            ),
            "pending: cascading",
        ),
        (
            lambda r: r["decision_points"]["turn_intent"]["calibrator"].update(
                kind="isotonic"
            ),
            "pending: isotonic calibrator is not implemented (ADR-0012)",
        ),
        (
            lambda r: r["decision_points"]["turn_intent"]["calibrator"]["by_lang"][
                "es"
            ].update(T=0),
            "needs exactly T",
        ),
        (
            lambda r: r["decision_points"]["turn_intent"]["thresholds"].update(es=1.5),
            "within [0, 1]",
        ),
        (
            lambda r: r["decision_points"]["turn_intent"]["thresholds"].update(fra=0.5),
            "language key",
        ),
        (
            lambda r: r["decision_points"]["confirm_gate"]["thresholds"]["es"].update(
                maybe=0.5
            ),
            "not in the view",
        ),
        (
            lambda r: r["backends"]["intent_tfidf"].update(labels=["a", "a"]),
            "without repeats",
        ),
        (
            lambda r: r["backends"]["intent_tfidf"].update(labels=["confirm"]),
            "not in its backend",
        ),
        (
            lambda r: r["decision_points"]["block_reason"]["view"]["groups"].update(
                STOLEN=["report_lost_card"]
            ),
            "more than one group",
        ),
    ],
)
def test_invalid_artifacts_fail_with_a_specific_message(
    mutate: Any, message: str
) -> None:
    with pytest.raises(ArtifactError, match=re.escape(message)):
        parse_artifact(broken(mutate), "fixture")


def top1_only_raw(**backend_changes: Any) -> dict[str, Any]:
    """The fixture reduced to `turn_intent` on a top1_only backend (GLiNER-like)."""
    raw = raw_fixture()
    labels = raw["decision_points"]["turn_intent"]["view"]["labels"]
    raw["backends"]["intent_tfidf"].update(
        {"probability_kind": "top1_only", "labels": labels, **backend_changes}
    )
    raw["decision_points"] = {"turn_intent": raw["decision_points"]["turn_intent"]}
    raw["decision_points"]["turn_intent"]["calibrator"] = {"kind": "none"}
    del raw["backends"]["gate_tfidf"]
    return raw


def test_a_top1_only_backend_serves_a_plain_threshold_on_its_own_labels() -> None:
    assert parse_artifact(with_artifact_id(top1_only_raw()))

    with pytest.raises(ArtifactError, match="must declare its labels"):
        parse_artifact(with_artifact_id(top1_only_raw(labels=None)))
    with pytest.raises(ArtifactError, match="serves its own labels"):
        parse_artifact(with_artifact_id(top1_only_raw(labels=["confirm", "deny"])))

    calibrated = top1_only_raw()
    calibrated["decision_points"]["turn_intent"]["calibrator"] = {
        "kind": "temperature",
        "by_lang": {"es": {"T": 0.5}},
    }
    with pytest.raises(ArtifactError, match="cannot be calibrated"):
        parse_artifact(with_artifact_id(calibrated))

    grouped = top1_only_raw()
    grouped["decision_points"]["turn_intent"]["view"] = {
        "kind": "groups",
        "groups": {"a": ["confirm"]},
    }
    with pytest.raises(ArtifactError, match="needs a labels view"):
        parse_artifact(with_artifact_id(grouped))


# --- apply_temperature ---


def test_temperature_sharpens_below_one_and_flattens_above() -> None:
    p = {"a": 0.6, "b": 0.3, "c": 0.1}
    sharp = apply_temperature(p, 0.5)
    assert sum(sharp.values()) == pytest.approx(1.0)
    assert sharp["a"] > p["a"] > sharp["c"]
    flat = apply_temperature(p, 4.0)
    assert flat["a"] < p["a"]
    assert apply_temperature(p, 1.0) == pytest.approx(p)
    # p ** (1/T), renormalized: 0.36 / (0.36 + 0.09 + 0.01)
    assert sharp["a"] == pytest.approx(0.36 / 0.46)


def test_temperature_survives_zero_probabilities() -> None:
    out = apply_temperature({"a": 1.0, "b": 0.0}, 0.2)
    assert out["a"] == pytest.approx(1.0)
    assert all(math.isfinite(v) for v in out.values())


# --- decide: outcomes ---


def test_decided_when_confidence_reaches_tau() -> None:
    result = decide("d", dp(), probabilities={"yes": 0.7, "no": 0.2, "other": 0.1})
    assert result.outcome == "decided"
    assert (result.label, result.tau, result.tau_source) == ("yes", 0.6, "artifact")
    assert result.confidence == pytest.approx(0.7)
    assert result.runner_up == ("no", pytest.approx(0.2))


def test_tau_is_inclusive() -> None:
    at_tau = decide("d", dp(), probabilities={"yes": 0.6, "no": 0.3, "other": 0.1})
    assert at_tau.outcome == "decided"  # same rule as the legacy `confidence < tau`


def test_abstained_below_tau_keeps_the_top_label_out() -> None:
    result = decide("d", dp(), probabilities={"yes": 0.5, "no": 0.4, "other": 0.1})
    assert result.outcome == "abstained"
    assert result.label is None
    assert result.tau == 0.6


def test_ties_resolve_in_view_order() -> None:
    result = decide(
        "d",
        dp(thresholds={"*": 0.4}),
        probabilities={"yes": 0.45, "no": 0.45, "other": 0.1},
    )
    assert result.label == "yes"


def test_disabled_and_infeasible_never_compute() -> None:
    assert decide("d", dp(enabled=False), probabilities={}).outcome == "off"
    assert (
        decide("d", dp(status="infeasible"), probabilities={}).outcome == "infeasible"
    )


def test_a_backend_that_breaks_its_contract_raises() -> None:
    with pytest.raises(ValueError, match="sum to"):
        decide("d", dp(), probabilities={"yes": 0.9, "no": 0.9, "other": 0.1})
    with pytest.raises(ValueError, match="omitted labels"):
        decide("d", dp(), probabilities={"yes": 0.9, "no": 0.1})
    with pytest.raises(ValueError, match="non-finite"):
        decide("d", dp(), probabilities={"yes": float("nan"), "no": 0.1, "other": 0.1})
    with pytest.raises(ValueError, match="must supply probabilities"):
        decide("d", dp())


# --- decide: thresholds per language ---


def test_threshold_lookup_prefers_the_language_then_the_star() -> None:
    spec = dp(thresholds={"es": 0.9, "*": 0.5})
    assert resolve_threshold("d", spec, "es", "yes") == (0.9, "artifact")
    assert resolve_threshold("d", spec, "pt", "yes") == (0.5, "artifact")
    assert resolve_threshold("d", spec, None, "yes") == (0.5, "artifact")


def test_null_is_infeasible_and_does_not_fall_back_to_star() -> None:
    spec = dp(thresholds={"en": None, "*": 0.5})
    assert resolve_threshold("d", spec, "en", "yes") == (None, None)
    result = decide(
        "d", spec, probabilities={"yes": 0.99, "no": 0.005, "other": 0.005}, lang="en"
    )
    assert result.outcome == "abstained" and result.tau is None


def test_no_threshold_at_all_abstains() -> None:
    spec = dp(thresholds={"es": 0.5})
    assert resolve_threshold("d", spec, "pt", "yes") == (None, None)
    assert resolve_threshold("d", spec, None, "yes") == (None, None)


def test_per_label_thresholds_and_the_label_default() -> None:
    spec = dp(thresholds={"es": {"yes": 0.9, "no": 0.5, "*": 0.7}})
    assert resolve_threshold("d", spec, "es", "yes")[0] == 0.9
    assert resolve_threshold("d", spec, "es", "no")[0] == 0.5
    assert resolve_threshold("d", spec, "es", "other")[0] == 0.7
    no_default = dp(thresholds={"es": {"yes": 0.9}})
    assert resolve_threshold("d", no_default, "es", "no") == (None, None)
    nulled = dp(thresholds={"es": {"yes": None, "*": 0.5}})
    assert resolve_threshold("d", nulled, "es", "yes") == (None, None)


def test_the_gate_needs_the_higher_bar_for_confirm() -> None:
    spec = dp(thresholds={"es": {"yes": 0.9, "no": 0.5, "other": 0.5}})
    probs = {"yes": 0.8, "no": 0.15, "other": 0.05}
    assert decide("d", spec, probabilities=probs, lang="es").outcome == "abstained"
    assert (
        decide(
            "d", spec, probabilities={"yes": 0.1, "no": 0.8, "other": 0.1}, lang="es"
        ).label
        == "no"
    )


def test_a_seed_status_reports_the_seed_source() -> None:
    spec = dp(status="uncalibrated_seed")
    assert resolve_threshold("d", spec, "es", "yes") == (0.6, "seed")


# --- decide: calibration ---


def test_temperature_calibration_is_applied_before_the_threshold() -> None:
    spec = dp(
        calibrator={"kind": "temperature", "by_lang": {"es": {"T": 0.5}}},
        thresholds={"*": 0.6},
    )
    probs = {"yes": 0.5, "no": 0.3, "other": 0.2}
    raw_only = decide("d", dp(), probabilities=probs, lang="es")
    assert raw_only.outcome == "abstained"  # 0.5 < 0.6 uncalibrated
    calibrated = decide("d", spec, probabilities=probs, lang="es")
    assert calibrated.outcome == "decided"  # sharpened to 0.25 / 0.38 = 0.657
    assert calibrated.confidence == pytest.approx(0.25 / 0.38)
    assert calibrated.raw_confidence == pytest.approx(0.5)


def test_a_language_without_calibrator_params_abstains() -> None:
    spec = dp(calibrator={"kind": "temperature", "by_lang": {"es": {"T": 0.5}}})
    result = decide(
        "d", spec, probabilities={"yes": 0.99, "no": 0.005, "other": 0.005}, lang="pt"
    )
    assert result.outcome == "abstained"
    assert (
        result.tau is None
    )  # its tau lives in a space this text was not calibrated in
    with_star = dp(calibrator={"kind": "temperature", "by_lang": {"*": {"T": 0.5}}})
    assert (
        decide(
            "d",
            with_star,
            probabilities={"yes": 0.99, "no": 0.005, "other": 0.005},
            lang="pt",
        ).outcome
        == "decided"
    )


# --- decide: views ---


GROUPS = {
    "kind": "groups",
    "groups": {"LOST": ["lost"], "STOLEN": ["stolen", "robbed"], "REQ": ["block"]},
}


def test_a_group_confidence_is_the_sum_of_its_members() -> None:
    spec = dp(view=GROUPS, thresholds={"*": 0.5})
    probs = {"lost": 0.2, "stolen": 0.3, "robbed": 0.3, "block": 0.1, "greeting": 0.1}
    result = decide("d", spec, probabilities=probs)
    assert result.outcome == "decided" and result.label == "STOLEN"
    assert result.confidence == pytest.approx(0.6)
    assert result.runner_up == ("LOST", pytest.approx(0.2))


def test_mass_outside_a_group_view_is_not_renormalized_away() -> None:
    """'yes' is not a block reason: the DP must abstain, not pick the least bad."""
    spec = dp(view=GROUPS, thresholds={"*": 0.5})
    probs = {
        "lost": 0.02,
        "stolen": 0.02,
        "robbed": 0.01,
        "block": 0.05,
        "confirm": 0.9,
    }
    result = decide("d", spec, probabilities=probs)
    assert result.outcome == "abstained"
    assert result.confidence == pytest.approx(0.05)


def test_the_calibrator_applies_to_the_whole_distribution_before_the_view() -> None:
    spec = dp(
        view=GROUPS,
        calibrator={"kind": "temperature", "by_lang": {"*": {"T": 0.5}}},
        thresholds={"*": 0.5},
    )
    probs = {"lost": 0.1, "stolen": 0.2, "robbed": 0.2, "block": 0.1, "confirm": 0.4}
    cal = apply_temperature(probs, 0.5)  # the whole distribution, "confirm" included
    expected = {
        "LOST": cal["lost"],
        "STOLEN": cal["stolen"] + cal["robbed"],
        "REQ": cal["block"],
    }
    result = decide("d", spec, probabilities=probs)
    assert result.label in (None, max(expected, key=expected.__getitem__))
    assert result.confidence == pytest.approx(max(expected.values()))
    # Aggregating first and calibrating after would give a different number.
    assert result.confidence != pytest.approx(
        apply_temperature({"LOST": 0.1, "STOLEN": 0.4, "REQ": 0.1}, 0.5)["STOLEN"]
    )


def test_view_labels_for_both_kinds() -> None:
    assert view_labels(dp()) == ["yes", "no", "other"]
    assert view_labels(dp(view=GROUPS)) == ["LOST", "STOLEN", "REQ"]


# --- decide: top1_only backends ---


def test_a_top1_only_backend_supports_only_a_threshold_on_its_top_confidence() -> None:
    spec = dp(view={"kind": "labels", "labels": ["a", "b"]}, thresholds={"*": 0.5})
    high = decide("d", spec, top1=("a", 0.8), probability_kind="top1_only")
    assert (high.outcome, high.label, high.confidence) == ("decided", "a", 0.8)
    assert high.runner_up is None
    low = decide("d", spec, top1=("b", 0.4), probability_kind="top1_only")
    assert low.outcome == "abstained"
    with pytest.raises(ValueError, match="outside the decision point's labels"):
        decide("d", spec, top1=("zzz", 0.9), probability_kind="top1_only")
    with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
        decide("d", spec, top1=("a", 1.4), probability_kind="top1_only")


# --- Raise-only override ---


def test_tau_raise_parses_and_validates() -> None:
    assert parse_tau_raise(None) == {}
    assert parse_tau_raise(" confirm_gate.es=0.97 , turn_intent.*=0.5 ") == {
        ("confirm_gate", "es"): 0.97,
        ("turn_intent", "*"): 0.5,
    }
    for bad in (
        "confirm_gate=0.9",
        "Confirm.es=0.9",
        "confirm_gate.es=high",
        "a_b.es=1.5",
    ):
        with pytest.raises(ArtifactError, match="DECISION_POINTS_TAU_RAISE"):
            parse_tau_raise(bad)


def test_an_override_raises_tau_and_reports_its_source() -> None:
    spec = dp(thresholds={"es": 0.6})
    raised = resolve_threshold("d", spec, "es", "yes", {("d", "es"): 0.95})
    assert raised == (0.95, "override")
    star = resolve_threshold("d", spec, "es", "yes", {("d", "*"): 0.8})
    assert star == (0.8, "override")
    other_lang = resolve_threshold("d", spec, "es", "yes", {("d", "pt"): 0.99})
    assert other_lang == (0.6, "artifact")


def test_an_override_never_lowers_or_creates_a_tau() -> None:
    spec = dp(thresholds={"es": 0.6, "pt": None})
    assert resolve_threshold("d", spec, "es", "yes", {("d", "es"): 0.2}) == (
        0.6,
        "artifact",
    )
    assert resolve_threshold("d", spec, "pt", "yes", {("d", "pt"): 0.99}) == (
        None,
        None,
    )


def test_an_override_can_turn_a_decision_into_an_abstention() -> None:
    spec = dp(thresholds={"es": 0.6})
    probs = {"yes": 0.8, "no": 0.1, "other": 0.1}
    assert decide("d", spec, probabilities=probs, lang="es").outcome == "decided"
    strict = decide(
        "d", spec, probabilities=probs, lang="es", raises={("d", "es"): 0.95}
    )
    assert strict.outcome == "abstained" and strict.tau_source == "override"


def test_check_tau_raise_refuses_what_is_not_a_raise() -> None:
    specs = {"d": dp(thresholds={"es": 0.6, "pt": None, "en": {"yes": 0.7, "no": 0.5}})}
    check_tau_raise(specs, {("d", "es"): 0.9})
    check_tau_raise(specs, {("d", "en"): 0.6})  # raises 'no' from 0.5
    with pytest.raises(ArtifactError, match="unknown decision point 'x'"):
        check_tau_raise(specs, {("x", "es"): 0.9})
    with pytest.raises(ArtifactError, match="raises no 'd' threshold"):
        check_tau_raise(specs, {("d", "es"): 0.3})  # a lowering is not allowed
    with pytest.raises(ArtifactError, match="raises no 'd' threshold"):
        check_tau_raise(specs, {("d", "pt"): 0.99})  # infeasible stays infeasible
    with pytest.raises(ArtifactError, match="no 'fr' tau to raise"):
        check_tau_raise(specs, {("d", "fr"): 0.99})


# --- Seed ---


def test_the_seed_dp_is_a_plain_threshold_on_the_legacy_top_label() -> None:
    backend, seed = seed_backend_and_dp(0.37, ["a", "b"], "tfidf_lr@train-sha256:abc")
    assert backend.probability_kind == "top1_only" and backend.local_only
    assert seed.status == "uncalibrated_seed" and seed.thresholds == {"*": 0.37}
    high = decide("turn_intent", seed, top1=("a", 0.37), probability_kind="top1_only")
    assert (high.outcome, high.tau, high.tau_source) == ("decided", 0.37, "seed")
    low = decide("turn_intent", seed, top1=("a", 0.369), probability_kind="top1_only")
    assert low.outcome == "abstained"


def test_artifact_model_is_strict_about_unknown_top_level_fields() -> None:
    assert "artifact_id" in DecisionPointsArtifact.model_fields
