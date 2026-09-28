"""Real backends behind /v1/analyze: tfidf_lr baseline and pluggable GLiNER."""

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import encoder_service.model_backends as model_backends
import pytest
from contracts.encoder import AnalyzeResponse
from contracts.labels import Intent
from encoder.models import DecisionPrediction, Slot
from encoder_service.backend import set_backend
from encoder_service.config import BackendSettings
from encoder_service.main import app
from encoder_service.model_backends import (
    BackendConfigError,
    GlinerBackend,
    TfidfLrBackend,
    build_backend,
    check_memory_floor,
)
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
TRAIN = REPO_ROOT / "data" / "eval" / "synthetic" / "decision.train.jsonl"

SAMPLES = {
    "es": "Me robaron la tarjeta terminada en 4321, bloquéenla ya",
    "pt": "Não reconheço uma compra de R$ 120 na Amazon ontem",
    "en": "The verification code is 819203",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for var in ("ENCODER_BACKEND", "ENCODER_MODEL", "ENCODER_DEVICE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENCODER_TRAIN_DATA", str(TRAIN))
    set_backend(None)
    yield
    set_backend(None)


BASE_SETTINGS = BackendSettings(
    backend="tfidf_lr", model=None, device="cpu", train_data=TRAIN
)


def _settings(**overrides: object) -> BackendSettings:
    return replace(BASE_SETTINGS, **overrides)


@pytest.fixture(scope="module")
def tfidf() -> TfidfLrBackend:
    return TfidfLrBackend(TRAIN)


def test_tfidf_serves_valid_responses_per_language(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENCODER_BACKEND", "tfidf_lr")
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.0")

    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        for lang, text in SAMPLES.items():
            resp = client.post("/v1/analyze", json={"text": text, "lang": lang})
            assert resp.status_code == 200, resp.text
            body = AnalyzeResponse.model_validate(resp.json())
            assert body.intent in set(Intent)
            assert body.model_id.startswith("tfidf_lr@train-sha256:")


def test_tfidf_regex_slots_reach_the_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENCODER_BACKEND", "tfidf_lr")
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.0")

    with TestClient(app) as client:
        body = client.post("/v1/analyze", json={"text": SAMPLES["pt"]}).json()

    slots = {(s["type"], s["value"]) for s in body["slots"]}
    assert {
        ("currency", "R$"),
        ("amount", "120"),
        ("transaction_date", "ontem"),
    } <= slots


def test_tau_still_gates_the_real_backend(monkeypatch: pytest.MonkeyPatch):
    """With tau unset the configured backend is built but /v1/analyze stays 503."""
    monkeypatch.setenv("ENCODER_BACKEND", "tfidf_lr")
    monkeypatch.delenv("ABSTENTION_THRESHOLD", raising=False)

    with TestClient(app) as client:
        assert client.post("/v1/analyze", json={"text": "hola"}).status_code == 503
        assert "uncalibrated" in client.get("/ready").json()["reason"]


def test_tfidf_is_deterministic(tfidf: TfidfLrBackend):
    other = TfidfLrBackend(TRAIN)
    for text in SAMPLES.values():
        assert tfidf.analyze(text) == other.analyze(text)
    assert tfidf.model_id == other.model_id


def test_unset_backend_keeps_service_unavailable():
    assert build_backend(_settings(backend=None)) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"backend": "bert"}, "unknown ENCODER_BACKEND"),
        ({"device": "cuda"}, "ENCODER_DEVICE must be 'cpu'"),
        ({"train_data": Path("/nonexistent/train.jsonl")}, "train data not found"),
        ({"backend": "gliner", "model": None}, "set ENCODER_MODEL"),
    ],
)
def test_bad_configuration_fails_loudly(overrides, reason):
    with pytest.raises(BackendConfigError, match=reason):
        build_backend(_settings(**overrides))


def test_bad_backend_aborts_startup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENCODER_BACKEND", "bert")
    with pytest.raises(BackendConfigError), TestClient(app):
        pass


class _FakeGliner:
    def __init__(self, slots: list[Slot], intent: str = "provide_identity_data"):
        self.slots = slots
        self.intent = intent
        self.calls: list[tuple[list[str], list[str]]] = []

    def predict(self, texts, candidate_intents=None, candidate_slots=None):
        self.calls.append((list(candidate_intents), list(candidate_slots)))
        return [
            DecisionPrediction(intent=self.intent, confidence=0.91, slots=self.slots)
            for _ in texts
        ]


def test_gliner_maps_pii_slots_to_pii_spans():
    text = "Soy Ana Ruiz, ana@example.com, tarjeta 4321"
    fake = _FakeGliner(
        [
            Slot(type="full_name", value="Ana Ruiz", start=4, end=12),
            Slot(type="email", value="ana@example.com", start=14, end=29),
            Slot(type="card_last4", value="4321", start=39, end=43),
        ]
    )
    backend = GlinerBackend("org/model", load_adapter=lambda _: fake)

    result = backend.analyze(text)

    assert result.model_id == "gliner:org/model"
    assert [(p.type, p.start, p.end) for p in result.pii_spans] == [
        ("NAME", 4, 12),
        ("EMAIL", 14, 29),
    ]
    intents, slots = fake.calls[0]
    assert set(intents) == {i.value for i in Intent}
    assert "otp_code" in slots


def test_gliner_unknown_label_is_rejected_by_the_api(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ABSTENTION_THRESHOLD", "0.5")
    fake = _FakeGliner([Slot(type="iban", value="ES12", start=0, end=4)])
    set_backend(GlinerBackend("org/model", load_adapter=lambda _: fake))

    with TestClient(app) as client:
        resp = client.post("/v1/analyze", json={"text": "ES12 abc"})

    assert resp.status_code == 500
    assert "unknown slot type" in resp.json()["detail"]


def test_gliner_load_failure_names_the_model():
    def boom(model: str):
        raise OSError("repository not found")

    with pytest.raises(BackendConfigError, match="cannot load model 'org/missing'"):
        GlinerBackend("org/missing", load_adapter=boom)


def test_tfidf_maps_regex_pii_slots_to_pii_spans(tfidf: TfidfLrBackend):
    text = "el código que me llegó es 482913"
    result = tfidf.analyze(text)

    assert [(s.type, s.value) for s in result.slots] == [("otp_code", "482913")]
    assert [(p.type, text[p.start : p.end]) for p in result.pii_spans] == [
        ("OTP", "482913")
    ]


def test_tfidf_non_pii_slots_have_no_pii_spans(tfidf: TfidfLrBackend):
    result = tfidf.analyze("bloqueen la tarjeta terminada en 4321")
    assert [s.type for s in result.slots] == ["card_last4"]
    assert result.pii_spans == []


GIB = 1024 * 1024 * 1024


def test_gliner_refused_below_memory_floor(tmp_path, monkeypatch):
    memory_max = tmp_path / "memory.max"
    memory_max.write_text(f"{3 * GIB}\n")
    monkeypatch.setattr(model_backends, "CGROUP_MEMORY_MAX", memory_max)

    with pytest.raises(BackendConfigError, match="3072 MiB, below the 4096 MiB"):
        build_backend(_settings(backend="gliner", model="org/model"))


def test_memory_floor_passes_at_the_limit(tmp_path):
    memory_max = tmp_path / "memory.max"
    memory_max.write_text(f"{4 * GIB}\n")
    check_memory_floor(4096, memory_max)


@pytest.mark.parametrize("content", ["max\n", None])
def test_memory_floor_unchecked_starts_with_warning(tmp_path, caplog, content):
    memory_max = tmp_path / "memory.max"
    if content is not None:
        memory_max.write_text(content)

    with caplog.at_level("WARNING", logger="encoder_service.model_backends"):
        check_memory_floor(4096, memory_max)

    assert "memory floor unchecked" in caplog.text


def test_memory_floor_is_configurable(monkeypatch):
    from encoder_service.config import get_backend_settings

    monkeypatch.setenv("ENCODER_GLINER_MIN_MEMORY_MB", "2048")
    assert get_backend_settings().gliner_min_memory_mb == 2048
    monkeypatch.setenv("ENCODER_GLINER_MIN_MEMORY_MB", "4g")
    with pytest.raises(ValueError, match="must be an integer"):
        get_backend_settings()
