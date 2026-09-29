"""``make calibration-verify``: the committed artifact is still the one its evidence
describes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from calibrate.artifact import (
    RunMeta,
    fragment,
    fragment_of,
    fragment_text,
    merge_fragments,
    write_artifact,
)
from calibrate.verify import file_sha256, main, verify
from encoder.decision_points import artifact_json_schema

RUN_ID = "0123456789ab"
REPORT = "reports/calibration-decision-points-2026-09-29.md"
TRAIN = b'{"id": "1"}\n'
VALIDATION = b'{"id": "2"}\n'
TEST = b'{"id": "3"}\n'
CONFIG = b"task: decision-points\n"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Repo:
    """A tiny repository: data files, a config, an artifact and its report."""

    def __init__(self, root: Path, make_backend, make_entry) -> None:
        self.root = root
        for name, data in (
            ("data/train.jsonl", TRAIN),
            ("data/validation.jsonl", VALIDATION),
            ("data/test.jsonl", TEST),
            ("cfg.yaml", CONFIG),
        ):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(data)
        self.artifact_path = root / "packages/encoder/calibration/decision_points.json"
        entry = make_entry("intent", ("a", "b"))
        entry["evidence"] = {
            "run_id": RUN_ID,
            "report": REPORT,
            "split": "test",
            "provenance": "synthetic-provisional",
            "certified": False,
            "data": {
                "train": {"path": "data/train.jsonl", "sha256": sha(TRAIN)},
                "validation": {
                    "path": "data/validation.jsonl",
                    "sha256": sha(VALIDATION),
                },
                "test": {"path": "data/test.jsonl", "sha256": sha(TEST)},
            },
            "config": {"path": "cfg.yaml", "sha256": sha(CONFIG)},
        }
        self.backend = make_backend(sha(TRAIN))
        self.entry = entry
        self.write()

    def write(self, entry: dict | None = None, report: bool = True) -> None:
        raw = merge_fragments(
            None,
            [fragment("alpha", entry or self.entry, "intent", self.backend)],
            RunMeta("2026-09-29T00:00:00Z", None, None, None),
        )
        write_artifact(self.artifact_path, raw)
        if report:
            self.write_report(fragment_text(fragment_of(raw, "alpha")))

    def write_report(self, embedded: str, run_id: str = RUN_ID) -> None:
        path = self.root / REPORT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# Report\n\nrun {run_id}\n\n```json\n{embedded}\n```\n", encoding="utf-8"
        )

    def verify(self, **kwargs):
        return verify(self.artifact_path, repo_root=self.root, **kwargs)


@pytest.fixture
def repo(tmp_path, make_backend, make_entry) -> Repo:
    return Repo(tmp_path, make_backend, make_entry)


def test_a_consistent_artifact_verifies(repo: Repo) -> None:
    result = repo.verify()
    assert result.ok, result.errors
    assert any("not certified" in note for note in result.notes)


def test_the_committed_json_schema_is_checked_for_drift(repo: Repo) -> None:
    schema = repo.root / "packages/encoder/calibration/decision_points.schema.json"
    schema.write_text(json.dumps(artifact_json_schema()), encoding="utf-8")
    assert repo.verify().ok

    schema.write_text(json.dumps({"title": "old"}), encoding="utf-8")
    errors = repo.verify().errors
    assert any("out of date" in e and "encoder.decision_points" in e for e in errors)


def test_a_hand_edited_artifact_fails_its_own_id(repo: Repo) -> None:
    edited = json.loads(repo.artifact_path.read_text(encoding="utf-8"))
    edited["decision_points"]["alpha"]["thresholds"]["es"] = 0.01
    repo.artifact_path.write_text(json.dumps(edited), encoding="utf-8")
    result = repo.verify()
    assert not result.ok and "edited by hand" in result.errors[0]


def test_a_missing_artifact_is_an_error(tmp_path: Path) -> None:
    result = verify(tmp_path / "nope.json", repo_root=tmp_path)
    assert not result.ok and "cannot read" in result.errors[0]


def test_train_data_that_changed_breaks_the_backend_pin(repo: Repo) -> None:
    (repo.root / "data/train.jsonl").write_bytes(TRAIN + b'{"id": "new"}\n')
    errors = repo.verify().errors
    assert any(
        "backend 'intent'" in e and "changed since calibration" in e for e in errors
    )


def test_a_model_id_that_disagrees_with_the_train_hash_is_reported(
    repo: Repo, make_backend
) -> None:
    repo.backend = {**make_backend(sha(TRAIN)), "model_id": "tfidf_lr@wrong"}
    repo.write()
    assert any("model_id" in e for e in repo.verify().errors)


def test_evaluation_data_that_changed_is_reported_per_split(repo: Repo) -> None:
    (repo.root / "data/test.jsonl").write_bytes(b"different\n")
    errors = repo.verify().errors
    assert any("decision point 'alpha'" in e and "test data" in e for e in errors)


def test_a_config_that_changed_is_a_warning_not_an_error(repo: Repo) -> None:
    (repo.root / "cfg.yaml").write_bytes(CONFIG + b"# a new DP for someone else\n")
    result = repo.verify()
    assert result.ok
    assert any("cfg.yaml changed" in w for w in result.warnings)


def test_every_decision_point_needs_its_report(repo: Repo) -> None:
    (repo.root / REPORT).unlink()
    assert any("report" in e and "not found" in e for e in repo.verify().errors)

    no_evidence = {**repo.entry, "evidence": {}}
    repo.write(entry=no_evidence, report=False)
    assert any("needs a run_id and a report" in e for e in repo.verify().errors)


def test_the_report_must_contain_the_run_id(repo: Repo) -> None:
    # A report of another run: neither its id nor this entry's fragment is in it.
    repo.write_report("{}", run_id="ffffffffffff")
    errors = repo.verify().errors
    assert any(f"run id {RUN_ID} does not appear" in e for e in errors)


def test_the_report_must_embed_the_fragment_verbatim(repo: Repo) -> None:
    raw = json.loads(repo.artifact_path.read_text(encoding="utf-8"))
    raw["decision_points"]["alpha"]["thresholds"]["es"] = 0.99  # a different tau
    repo.write_report(fragment_text(fragment_of(raw, "alpha")))
    errors = repo.verify().errors
    assert any("does not embed" in e and "verbatim" in e for e in errors)


def test_a_seed_never_ships(repo: Repo) -> None:
    repo.write(entry={**repo.entry, "status": "uncalibrated_seed"})
    assert any("uncalibrated_seed" in e for e in repo.verify().errors)


def test_calibrated_needs_a_threshold_somewhere(repo: Repo) -> None:
    repo.write(entry={**repo.entry, "thresholds": {"es": None, "pt": None}})
    assert any("should be infeasible" in e for e in repo.verify().errors)


def test_a_threshold_without_a_calibrator_would_abstain(repo: Repo) -> None:
    repo.write(entry={**repo.entry, "thresholds": {"es": 0.5, "en": 0.4}})
    assert any(
        "'en' has a threshold but no calibrator" in e for e in repo.verify().errors
    )


def test_an_infeasible_decision_point_still_needs_its_evidence(repo: Repo) -> None:
    repo.write(entry={**repo.entry, "status": "infeasible", "thresholds": {}})
    assert repo.verify().ok


def test_a_hub_backend_must_be_pinned_to_a_commit(repo: Repo) -> None:
    repo.backend = {
        "kind": "gliner",
        "model_id": "gliner@x",
        "revision": "main",
        "probability_kind": "top1_only",
        "labels": ["a", "b"],
        "local_only": True,
        "timeout_ms": 500,
    }
    entry = {**repo.entry, "calibrator": {"kind": "none", "by_lang": {}}}
    repo.write(entry=entry)
    errors = repo.verify().errors
    assert any("40-hex commit" in e for e in errors)
    assert any("weights_sha256 is missing" in e for e in errors)


def test_llm_sidecar_is_reported_as_pending(repo: Repo) -> None:
    repo.backend = {
        "kind": "llm_sidecar",
        "model_id": "llm@x",
        "probability_kind": "distribution",
        "local_only": True,
        "timeout_ms": 500,
    }
    repo.write()
    assert any("pending: llm_sidecar" in e for e in repo.verify().errors)


# --- effects <-> artifact ---


def effects(repo: Repo, points: dict) -> Path:
    path = repo.root / "apps/orchestrator/config/decision_effects.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": 1, "decision_points": points}), encoding="utf-8"
    )
    return path


def test_without_an_effects_file_the_cross_check_is_skipped_and_says_so(
    repo: Repo,
) -> None:
    result = repo.verify()
    assert any("cross-check skipped" in note for note in result.notes)


def test_effects_that_match_the_artifact_pass(repo: Repo) -> None:
    effects(
        repo,
        {
            "alpha": {
                "mode": "shadow",
                "effect": "gate",
                "params": {
                    "consent_labels": ["a"],
                    "revoke_labels": ["b"],
                    "explicit_request": {"dp": "alpha", "labels": ["a"]},
                    "ledger": {"policy": "priority", "order": ["a", "b"]},
                    "targets": [{"tool": "card.block", "map": {"a": "X", "b": "Y"}}],
                },
            }
        },
    )
    result = repo.verify()
    assert result.ok, result.errors
    assert any("1 decision points cross-checked" in n for n in result.notes)


def test_effects_that_name_something_the_artifact_lacks_fail(repo: Repo) -> None:
    effects(
        repo,
        {
            "ghost": {"mode": "shadow", "effect": "record"},
            "alpha": {
                "mode": "shadow",
                "effect": "gate",
                "params": {
                    "consent_labels": ["confirm"],
                    "explicit_request": {"dp": "elsewhere", "labels": ["x"]},
                    "targets": [{"tool": "card.block", "map": {"LOST": "LOST"}}],
                },
            },
        },
    )
    text = "\n".join(repo.verify().errors)
    assert "'ghost' is not a decision point of the artifact" in text
    assert "params.consent_labels names ['confirm']" in text
    assert "params.explicit_request.dp names 'elsewhere'" in text
    assert "params.targets[card.block].map names ['LOST']" in text


def test_enforcing_a_decision_point_the_artifact_cannot_decide_fails(
    repo: Repo,
) -> None:
    repo.write(entry={**repo.entry, "status": "infeasible", "thresholds": {}})
    effects(repo, {"alpha": {"mode": "enforce", "effect": "gate"}})
    assert any("enforce" in e and "infeasible" in e for e in repo.verify().errors)


def test_the_command_exits_nonzero_on_a_finding(repo: Repo, capsys) -> None:
    args = ["--artifact", str(repo.artifact_path), "--repo-root", str(repo.root)]
    assert main(args) == 0
    assert "calibration-verify: OK" in capsys.readouterr().out

    (repo.root / "data/test.jsonl").write_bytes(b"x\n")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err and "FAILED" in captured.err


def test_file_sha256_streams_the_file(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert file_sha256(path) == hashlib.sha256(b"abc").hexdigest()
