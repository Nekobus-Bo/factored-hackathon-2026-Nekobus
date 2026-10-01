"""The artifact writer: merge fragments without clobbering other decision points."""

from __future__ import annotations

import json

import pytest
from calibrate.artifact import (
    ArtifactMergeError,
    RunMeta,
    compute_run_id,
    diff_entries,
    fragment,
    fragment_of,
    fragment_text,
    load_raw,
    merge_fragments,
    summarize_data,
    write_artifact,
)
from encoder.decision_points import load_artifact

SHA_A = "a" * 64
SHA_B = "b" * 64
META = RunMeta(
    created_at="2026-09-29T12:00:00Z",
    git_sha="abc123",
    config_path="tools/calibrate/configs/decision_points.yaml",
    config_sha256=SHA_A,
)
META_LATER = RunMeta("2026-09-30T08:00:00Z", "def456", "cfg.yaml", SHA_B)


def one(dp_id: str, entry: dict, backend_id: str, backend: dict) -> dict:
    return fragment(dp_id, entry, backend_id, backend)


def test_first_run_creates_a_valid_artifact(make_backend, make_entry, tmp_path) -> None:
    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    path = tmp_path / "decision_points.json"
    artifact_id = write_artifact(path, raw)

    loaded = load_artifact(path)  # the encoder's own loader, id check included
    assert loaded.artifact_id == artifact_id
    assert list(loaded.decision_points) == ["alpha"]
    assert loaded.harness and loaded.harness.git_sha == "abc123"
    assert loaded.created_at == "2026-09-29T12:00:00Z"
    # The encoder image reads it as a non-root user: never the 0600 of mkstemp.
    assert path.stat().st_mode & 0o777 == 0o644


def test_a_second_decision_point_does_not_touch_the_first(
    make_backend, make_entry
) -> None:
    backend = make_backend()
    first = merge_fragments(
        None, [one("alpha", make_entry(tau=0.7), "intent", backend)], META
    )
    second = merge_fragments(
        first,
        [one("beta", make_entry(tau=0.4, run_id="run000000002"), "intent", backend)],
        META_LATER,
    )
    assert second["decision_points"]["alpha"] == first["decision_points"]["alpha"]
    assert second["decision_points"]["beta"]["thresholds"]["es"] == 0.4
    assert second["artifact_id"] != first["artifact_id"]
    assert second["created_at"] == "2026-09-30T08:00:00Z"


def test_recalibrating_a_decision_point_replaces_only_that_entry(
    make_backend, make_entry
) -> None:
    backend = make_backend()
    both = merge_fragments(
        None,
        [
            one("alpha", make_entry(tau=0.7), "intent", backend),
            one("beta", make_entry(tau=0.4), "intent", backend),
        ],
        META,
    )
    again = merge_fragments(
        both, [one("beta", make_entry(tau=0.9), "intent", backend)], META_LATER
    )
    assert again["decision_points"]["beta"]["thresholds"]["es"] == 0.9
    assert again["decision_points"]["alpha"] == both["decision_points"]["alpha"]


def test_null_thresholds_survive_the_merge(make_backend, make_entry) -> None:
    # null means "infeasible in that language" and must not turn into "absent",
    # which would fall back to the '*' entry.
    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    assert raw["decision_points"]["alpha"]["thresholds"] == {"es": 0.5, "pt": None}


def test_a_changed_backend_cannot_strand_other_decision_points(
    make_backend, make_entry
) -> None:
    old = merge_fragments(
        None,
        [
            one("alpha", make_entry(), "intent", make_backend(SHA_A)),
            one("beta", make_entry(), "intent", make_backend(SHA_A)),
        ],
        META,
    )
    retrained = make_backend(SHA_B)
    with pytest.raises(ArtifactMergeError) as error:
        merge_fragments(old, [one("alpha", make_entry(), "intent", retrained)], META)
    message = str(error.value)
    assert "beta" in message and "intent" in message and "same run" in message

    # Recalibrating both in one run is fine.
    fixed = merge_fragments(
        old,
        [
            one("alpha", make_entry(), "intent", retrained),
            one("beta", make_entry(), "intent", retrained),
        ],
        META,
    )
    assert fixed["backends"]["intent"]["train"]["sha256"] == SHA_B


def test_unreferenced_backends_are_dropped(make_backend, make_entry) -> None:
    old = merge_fragments(
        None, [one("alpha", make_entry("v1"), "v1", make_backend(SHA_A))], META
    )
    moved = merge_fragments(
        old, [one("alpha", make_entry("v2"), "v2", make_backend(SHA_B))], META
    )
    assert list(moved["backends"]) == ["v2"]


def test_two_backends_with_one_id_in_one_run_are_refused(
    make_backend, make_entry
) -> None:
    with pytest.raises(ArtifactMergeError, match="one backend id names one model"):
        merge_fragments(
            None,
            [
                one("alpha", make_entry(), "intent", make_backend(SHA_A)),
                one("beta", make_entry(), "intent", make_backend(SHA_B)),
            ],
            META,
        )


def test_duplicate_decision_point_and_empty_run_are_refused(
    make_backend, make_entry
) -> None:
    frag = one("alpha", make_entry(), "intent", make_backend())
    with pytest.raises(ArtifactMergeError, match="twice"):
        merge_fragments(None, [frag, frag], META)
    with pytest.raises(ArtifactMergeError, match="nothing to merge"):
        merge_fragments(None, [], META)


def test_an_entry_the_service_would_refuse_is_refused_here(
    make_backend, make_entry, tmp_path
) -> None:
    bad = make_entry()
    bad["calibrator"]["by_lang"]["es"] = {"T": 0.0}
    with pytest.raises(ArtifactMergeError, match="decision point 'alpha'"):
        merge_fragments(None, [one("alpha", bad, "intent", make_backend())], META)

    # A reference to a backend the artifact does not have is caught when it is written.
    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    raw["decision_points"]["alpha"]["backend"] = "nope"
    target = tmp_path / "decision_points.json"
    with pytest.raises(ArtifactMergeError, match="unknown backend"):
        write_artifact(target, raw)
    assert not target.exists()


def test_load_raw_refuses_a_file_edited_by_hand(
    make_backend, make_entry, tmp_path
) -> None:
    path = tmp_path / "a.json"
    assert load_raw(path) is None

    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    write_artifact(path, raw)
    assert load_raw(path) is not None

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["decision_points"]["alpha"]["thresholds"]["es"] = 0.01
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ArtifactMergeError, match="edited by hand"):
        load_raw(path)

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactMergeError, match="not a valid calibration artifact"):
        load_raw(path)


def test_write_is_deterministic_and_leaves_no_temporary_files(
    make_backend, make_entry, tmp_path
) -> None:
    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    path = tmp_path / "out" / "decision_points.json"
    write_artifact(path, raw)
    first = path.read_bytes()
    write_artifact(path, load_raw(path))
    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    assert [p.name for p in path.parent.iterdir()] == ["decision_points.json"]


def test_a_broken_merge_never_replaces_the_file(
    make_backend, make_entry, tmp_path
) -> None:
    path = tmp_path / "decision_points.json"
    raw = merge_fragments(
        None, [one("alpha", make_entry(), "intent", make_backend())], META
    )
    write_artifact(path, raw)
    before = path.read_bytes()

    broken = json.loads(json.dumps(raw))
    broken["decision_points"]["alpha"]["backend"] = "missing"
    with pytest.raises(ArtifactMergeError):
        write_artifact(path, broken)
    assert path.read_bytes() == before


def test_fragment_round_trip_matches_what_a_report_embeds(
    make_backend, make_entry
) -> None:
    backend = make_backend()
    entry = make_entry()
    raw = merge_fragments(None, [one("alpha", entry, "intent", backend)], META)
    assert fragment_of(raw, "alpha") == one("alpha", entry, "intent", backend)
    assert fragment_text(fragment_of(raw, "alpha")).startswith("{\n")


def test_summarize_data_agrees_only_where_every_entry_does(make_entry) -> None:
    def with_data(train: str, test: str, provenance: str) -> dict:
        entry = make_entry()
        entry["evidence"]["data"] = {
            "train": {"sha256": train},
            "test": {"sha256": test},
        }
        entry["evidence"]["provenance"] = provenance
        return entry

    summary = summarize_data(
        {
            "a": with_data(SHA_A, SHA_A, "human"),
            "b": with_data(SHA_A, SHA_B, "synthetic-provisional"),
        }
    )
    assert summary == {
        "train_sha256": SHA_A,  # both agree
        "test_provenance": "synthetic-provisional",  # the weakest
    }
    assert summarize_data({"a": make_entry()}) is None


def test_run_id_depends_on_content_not_on_key_order() -> None:
    a = compute_run_id({"x": 1, "y": [1, 2]})
    assert a == compute_run_id({"y": [1, 2], "x": 1})
    assert a != compute_run_id({"x": 2, "y": [1, 2]})
    assert len(a) == 12


def test_diff_entries_lists_thresholds_and_ignores_run_ids(make_entry) -> None:
    old = make_entry(tau=0.5, run_id="run000000001")
    new = make_entry(tau=0.6, run_id="run000000002")
    new["thresholds"]["en"] = 0.3
    lines = diff_entries(old, new)
    assert "~ thresholds.es: 0.5 -> 0.6" in lines
    assert "+ thresholds.en = 0.3" in lines
    assert not any("run_id" in line or "report" in line for line in lines)
    assert diff_entries(None, new) == ["new decision point (no previous entry)"]
