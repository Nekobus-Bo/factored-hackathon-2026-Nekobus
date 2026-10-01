"""Shared test setup for the calibration harness.

The decision-points task never imports PyTorch, so its tests must run anywhere. A few
older tests exercise the GLiNER and sentence-transformers adapters; where PyTorch is
not installed (a sandbox that cannot reach the PyTorch wheel index) they are skipped
here instead of failing at collection. CI installs PyTorch and runs all of them.
"""

from __future__ import annotations

import importlib.util

import pytest

HAS_TORCH = importlib.util.find_spec("torch") is not None

# Whole modules that import a PyTorch adapter at the top.
collect_ignore: list[str] = [] if HAS_TORCH else ["test_adapter_failures.py"]

# Individual tests whose candidates load a PyTorch model.
_NEEDS_TORCH = {
    "test_runner_smoke.py::test_runner_decision_smoke",
    "test_runner_smoke.py::test_runner_embedding_smoke",
}


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if HAS_TORCH:
        return
    skip = pytest.mark.skip(reason="needs PyTorch (not installed here)")
    for item in items:
        if any(item.nodeid.endswith(name) for name in _NEEDS_TORCH):
            item.add_marker(skip)


# --- Builders for artifact fragments (plain dicts, as the harness writes them) ---

SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture
def make_backend():
    """A valid ``tfidf_lr`` backend spec as a plain dict."""

    def make(
        sha: str = SHA_A,
        label_map: dict[str, str] | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        from encoder.registry import tfidf_model_id

        train: dict = {"path": "data/train.jsonl", "sha256": sha}
        if label_map:
            train["label_map"] = label_map
        spec: dict = {
            "kind": "tfidf_lr",
            "model_id": tfidf_model_id(sha, label_map),
            "train": train,
            "probability_kind": "distribution",
            "local_only": True,
            "cost_class": "low",
            "timeout_ms": 200,
            "params": {},
        }
        if labels:
            spec["labels"] = labels
        return spec

    return make


@pytest.fixture
def make_entry():
    """A valid decision-point entry as a plain dict."""

    def make(
        backend: str = "intent",
        labels: tuple[str, ...] = ("a", "b"),
        tau: float | None = 0.5,
        run_id: str = "run000000001",
    ) -> dict:
        return {
            "backend": backend,
            "view": {"kind": "labels", "labels": list(labels)},
            "enabled": True,
            "always_on": True,
            "calibrator": {"kind": "temperature", "by_lang": {"es": {"T": 0.5}}},
            "thresholds": {"es": tau, "pt": None},
            "status": "calibrated",
            "evidence": {"run_id": run_id, "report": f"reports/{run_id}.md"},
        }

    return make


# --- A tiny repository for end-to-end runs of the decision-points task ---

_WORDS = {
    "confirm": {
        "en": ["yes", "sure", "okay", "please", "do it", "go ahead"],
        "es": ["si", "claro", "vale", "adelante", "hazlo", "dale"],
        "pt": ["sim", "claro", "certo", "pode", "faca", "vai"],
    },
    "deny": {
        "en": ["no", "nope", "never", "dont", "stop", "cancel"],
        "es": ["no", "nunca", "para", "cancela", "jamas", "deja"],
        "pt": ["nao", "nunca", "pare", "cancela", "jamais", "deixa"],
    },
    "lost": {
        "en": ["lost", "misplaced", "cannot find", "missing", "my card", "wallet"],
        "es": ["perdi", "extravie", "no encuentro", "falta", "mi tarjeta", "cartera"],
        "pt": ["perdi", "extraviei", "nao acho", "sumiu", "meu cartao", "carteira"],
    },
    "stolen": {
        "en": ["stolen", "robbed", "thief", "mugged", "took my", "pickpocket"],
        "es": ["robaron", "asaltaron", "ladron", "hurto", "se llevaron", "carterista"],
        "pt": ["roubaram", "assaltaram", "ladrao", "furto", "levaram", "batedor"],
    },
    "greeting": {
        "en": ["hello", "hi", "good morning", "hey", "greetings", "howdy"],
        "es": ["hola", "buenas", "buen dia", "saludos", "que tal", "ey"],
        "pt": ["ola", "oi", "bom dia", "salve", "e ai", "opa"],
    },
}
INTENTS = list(_WORDS)
LANGS = ("es", "pt", "en")


def _rows(split: str, per: int, seed: int, noise: float, source: str) -> list[dict]:
    import random

    rng = random.Random(seed)
    rows = []
    for lang in LANGS:
        for intent in INTENTS:
            for i in range(per):
                words = rng.sample(_WORDS[intent][lang], 2)
                if rng.random() < noise:
                    other = rng.choice([x for x in INTENTS if x != intent])
                    words.append(rng.choice(_WORDS[other][lang]))
                rng.shuffle(words)
                rows.append(
                    {
                        "id": f"{split}-{lang}-{intent}-{i}",
                        "text": " ".join(words),
                        "lang": lang,
                        "intent": intent,
                        "slots": [],
                        "split": split,
                        "source": source,
                    }
                )
    return rows


TINY_CONFIG = """
task: decision-points
languages: [es, pt, en]
artifact: packages/encoder/calibration/decision_points.json
calibrator_min_rows: 20
data:
  train: data/train.jsonl
  validation: data/validation.jsonl
  test: data/test.jsonl
backends:
  intent_tfidf: {kind: tfidf_lr, timeout_ms: 200}
  gate_tfidf: {kind: tfidf_lr, timeout_ms: 200}
decision_points:
  intent:
    candidates: [intent_tfidf]
    view: {kind: labels, labels: [confirm, deny, lost, stolen, greeting]}
    calibrator: temperature
    threshold_scope: per_language
    constraint:
      labels: [lost, stolen]
      p_min: 0.8
      ci: point
      n_min: 10
  gate:
    candidates: [gate_tfidf]
    label_map: {confirm: confirm, deny: deny, "*": other}
    view: {kind: labels, labels: [confirm, deny, other]}
    calibrator: temperature
    threshold_scope: per_language_per_label
    constraint:
      p_min: {confirm: 0.9, deny: 0.8}
      ci: point
      n_min: 10
  reason:
    candidates: [intent_tfidf]
    view:
      kind: groups
      groups: {LOST: [lost], STOLEN: [stolen]}
    calibrator: temperature
    threshold_scope: per_label_pooled
    constraint: {p_min: 0.8, ci: point, n_min: 30}
"""


class TinyRepo:
    """A repository root with data, a config and a ``reports/`` directory."""

    def __init__(self, root) -> None:
        import json

        self.root = root
        (root / "data").mkdir()
        (root / "reports").mkdir()
        (root / "packages/encoder/calibration").mkdir(parents=True)
        for split, per, seed, noise, source in (
            ("train", 30, 1, 0.15, "synthetic"),
            ("validation", 12, 2, 0.25, "synthetic"),
            ("test", 12, 3, 0.35, "synthetic-provisional"),
        ):
            rows = _rows(split, per, seed, noise, source)
            (root / f"data/{split}.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
        self.config = root / "tools/calibrate/configs/decision_points.yaml"
        self.write_config(TINY_CONFIG)

    def write_config(self, text: str) -> None:
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(text, encoding="utf-8")

    @property
    def committed(self):
        return self.root / "packages/encoder/calibration/decision_points.json"


@pytest.fixture
def tiny_repo(tmp_path, monkeypatch) -> TinyRepo:
    """Data paths in the artifact are relative to the working directory, as in the
    service, so runs happen from the tiny repository's root."""
    repo = TinyRepo(tmp_path)
    monkeypatch.chdir(tmp_path)
    return repo


@pytest.fixture
def tiny_config_text() -> str:
    return TINY_CONFIG
