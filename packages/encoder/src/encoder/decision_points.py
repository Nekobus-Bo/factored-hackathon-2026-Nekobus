"""Decision points: the calibration artifact and the pure logic that turns one
backend's output into one decision (ADR-0012).

A decision point (DP) is data. Its backend, label view, confidence calibrator,
threshold (tau) per language and evidence live in one calibration artifact,
written by the harness and read by the encoder service at startup. This module
holds:

* the artifact schema (``schema_version: 1``, Appendix B.3), its canonical id
  and a fail-loud loader;
* ``decide``, a pure function from a backend's probabilities to an outcome.
  It never touches a model, a file or the network, so every rule is unit-tested.

Nothing here decides *what to do* with a decision. That is the orchestrator's
effects (Appendix E); a decision only records what a calibrated model said.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from contracts.locale import LOCALES, lang_of
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from encoder.base import ProbabilityKind

SCHEMA_VERSION = 1
# Relative to the working directory (the repo root, /app in the image), like
# ENCODER_TRAIN_DATA. DECISION_POINTS_FILE overrides it.
DEFAULT_ARTIFACT_PATH = "packages/encoder/calibration/decision_points.json"
# Registry kind of the seed backend: the encoder's own legacy intent result.
LEGACY_KIND = "legacy_encoder"
SEED_BACKEND_ID = "legacy"
DP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
# A threshold or calibrator key: a language ("es"), a locale ("es-MX", ADR-0014) or
# "*". Lookup goes locale -> language -> "*" (resolve_key).
LANG_KEY_PATTERN = re.compile(r"^(\*|[a-z]{2}|[a-z]{2}-[A-Z]{2})$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# A backend that says it returns a distribution must sum to 1 within this.
SUM_TOLERANCE = 1e-3
_EPS = 1e-12
_MAX_TEMPERATURE = 100.0


class ArtifactError(ValueError):
    """The calibration artifact is invalid or cannot be used. The message says what
    to fix and never includes customer text (it has none)."""


# --- Artifact schema ---


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Harness(_Model):
    git_sha: str | None = None
    config_path: str | None = None
    config_sha256: str | None = None


class DataRefs(_Model):
    train_sha256: str | None = None
    validation_sha256: str | None = None
    test_sha256: str | None = None
    test_provenance: Literal["human", "synthetic", "synthetic-provisional"] | None = (
        None
    )


class TrainSpec(_Model):
    """Where a ``tfidf_lr`` backend trains from: the model is a pure function of it."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN.pattern)
    # Relabels the train file's `intent` (e.g. confirm / deny / everything else);
    # "*" is the default label.
    label_map: dict[str, str] | None = None


class Resources(_Model):
    ram_mb: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    measured_on: str | None = None


class BackendSpec(_Model):
    kind: str = Field(
        min_length=1, max_length=64, description="Key in encoder.registry"
    )
    model_id: str = Field(min_length=1, max_length=128)
    revision: str | None = None
    weights_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN.pattern)
    train: TrainSpec | None = None
    probability_kind: ProbabilityKind
    labels: list[str] | None = Field(
        default=None,
        description="Label space of the backend; required when top1_only",
    )
    local_only: bool = Field(
        description="Must be true: raw text never leaves our containers"
    )
    cost_class: Literal["low", "high"] = "low"
    timeout_ms: int = Field(ge=1, le=60_000)
    params: dict[str, Any] = Field(default_factory=dict)
    resources: Resources | None = None

    @field_validator("local_only")
    @classmethod
    def _must_be_local(cls, value: bool) -> bool:
        if not value:
            raise ValueError("local_only must be true (ADR-0012, I4)")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("labels must be a non-empty list without repeats")
        return value


class LabelsView(_Model):
    kind: Literal["labels"]
    labels: list[str] = Field(min_length=1)

    @field_validator("labels")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("view labels must not repeat")
        return value


class GroupsView(_Model):
    kind: Literal["groups"]
    groups: dict[str, list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def _disjoint(self) -> GroupsView:
        seen: set[str] = set()
        for name, members in self.groups.items():
            if not members:
                raise ValueError(f"group '{name}' has no members")
            for member in members:
                if member in seen:
                    raise ValueError(f"'{member}' belongs to more than one group")
                seen.add(member)
        return self


View = Annotated[LabelsView | GroupsView, Field(discriminator="kind")]


class CalibratorSpec(_Model):
    kind: Literal["none", "temperature", "isotonic"] = "none"
    by_lang: dict[str, dict[str, float]] = Field(default_factory=dict)


# A scalar applies to every label; null is infeasible; a mapping is per label.
Threshold = float | dict[str, float | None] | None


class DecisionPointSpec(_Model):
    backend: str
    view: View
    enabled: bool = True
    always_on: bool = True
    calibrator: CalibratorSpec = Field(default_factory=CalibratorSpec)
    thresholds: dict[str, Threshold] = Field(default_factory=dict)
    constraint: dict[str, Any] | None = None
    status: Literal["calibrated", "infeasible", "uncalibrated_seed"]
    evidence: dict[str, Any] = Field(default_factory=dict)
    escalate_to: str | None = None

    @model_validator(mode="after")
    def _self_consistent(self) -> DecisionPointSpec:
        if self.escalate_to is not None:
            raise ValueError(
                "pending: cascading (escalate_to) is not implemented (ADR-0012)"
            )
        if self.calibrator.kind == "isotonic":
            raise ValueError(
                "pending: isotonic calibrator is not implemented (ADR-0012)"
            )
        for lang in self.calibrator.by_lang:
            _check_key(lang, "calibrator")
        if self.calibrator.kind == "temperature":
            for lang, params in self.calibrator.by_lang.items():
                if set(params) != {"T"} or not 0 < params["T"] <= _MAX_TEMPERATURE:
                    raise ValueError(
                        f"temperature calibrator for '{lang}' needs exactly T in (0, "
                        f"{_MAX_TEMPERATURE:g}]"
                    )
        labels = set(view_labels(self))
        for lang, entry in self.thresholds.items():
            _check_key(lang, "threshold")
            if isinstance(entry, float) and not 0.0 <= entry <= 1.0:
                raise ValueError(f"threshold for '{lang}' must be within [0, 1]")
            if isinstance(entry, dict):
                for label, tau in entry.items():
                    if label != "*" and label not in labels:
                        raise ValueError(
                            f"threshold for '{lang}' names '{label}', not in the view"
                        )
                    if tau is not None and not 0.0 <= tau <= 1.0:
                        raise ValueError(
                            f"threshold for '{lang}.{label}' must be within [0, 1]"
                        )
        if self.calibrator.kind != "none":
            # A locale tau was fitted on scores calibrated with that locale's T, so it
            # never travels without it (ADR-0014).
            cal = {k for k in self.calibrator.by_lang if k in LOCALES}
            thr = {k for k in self.thresholds if k in LOCALES}
            if not thr <= cal:
                raise ValueError(
                    f"threshold locale keys {sorted(thr - cal)} have no calibrator "
                    "entry; a locale tau needs the locale's temperature"
                )
        return self


def _check_key(key: str, what: str) -> None:
    if not LANG_KEY_PATTERN.match(key) or ("-" in key and key not in LOCALES):
        raise ValueError(
            f"{what} key {key!r} must be a language ('es'), one of the locales "
            f"{list(LOCALES)} or '*'"
        )


def resolve_key(
    keys: Mapping[str, Any], lang: str | None, locale: str | None = None
) -> str | None:
    """The first key present among ``locale``, ``lang`` and ``"*"`` (ADR-0014).

    Presence is what counts: a key present with ``null`` is chosen, so an infeasible
    locale abstains instead of falling back to its language.
    """
    for key in (locale, lang, "*"):
        if key is not None and key in keys:
            return key
    return None


class DecisionPointsArtifact(_Model):
    """``packages/encoder/calibration/decision_points.json`` (Appendix B.3)."""

    schema_version: Literal[1]
    artifact_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    created_at: str | None = None
    harness: Harness | None = None
    data: DataRefs | None = None
    backends: dict[str, BackendSpec] = Field(min_length=1)
    decision_points: dict[str, DecisionPointSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_references(self) -> DecisionPointsArtifact:
        for dp_id, dp in self.decision_points.items():
            if not DP_ID_PATTERN.match(dp_id):
                raise ValueError(
                    f"decision point id {dp_id!r} must match {DP_ID_PATTERN.pattern}"
                )
            backend = self.backends.get(dp.backend)
            if backend is None:
                raise ValueError(
                    f"decision point '{dp_id}' names unknown backend '{dp.backend}'"
                )
            check_view_against_backend(dp_id, dp, backend)
        return self


def view_labels(dp: DecisionPointSpec) -> list[str]:
    """The labels a DP can decide (a group's name for a groups view)."""
    view = dp.view
    return list(view.labels) if isinstance(view, LabelsView) else list(view.groups)


def view_members(dp: DecisionPointSpec) -> set[str]:
    """The backend labels the view reads."""
    view = dp.view
    if isinstance(view, LabelsView):
        return set(view.labels)
    return {member for members in view.groups.values() for member in members}


def check_view_against_backend(
    dp_id: str, dp: DecisionPointSpec, backend: BackendSpec
) -> None:
    """Rules tying a view and a calibrator to what the backend can supply."""
    if backend.probability_kind == "top1_only":
        if not isinstance(dp.view, LabelsView):
            raise ValueError(
                f"decision point '{dp_id}': a top1_only backend needs a labels view"
            )
        if dp.calibrator.kind != "none":
            raise ValueError(
                f"decision point '{dp_id}': a top1_only backend cannot be calibrated "
                "(its probabilities are not a distribution)"
            )
        if backend.labels is None:
            raise ValueError(
                f"backend of '{dp_id}' is top1_only and must declare its labels"
            )
        if set(dp.view.labels) != set(backend.labels):
            raise ValueError(
                f"decision point '{dp_id}': a top1_only backend serves its own labels"
            )
    elif backend.labels is not None:
        unknown = view_members(dp) - set(backend.labels)
        if unknown:
            raise ValueError(
                f"decision point '{dp_id}' reads {sorted(unknown)}, not in its backend"
            )


# --- Canonical id, loading and writing ---


def compute_artifact_id(raw: Mapping[str, Any]) -> str:
    """First 12 hex of the SHA-256 of the canonical JSON without ``artifact_id``."""
    body = {key: value for key, value in raw.items() if key != "artifact_id"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def with_artifact_id(raw: Mapping[str, Any]) -> dict[str, Any]:
    """``raw`` with its ``artifact_id`` (re)computed. What a writer calls last."""
    return {
        **{k: v for k, v in raw.items() if k != "artifact_id"},
        "artifact_id": compute_artifact_id(raw),
    }


def parse_artifact(raw: Any, source: str = "artifact") -> DecisionPointsArtifact:
    """Validate a decoded artifact, including that its id matches its content."""
    if not isinstance(raw, dict):
        raise ArtifactError(f"{source}: the top level must be a JSON object")
    stated = raw.get("artifact_id")
    if stated != compute_artifact_id(raw):
        raise ArtifactError(
            f"{source}: artifact_id {stated!r} does not match its content "
            f"({compute_artifact_id(raw)}); it was edited by hand. Recalibrate instead"
        )
    try:
        return DecisionPointsArtifact.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        raise ArtifactError(
            f"{source}: invalid calibration artifact: {problems}"
        ) from exc


def load_artifact(path: Path | str) -> DecisionPointsArtifact:
    """Read and validate the artifact file. Raises ``ArtifactError`` with the path."""
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ArtifactError(
            f"{file}: cannot read the calibration artifact ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(
            f"{file}: not valid JSON ({exc.msg} at line {exc.lineno})"
        ) from exc
    return parse_artifact(raw, str(file))


def artifact_to_json(artifact: DecisionPointsArtifact | Mapping[str, Any]) -> str:
    """Deterministic file content for an artifact, with its id recomputed.

    Sorted keys, two-space indent, trailing newline: a diff shows only what changed.
    """
    raw = (
        artifact.model_dump(mode="json")
        if isinstance(artifact, DecisionPointsArtifact)
        else dict(artifact)
    )
    return (
        json.dumps(with_artifact_id(raw), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def artifact_json_schema() -> dict[str, Any]:
    """The JSON Schema of the artifact, published next to it for the harness."""
    return DecisionPointsArtifact.model_json_schema()


# --- Deciding ---


@dataclass(frozen=True)
class Decision:
    """The outcome of ``decide``. Plain data; the service maps it to the contract."""

    outcome: Literal["decided", "abstained", "infeasible", "off"]
    label: str | None = None
    confidence: float = 0.0
    raw_confidence: float | None = None
    runner_up: tuple[str, float] | None = None
    tau: float | None = None
    tau_source: Literal["artifact", "override", "seed"] | None = None


def check_distribution(probabilities: Mapping[str, float], needed: set[str]) -> None:
    """Enforce the ``distribution`` contract on one prediction (else ``ValueError``)."""
    missing = needed - set(probabilities)
    if missing:
        raise ValueError(f"backend omitted labels {sorted(missing)}")
    values = list(probabilities.values())
    if not all(math.isfinite(v) and v >= 0.0 for v in values):
        raise ValueError("backend returned a negative or non-finite probability")
    if abs(sum(values) - 1.0) > SUM_TOLERANCE:
        raise ValueError(f"probabilities sum to {sum(values):.4f}, not 1")


def apply_temperature(
    probabilities: Mapping[str, float], temperature: float
) -> dict[str, float]:
    """``p_i ** (1 / T)`` renormalized. T < 1 sharpens an under-confident model."""
    scaled = {k: math.log(max(v, _EPS)) / temperature for k, v in probabilities.items()}
    top = max(scaled.values())
    exps = {k: math.exp(v - top) for k, v in scaled.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def _calibrate(
    dp: DecisionPointSpec,
    probabilities: Mapping[str, float],
    lang: str | None,
    locale: str | None = None,
) -> tuple[dict[str, float], bool]:
    """Calibrated distribution, and whether the calibrator applies to this language."""
    if dp.calibrator.kind == "none":
        return dict(probabilities), True
    key = resolve_key(dp.calibrator.by_lang, lang, locale)
    if key is None:
        return dict(probabilities), False
    return apply_temperature(probabilities, dp.calibrator.by_lang[key]["T"]), True


def _aggregate(
    dp: DecisionPointSpec, probabilities: Mapping[str, float]
) -> dict[str, float]:
    view = dp.view
    if isinstance(view, LabelsView):
        return {label: probabilities[label] for label in view.labels}
    # Never renormalized over the view: mass outside it lowers every confidence.
    return {
        name: min(1.0, sum(probabilities[m] for m in members))
        for name, members in view.groups.items()
    }


def resolve_threshold(
    dp_id: str,
    dp: DecisionPointSpec,
    lang: str | None,
    label: str,
    raises: Mapping[tuple[str, str], float] | None = None,
    locale: str | None = None,
) -> tuple[float | None, Literal["artifact", "override", "seed"] | None]:
    """The tau for ``label`` in ``locale`` / ``lang`` and its source; ``(None, None)``
    if none.

    Keys are tried locale, then language, then ``"*"`` (``resolve_key``). A key that
    is present with ``null`` is infeasible and does not fall back; a key that is
    absent does. A per-label mapping without the label (and without ``"*"``) has no
    tau for it.
    """
    key = resolve_key(dp.thresholds, lang, locale)
    if key is None:
        return None, None
    entry = dp.thresholds[key]
    if isinstance(entry, dict):
        entry = entry.get(label, entry.get("*"))
    if entry is None:
        return None, None
    tau = float(entry)
    source: Literal["artifact", "override", "seed"] = (
        "seed" if dp.status == "uncalibrated_seed" else "artifact"
    )
    if raises:
        keys = ((dp_id, locale or ""), (dp_id, lang or ""), (dp_id, "*"))
        wanted = [raises[k] for k in keys if k in raises]
        if wanted and max(wanted) > tau:
            return max(wanted), "override"
    return tau, source


def decide(
    dp_id: str,
    dp: DecisionPointSpec,
    *,
    probabilities: Mapping[str, float] | None = None,
    top1: tuple[str, float] | None = None,
    lang: str | None = None,
    raises: Mapping[tuple[str, str], float] | None = None,
    probability_kind: ProbabilityKind = "distribution",
    locale: str | None = None,
) -> Decision:
    """One decision from one backend output. Pure.

    ``distribution``: ``probabilities`` over the backend's whole label space.
    ``top1_only``: ``top1`` is the (label, confidence) the backend is sure about.
    Raises ``ValueError`` when the backend broke its contract; the caller reports
    the DP as unavailable.
    """
    if not dp.enabled:
        return Decision(outcome="off")
    if dp.status == "infeasible":
        return Decision(outcome="infeasible")

    calibrated_ok = True
    if probability_kind == "top1_only":
        if top1 is None:
            raise ValueError("a top1_only backend must supply its top label")
        label, confidence = top1
        if label not in view_labels(dp):
            raise ValueError(
                "backend returned a label outside the decision point's labels"
            )
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("backend returned a confidence outside [0, 1]")
        raw_scores = scores = {label: confidence}
    else:
        if probabilities is None:
            raise ValueError("a distribution backend must supply probabilities")
        check_distribution(probabilities, view_members(dp))
        raw_scores = _aggregate(dp, probabilities)
        calibrated, calibrated_ok = _calibrate(dp, probabilities, lang, locale)
        scores = _aggregate(dp, calibrated)

    order = {name: index for index, name in enumerate(view_labels(dp))}
    ranked = sorted(scores, key=lambda name: (-scores[name], order[name]))
    top = ranked[0]
    runner_up = (ranked[1], scores[ranked[1]]) if len(ranked) > 1 else None
    confidence = scores[top]
    raw_confidence = raw_scores.get(top)

    tau, tau_source = (None, None)
    if calibrated_ok:
        tau, tau_source = resolve_threshold(dp_id, dp, lang, top, raises, locale)
    if tau is None or confidence < tau:
        return Decision(
            outcome="abstained",
            confidence=confidence,
            raw_confidence=raw_confidence,
            runner_up=runner_up,
            tau=tau,
            tau_source=tau_source,
        )
    return Decision(
        outcome="decided",
        label=top,
        confidence=confidence,
        raw_confidence=raw_confidence,
        runner_up=runner_up,
        tau=tau,
        tau_source=tau_source,
    )


# --- Raise-only tau overrides (DECISION_POINTS_TAU_RAISE) ---


def parse_tau_raise(raw: str | None) -> dict[tuple[str, str], float]:
    """``'confirm_gate.es=0.97,x.*=0.5'`` -> ``{('confirm_gate','es'): 0.97, ...}``."""
    raises: dict[tuple[str, str], float] = {}
    if raw is None or not raw.strip():
        return raises
    for item in raw.split(","):
        key, _, value = item.strip().partition("=")
        dp_id, _, lang = key.partition(".")
        if not DP_ID_PATTERN.match(dp_id) or not LANG_KEY_PATTERN.match(lang):
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE entry {item.strip()!r} must look like "
                "'<decision_point>.<key>=<tau>' (key is a language such as 'es', a "
                "locale such as 'es-MX', or '*')"
            )
        try:
            tau = float(value)
        except ValueError as exc:
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE entry {item.strip()!r}: not a number"
            ) from exc
        if not 0.0 <= tau <= 1.0:
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE entry {item.strip()!r}: tau not in [0, 1]"
            )
        raises[(dp_id, lang)] = tau
    return raises


def check_tau_raise(
    decision_points: Mapping[str, DecisionPointSpec],
    raises: Mapping[tuple[str, str], float],
) -> None:
    """Refuse an override that names an unknown DP or raises nothing (raise-only)."""
    for (dp_id, lang), value in raises.items():
        dp = decision_points.get(dp_id)
        if dp is None:
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE names unknown decision point '{dp_id}'"
            )
        locale = lang if lang in LOCALES else None
        entry_lang = resolve_key(
            dp.thresholds, lang_of(lang) if locale else lang, locale
        )
        if entry_lang is None:
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE: '{dp_id}' has no '{lang}' tau to raise"
            )
        entry = dp.thresholds[entry_lang]
        taus = (
            [entry]
            if isinstance(entry, float)
            else [t for t in entry.values() if t is not None]
            if isinstance(entry, dict)
            else []
        )
        if not any(value > tau for tau in taus):
            raise ArtifactError(
                f"DECISION_POINTS_TAU_RAISE: {value} raises no '{dp_id}' threshold for "
                f"'{lang}' (current: {sorted(taus) or 'none'}); only raising is allowed"
            )


def seed_backend_and_dp(
    tau: float, labels: Sequence[str], model_id: str
) -> tuple[BackendSpec, DecisionPointSpec]:
    """The one-DP artifact ``ABSTENTION_THRESHOLD`` stands for when no file exists.

    The backend is the encoder's own legacy intent result (``top1_only``: a plain
    threshold on its raw confidence), so legacy behavior is exactly as before.
    """
    backend = BackendSpec(
        kind=LEGACY_KIND,
        model_id=model_id[:128] or "unavailable",
        probability_kind="top1_only",
        labels=list(labels),
        local_only=True,
        timeout_ms=1,
    )
    dp = DecisionPointSpec(
        backend=SEED_BACKEND_ID,
        view=LabelsView(kind="labels", labels=list(labels)),
        thresholds={"*": tau},
        status="uncalibrated_seed",
    )
    return backend, dp


def main() -> None:
    """``python -m encoder.decision_points <out.json>`` writes the JSON Schema."""
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python -m encoder.decision_points <schema-output.json>")
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(artifact_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
