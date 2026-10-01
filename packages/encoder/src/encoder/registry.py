"""Registry of decision backends: an artifact names a ``kind``, this builds it.

A model that implements ``DecisionAdapter`` and declares its ``kind`` and
``probability_kind`` registers here once, and the service (and the harness) can
use it without further changes (ADR-0012, Appendix C). An artifact never names a
dotted import path, so a JSON file cannot make the service import arbitrary code.

Imports are lazy: ``tfidf_lr`` never loads PyTorch, and a kind whose dependencies
are missing fails with a message that names the extra to install.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from encoder.base import DecisionAdapter
from encoder.models import DecisionExample
from encoder.pinning import PinMismatchError, resolve_pinned_model

if TYPE_CHECKING:
    from encoder.decision_points import BackendSpec

logger = logging.getLogger(__name__)

Factory = Callable[["BackendSpec"], DecisionAdapter]


class BackendBuildError(RuntimeError):
    """A backend named by the artifact cannot be built. Never downgraded: the service
    stops. (A pin mismatch is a ``PinMismatchError`` and is handled apart.)"""


class BackendPendingError(BackendBuildError):
    """The backend is promised by ADR-0012 but not implemented (AGENTS.md, rule 7)."""


_LOADERS: dict[str, Callable[[], Factory]] = {}


def register(kind: str, loader: Callable[[], Factory]) -> None:
    """Register ``kind``. ``loader`` is called on first use and returns the factory,
    so importing this module never imports a model library."""
    if not kind or kind in _LOADERS:
        raise ValueError(f"backend kind {kind!r} is empty or already registered")
    _LOADERS[kind] = loader


def kinds() -> list[str]:
    return sorted(_LOADERS)


def build(spec: BackendSpec) -> DecisionAdapter:
    """Build (and, for ``tfidf_lr``, train) the adapter an artifact backend describes.

    Verifies the pin (``PinMismatchError``) and that the adapter's declared
    ``kind`` and ``probability_kind`` are what the artifact says.
    """
    loader = _LOADERS.get(spec.kind)
    if loader is None:
        raise BackendBuildError(
            f"unknown backend kind {spec.kind!r}; registered: {', '.join(kinds())}"
        )
    adapter = loader()(spec)
    if adapter.kind != spec.kind:
        raise BackendBuildError(
            f"adapter for {spec.kind!r} declares kind {adapter.kind!r}"
        )
    if adapter.probability_kind != spec.probability_kind:
        raise BackendBuildError(
            f"backend kind {spec.kind!r} is '{adapter.probability_kind}', "
            f"but the artifact says '{spec.probability_kind}'"
        )
    return adapter


# --- tfidf_lr ---


def label_map_tag(label_map: Mapping[str, str] | None) -> str:
    """Short id of a relabeling, so two of one train file differ in model_id."""
    canonical = json.dumps(dict(label_map or {}), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def tfidf_model_id(
    train_sha256: str, label_map: Mapping[str, str] | None = None
) -> str:
    """``tfidf_lr@train-sha256:<12>``, or ``tfidf_lr@map-<8>/train-sha256:<12>`` when a
    ``label_map`` relabels the train file. The harness and the loader both use this."""
    tag = f"map-{label_map_tag(label_map)}/" if label_map else ""
    return f"tfidf_lr@{tag}train-sha256:{train_sha256[:12]}"


def relabel(intent: str, label_map: Mapping[str, str] | None) -> str:
    if not label_map:
        return intent
    if intent in label_map:
        return label_map[intent]
    if "*" in label_map:
        return label_map["*"]
    return intent


def _build_tfidf(spec: BackendSpec) -> DecisionAdapter:
    from encoder.adapters import TFIDFLRAdapter

    if spec.train is None:
        raise BackendBuildError(
            "tfidf_lr: the backend needs a 'train' block (path, sha256)"
        )
    path = Path(spec.train.path)
    if not path.is_file():
        raise BackendBuildError(f"tfidf_lr: train data not found at {path}")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != spec.train.sha256:
        raise PinMismatchError(
            f"tfidf_lr: {path} hashes to {actual[:12]}..., the artifact pins "
            f"{spec.train.sha256[:12]}...; the train data changed since calibration"
        )
    model_id = tfidf_model_id(actual, spec.train.label_map)
    if spec.model_id != model_id:
        raise PinMismatchError(
            f"tfidf_lr: the artifact says model_id {spec.model_id!r}, "
            f"but its train block gives {model_id!r}"
        )
    examples = [
        DecisionExample(**json.loads(line))
        for line in data.decode("utf-8").splitlines()
        if line.strip()
    ]
    train = [
        example.model_copy(
            update={"intent": relabel(example.intent, spec.train.label_map)}
        )
        for example in examples
        if example.split == "train"
    ]
    if not train:
        raise BackendBuildError(f"tfidf_lr: no split=train rows in {path}")
    adapter = TFIDFLRAdapter(
        name=model_id, c_param=float(spec.params.get("c_param", 1.0))
    )
    adapter.fit(train)
    logger.info("tfidf_lr trained on %d rows (%s)", len(train), model_id)
    return adapter


def _load_tfidf() -> Factory:
    return _build_tfidf


# --- gliner ---


def _build_gliner(spec: BackendSpec) -> DecisionAdapter:
    try:
        from encoder.adapters.gliner import GLiNERAdapter
    except ImportError as exc:
        raise BackendBuildError(
            "gliner: dependencies missing; install encoder-service with the "
            "`gliner` extra (Docker: --build-arg ENCODER_EXTRAS=gliner)"
        ) from exc
    model = spec.params.get("model")
    if not isinstance(model, str) or not model:
        raise BackendBuildError(
            "gliner: params.model must name a hub id or a local directory"
        )
    # The pin is verified before the model loads, and the adapter is pointed at the
    # verified snapshot, so it cannot load a different revision.
    resolved = resolve_pinned_model(
        model, revision=spec.revision, expected_sha256=spec.weights_sha256
    )
    try:
        return GLiNERAdapter(
            model_id=str(resolved.path), name=spec.model_id, device="cpu"
        )
    except Exception as exc:
        raise BackendBuildError(
            f"gliner: cannot load {model!r}: {type(exc).__name__}"
        ) from exc


def _load_gliner() -> Factory:
    return _build_gliner


# --- hf_seqcls (ADR-0014) ---


def hf_seqcls_model_id(name: str, weights_sha256: str) -> str:
    """``hf_seqcls:<name>@sha256:<12 hex of the weights>``. The harness and the
    loader both use this."""
    return f"hf_seqcls:{name}@sha256:{weights_sha256[:12]}"


def _build_hf_seqcls(spec: BackendSpec) -> DecisionAdapter:
    from encoder.weights import verify_manifest

    model = spec.params.get("model")
    if not isinstance(model, str) or not model:
        raise BackendBuildError(
            "hf_seqcls: params.model must name the trained model directory"
        )
    if not Path(model).is_dir():
        raise BackendBuildError(
            f"hf_seqcls: {model!r} is not a directory; the encoder image carries it "
            "(ENCODER_WEIGHTS_IMAGE), or `make train-encoder` writes it locally"
        )
    # Pin chain (ADR-0014, Appendix A): weights SHA-256 and revision label, then the
    # manifest (every file hashed), then the label ids, all before the model loads.
    resolved = resolve_pinned_model(
        model, revision=spec.revision, expected_sha256=spec.weights_sha256
    )
    manifest = verify_manifest(resolved.path)
    if spec.revision != manifest.revision_label():
        raise PinMismatchError(
            f"hf_seqcls: the artifact pins revision {spec.revision!r}, the directory's "
            f"manifest gives {manifest.revision_label()!r}"
        )
    expected_id = hf_seqcls_model_id(manifest.name, resolved.weights_sha256)
    if spec.model_id != expected_id:
        raise PinMismatchError(
            f"hf_seqcls: the artifact says model_id {spec.model_id!r}, "
            f"the directory gives {expected_id!r}"
        )
    if manifest.kind != "hf_seqcls":
        raise BackendBuildError(
            f"hf_seqcls: {model!r} was trained as {manifest.kind!r}"
        )
    if spec.labels is not None and list(spec.labels) != manifest.labels:
        raise BackendBuildError(
            f"hf_seqcls: label drift: the artifact lists {spec.labels}, "
            f"the model's head is {manifest.labels}"
        )
    max_length = int(spec.params.get("max_length", manifest.max_length))
    if max_length != manifest.max_length:
        raise BackendBuildError(
            f"hf_seqcls: params.max_length {max_length} differs from the "
            f"{manifest.max_length} the model was calibrated with"
        )
    try:
        from encoder.adapters.hf_seqcls import HFSequenceClassifierAdapter
    except ImportError as exc:
        raise BackendBuildError(
            "hf_seqcls: dependencies missing; install encoder-service with the `hf` "
            'extra (Docker: --build-arg ENCODER_EXTRAS="embed hf")'
        ) from exc
    adapter = HFSequenceClassifierAdapter(
        name=spec.model_id,
        labels=manifest.labels,
        max_length=max_length,
        batch_size=int(spec.params.get("batch_size", 64)),
    )
    try:
        adapter.load(resolved.path)
    except Exception as exc:
        raise BackendBuildError(
            f"hf_seqcls: cannot load {model!r}: {type(exc).__name__}: {exc}"
        ) from exc
    return adapter


def _load_hf_seqcls() -> Factory:
    return _build_hf_seqcls


# --- llm_sidecar (interface only; the container is post-freeze) ---


def _load_llm_sidecar() -> Factory:
    from encoder.adapters.llm_sidecar import LLMSidecarAdapter

    def factory(spec: BackendSpec) -> DecisionAdapter:
        try:
            return LLMSidecarAdapter(spec)
        except NotImplementedError as exc:
            raise BackendPendingError(str(exc)) from exc

    return factory


register("tfidf_lr", _load_tfidf)
register("gliner", _load_gliner)
register("hf_seqcls", _load_hf_seqcls)
register("llm_sidecar", _load_llm_sidecar)
