"""End to end: calibrate decision points on a tiny synthetic repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from calibrate.artifact import fragment_of, fragment_text
from calibrate.dp import (
    OUTSIDE,
    Outcome,
    RunError,
    choose,
    macro_f1_over,
    rank_key,
    run_decision_points_calibration,
    split_metrics,
    view_truth,
)
from calibrate.dpconfig import load_run_config
from calibrate.verify import verify
from encoder import registry
from encoder.decision_points import (
    BackendSpec,
    DecisionPointSpec,
    decide,
    load_artifact,
)

DAY = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
NEXT_DAY = datetime(2026, 9, 30, 9, 30, tzinfo=UTC)


def run(repo, out, **kwargs):
    return run_decision_points_calibration(
        repo.config, out, repo_root=repo.root, now=kwargs.pop("now", DAY), **kwargs
    )


def test_a_dev_run_writes_a_report_and_a_loadable_artifact(tiny_repo, tmp_path) -> None:
    out = tmp_path / "scratch"
    result = run(tiny_repo, out)

    assert not result.official
    assert result.artifact_path == out / "decision_points.json"
    artifact = load_artifact(result.artifact_path)  # the encoder's own loader
    assert artifact.artifact_id == result.artifact_id
    assert set(artifact.decision_points) == {"intent", "gate", "reason"}
    # One backend per model: the intent model is shared by two decision points.
    assert set(artifact.backends) == {"intent_tfidf", "gate_tfidf"}
    assert artifact.data and artifact.data.test_provenance == "synthetic-provisional"
    assert (
        not tiny_repo.committed.exists()
    )  # a dev run never touches the committed file

    report = result.report_path.read_text(encoding="utf-8")
    assert result.report_path.name == "calibration-decision-points-2026-09-29.md"
    assert result.run_id in report
    assert "Decision Points Calibration Report" in report
    assert "provisional synthetic (not human)" in report
    for dp_id in artifact.decision_points:
        assert f"## `{dp_id}`" in report


def test_the_report_embeds_each_fragment_verbatim_and_verify_agrees(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch")
    raw = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    report = result.report_path.read_text(encoding="utf-8")
    for dp_id in raw["decision_points"]:
        assert fragment_text(fragment_of(raw, dp_id)) in report

    findings = verify(result.artifact_path, repo_root=tiny_repo.root)
    assert findings.ok, findings.errors
    assert all(
        raw["decision_points"][d]["evidence"]["run_id"] == result.run_id
        for d in raw["decision_points"]
    )


def test_the_run_is_deterministic(tiny_repo, tmp_path) -> None:
    out = tmp_path / "scratch"
    first = run(tiny_repo, out)
    written = first.artifact_path.read_bytes()
    second = run(tiny_repo, out)  # replaces every DP with what it just wrote
    assert first.run_id == second.run_id
    assert first.artifact_id == second.artifact_id
    assert second.artifact_path.read_bytes() == written


def test_tau_is_chosen_on_validation_and_never_on_test(tiny_repo, tmp_path) -> None:
    before = run(tiny_repo, tmp_path / "a")
    test_file = tiny_repo.root / "data/test.jsonl"
    rows = [json.loads(line) for line in test_file.read_text().splitlines()]
    for row in rows:  # destroy the test labels
        row["intent"] = "greeting" if row["intent"] != "greeting" else "lost"
    test_file.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    after = run(tiny_repo, tmp_path / "b")

    a = json.loads(before.artifact_path.read_text())["decision_points"]
    b = json.loads(after.artifact_path.read_text())["decision_points"]
    for dp_id in a:
        assert a[dp_id]["thresholds"] == b[dp_id]["thresholds"]
        assert a[dp_id]["calibrator"] == b[dp_id]["calibrator"]
    assert a["gate"]["evidence"]["per_lang"] != b["gate"]["evidence"]["per_lang"]
    assert before.run_id != after.run_id  # the evidence moved


def test_the_constraint_holds_on_validation_for_every_acted_label(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch")
    checked = 0
    for dp_result in result.dps:
        dp = dp_result.dp
        # A pooled tau is fitted on all languages together, so that is where it holds.
        scopes = ["all"] if dp.scope == "per_label_pooled" else ["es", "pt", "en"]
        for scope in scopes:
            metrics = dp_result.chosen.val[scope]
            for label, floor in dp.constraint.p_min.items():
                m = metrics.labels[label]
                if m.accepted:
                    checked += 1
                    assert m.tp / m.accepted >= floor, (dp.dp_id, scope, label)
    assert checked >= 10  # it is not vacuous


def test_the_artifact_serves_the_numbers_the_report_states(tiny_repo, tmp_path) -> None:
    """Rebuild the backends from the artifact, as the service does, and decide the
    test rows with the service's ``decide``: the counts must equal the evidence."""
    result = run(tiny_repo, tmp_path / "scratch")
    artifact = load_artifact(result.artifact_path)
    test_rows = [
        json.loads(line)
        for line in (tiny_repo.root / "data/test.jsonl").read_text().splitlines()
    ]
    gate = artifact.decision_points["gate"]
    adapter = registry.build(artifact.backends[gate.backend])
    label_map = artifact.backends[gate.backend].train.label_map
    for lang in ("es", "pt", "en"):
        rows = [r for r in test_rows if r["lang"] == lang]
        predictions = adapter.predict([r["text"] for r in rows])
        decisions = [
            decide("gate", gate, probabilities=p.probabilities, lang=lang)
            for p in predictions
        ]
        evidence = gate.evidence["per_lang"][lang]["precision_test"]
        for label in ("confirm", "deny"):
            decided = [
                (d, r) for d, r in zip(decisions, rows, strict=True) if d.label == label
            ]
            tp = sum(
                1
                for _, r in decided
                if registry.relabel(r["intent"], label_map) == label
            )
            assert [tp, len(decided)] == evidence[label][:2], (lang, label)


def test_the_official_run_merges_and_a_partial_run_keeps_the_others(
    tiny_repo,
) -> None:
    reports = tiny_repo.root / "reports"
    full = run(tiny_repo, reports)
    assert full.official and full.artifact_path == tiny_repo.committed
    assert full.report_path.name == "calibration-decision-points-2026-09-29.md"
    committed_before = json.loads(tiny_repo.committed.read_text())

    partial = run(tiny_repo, reports, dp_ids=["gate"], now=NEXT_DAY)
    assert partial.report_path.name == "calibration-decision-points-2026-09-30-gate.md"
    assert full.report_path.exists()  # the earlier report still backs the other DPs
    after = json.loads(tiny_repo.committed.read_text())

    assert (
        after["decision_points"]["intent"]
        == committed_before["decision_points"]["intent"]
    )
    assert (
        after["decision_points"]["reason"]
        == committed_before["decision_points"]["reason"]
    )
    assert after["decision_points"]["gate"]["evidence"]["run_id"] == partial.run_id
    assert after["decision_points"]["gate"]["evidence"]["report"] == (
        "reports/calibration-decision-points-2026-09-30-gate.md"
    )
    assert after["decision_points"]["intent"]["evidence"]["run_id"] == full.run_id
    assert after["artifact_id"] != committed_before["artifact_id"]
    assert after["created_at"] == "2026-09-30T09:30:00Z"

    findings = verify(tiny_repo.committed, repo_root=tiny_repo.root)
    assert findings.ok, findings.errors
    # The partial report shows what changed for the DP it recalibrated.
    assert "Diff against the previous artifact" in partial.report_path.read_text()


def test_a_dev_run_starts_from_the_committed_artifact_without_changing_it(
    tiny_repo, tmp_path
) -> None:
    run(tiny_repo, tiny_repo.root / "reports")
    committed_bytes = tiny_repo.committed.read_bytes()

    dev = run(tiny_repo, tmp_path / "scratch", dp_ids=["reason"], now=NEXT_DAY)
    assert tiny_repo.committed.read_bytes() == committed_bytes
    merged = json.loads(dev.artifact_path.read_text())
    assert set(merged["decision_points"]) == {"intent", "gate", "reason"}
    committed = json.loads(committed_bytes)
    assert merged["decision_points"]["gate"] == committed["decision_points"]["gate"]


def test_an_explicit_artifact_path_wins(tiny_repo, tmp_path) -> None:
    target = tmp_path / "elsewhere.json"
    result = run(tiny_repo, tmp_path / "scratch", artifact_path=target)
    assert result.artifact_path == target and target.is_file()
    assert not (tmp_path / "scratch/decision_points.json").exists()


def test_a_retrained_backend_cannot_strand_a_decision_point_not_in_the_run(
    tiny_repo,
) -> None:
    reports = tiny_repo.root / "reports"
    run(tiny_repo, reports)
    train = tiny_repo.root / "data/train.jsonl"
    train.write_text(
        train.read_text()
        + json.dumps(
            {
                "id": "extra",
                "text": "hello there",
                "lang": "en",
                "intent": "greeting",
                "slots": [],
                "split": "train",
                "source": "synthetic",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # 'intent' and 'reason' share intent_tfidf; recalibrating one leaves the other
    # fitted on a model that no longer exists.
    with pytest.raises(RunError, match=r"still use it.*same run"):
        run(tiny_repo, reports, dp_ids=["intent"], now=NEXT_DAY)
    run(tiny_repo, reports, now=NEXT_DAY)  # all together is fine
    assert verify(tiny_repo.committed, repo_root=tiny_repo.root).ok


def test_a_committed_artifact_edited_by_hand_blocks_the_merge(tiny_repo) -> None:
    reports = tiny_repo.root / "reports"
    run(tiny_repo, reports)
    raw = json.loads(tiny_repo.committed.read_text())
    raw["decision_points"]["gate"]["thresholds"]["es"]["confirm"] = 0.01
    tiny_repo.committed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RunError, match="edited by hand"):
        run(tiny_repo, reports, dp_ids=["gate"], now=NEXT_DAY)


def test_a_language_without_enough_rows_has_no_calibrator_and_abstains(
    tiny_repo, tmp_path
) -> None:
    tiny_repo.write_config(
        tiny_repo.config.read_text().replace(
            "calibrator_min_rows: 20", "calibrator_min_rows: 500"
        )
    )
    result = run(tiny_repo, tmp_path / "scratch")
    entry = json.loads(result.artifact_path.read_text())["decision_points"]["gate"]
    assert entry["calibrator"]["by_lang"] == {}
    assert entry["thresholds"] == {"es": None, "pt": None, "en": None}
    assert entry["status"] == "infeasible"  # it decides nowhere: the artifact says so
    report = result.report_path.read_text()
    assert "calibrator_min_rows is 500" in report
    assert verify(result.artifact_path, repo_root=tiny_repo.root).ok


def test_a_constraint_nothing_can_meet_makes_the_language_infeasible(
    tiny_repo, tmp_path
) -> None:
    # Wilson selection with 12 rows per label cannot reach 0.99: null everywhere.
    text = tiny_repo.config.read_text().replace(
        "p_min: {confirm: 0.9, deny: 0.8}\n      ci: point",
        "p_min: {confirm: 0.99, deny: 0.99}\n      ci: wilson95_lower",
    )
    tiny_repo.write_config(text)
    result = run(tiny_repo, tmp_path / "scratch", dp_ids=["gate"])
    entry = json.loads(result.artifact_path.read_text())["decision_points"]["gate"]
    assert entry["status"] == "infeasible"
    assert all(v is None for v in entry["thresholds"].values())
    report = result.report_path.read_text()
    assert "no threshold reaches wilson95_lower precision 0.99" in report
    # The artifact still loads, and the DP never decides.
    spec = load_artifact(result.artifact_path).decision_points["gate"]
    assert (
        decide(
            "gate",
            spec,
            probabilities={"confirm": 1.0, "deny": 0.0, "other": 0.0},
            lang="es",
        ).outcome
        == "infeasible"
    )


def test_pooled_scope_shares_a_tau_across_languages_short_of_n_min(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch", dp_ids=["reason"])
    thresholds = json.loads(result.artifact_path.read_text())["decision_points"][
        "reason"
    ]["thresholds"]
    # 12 rows per label and language is under n_min 30: every language is pooled.
    assert thresholds["es"] == thresholds["pt"] == thresholds["en"] == thresholds["*"]
    pooled = result.dps[0].chosen
    assert set(pooled.tau_scopes["es"].values()) <= {"pooled", None}
    assert all(c.scope.startswith("pooled") for c in pooled.certifications)


def test_a_small_test_set_certifies_nothing_and_says_what_it_needs(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch")
    raw = json.loads(result.artifact_path.read_text())
    assert all(not e["evidence"]["certified"] for e in raw["decision_points"].values())
    report = result.report_path.read_text()
    assert (
        "73 decided with zero errors" in report
        or "35 decided with zero errors" in report
    )
    assert "not ready for enforce" in report


def test_fixture_data_is_refused_for_reports(monkeypatch, tmp_path) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(root)  # data paths in a config are relative to the repo root
    config = tmp_path / "fixture-config.yaml"
    config.write_text(
        """
task: decision-points
data:
  train: tools/calibrate/fixtures/decision.jsonl
  validation: tools/calibrate/fixtures/decision.jsonl
  test: tools/calibrate/fixtures/decision.jsonl
decision_points:
  dp_one:
    candidates: [{name: t, kind: tfidf_lr}]
    view: {kind: labels, labels: [a, b]}
    constraint: {p_min: 0.9}
""",
        encoding="utf-8",
    )
    before = sorted(p.name for p in (root / "reports").iterdir())
    with pytest.raises(ValueError, match="Refusing to write fixture"):
        run_decision_points_calibration(config, root / "reports")
    assert sorted(p.name for p in (root / "reports").iterdir()) == before


def test_unknown_decision_point_and_bad_config_are_run_errors(
    tiny_repo, tmp_path
) -> None:
    with pytest.raises(RunError, match="unknown decision point"):
        run(tiny_repo, tmp_path / "x", dp_ids=["nope"])
    tiny_repo.write_config("task: decision\n")
    with pytest.raises(RunError, match="task must be 'decision-points'"):
        run(tiny_repo, tmp_path / "x")


def test_missing_train_data_says_where_to_run_from(tiny_repo, tmp_path) -> None:
    (tiny_repo.root / "data/train.jsonl").unlink()
    with pytest.raises(RunError, match="run from the repository root"):
        run(tiny_repo, tmp_path / "x")


def test_source_of_test_rows_must_be_a_known_provenance(tiny_repo, tmp_path) -> None:
    test_file = tiny_repo.root / "data/test.jsonl"
    test_file.write_text(
        test_file.read_text().replace("synthetic-provisional", "vibes")
    )
    with pytest.raises(RunError, match="test rows have sources"):
        run(tiny_repo, tmp_path / "x")


def test_a_top1_only_candidate_is_thresholded_without_a_calibrator(
    tiny_repo, tmp_path, monkeypatch
) -> None:
    from encoder.base import DecisionAdapter
    from encoder.models import DecisionPrediction

    class Top1(DecisionAdapter):
        kind = "fake_top1"
        probability_kind = "top1_only"

        def __init__(self, spec: BackendSpec) -> None:
            self.name = spec.model_id

        def fit(self, *a, **k) -> None: ...
        def save(self, path) -> None: ...
        def load(self, path) -> None: ...

        def predict(self, texts, candidate_intents=None, candidate_slots=None):
            out = []
            for text in texts:
                top = "confirm" if "yes" in text or "si" in text else "other"
                out.append(
                    DecisionPrediction(
                        intent=top,
                        confidence=min(0.99, 0.5 + len(text) / 40),
                        probabilities={top: 0.9},
                    )
                )
            return out

    monkeypatch.setitem(registry._LOADERS, "fake_top1", lambda: Top1)
    tiny_repo.write_config(
        """
task: decision-points
languages: [es, pt, en]
data:
  train: data/train.jsonl
  validation: data/validation.jsonl
  test: data/test.jsonl
decision_points:
  yes_no:
    candidates:
      - name: zero_shot
        kind: fake_top1
        model_id: "fake@1"
        probability_kind: top1_only
    label_map: {confirm: confirm, "*": other}
    view: {kind: labels, labels: [confirm, other]}
    calibrator: none
    threshold_scope: per_language
    constraint: {labels: [confirm], p_min: 0.5, ci: point, n_min: 10}
"""
    )
    result = run(tiny_repo, tmp_path / "scratch")
    artifact = load_artifact(result.artifact_path)  # top1_only rules hold
    spec = artifact.decision_points["yes_no"]
    assert spec.calibrator.kind == "none"
    assert artifact.backends["zero_shot"].probability_kind == "top1_only"
    assert artifact.backends["zero_shot"].labels == ["confirm", "other"]
    assert isinstance(spec.thresholds["es"], float)


# --- Pure helpers ---


def test_view_truth_maps_intents_through_the_label_map_and_groups(tiny_repo) -> None:
    config = load_run_config(tiny_repo.config)
    assert view_truth(config.dps["gate"], "confirm") == "confirm"
    assert view_truth(config.dps["gate"], "stolen") == "other"
    assert view_truth(config.dps["reason"], "lost") == "LOST"
    assert view_truth(config.dps["reason"], "greeting") == OUTSIDE
    assert view_truth(config.dps["intent"], "lost") == "lost"


def outcome(truth, top, confidence, decided=None, lang="es") -> Outcome:
    return Outcome(lang, truth, top, confidence, top, confidence, decided)


def test_split_metrics_counts_decisions_precision_and_confusion() -> None:
    rows = [
        outcome("a", "a", 0.9, "a"),
        outcome("a", "a", 0.8, "a"),
        outcome("b", "a", 0.7, "a"),  # a wrong decision on a
        outcome("a", "b", 0.4),  # abstained
        outcome(OUTSIDE, "a", 0.6, "a"),  # a decision on an utterance outside the view
    ]
    metrics = split_metrics(rows, ["a", "b"], {"a": 0.9})
    a = metrics.labels["a"]
    assert (a.support, a.accepted, a.tp) == (3, 4, 2)
    assert a.precision == pytest.approx(0.5)
    assert a.recall == pytest.approx(2 / 3)
    assert metrics.decided == 4 and metrics.acted_decided == 4
    assert metrics.coverage == pytest.approx(0.8)
    assert metrics.confusion["a"] == {"a": 2, "(abstained)": 1}
    assert metrics.confusion[OUTSIDE] == {"a": 1}
    assert 0.0 <= metrics.ece_post <= 1.0


def test_macro_f1_over_ignores_labels_absent_from_the_truth() -> None:
    truth, pred = ["a", "a", "b"], ["a", "b", "b"]
    # a: P 1, R 0.5 -> 2/3; b: P 0.5, R 1 -> 2/3.
    assert macro_f1_over(["a", "b", "c"], truth, pred) == pytest.approx(2 / 3)


def test_candidates_rank_by_feasibility_certification_coverage_then_cost() -> None:
    def fake(status, certified, coverage, p95, ram):
        return SimpleNamespace(
            status=status,
            certified_scopes=certified,
            test={"all": SimpleNamespace(acted_coverage=coverage)},
            backend=SimpleNamespace(
                bench=SimpleNamespace(p95_latency_ms=p95), ram_mb=ram
            ),
            candidate=SimpleNamespace(name=f"{status}-{certified}-{coverage}"),
        )

    infeasible = fake("infeasible", 0, 0.9, 1, 1)
    plain = fake("calibrated", 0, 0.5, 5, 50)
    certified = fake("calibrated", 2, 0.2, 5, 50)
    broader = fake("calibrated", 2, 0.4, 5, 50)
    faster = fake("calibrated", 2, 0.4, 1, 50)
    lighter = fake("calibrated", 2, 0.4, 1, 10)
    ranked = sorted(
        [infeasible, plain, certified, broader, faster, lighter],
        key=rank_key,
        reverse=True,
    )
    assert ranked == [lighter, faster, broader, certified, plain, infeasible]

    best, why = choose([plain, certified])
    assert best is certified and "Wilson-certified" in why
    only, reason = choose([plain])
    assert only is plain and "only candidate" in reason
    none, reason = choose([infeasible, fake("infeasible", 0, 0.1, 1, 1)])
    assert "infeasible" in reason


def test_decide_on_the_written_spec_matches_the_pydantic_round_trip(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch")
    raw = json.loads(result.artifact_path.read_text())
    spec = DecisionPointSpec.model_validate(raw["decision_points"]["intent"])
    decision = decide(
        "intent",
        spec,
        probabilities={
            "confirm": 0.0,
            "deny": 0.0,
            "lost": 1.0,
            "stolen": 0.0,
            "greeting": 0.0,
        },
        lang="es",
    )
    assert decision.outcome in {"decided", "abstained"}


def test_the_report_leads_with_where_the_validation_tau_did_not_hold(
    tiny_repo, tmp_path
) -> None:
    result = run(tiny_repo, tmp_path / "scratch")
    report = result.report_path.read_text(encoding="utf-8")
    assert "\n## Findings\n" in report
    below = [c for r in result.dps for c in r.chosen.certifications if c.below_floor]
    if below:  # the tiny data is noisy enough that some label misses its floor
        first = below[0]
        assert f"{first.tp} of {first.accepted} decisions correct on test" in report
    else:
        assert "Nothing to flag" in report


def test_an_official_report_names_paths_relative_to_the_repo(tiny_repo) -> None:
    result = run(tiny_repo, tiny_repo.root / "reports")
    report = result.report_path.read_text(encoding="utf-8")
    assert str(tiny_repo.root) not in report
    assert "`packages/encoder/calibration/decision_points.json`" in report
