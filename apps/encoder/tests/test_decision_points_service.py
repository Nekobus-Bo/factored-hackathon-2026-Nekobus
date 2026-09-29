"""Decision points served by /v1/analyze, /v1/decision-points and /ready (ADR-0012)."""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from contracts.encoder import AnalyzeResponse, DecisionPointsResponse
from encoder.base import DecisionAdapter
from encoder.decision_points import (
    BackendSpec,
    DecisionPointSpec,
    compute_artifact_id,
    with_artifact_id,
)
from encoder.models import DecisionPrediction
from encoder_service.backend import set_backend
from encoder_service.config import DecisionPointSettings, get_decision_point_settings
from encoder_service.decisions import DecisionRuntime, load_runtime
from encoder_service.main import app
from encoder_service.model_backends import BackendConfigError
from encoder_service.scoring import RequestScores, ScoringBackend
from fastapi.testclient import TestClient

from .fake_backend import FakeEncoderBackend

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "packages" / "encoder" / "tests" / "fixtures"
FIXTURE_ARTIFACT = FIXTURES / "decision_points.fixture.json"
TRAIN_ROWS = [
    json.loads(line)
    for line in (FIXTURES / "intent.train.jsonl").read_text("utf-8").splitlines()
]
GATE_ONLY = ["confirm_gate"]


def train_text(intent: str, lang: str) -> str:
    return next(
        r["text"] for r in TRAIN_ROWS if r["intent"] == intent and r["lang"] == lang
    )


@pytest.fixture(autouse=True)
def from_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Artifact paths are relative to the working directory (/app in the image)."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def legacy_backend() -> Generator[None, None, None]:
    # The legacy backend supplies slots and PII spans; its intent is not used when the
    # artifact has an enabled turn_intent. A wrong one proves that.
    set_backend(
        FakeEncoderBackend(intent="greeting", confidence=0.99, model_id="legacy-fake")
    )
    yield
    set_backend(None)


@pytest.fixture
def artifact_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DECISION_POINTS_FILE", str(FIXTURE_ARTIFACT))
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.99")  # ignored: the artifact wins
    with TestClient(app) as client:
        yield client


def analyze(
    client: TestClient, text: str, lang: str | None, **extra: Any
) -> AnalyzeResponse:
    body: dict[str, Any] = {"text": text, **extra}
    if lang is not None:
        body["lang"] = lang
    response = client.post("/v1/analyze", json=body)
    assert response.status_code == 200, response.text
    return AnalyzeResponse.model_validate(response.json())


# --- Legacy seed mode: no artifact file ---


def test_seed_mode_reports_itself_and_keeps_the_legacy_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.75")
    set_backend(FakeEncoderBackend(intent="request_card_block", confidence=0.92))
    with TestClient(app) as client:
        body = analyze(client, "Bloquea mi tarjeta", "es")
        assert (body.intent, body.confidence, body.abstain) == (
            "request_card_block",
            0.92,
            False,
        )
        assert body.config_version is None
        turn = body.decisions["turn_intent"]
        assert turn.outcome == "decided" and turn.label == "request_card_block"
        assert (turn.tau, turn.tau_source) == (0.75, "seed")
        assert turn.model_id == "fake-encoder-v1"

        info = DecisionPointsResponse.model_validate(
            client.get("/v1/decision-points").json()
        )
        assert info.source == "legacy_seed" and info.config_version is None
        [point] = info.decision_points
        assert (point.id, point.status, point.state) == (
            "turn_intent",
            "uncalibrated_seed",
            "ready",
        )
        assert point.probability_kind == "top1_only" and point.languages_with_tau == [
            "*"
        ]

        ready = client.get("/ready").json()
        assert ready["decision_points"]["source"] == "legacy_seed"
        assert ready["decision_points"]["config_version"] is None


def test_seed_mode_abstains_exactly_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.75")
    set_backend(FakeEncoderBackend(intent="request_card_block", confidence=0.60))
    with TestClient(app) as client:
        body = analyze(client, "card", "en")
    assert (body.intent, body.abstain, body.confidence) == (None, True, 0.60)
    assert body.decisions["turn_intent"].outcome == "abstained"
    assert body.decisions["turn_intent"].label is None


def test_seed_mode_without_a_threshold_is_still_uncalibrated() -> None:
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503
        assert client.post("/v1/analyze", json={"text": "hola"}).status_code == 503
        assert client.get("/v1/decision-points").status_code == 503


def test_seed_mode_only_knows_turn_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    with TestClient(app) as client:
        response = client.post(
            "/v1/analyze", json={"text": "sí", "decision_points": ["confirm_gate"]}
        )
        assert response.status_code == 422
        assert "confirm_gate" in response.json()["detail"]
        assert "turn_intent" in response.json()["detail"]


def test_a_tau_raise_applies_in_seed_mode_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    monkeypatch.setenv("DECISION_POINTS_TAU_RAISE", "turn_intent.*=0.97")
    set_backend(FakeEncoderBackend(intent="request_card_block", confidence=0.9))
    with TestClient(app) as client:
        body = analyze(client, "bloquea mi tarjeta", "es")
    assert body.abstain is True
    assert body.decisions["turn_intent"].tau_source == "override"


# --- Artifact mode ---


def test_the_artifact_is_loaded_and_reported(artifact_client: TestClient) -> None:
    artifact_id = json.loads(FIXTURE_ARTIFACT.read_text("utf-8"))["artifact_id"]
    ready = artifact_client.get("/ready")
    assert ready.status_code == 200
    states = ready.json()["decision_points"]
    assert states["source"] == "artifact" and states["config_version"] == artifact_id
    assert states["states"] == {
        "turn_intent": "ready",
        "confirm_gate": "ready",
        "block_reason": "ready",
        "smalltalk_route": "off",
        "handoff_route": "infeasible",
    }

    info = DecisionPointsResponse.model_validate(
        artifact_client.get("/v1/decision-points").json()
    )
    assert info.source == "artifact" and info.config_version == artifact_id
    by_id = {point.id: point for point in info.decision_points}
    assert by_id["confirm_gate"].labels == ["confirm", "deny", "other"]
    assert by_id["confirm_gate"].languages_with_tau == ["*", "es"]  # pt null, en via *
    assert by_id["turn_intent"].languages_with_tau == ["es", "pt"]  # en is null
    assert by_id["block_reason"].backend_kind == "tfidf_lr"
    assert by_id["block_reason"].probability_kind == "distribution"
    assert by_id["smalltalk_route"].enabled is False
    assert by_id["smalltalk_route"].always_on is False


def test_the_default_request_evaluates_enabled_always_on_points(
    artifact_client: TestClient,
) -> None:
    body = analyze(artifact_client, train_text("report_lost_card", "es"), "es")
    assert sorted(body.decisions) == ["block_reason", "confirm_gate", "turn_intent"]
    assert (
        body.config_version
        == json.loads(FIXTURE_ARTIFACT.read_text("utf-8"))["artifact_id"]
    )
    assert all(d.config_version == body.config_version for d in body.decisions.values())


def test_legacy_fields_come_from_the_turn_intent_decision_point(
    artifact_client: TestClient,
) -> None:
    text = train_text("report_lost_card", "es")
    body = analyze(artifact_client, text, "es")
    turn = body.decisions["turn_intent"]
    assert turn.outcome == "decided" and turn.label == "report_lost_card"
    # The legacy fake says "greeting" with 0.99; it is not consulted for the intent.
    assert (body.intent, body.abstain) == ("report_lost_card", False)
    assert body.confidence == turn.confidence  # the calibrated confidence
    assert turn.raw_confidence is not None and turn.confidence > turn.raw_confidence
    assert body.model_id == "legacy-fake"  # slots and PII keep the legacy backend
    assert turn.model_id.startswith("tfidf_lr@train-sha256:")


def test_block_reason_reads_the_same_backend_and_maps_groups(
    artifact_client: TestClient,
) -> None:
    expected = {
        "report_lost_card": "LOST",
        "report_stolen_card": "STOLEN",
        "request_card_block": "CUSTOMER_REQUEST",
    }
    for intent, reason in expected.items():
        body = analyze(artifact_client, train_text(intent, "es"), "es")
        result = body.decisions["block_reason"]
        assert (result.outcome, result.label) == ("decided", reason), intent
    # One forward pass served both decision points: only the first reports its time.
    both = analyze(artifact_client, train_text("report_lost_card", "es"), "es")
    latencies = sorted(
        both.decisions[dp].latency_ms for dp in ("turn_intent", "block_reason")
    )
    assert latencies[0] == 0.0 and latencies[1] > 0.0


def test_a_group_view_abstains_on_an_utterance_outside_it(
    artifact_client: TestClient,
) -> None:
    body = analyze(artifact_client, train_text("confirm", "es"), "es")
    assert body.decisions["turn_intent"].label == "confirm"
    reason = body.decisions["block_reason"]
    assert reason.outcome == "abstained" and reason.label is None
    assert reason.confidence < 0.05


def test_confirm_gate_has_its_own_label_space_and_per_label_tau(
    artifact_client: TestClient,
) -> None:
    yes = analyze(artifact_client, train_text("confirm", "es"), "es").decisions[
        "confirm_gate"
    ]
    assert (yes.outcome, yes.label, yes.tau) == ("decided", "confirm", 0.6)
    no = analyze(artifact_client, train_text("deny", "es"), "es").decisions[
        "confirm_gate"
    ]
    assert (no.outcome, no.label, no.tau) == ("decided", "deny", 0.5)
    other = analyze(artifact_client, train_text("check_balance", "es"), "es")
    assert (
        other.decisions["confirm_gate"].label == "other"
    )  # decided 'other' is a label


def test_an_infeasible_language_abstains_and_says_it_has_no_tau(
    artifact_client: TestClient,
) -> None:
    pt = analyze(artifact_client, train_text("confirm", "pt"), "pt")
    gate = pt.decisions["confirm_gate"]
    assert (gate.outcome, gate.label, gate.tau, gate.tau_source) == (
        "abstained",
        None,
        None,
        None,
    )
    en = analyze(artifact_client, train_text("report_lost_card", "en"), "en")
    assert en.decisions["turn_intent"].outcome == "abstained"
    assert (en.intent, en.abstain) == (None, True)  # legacy follows turn_intent
    # en falls back to '*' for the gate, and decides.
    assert (
        analyze(artifact_client, train_text("confirm", "en"), "en")
        .decisions["confirm_gate"]
        .outcome
        == "decided"
    )


def test_no_language_uses_the_star_or_abstains(artifact_client: TestClient) -> None:
    body = analyze(artifact_client, train_text("confirm", "es"), None)
    assert (
        body.decisions["turn_intent"].outcome == "abstained"
    )  # no '*' for turn_intent
    assert body.decisions["confirm_gate"].outcome == "decided"  # '*' = 0.5


def test_gibberish_abstains_everywhere(artifact_client: TestClient) -> None:
    body = analyze(artifact_client, "zzzz qqqq", "es")
    assert body.decisions["turn_intent"].outcome == "abstained"
    assert body.decisions["block_reason"].outcome == "abstained"
    assert (body.intent, body.abstain) == (None, True)


def test_only_requested_points_are_returned_and_legacy_still_follows_turn_intent(
    artifact_client: TestClient,
) -> None:
    text = train_text("report_stolen_card", "es")
    body = analyze(artifact_client, text, "es", decision_points=GATE_ONLY)
    assert list(body.decisions) == GATE_ONLY
    assert (body.intent, body.abstain) == ("report_stolen_card", False)
    none = analyze(artifact_client, text, "es", decision_points=[])
    assert none.decisions == {} and none.intent == "report_stolen_card"


def test_disabled_and_infeasible_points_answer_only_when_asked(
    artifact_client: TestClient,
) -> None:
    body = analyze(
        artifact_client,
        train_text("greeting", "es"),
        "es",
        decision_points=["smalltalk_route", "handoff_route"],
    )
    off, infeasible = body.decisions["smalltalk_route"], body.decisions["handoff_route"]
    assert (off.outcome, off.confidence, off.tau, off.label) == ("off", 0.0, None, None)
    assert (infeasible.outcome, infeasible.confidence) == ("infeasible", 0.0)


def test_an_unknown_decision_point_is_a_422_that_names_the_known_ones(
    artifact_client: TestClient,
) -> None:
    response = artifact_client.post(
        "/v1/analyze", json={"text": "sí", "decision_points": ["ghost_point"]}
    )
    assert response.status_code == 422
    assert "ghost_point" in response.json()["detail"]
    assert "confirm_gate" in response.json()["detail"]
    bad_id = artifact_client.post(
        "/v1/analyze", json={"text": "sí", "decision_points": ["Bad-Id"]}
    )
    assert bad_id.status_code == 422


def test_responses_carry_no_text(artifact_client: TestClient) -> None:
    text = "Zorgblatt me robaron la tarjeta 4111111111111111"
    raw = artifact_client.post("/v1/analyze", json={"text": text, "lang": "es"}).text
    assert "Zorgblatt" not in raw and "4111111111111111" not in raw


# --- Fail-loud startup ---


def write_artifact(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    raw = json.loads(FIXTURE_ARTIFACT.read_text("utf-8"))
    mutate(raw)
    path = tmp_path / "decision_points.json"
    path.write_text(json.dumps(with_artifact_id(raw)), encoding="utf-8")
    return path


def start(monkeypatch: pytest.MonkeyPatch, path: Path, **env: str) -> None:
    monkeypatch.setenv("DECISION_POINTS_FILE", str(path))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with TestClient(app):
        pass


def test_an_invalid_artifact_stops_the_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write_artifact(
        tmp_path,
        lambda raw: raw["decision_points"]["confirm_gate"].update(backend="ghost"),
    )
    with pytest.raises(BackendConfigError, match="unknown backend 'ghost'"):
        start(monkeypatch, path)


def test_a_hand_edited_artifact_stops_the_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edited = tmp_path / "edited.json"
    raw = json.loads(FIXTURE_ARTIFACT.read_text("utf-8"))
    raw["decision_points"]["confirm_gate"]["thresholds"]["*"] = 0.01
    edited.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BackendConfigError, match="edited by hand"):
        start(monkeypatch, edited)


def test_a_backend_that_cannot_be_built_stops_the_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write_artifact(
        tmp_path, lambda raw: raw["backends"]["gate_tfidf"].update(kind="llm_sidecar")
    )
    with pytest.raises(
        BackendConfigError,
        match=r"pending: llm_sidecar is not implemented \(ADR-0012\)",
    ):
        start(monkeypatch, path)


def moved_train(tmp_path: Path) -> str:
    """A copy of the train file the artifact will point at, then edited."""
    train = tmp_path / "intent.train.jsonl"
    shutil.copy(FIXTURES / "intent.train.jsonl", train)
    return str(train)


def stale_pin_artifact(tmp_path: Path) -> Path:
    train = moved_train(tmp_path)

    def mutate(raw: dict[str, Any]) -> None:
        raw["backends"]["intent_tfidf"]["train"]["path"] = train
        raw["backends"]["gate_tfidf"]["train"]["path"] = train

    path = write_artifact(tmp_path, mutate)
    Path(train).write_text(Path(train).read_text("utf-8") + "\n", encoding="utf-8")
    return path


def test_a_train_file_that_no_longer_matches_its_pin_stops_the_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(BackendConfigError, match="changed since calibration"):
        start(monkeypatch, stale_pin_artifact(tmp_path))


def test_allow_stale_downgrades_a_pin_mismatch_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = stale_pin_artifact(tmp_path)
    monkeypatch.setenv("DECISION_POINTS_FILE", str(path))
    monkeypatch.setenv("DECISION_POINTS_ALLOW_STALE", "true")
    with caplog.at_level(logging.ERROR), TestClient(app) as client:
        ready = client.get("/ready").json()["decision_points"]["states"]
        assert (
            ready["turn_intent"]
            == ready["confirm_gate"]
            == ready["block_reason"]
            == "unavailable"
        )
        body = analyze(client, "Perdí mi tarjeta", "es")
        assert body.decisions["turn_intent"].outcome == "unavailable"
        assert body.decisions["turn_intent"].confidence == 0.0
        # The legacy fields fall toward abstaining, never toward acting.
        assert (body.intent, body.abstain, body.confidence) == (None, True, 0.0)
    assert "UNAVAILABLE" in caplog.text


def test_allow_stale_is_refused_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="refused when APP_ENV=production"):
        start(
            monkeypatch,
            stale_pin_artifact(tmp_path),
            DECISION_POINTS_ALLOW_STALE="true",
            APP_ENV="production",
        )
    assert get_decision_point_settings(
        {"DECISION_POINTS_ALLOW_STALE": "true"}
    ).allow_stale


def test_a_missing_explicit_file_is_seed_mode_except_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    with caplog.at_level(logging.WARNING):
        start(monkeypatch, tmp_path / "typo.json")
    assert "legacy seed mode" in caplog.text
    with pytest.raises(
        BackendConfigError, match="refusing to fall back to the legacy seed"
    ):
        start(monkeypatch, tmp_path / "typo.json", APP_ENV="production")


def test_the_default_path_missing_is_seed_mode_even_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DECISION_POINTS_FILE")
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.chdir(REPO_ROOT / "docs")  # no packages/encoder/calibration here
    with TestClient(app) as client:
        assert client.get("/v1/decision-points").json()["source"] == "legacy_seed"


def test_tau_raise_makes_a_decision_point_more_conservative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_POINTS_FILE", str(FIXTURE_ARTIFACT))
    monkeypatch.setenv("DECISION_POINTS_TAU_RAISE", "confirm_gate.es=0.99")
    with TestClient(app) as client:
        gate = analyze(client, train_text("confirm", "es"), "es").decisions[
            "confirm_gate"
        ]
    assert gate.outcome == "abstained"
    assert (gate.tau, gate.tau_source) == (0.99, "override")


def test_tau_raise_that_raises_nothing_stops_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DECISION_POINTS_FILE", str(FIXTURE_ARTIFACT))
    monkeypatch.setenv("DECISION_POINTS_TAU_RAISE", "confirm_gate.es=0.1")
    with pytest.raises(BackendConfigError, match="raises no 'confirm_gate' threshold"):
        with TestClient(app):
            pass


def test_the_startup_memory_budget_is_enforced(tmp_path: Path) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["backends"]["intent_tfidf"]["resources"] = {"ram_mb": 5000}

    path = write_artifact(tmp_path, mutate)
    limit = tmp_path / "memory.max"
    limit.write_text(str(1024 * 1024 * 1024))
    settings = DecisionPointSettings(
        file=path,
        file_explicit=True,
        allow_stale=False,
        tau_raise={},
        max_workers=2,
        app_env="",
    )
    with pytest.raises(BackendConfigError, match="need about 5000 MiB"):
        load_runtime(settings, memory_max=limit)
    limit.write_text("max\n")
    runtime = load_runtime(settings, memory_max=limit)
    assert runtime is not None
    runtime.close()


def test_a_backend_used_only_by_a_disabled_point_is_not_built(tmp_path: Path) -> None:
    """A heavy or pending backend that no enabled point reads costs nothing."""

    def mutate(raw: dict[str, Any]) -> None:
        raw["backends"]["sidecar"] = {
            "kind": "llm_sidecar",
            "model_id": "llm_sidecar@pending",
            "probability_kind": "distribution",
            "local_only": True,
            "timeout_ms": 5000,
        }
        raw["decision_points"]["smalltalk_route"]["backend"] = "sidecar"

    path = write_artifact(tmp_path, mutate)
    settings = DecisionPointSettings(
        file=path,
        file_explicit=True,
        allow_stale=False,
        tau_raise={},
        max_workers=2,
        app_env="",
    )
    runtime = load_runtime(settings)
    assert runtime is not None
    assert runtime.state("smalltalk_route") == "off"
    runtime.close()


# --- Scoring: one pass per backend, a budget each, failures stay local ---


class ScriptedAdapter(DecisionAdapter):
    kind = "scripted"
    probability_kind = "distribution"

    def __init__(
        self,
        probabilities: dict[str, float],
        *,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.probabilities = probabilities
        self.delay = delay
        self.error = error
        self.calls = 0

    def fit(self, *a: Any, **k: Any) -> None: ...
    def save(self, path: Any) -> None: ...
    def load(self, path: Any) -> None: ...

    def predict(
        self, texts: Any, candidate_intents: Any = None, candidate_slots: Any = None
    ) -> list[DecisionPrediction]:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        top = max(self.probabilities, key=self.probabilities.__getitem__)
        return [
            DecisionPrediction(
                intent=top,
                confidence=self.probabilities[top],
                probabilities=self.probabilities,
            )
            for _ in texts
        ]


def backend_spec(timeout_ms: int = 500) -> BackendSpec:
    return BackendSpec.model_validate(
        {
            "kind": "scripted",
            "model_id": "scripted@1",
            "probability_kind": "distribution",
            "local_only": True,
            "timeout_ms": timeout_ms,
        }
    )


def gate_dp(backend: str = "b") -> DecisionPointSpec:
    return DecisionPointSpec.model_validate(
        {
            "backend": backend,
            "view": {"kind": "labels", "labels": ["confirm", "deny", "other"]},
            "thresholds": {"*": 0.6},
            "status": "calibrated",
        }
    )


def runtime_with(
    executor: ThreadPoolExecutor, **adapters: tuple[ScriptedAdapter, int]
) -> DecisionRuntime:
    backends = {
        name: ScoringBackend(
            name, backend_spec(timeout), adapter, ["confirm", "deny", "other"], executor
        )
        for name, (adapter, timeout) in adapters.items()
    }
    return DecisionRuntime(
        source="artifact",
        config_version="abc123abc123",
        decision_points={f"dp_{name}": gate_dp(name) for name in adapters},
        backends=backends,
        tau_raise={},
        executor=executor,
    )


GOOD = {"confirm": 0.9, "deny": 0.05, "other": 0.05}


def test_a_slow_backend_is_unavailable_and_the_others_still_decide() -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        runtime = runtime_with(
            pool,
            slow=(ScriptedAdapter(GOOD, delay=0.4), 50),
            fast=(ScriptedAdapter(GOOD), 500),
        )
        results = runtime.evaluate(
            ["dp_slow", "dp_fast"], RequestScores(text="sí", lang="es")
        )
    assert results["dp_slow"].outcome == "unavailable"
    assert results["dp_slow"].confidence == 0.0 and results["dp_slow"].label is None
    assert results["dp_fast"].outcome == "decided"


def test_a_failing_backend_is_unavailable_and_its_message_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "Zorgblatt-4111111111111111"
    with ThreadPoolExecutor(max_workers=1) as pool, caplog.at_level(logging.DEBUG):
        runtime = runtime_with(
            pool,
            boom=(
                ScriptedAdapter(
                    GOOD, error=RuntimeError(f"bad output for text: {secret}")
                ),
                500,
            ),
        )
        result = runtime.evaluate(["dp_boom"], RequestScores(text=secret, lang="es"))[
            "dp_boom"
        ]
    assert result.outcome == "unavailable"
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_a_backend_that_breaks_the_distribution_contract_is_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with ThreadPoolExecutor(max_workers=1) as pool, caplog.at_level(logging.ERROR):
        runtime = runtime_with(
            pool,
            bad=(ScriptedAdapter({"confirm": 0.9, "deny": 0.9, "other": 0.9}), 500),
        )
        result = runtime.evaluate(["dp_bad"], RequestScores(text="sí", lang="es"))[
            "dp_bad"
        ]
    assert result.outcome == "unavailable"
    assert "broke its contract" in caplog.text


def test_a_shared_backend_runs_once_per_request() -> None:
    adapter = ScriptedAdapter(GOOD)
    with ThreadPoolExecutor(max_workers=1) as pool:
        scoring = ScoringBackend(
            "b", backend_spec(), adapter, ["confirm", "deny", "other"], pool
        )
        runtime = DecisionRuntime(
            source="artifact",
            config_version=None,
            decision_points={"dp_one": gate_dp(), "dp_two": gate_dp()},
            backends={"b": scoring},
            tau_raise={},
        )
        request = RequestScores(text="sí", lang="es")
        results = runtime.evaluate(["dp_one", "dp_two"], request)
        assert adapter.calls == 1
        assert (
            results["dp_one"].latency_ms > 0.0 and results["dp_two"].latency_ms == 0.0
        )
        runtime.evaluate(["dp_one"], RequestScores(text="sí", lang="es"))
        assert adapter.calls == 2  # a new request scores again


def test_compute_artifact_id_is_the_config_version() -> None:
    raw = json.loads(FIXTURE_ARTIFACT.read_text("utf-8"))
    assert raw["artifact_id"] == compute_artifact_id(raw)
