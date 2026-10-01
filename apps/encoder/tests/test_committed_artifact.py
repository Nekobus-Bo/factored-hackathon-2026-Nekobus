"""The committed calibration artifact loads through the service's real loader.

``packages/encoder/calibration/decision_points.json`` is written by the harness
(``make calibrate TASK=decision-points``) and read here exactly as the service reads
it at startup: schema, backend pins (the train file must hash as pinned), the probe of
every backend, then ``decide`` for each decision point. If ``make synth-data`` changes
the train file, or someone edits the artifact, this fails before an image does.

These tests assert what must hold after *any* recalibration (loads, ready, labels in
the view, every acted label reachable), not the numbers of one run.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from contracts.encoder import AnalyzeResponse, DecisionPointsResponse
from encoder.decision_points import (
    DecisionPointsArtifact,
    DecisionPointSpec,
    LabelsView,
    load_artifact,
    view_labels,
)
from encoder.registry import relabel
from encoder_service.backend import set_backend
from encoder_service.config import get_decision_point_settings
from encoder_service.decisions import DecisionRuntime, load_runtime
from encoder_service.main import app
from encoder_service.scoring import RequestScores
from fastapi.testclient import TestClient

from .fake_backend import FakeEncoderBackend

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = REPO_ROOT / "packages/encoder/calibration/decision_points.json"
FREEZE_DPS = {
    "turn_intent",
    "confirm_gate",
    "block_reason",
    "handoff_route",
    "smalltalk_route",
}


@pytest.fixture(autouse=True)
def committed_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Artifact paths are relative to the working directory (/app in the image)."""
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("DECISION_POINTS_FILE", str(ARTIFACT))


@pytest.fixture(scope="module")
def artifact() -> DecisionPointsArtifact:
    return load_artifact(ARTIFACT)


@pytest.fixture(scope="module")
def runtime() -> Generator[DecisionRuntime, None, None]:
    """Loaded once: building the backends trains two TF-IDF models."""
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(REPO_ROOT)
        settings = get_decision_point_settings({"DECISION_POINTS_FILE": str(ARTIFACT)})
        loaded = load_runtime(settings)
        assert loaded is not None, "the committed artifact was not found"
        yield loaded
        loaded.close()


def train_rows() -> list[dict[str, Any]]:
    path = REPO_ROOT / "data/eval/synthetic/decision.train.jsonl"
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def test_the_artifact_holds_the_freeze_decision_points(
    artifact: DecisionPointsArtifact,
) -> None:
    assert set(artifact.decision_points) == FREEZE_DPS
    # Only this train file is copied into the encoder image (.dockerignore).
    for backend in artifact.backends.values():
        assert backend.train is not None
        assert backend.train.path == "data/eval/synthetic/decision.train.jsonl"


def test_the_service_loads_it_and_every_decision_point_is_ready(
    runtime: DecisionRuntime, artifact: DecisionPointsArtifact
) -> None:
    assert runtime.source == "artifact"
    assert runtime.config_version == artifact.artifact_id
    assert set(runtime.decision_points) == FREEZE_DPS
    states = {dp_id: runtime.state(dp_id) for dp_id in FREEZE_DPS}
    assert states == dict.fromkeys(FREEZE_DPS, "ready")
    assert set(runtime.default_ids()) == FREEZE_DPS


def test_decide_runs_for_each_decision_point_and_stays_inside_its_view(
    runtime: DecisionRuntime,
) -> None:
    samples = [
        ("Perdí mi tarjeta", "es"),
        ("sí, bloquéala", "es"),
        ("não, obrigado", "pt"),
        ("I want to talk to a person", "en"),
        ("hola", "es"),
        ("zzz qqq xxx", "en"),
    ]
    for text, lang in samples:
        results = runtime.evaluate(
            runtime.default_ids(), RequestScores(text=text, lang=lang)
        )
        assert set(results) == FREEZE_DPS
        for dp_id, result in results.items():
            labels = view_labels(runtime.decision_points[dp_id])
            assert result.outcome in {"decided", "abstained"}, (dp_id, text)
            assert result.config_version == runtime.config_version
            assert 0.0 <= result.confidence <= 1.0
            if result.outcome == "decided":
                assert result.label in labels
                assert result.tau is not None and result.confidence >= result.tau
                assert result.tau_source == "artifact"
            else:
                assert result.label is None


def test_every_acted_label_can_be_decided_wherever_it_has_a_threshold(
    runtime: DecisionRuntime, artifact: DecisionPointsArtifact
) -> None:
    """A DP that cannot decide its acted labels in a language it claims to serve is
    dead there. The most typical utterance of a label is one it was trained on."""
    rows = train_rows()
    for dp_id, dp in artifact.decision_points.items():
        acted = (dp.constraint or {}).get("labels", [])
        assert acted, f"{dp_id}: the artifact records no acted labels"
        train = artifact.backends[dp.backend].train
        assert train is not None
        for lang in ("es", "pt", "en"):
            entry = dp.thresholds.get(lang)
            if entry is None:
                continue  # infeasible in that language: it abstains, by design
            for label in acted:
                if isinstance(entry, dict) and entry.get(label) is None:
                    continue
                texts = [
                    r["text"]
                    for r in rows
                    if r["lang"] == lang
                    and dp_label(dp, relabel(r["intent"], train.label_map)) == label
                ]
                assert texts, (dp_id, lang, label)
                decided = (
                    runtime.evaluate([dp_id], RequestScores(text=t, lang=lang))[dp_id]
                    for t in texts
                )
                assert any(d.label == label for d in decided), (dp_id, lang, label)


def dp_label(dp: DecisionPointSpec, backend_label: str) -> str | None:
    """The DP label a backend label falls under, or None if outside its view."""
    view = dp.view
    if isinstance(view, LabelsView):
        return backend_label if backend_label in view.labels else None
    for name, members in view.groups.items():
        if backend_label in members:
            return name
    return None


def test_the_running_service_serves_the_committed_artifact(
    artifact: DecisionPointsArtifact,
) -> None:
    set_backend(FakeEncoderBackend(intent="greeting", confidence=0.99))
    try:
        with TestClient(app) as client:
            info = DecisionPointsResponse.model_validate(
                client.get("/v1/decision-points").json()
            )
            assert info.source == "artifact"
            assert info.config_version == artifact.artifact_id
            assert {p.id for p in info.decision_points} == FREEZE_DPS
            assert {p.state for p in info.decision_points} == {"ready"}

            ready = client.get("/ready")
            assert ready.status_code == 200
            assert ready.json()["decision_points"]["config_version"] == (
                artifact.artifact_id
            )

            response = client.post(
                "/v1/analyze", json={"text": "sí, bloquéala", "lang": "es"}
            )
            assert response.status_code == 200, response.text
            body = AnalyzeResponse.model_validate(response.json())
            assert body.config_version == artifact.artifact_id
            assert set(body.decisions) == FREEZE_DPS
            # The legacy fields follow turn_intent, not the (wrong) legacy backend.
            turn = body.decisions["turn_intent"]
            assert body.abstain == (turn.outcome == "abstained")
            assert body.intent == turn.label
    finally:
        set_backend(None)


def test_the_environment_seed_is_ignored_once_an_artifact_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.99")
    set_backend(FakeEncoderBackend(intent="greeting", confidence=0.5))
    try:
        with TestClient(app) as client:
            body = AnalyzeResponse.model_validate(
                client.post("/v1/analyze", json={"text": "hola", "lang": "es"}).json()
            )
            assert body.config_version is not None
            assert body.decisions["turn_intent"].tau_source == "artifact"
    finally:
        set_backend(None)
