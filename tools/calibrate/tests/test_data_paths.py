"""Multi-file decision data (`data_paths`), `eval_split` and the split banner."""

import json
from pathlib import Path

import pytest
from calibrate.report import PROVISIONAL_LABEL
from calibrate.runner import (
    resolve_decision_data_paths,
    resolve_eval_split,
    run_decision_calibration,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "tools" / "calibrate" / "fixtures" / "decision.jsonl"


def _split_fixture(tmp_path: Path, test_source: str) -> list[Path]:
    """Write the fixture as one file per split, overriding the test `source`."""
    rows: dict[str, list[dict]] = {"train": [], "validation": [], "test": []}
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        row = json.loads(line)
        if row["split"] == "test":
            row["source"] = test_source
        rows[row["split"]].append(row)
    paths = []
    for split, split_rows in rows.items():
        path = tmp_path / f"decision.{split}.jsonl"
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in split_rows),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _write_config(tmp_path: Path, data_lines: str, extra: str = "") -> Path:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        f"""
task: decision
mode: zeroshot
{data_lines}
{extra}
p_min: 0.9
languages: [es, pt, en]
candidates:
  - name: tfidf_lr_baseline
    type: tfidf_lr
    model_id: tfidf_lr
""",
        encoding="utf-8",
    )
    return cfg


def _data_paths_yaml(paths: list[Path]) -> str:
    return "data_paths:\n" + "".join(f"  - {p}\n" for p in paths)


def test_resolve_legacy_data_path():
    assert resolve_decision_data_paths({"data_path": "a.jsonl"}) == ["a.jsonl"]


def test_resolve_default_is_fixture():
    assert resolve_decision_data_paths({}) == [
        "tools/calibrate/fixtures/decision.jsonl"
    ]


def test_resolve_data_paths_list():
    cfg = {"data_paths": ["train.jsonl", "val.jsonl", "test.jsonl"]}
    assert resolve_decision_data_paths(cfg) == [
        "train.jsonl",
        "val.jsonl",
        "test.jsonl",
    ]


@pytest.mark.parametrize(
    "cfg",
    [
        {"data_path": "a.jsonl", "data_paths": ["b.jsonl"]},
        {"data_paths": []},
        {"data_paths": "a.jsonl"},
    ],
)
def test_resolve_rejects_invalid(cfg):
    with pytest.raises(ValueError):
        resolve_decision_data_paths(cfg)


def test_multi_file_run_lists_every_file(tmp_path):
    paths = _split_fixture(tmp_path, test_source="human")
    cfg = _write_config(tmp_path, _data_paths_yaml(paths))

    report = run_decision_calibration(cfg, tmp_path / "out").read_text("utf-8")

    for p in paths:
        assert str(p) in report
    assert "| `tfidf_lr` | zeroshot | es |" in report
    assert "no data" not in report
    assert "**Scored split:** `test` (provenance: human)" in report
    assert PROVISIONAL_LABEL not in report
    assert "Optimistic" not in report


def test_provisional_test_source_adds_banner(tmp_path):
    paths = _split_fixture(tmp_path, test_source="synthetic-provisional")
    cfg = _write_config(tmp_path, _data_paths_yaml(paths))

    report = run_decision_calibration(cfg, tmp_path / "out").read_text("utf-8")

    assert "(provenance: provisional synthetic (not human))" in report
    assert report.index("> [!WARNING]") < report.index("**Date:**")


def test_guard_applies_to_any_fixture_in_data_paths(tmp_path):
    real = REPO_ROOT / "data" / "eval" / "synthetic" / "decision.train.jsonl"
    cfg = _write_config(tmp_path, _data_paths_yaml([real, FIXTURE]))

    with pytest.raises(ValueError, match="Refusing to write fixture"):
        run_decision_calibration(cfg, REPO_ROOT / "reports")


def test_resolve_eval_split_defaults_to_test():
    assert resolve_eval_split({}) == "test"
    assert resolve_eval_split({"eval_split": "validation"}) == "validation"


def test_resolve_eval_split_rejects_train():
    with pytest.raises(ValueError, match="eval_split"):
        resolve_eval_split({"eval_split": "train"})


def test_decision_eval_split_validation_is_flagged_optimistic(tmp_path):
    paths = _split_fixture(tmp_path, test_source="human")
    cfg = _write_config(
        tmp_path, _data_paths_yaml(paths), extra="eval_split: validation"
    )

    report = run_decision_calibration(cfg, tmp_path / "out").read_text("utf-8")

    assert "**Scored split:** `validation` (provenance: human, synthetic)" in report
    assert "Optimistic: tau is chosen on validation" in report
    assert "Validation min precision" in report
    assert "no data" not in report
