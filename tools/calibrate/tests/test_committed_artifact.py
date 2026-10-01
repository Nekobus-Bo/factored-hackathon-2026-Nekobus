"""The artifact and report committed in this repository still describe each other.

This is ``make calibration-verify`` run as a test, so a change that leaves the
artifact behind fails here: a new ``decision.train.jsonl`` (for example after
``make synth-data``), an edited config-independent pin, a report that no longer
embeds an entry, or an artifact edited by hand. The fix is always to recalibrate:
``make calibrate TASK=decision-points`` and commit the artifact with its report.
"""

from __future__ import annotations

import json
from pathlib import Path

from calibrate.verify import verify
from encoder.decision_points import load_artifact

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = REPO_ROOT / "packages/encoder/calibration/decision_points.json"


def test_the_committed_artifact_verifies() -> None:
    result = verify(repo_root=REPO_ROOT)
    assert result.ok, "\n".join(result.errors)


def test_the_seed_artifact_is_honest_about_its_evidence() -> None:
    artifact = load_artifact(ARTIFACT)
    assert set(artifact.decision_points) >= {
        "turn_intent",
        "confirm_gate",
        "block_reason",
        "handoff_route",
        "smalltalk_route",
    }
    raw = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    for dp_id, entry in raw["decision_points"].items():
        evidence = entry["evidence"]
        # The provisional test split cannot certify a precision of 0.90 or 0.95:
        # while it is the only one, no entry may claim to be certified.
        if evidence["provenance"] == "synthetic-provisional":
            assert evidence["certified"] is False, dp_id
        assert entry["status"] in {"calibrated", "infeasible"}, dp_id
    assert artifact.data is not None
    if artifact.data.test_provenance == "synthetic-provisional":
        assert not any(
            e["evidence"]["certified"] for e in raw["decision_points"].values()
        )
