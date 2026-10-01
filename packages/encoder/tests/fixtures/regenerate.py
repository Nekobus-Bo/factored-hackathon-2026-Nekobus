"""Rebuild the decision-point test fixtures.

    uv run python packages/encoder/tests/fixtures/regenerate.py

Writes ``intent.train.jsonl`` (a small, fixed sample of the versioned synthetic
train split) and ``decision_points.fixture.json`` (an artifact over it, with
its canonical id). Both are committed: tests must not depend on the full
dataset, and a change to either shows up in review. The artifact is a test
fixture, not a calibration: its numbers were picked, not fitted.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from encoder.decision_points import artifact_to_json
from encoder.registry import tfidf_model_id

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FULL_TRAIN = REPO / "data" / "eval" / "synthetic" / "decision.train.jsonl"
TRAIN = HERE / "intent.train.jsonl"
ARTIFACT = HERE / "decision_points.fixture.json"
# Relative to the repo root, as an artifact's paths are in the service.
TRAIN_REL = "packages/encoder/tests/fixtures/intent.train.jsonl"
PER_INTENT_AND_LANG = 4
GATE_MAP = {"confirm": "confirm", "deny": "deny", "*": "other"}
INTENTS = [
    "report_unrecognized_charge",
    "report_lost_card",
    "report_stolen_card",
    "report_suspicious_activity",
    "request_card_block",
    "request_dispute",
    "request_human_agent",
    "provide_identity_data",
    "provide_otp_code",
    "confirm",
    "deny",
    "check_balance",
    "check_recent_transactions",
    "greeting",
    "out_of_scope",
]


def sample_train() -> str:
    seen: dict[tuple[str, str], int] = defaultdict(int)
    kept: list[str] = []
    for line in FULL_TRAIN.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["intent"], row["lang"])
        if row["split"] == "train" and seen[key] < PER_INTENT_AND_LANG:
            seen[key] += 1
            kept.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(kept) + "\n"


def backend(label_map: dict[str, str] | None, sha: str) -> dict:
    train: dict = {"path": TRAIN_REL, "sha256": sha}
    if label_map:
        train["label_map"] = label_map
    return {
        "kind": "tfidf_lr",
        "model_id": tfidf_model_id(sha, label_map),
        "train": train,
        "probability_kind": "distribution",
        "local_only": True,
        "cost_class": "low",
        "timeout_ms": 2000,
    }


def main() -> None:
    content = sample_train()
    TRAIN.write_text(content, encoding="utf-8")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    others = [i for i in INTENTS if i not in ("greeting", "out_of_scope")]
    raw = {
        "schema_version": 1,
        "created_at": "2026-09-29T00:00:00Z",
        "harness": {"git_sha": None, "config_path": None, "config_sha256": None},
        "data": {"train_sha256": sha, "test_provenance": "synthetic-provisional"},
        "backends": {
            "intent_tfidf": backend(None, sha),
            "gate_tfidf": backend(GATE_MAP, sha),
        },
        "decision_points": {
            "turn_intent": {
                "backend": "intent_tfidf",
                "view": {"kind": "labels", "labels": INTENTS},
                "calibrator": {
                    "kind": "temperature",
                    "by_lang": {"es": {"T": 0.5}, "pt": {"T": 0.5}, "en": {"T": 0.5}},
                },
                # en is infeasible on purpose: the DP must abstain there.
                "thresholds": {"es": 0.3, "pt": 0.3, "en": None},
                "status": "calibrated",
                "evidence": {"run_id": "fixture", "provenance": "fixture"},
            },
            "confirm_gate": {
                "backend": "gate_tfidf",
                "view": {"kind": "labels", "labels": ["confirm", "deny", "other"]},
                "calibrator": {"kind": "none", "by_lang": {}},
                "constraint": {
                    "metric": "precision",
                    "label": "confirm",
                    "p_min": 0.95,
                    "ci": "wilson95_lower",
                    "n_min": 30,
                },
                # es per label, pt infeasible, en falls back to "*".
                "thresholds": {
                    "es": {"confirm": 0.6, "deny": 0.5, "other": 0.5},
                    "pt": None,
                    "*": 0.5,
                },
                "status": "calibrated",
                "evidence": {"run_id": "fixture", "provenance": "fixture"},
            },
            "block_reason": {
                "backend": "intent_tfidf",
                "view": {
                    "kind": "groups",
                    "groups": {
                        "LOST": ["report_lost_card"],
                        "STOLEN": ["report_stolen_card"],
                        "UNRECOGNIZED_CHARGE": ["report_unrecognized_charge"],
                        "SUSPICIOUS_ACTIVITY": ["report_suspicious_activity"],
                        "CUSTOMER_REQUEST": ["request_card_block"],
                    },
                },
                # A sharp temperature so a clear utterance passes; "yes" still does not.
                "calibrator": {"kind": "temperature", "by_lang": {"*": {"T": 0.25}}},
                "thresholds": {"*": 0.5},
                "status": "calibrated",
                "evidence": {"run_id": "fixture", "provenance": "fixture"},
            },
            "smalltalk_route": {
                "backend": "intent_tfidf",
                "view": {
                    "kind": "groups",
                    "groups": {
                        "greeting": ["greeting"],
                        "out_of_scope": ["out_of_scope"],
                        "other": others,
                    },
                },
                "enabled": False,
                "always_on": False,
                "thresholds": {"*": 0.5},
                "status": "calibrated",
            },
            "handoff_route": {
                "backend": "intent_tfidf",
                "view": {
                    "kind": "groups",
                    "groups": {
                        "DISPUTE": ["request_dispute"],
                        "HUMAN_REQUEST": ["request_human_agent"],
                    },
                },
                "always_on": False,
                "thresholds": {},
                "status": "infeasible",
            },
        },
    }
    ARTIFACT.write_text(artifact_to_json(raw), encoding="utf-8")
    print(f"wrote {TRAIN.name} ({len(content.splitlines())} rows) and {ARTIFACT.name}")


if __name__ == "__main__":
    main()
