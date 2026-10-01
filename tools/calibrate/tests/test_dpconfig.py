"""The decision-points config fails on the field that is wrong, before any training."""

from __future__ import annotations

import pytest
from calibrate.dpconfig import (
    ConfigError,
    load_run_config,
    parse_run_config,
    select_dps,
)


def test_the_tiny_config_parses(tiny_config_text: str) -> None:
    config = parse_run_config(tiny_config_text, "cfg.yaml")
    assert list(config.dps) == ["intent", "gate", "reason"]
    gate = config.dps["gate"]
    assert gate.scope == "per_language_per_label"
    assert gate.constraint.p_min == {"confirm": 0.9, "deny": 0.8}
    assert gate.label_map == {"confirm": "confirm", "deny": "deny", "*": "other"}
    assert config.dps["intent"].constraint.p_min == {"lost": 0.8, "stolen": 0.8}
    # A DP with no `labels` and a scalar floor acts on every label of its view.
    assert set(config.dps["reason"].constraint.p_min) == {"LOST", "STOLEN"}


def test_the_seed_config_in_the_repo_parses() -> None:
    config = load_run_config("tools/calibrate/configs/decision_points.yaml")
    assert set(config.dps) == {
        "turn_intent",
        "confirm_gate",
        "block_reason",
        "handoff_route",
        "smalltalk_route",
        "intent_hint",
        "clarify_route",
    }
    # Nothing in the config is a threshold: the constraint is the question.
    assert all(dp.constraint.p_min for dp in config.dps.values())
    assert config.dps["confirm_gate"].constraint.p_min == {
        "confirm": 0.95,
        "deny": 0.90,
    }


def test_the_hash_is_of_the_bytes_on_disk(tmp_path, tiny_config_text: str) -> None:
    import hashlib

    path = tmp_path / "cfg.yaml"
    path.write_bytes(tiny_config_text.encode("utf-8"))
    assert (
        load_run_config(path).sha256
        == hashlib.sha256(tiny_config_text.encode("utf-8")).hexdigest()
    )


def broken(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("task: decision-points", "task: decision", "task must be 'decision-points'"),
        ("train: data/train.jsonl", "train: /abs/train.jsonl", "is absolute"),
        (
            "calibrator: temperature\n    threshold_scope: per_language\n",
            "calibrator: isotonic\n    threshold_scope: per_language\n",
            "pending: isotonic",
        ),
        ("threshold_scope: per_language\n", "threshold_scope: nightly\n", "one of"),
        ("labels: [lost, stolen]", "labels: [lost, mystery]", "not labels of the view"),
        (
            "ci: point\n      n_min: 10\n  gate",
            "ci: maybe\n      n_min: 10\n  gate",
            "ci",
        ),
        (
            "p_min: 0.8\n      ci: point\n      n_min: 10\n  gate",
            "p_min: 1.0\n      ci: point\n      n_min: 10\n  gate",
            r"must be in \(0, 1\)",
        ),
        (
            "candidates: [intent_tfidf]\n    view: {kind: labels",
            "candidates: [nope]\n    view: {kind: labels",
            "not defined under 'backends'",
        ),
        ("languages: [es, pt, en]", "languages: []", "languages"),
    ],
)
def test_bad_config_names_the_field(
    tiny_config_text: str, old: str, new: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_run_config(broken(tiny_config_text, old, new), "cfg.yaml")


def test_tau_is_never_configured(tiny_config_text: str) -> None:
    # A `thresholds:` block would be a constant in a file that only asks questions.
    config = parse_run_config(tiny_config_text, "cfg.yaml")
    assert not hasattr(config.dps["gate"], "thresholds")


def test_top1_only_needs_no_calibrator_and_a_labels_view(tiny_config_text: str) -> None:
    top1 = """
task: decision-points
data: {train: a.jsonl, validation: b.jsonl, test: c.jsonl}
decision_points:
  dp_one:
    candidates:
      - {name: zero_shot, kind: gliner, model_id: x, probability_kind: top1_only}
    view: {kind: labels, labels: [a, b]}
    calibrator: temperature
    constraint: {p_min: 0.9}
"""
    with pytest.raises(ConfigError, match="cannot be calibrated"):
        parse_run_config(top1, "cfg.yaml")
    ok = top1.replace("calibrator: temperature", "calibrator: none")
    assert parse_run_config(ok, "cfg.yaml").dps["dp_one"].calibrator == "none"


def test_fine_tuning_a_non_tfidf_candidate_is_pending() -> None:
    text = """
task: decision-points
data: {train: a.jsonl, validation: b.jsonl, test: c.jsonl}
decision_points:
  dp_one:
    candidates:
      - {name: xlmr, kind: hf_seqcls, mode: finetune, model_id: x}
    view: {kind: labels, labels: [a, b]}
    constraint: {p_min: 0.9}
"""
    with pytest.raises(ConfigError, match="pending: fine-tuning"):
        parse_run_config(text, "cfg.yaml")


def test_select_dps_keeps_config_order_and_rejects_unknown(
    tiny_config_text: str,
) -> None:
    config = parse_run_config(tiny_config_text, "cfg.yaml")
    assert [dp.dp_id for dp in select_dps(config, ["reason", "intent"])] == [
        "intent",
        "reason",
    ]
    assert len(select_dps(config, None)) == 3
    with pytest.raises(ConfigError, match=r"unknown decision point \['nope'\]"):
        select_dps(config, ["nope"])


# --- Locale groups (ADR-0014) ---


def test_the_distilbert_config_adds_locale_groups_to_per_language_dps_only() -> None:
    from calibrate.dpconfig import load_run_config

    config = load_run_config("tools/calibrate/configs/decision_points_distilbert.yaml")
    assert config.locales == ("pt-BR", "es-MX", "es-AR", "es-CO")
    assert config.report_tag == "distilbert"
    per_language = config.for_dp(config.dps["turn_intent"])
    assert per_language.languages == (
        "es",
        "pt",
        "en",
        "pt-BR",
        "es-MX",
        "es-AR",
        "es-CO",
    )
    pooled = config.for_dp(config.dps["block_reason"])
    assert pooled.languages == ("es", "pt", "en")  # no row counted twice


def test_a_tagged_report_never_overwrites_the_default_one() -> None:
    from calibrate.dp import _report_name

    every = ["a", "b"]
    assert _report_name("2026-09-30", every, every) == (
        "calibration-decision-points-2026-09-30.md"
    )
    assert _report_name("2026-09-30", every, every, "distilbert") == (
        "calibration-decision-points-2026-09-30-distilbert.md"
    )
