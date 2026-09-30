"""Adapter conformance: the checklist for a new decision backend (ADR-0012, Appendix C).

Run one kind while developing it:

    uv run pytest packages/encoder/tests/test_adapter_conformance.py -k <kind>

To add a model: implement ``DecisionAdapter`` (declare ``kind`` and
``probability_kind``), register it in ``encoder/registry.py``, then add ONE entry to
``BUILDERS`` below. ``test_every_registered_kind_has_a_conformance_builder`` fails
until you do, so a backend cannot ship unchecked.

What every adapter must satisfy:

1. It declares ``kind`` and ``probability_kind``.
2. ``predict([]) == []``.
3. Every label it returns is inside the contract labels it is used for.
4. ``distribution``: ``probabilities`` covers every label, is non-negative and sums
   to 1 (+/- 1e-3), and the top label and confidence agree with it.
5. ``top1_only``: the confidence is in [0, 1] (nothing else is promised).
6. Two calls give identical output, and a text alone gives what it gives in a batch.
7. Nothing it logs contains the text it was given.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from contracts.labels import Intent
from encoder import registry
from encoder.base import DecisionAdapter
from encoder.decision_points import SUM_TOLERANCE, BackendSpec
from encoder.models import DecisionPrediction
from encoder.registry import BackendPendingError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "decision_points.fixture.json"
# Distinct enough to find in a log line, and not something a model would emit.
SAMPLES = [
    "Me robaron la tarjeta terminada en 4321 (Zorgblatt-es)",
    "Não reconheço uma compra de R$ 120 (Zorgblatt-pt)",
    "yes, please block it (Zorgblatt-en)",
]
INTENTS = {i.value for i in Intent}
GATE = {"confirm", "deny", "other"}


@dataclass(frozen=True)
class Built:
    adapter: DecisionAdapter
    # The labels this adapter is used for; predictions must stay inside them.
    contract_labels: set[str]


def _fixture_backend(name: str) -> BackendSpec:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return BackendSpec.model_validate(raw["backends"][name])


def _tfidf_intents() -> Built:
    return Built(registry.build(_fixture_backend("intent_tfidf")), INTENTS)


def _tfidf_gate() -> Built:
    return Built(registry.build(_fixture_backend("gate_tfidf")), GATE)


def _gliner() -> Built:
    """Opt-in: needs the `gliner` extra and a local model directory."""
    model_dir = os.environ.get("ENCODER_CONFORMANCE_GLINER_MODEL")
    if not model_dir:
        pytest.skip(
            "gliner conformance needs the `gliner` extra and a local model: set "
            "ENCODER_CONFORMANCE_GLINER_MODEL to a directory with the weights"
        )
    pytest.importorskip("torch")
    from encoder.adapters.gliner import GLiNERAdapter

    return Built(GLiNERAdapter(model_id=model_dir, device="cpu"), INTENTS)


_HF_DIR: list[Path] = []


def _hf_seqcls() -> Built:
    """A tiny random DistilBERT, pinned and built through the registry."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from .tiny_hf import backend_spec_dict, build_pinned_dir

    if not _HF_DIR:
        _HF_DIR.append(build_pinned_dir(Path(tempfile.mkdtemp()) / "tiny-intent"))
    spec = BackendSpec.model_validate(backend_spec_dict(_HF_DIR[0]))
    return Built(registry.build(spec), INTENTS)


# One entry per registered kind. A new adapter adds its line here.
BUILDERS: dict[str, Callable[[], Built]] = {
    "tfidf_lr": _tfidf_intents,
    "tfidf_lr/gate": _tfidf_gate,
    "gliner": _gliner,
    "hf_seqcls": _hf_seqcls,
}
# Registered kinds that are promised but not implemented: they must say so.
PENDING_KINDS = {"llm_sidecar"}


def check_conformance(built: Built, caplog: pytest.LogCaptureFixture) -> None:
    adapter = built.adapter
    assert isinstance(adapter.kind, str) and adapter.kind, "declare `kind`"
    assert adapter.probability_kind in ("distribution", "top1_only")
    assert adapter.predict([]) == []

    with caplog.at_level(logging.DEBUG):
        first = adapter.predict(
            SAMPLES, candidate_intents=sorted(built.contract_labels)
        )
        second = adapter.predict(
            SAMPLES, candidate_intents=sorted(built.contract_labels)
        )
    assert len(first) == len(SAMPLES)
    assert first == second, "two calls must give identical output"

    for text in SAMPLES:
        assert text not in caplog.text, "an adapter must not log the text it is given"
        assert text.split("(")[-1] not in caplog.text

    for prediction in first:
        assert prediction.intent in built.contract_labels
        assert 0.0 <= prediction.confidence <= 1.0
        if adapter.probability_kind == "distribution":
            _check_distribution(prediction, built.contract_labels)

    alone = adapter.predict(
        SAMPLES[:1], candidate_intents=sorted(built.contract_labels)
    )[0]
    assert alone.intent == first[0].intent
    assert alone.confidence == pytest.approx(first[0].confidence, abs=1e-6)


def _check_distribution(prediction: DecisionPrediction, labels: set[str]) -> None:
    probs = prediction.probabilities
    assert labels <= set(probs), "a distribution covers every label"
    assert all(p >= 0.0 for p in probs.values())
    assert sum(probs.values()) == pytest.approx(1.0, abs=SUM_TOLERANCE)
    assert prediction.intent == max(probs, key=probs.__getitem__)
    assert prediction.confidence == pytest.approx(probs[prediction.intent], abs=1e-9)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_adapter_conforms(name: str, caplog: pytest.LogCaptureFixture) -> None:
    check_conformance(BUILDERS[name](), caplog)


def test_every_registered_kind_has_a_conformance_builder() -> None:
    covered = {name.split("/")[0] for name in BUILDERS} | PENDING_KINDS
    missing = set(registry.kinds()) - covered
    assert not missing, (
        f"registered kind(s) {sorted(missing)} have no entry in BUILDERS: add one so "
        "the adapter is checked (see this module's docstring)"
    )


@pytest.mark.parametrize("kind", sorted(PENDING_KINDS))
def test_pending_kinds_fail_loudly_with_the_pending_message(kind: str) -> None:
    spec = BackendSpec.model_validate(
        {
            "kind": kind,
            "model_id": f"{kind}@pending",
            "probability_kind": "distribution",
            "local_only": True,
            "timeout_ms": 1000,
        }
    )
    with pytest.raises(
        BackendPendingError, match=f"pending: {kind} is not implemented"
    ):
        registry.build(spec)


def test_the_declared_kind_matches_the_registry_key() -> None:
    for name in ("tfidf_lr", "tfidf_lr/gate"):
        assert BUILDERS[name]().adapter.kind == name.split("/")[0]


# --- The checklist itself is tested: a bad adapter must fail it ---


class _Broken(DecisionAdapter):
    kind = "broken"
    probability_kind = "distribution"

    def __init__(self, **flaws: Any) -> None:
        self.flaws = flaws
        self.calls = 0

    def fit(self, *args: Any, **kwargs: Any) -> None: ...
    def save(self, path: Any) -> None: ...
    def load(self, path: Any) -> None: ...

    def predict(
        self,
        texts: Any,
        candidate_intents: Any = None,
        candidate_slots: Any = None,
    ) -> list[DecisionPrediction]:
        if not texts:
            return []
        self.calls += 1
        out = []
        for text in texts:
            if self.flaws.get("logs_text"):
                logging.getLogger("broken").debug("predicting %s", text)
            probs = {"confirm": 0.5, "deny": 0.3, "other": 0.2}
            if self.flaws.get("bad_sum"):
                probs = {"confirm": 0.9, "deny": 0.9, "other": 0.9}
            label = self.flaws.get("label", "confirm")
            out.append(
                DecisionPrediction(
                    intent=label,
                    confidence=probs.get(label, 0.5),
                    probabilities=probs,
                )
            )
        if self.flaws.get("flaky") and self.calls % 2 == 0:
            out[0] = out[0].model_copy(update={"confidence": 0.51})
        return out


def test_a_conforming_adapter_passes_the_checklist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check_conformance(Built(_Broken(), GATE), caplog)


@pytest.mark.parametrize(
    "flaw",
    [
        {"logs_text": True},
        {"bad_sum": True},
        {"label": "not_a_contract_label"},
        {"flaky": True},
    ],
)
def test_a_flawed_adapter_fails_the_checklist(
    flaw: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(AssertionError):
        check_conformance(Built(_Broken(**flaw), GATE), caplog)
