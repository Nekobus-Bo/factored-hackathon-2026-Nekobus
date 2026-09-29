"""The backend registry: an artifact names a kind, the registry builds and pins it."""

from __future__ import annotations

import hashlib
import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from encoder import registry
from encoder.base import DecisionAdapter
from encoder.decision_points import BackendSpec, load_artifact
from encoder.pinning import PinError, PinMismatchError
from encoder.registry import (
    BackendBuildError,
    BackendPendingError,
    build,
    kinds,
    label_map_tag,
    tfidf_model_id,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "decision_points.fixture.json"


def fixture_backend(name: str = "intent_tfidf") -> dict[str, Any]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return raw["backends"][name]


def spec(**overrides: Any) -> BackendSpec:
    return BackendSpec.model_validate({**fixture_backend(), **overrides})


def test_the_freeze_kinds_are_registered() -> None:
    assert {"tfidf_lr", "gliner", "llm_sidecar"} <= set(kinds())


def test_registering_twice_or_empty_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register("tfidf_lr", lambda: lambda spec: None)  # type: ignore[arg-type, return-value]
    with pytest.raises(ValueError):
        registry.register("", lambda: lambda spec: None)  # type: ignore[arg-type, return-value]


def test_an_unknown_kind_lists_what_is_registered() -> None:
    with pytest.raises(
        BackendBuildError, match="unknown backend kind 'hf_seqcls'"
    ) as info:
        build(spec(kind="hf_seqcls"))
    assert "tfidf_lr" in str(info.value)


# --- tfidf_lr ---


def test_tfidf_builds_from_the_artifact_and_is_deterministic() -> None:
    first, second = build(spec()), build(spec())
    text = ["me robaron la tarjeta, bloquéenla ya"]
    assert first.kind == "tfidf_lr" and first.probability_kind == "distribution"
    assert first.predict(text) == second.predict(text)
    probs = first.predict(text)[0].probabilities
    assert set(probs) == {
        line["intent"]
        for line in map(
            json.loads,
            Path("packages/encoder/tests/fixtures/intent.train.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    assert sum(probs.values()) == pytest.approx(1.0)


def test_a_label_map_relabels_the_train_file() -> None:
    gate = build(BackendSpec.model_validate(fixture_backend("gate_tfidf")))
    probs = gate.predict(["sí, confirmo"])[0].probabilities
    assert set(probs) == {"confirm", "deny", "other"}
    assert sum(probs.values()) == pytest.approx(1.0)


def test_model_id_is_derived_from_the_train_hash_and_the_relabeling() -> None:
    sha = "a563c0c445d6" + "0" * 52
    assert tfidf_model_id(sha) == "tfidf_lr@train-sha256:a563c0c445d6"
    with_map = tfidf_model_id(sha, {"confirm": "confirm", "*": "other"})
    assert with_map.startswith("tfidf_lr@map-") and with_map.endswith(
        "/train-sha256:a563c0c445d6"
    )
    # A different relabeling of the same file is a different model.
    assert with_map != tfidf_model_id(sha, {"deny": "deny", "*": "other"})
    assert label_map_tag({"a": "b", "c": "d"}) == label_map_tag({"c": "d", "a": "b"})


def test_train_data_that_changed_since_calibration_is_a_pin_mismatch(
    tmp_path: Path,
) -> None:
    train = tmp_path / "train.jsonl"
    train.write_bytes(
        Path("packages/encoder/tests/fixtures/intent.train.jsonl").read_bytes()
    )
    sha = hashlib.sha256(train.read_bytes()).hexdigest()
    good = {
        **fixture_backend(),
        "train": {"path": str(train), "sha256": sha},
        "model_id": tfidf_model_id(sha),
    }
    assert build(BackendSpec.model_validate(good)).kind == "tfidf_lr"

    train.write_text(train.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PinMismatchError, match="changed since calibration"):
        build(BackendSpec.model_validate(good))


def test_a_model_id_that_does_not_match_the_train_block_is_a_pin_mismatch() -> None:
    with pytest.raises(PinMismatchError, match="its train block gives"):
        build(spec(model_id="tfidf_lr@train-sha256:000000000000"))


def test_tfidf_needs_its_train_block_and_a_file() -> None:
    with pytest.raises(BackendBuildError, match="needs a 'train' block"):
        build(spec(train=None))
    with pytest.raises(BackendBuildError, match="train data not found"):
        build(spec(train={"path": "/nonexistent/train.jsonl", "sha256": "0" * 64}))


def test_tfidf_with_no_train_rows_fails(tmp_path: Path) -> None:
    rows = tmp_path / "validation_only.jsonl"
    rows.write_text(
        json.dumps(
            {
                "id": "x",
                "text": "hola",
                "lang": "es",
                "intent": "greeting",
                "slots": [],
                "split": "validation",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sha = hashlib.sha256(rows.read_bytes()).hexdigest()
    with pytest.raises(BackendBuildError, match="no split=train rows"):
        build(
            spec(train={"path": str(rows), "sha256": sha}, model_id=tfidf_model_id(sha))
        )


# --- kind and probability_kind must match the artifact ---


class _Stub(DecisionAdapter):
    kind = "stub"
    probability_kind = "distribution"

    def fit(self, *args: Any, **kwargs: Any) -> None: ...
    def predict(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def save(self, path: Any) -> None: ...
    def load(self, path: Any) -> None: ...


def register_stub(
    monkeypatch: pytest.MonkeyPatch, adapter: Callable[[BackendSpec], DecisionAdapter]
) -> None:
    monkeypatch.setitem(registry._LOADERS, "stub", lambda: adapter)


def test_a_registered_kind_builds_through_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_stub(monkeypatch, lambda spec: _Stub())
    assert isinstance(build(spec(kind="stub")), _Stub)


def test_the_artifact_cannot_misdeclare_the_probability_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_stub(monkeypatch, lambda spec: _Stub())
    with pytest.raises(
        BackendBuildError, match="is 'distribution', but the artifact says"
    ):
        build(spec(kind="stub", probability_kind="top1_only", labels=["a"]))


def test_an_adapter_cannot_answer_to_another_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Liar(_Stub):
        kind = "something_else"

    register_stub(monkeypatch, lambda spec: Liar())
    with pytest.raises(BackendBuildError, match="declares kind"):
        build(spec(kind="stub"))


# --- llm_sidecar: interface only ---


def test_llm_sidecar_fails_as_pending() -> None:
    with pytest.raises(
        BackendPendingError,
        match=r"^pending: llm_sidecar is not implemented \(ADR-0012\)$",
    ):
        build(spec(kind="llm_sidecar", params={"url": "http://llm-local:8091"}))


# --- gliner ---


def gliner_spec(**overrides: Any) -> BackendSpec:
    return BackendSpec.model_validate(
        {
            "kind": "gliner",
            "model_id": "gliner:org/model@86741b4e3f5c",
            "revision": "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d",
            "probability_kind": "top1_only",
            "labels": ["confirm", "deny"],
            "local_only": True,
            "timeout_ms": 2000,
            "params": {"model": "org/model"},
            **overrides,
        }
    )


def test_gliner_without_its_extra_names_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "encoder.adapters.gliner", None)
    with pytest.raises(BackendBuildError, match="`gliner` extra"):
        build(gliner_spec())


def fake_gliner_module(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeGLiNER(DecisionAdapter):
        kind = "gliner"
        probability_kind = "top1_only"

        def __init__(self, model_id: str, name: str, device: str) -> None:
            calls.append({"model_id": model_id, "name": name, "device": device})

        def fit(self, *args: Any, **kwargs: Any) -> None: ...
        def predict(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

        def save(self, path: Any) -> None: ...
        def load(self, path: Any) -> None: ...

    module = types.ModuleType("encoder.adapters.gliner")
    module.GLiNERAdapter = FakeGLiNER  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "encoder.adapters.gliner", module)
    return calls


def test_gliner_loads_only_the_pinned_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = fake_gliner_module(monkeypatch)
    revision = "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d"
    snapshot = tmp_path / "models--org--model" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"weights")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))

    build(gliner_spec())
    assert calls == [
        {
            "model_id": str(snapshot),
            "name": "gliner:org/model@86741b4e3f5c",
            "device": "cpu",
        }
    ]

    with pytest.raises(PinMismatchError):
        build(gliner_spec(weights_sha256="1" * 64))


def test_gliner_without_a_pinned_revision_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_gliner_module(monkeypatch)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    with pytest.raises(PinError, match="needs a pinned revision"):
        build(gliner_spec(revision=None))
    with pytest.raises(PinError, match="full 40-hex commit"):
        build(gliner_spec(revision="main"))
    with pytest.raises(BackendBuildError, match="params.model"):
        build(gliner_spec(params={}))


def test_the_fixture_backends_are_all_buildable_kinds() -> None:
    artifact = load_artifact(FIXTURE)
    assert {backend.kind for backend in artifact.backends.values()} <= set(kinds())
