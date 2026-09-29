"""The decision-points calibration config (``configs/decision_points.yaml``).

One file describes every decision point (DP) the harness calibrates: its label view,
the candidate backends to try, the calibrator, how tau is scoped and the precision
constraint on the labels the engine acts on (ADR-0012, Appendix F). Nothing here is
a threshold: tau is *found* by a run and written to the artifact, never configured.

Invalid config fails with the field that is wrong, before any model is trained.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from encoder.decision_points import DP_ID_PATTERN, GroupsView, LabelsView
from pydantic import TypeAdapter, ValidationError

from calibrate.calibrators import require_supported
from calibrate.thresholds import CONFIDENCE_INTERVALS, ConfidenceInterval

Scope = Literal["per_language", "per_language_per_label", "per_label_pooled"]
SCOPES: tuple[str, ...] = ("per_language", "per_language_per_label", "per_label_pooled")
DEFAULT_LANGUAGES = ("es", "pt", "en")
DEFAULT_ARTIFACT = "packages/encoder/calibration/decision_points.json"
_VIEW_ADAPTER: TypeAdapter[LabelsView | GroupsView] = TypeAdapter(
    LabelsView | GroupsView
)


class ConfigError(ValueError):
    """The calibration config is invalid. The message names the field."""


@dataclass(frozen=True)
class DataPaths:
    train: str
    validation: str
    test: str

    def as_dict(self) -> dict[str, str]:
        return {"train": self.train, "validation": self.validation, "test": self.test}


@dataclass(frozen=True)
class Candidate:
    """A backend to try for a DP. ``name`` is its id in the artifact."""

    name: str
    kind: str
    probability_kind: Literal["distribution", "top1_only"] = "distribution"
    train: str | None = None
    model_id: str | None = None
    revision: str | None = None
    weights_sha256: str | None = None
    labels: tuple[str, ...] | None = None  # the backend's label space, if it has one
    timeout_ms: int = 200
    cost_class: Literal["low", "high"] = "low"
    params: dict[str, Any] = field(default_factory=dict)
    mode: Literal["zeroshot", "finetune"] = "zeroshot"


@dataclass(frozen=True)
class Constraint:
    """Precision on the labels the engine acts on (``p_min`` maps label to floor)."""

    p_min: dict[str, float]
    ci: ConfidenceInterval = "point"
    n_min: int = 30
    calibration_split: Literal["validation"] = "validation"
    metric: Literal["precision"] = "precision"

    def as_artifact(self) -> dict[str, Any]:
        floors = set(self.p_min.values())
        return {
            "metric": self.metric,
            "labels": sorted(self.p_min),
            "p_min": next(iter(floors)) if len(floors) == 1 else dict(self.p_min),
            "ci": self.ci,
            "n_min": self.n_min,
            "calibration_split": self.calibration_split,
        }


@dataclass(frozen=True)
class DpConfig:
    dp_id: str
    view: LabelsView | GroupsView
    candidates: tuple[Candidate, ...]
    calibrator: Literal["none", "temperature"]
    scope: Scope
    constraint: Constraint
    label_map: dict[str, str] | None = None
    unconstrained_tau: float = 0.0
    data: DataPaths | None = None  # overrides the run's data for this DP
    enabled: bool = True
    always_on: bool = True
    note: str | None = None

    @property
    def labels(self) -> list[str]:
        return list(view_labels_of(self.view))

    def view_dict(self) -> dict[str, Any]:
        return self.view.model_dump(mode="json")


def view_labels_of(view: LabelsView | GroupsView) -> list[str]:
    return list(view.labels) if isinstance(view, LabelsView) else list(view.groups)


@dataclass(frozen=True)
class RunConfig:
    path: str
    sha256: str
    languages: tuple[str, ...]
    artifact: str
    data: DataPaths
    calibrator_min_rows: int
    dps: dict[str, DpConfig]


# --- Parsing ---


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{where}: '{key}' is required")
    return mapping[key]


def _data_paths(block: Any, where: str) -> DataPaths:
    if not isinstance(block, dict):
        raise ConfigError(f"{where}: needs train, validation and test paths")
    values = {}
    for split in ("train", "validation", "test"):
        value = _require(block, split, where)
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where}.{split}: must be a path")
        if Path(value).is_absolute():
            raise ConfigError(
                f"{where}.{split}: '{value}' is absolute; paths are relative to the "
                "repository root, because the encoder resolves them from its own"
            )
        values[split] = value
    return DataPaths(**values)


def _candidate(
    raw: Any, named: dict[str, Any], where: str, default_train: str
) -> Candidate:
    if isinstance(raw, str):
        if raw not in named:
            raise ConfigError(
                f"{where}: candidate '{raw}' is not defined under 'backends' "
                f"({', '.join(sorted(named)) or 'none defined'})"
            )
        return _candidate(
            {"name": raw, **named[raw]}, {}, f"{where}[{raw}]", default_train
        )
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: a candidate is a name or a mapping")
    name = _require(raw, "name", where)
    kind = _require(raw, "kind", where)
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}.name: must be a non-empty string")
    if raw.get("mode", "zeroshot") not in ("zeroshot", "finetune"):
        raise ConfigError(f"{where}.mode: must be zeroshot or finetune")
    if raw.get("mode") == "finetune" and kind != "tfidf_lr":
        raise ConfigError(
            f"{where}: pending: fine-tuning a '{kind}' candidate is not implemented in "
            "the decision-points harness; the registry builds pinned backends"
        )
    probability_kind = raw.get("probability_kind", "distribution")
    if probability_kind not in ("distribution", "top1_only"):
        raise ConfigError(f"{where}.probability_kind: distribution or top1_only")
    timeout = raw.get("timeout_ms", 200)
    if not isinstance(timeout, int) or not 1 <= timeout <= 60_000:
        raise ConfigError(f"{where}.timeout_ms: an integer of 1 to 60000")
    train = raw.get("train", default_train if kind == "tfidf_lr" else None)
    if train is not None and Path(train).is_absolute():
        raise ConfigError(f"{where}.train: '{train}' must be relative to the repo root")
    return Candidate(
        name=name,
        kind=kind,
        probability_kind=probability_kind,
        train=train,
        model_id=raw.get("model_id"),
        revision=raw.get("revision"),
        weights_sha256=raw.get("weights_sha256"),
        labels=tuple(raw["labels"]) if raw.get("labels") else None,
        timeout_ms=timeout,
        cost_class=raw.get("cost_class", "low"),
        params=dict(raw.get("params") or {}),
        mode=raw.get("mode", "zeroshot"),
    )


def _constraint(raw: Any, labels: list[str], where: str) -> Constraint:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: a constraint mapping is required")
    if raw.get("metric", "precision") != "precision":
        raise ConfigError(f"{where}.metric: only 'precision' exists")
    ci = raw.get("ci", "point")
    if ci not in CONFIDENCE_INTERVALS:
        raise ConfigError(f"{where}.ci: one of {', '.join(CONFIDENCE_INTERVALS)}")
    if raw.get("calibration_split", "validation") != "validation":
        raise ConfigError(
            f"{where}.calibration_split: tau is chosen on validation, never on test"
        )
    n_min = raw.get("n_min", 30)
    if not isinstance(n_min, int) or n_min < 0:
        raise ConfigError(f"{where}.n_min: a non-negative integer")
    p_min = _require(raw, "p_min", where)
    acted = raw.get("labels")
    if isinstance(p_min, dict):
        floors = {str(k): float(v) for k, v in p_min.items()}
        if acted is not None and set(acted) != set(floors):
            raise ConfigError(f"{where}: 'labels' and the keys of 'p_min' disagree")
    else:
        names = list(acted) if acted is not None else list(labels)
        floors = {str(name): float(p_min) for name in names}
    unknown = sorted(set(floors) - set(labels))
    if unknown:
        raise ConfigError(f"{where}: acted labels {unknown} are not labels of the view")
    if not floors:
        raise ConfigError(f"{where}: at least one acted label is required")
    for label, floor in floors.items():
        if not 0.0 < floor < 1.0:
            raise ConfigError(f"{where}.p_min[{label}]: must be in (0, 1)")
    return Constraint(p_min=floors, ci=ci, n_min=n_min)


def _dp(
    dp_id: str,
    raw: Any,
    named: dict[str, Any],
    run_data: DataPaths,
    where: str,
) -> DpConfig:
    if not DP_ID_PATTERN.match(dp_id):
        raise ConfigError(f"{where}: id must match {DP_ID_PATTERN.pattern}")
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: a mapping is required")
    try:
        view = _VIEW_ADAPTER.validate_python(_require(raw, "view", where))
    except ValidationError as exc:
        raise ConfigError(f"{where}.view: {exc.errors()[0]['msg']}") from exc
    labels = view_labels_of(view)

    scope = raw.get("threshold_scope", "per_language")
    if scope not in SCOPES:
        raise ConfigError(f"{where}.threshold_scope: one of {', '.join(SCOPES)}")
    calibrator = raw.get("calibrator", "temperature")
    try:
        require_supported(calibrator)
    except (NotImplementedError, ValueError) as exc:
        raise ConfigError(f"{where}.calibrator: {exc}") from exc

    data = _data_paths(raw["data"], f"{where}.data") if "data" in raw else None
    raw_candidates = _require(raw, "candidates", where)
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ConfigError(f"{where}.candidates: a non-empty list is required")
    default_train = (data or run_data).train
    candidates = tuple(
        _candidate(c, named, f"{where}.candidates[{i}]", default_train)
        for i, c in enumerate(raw_candidates)
    )
    if len({c.name for c in candidates}) != len(candidates):
        raise ConfigError(f"{where}.candidates: names must be unique")
    for candidate in candidates:
        if candidate.probability_kind == "top1_only":
            if calibrator != "none":
                raise ConfigError(
                    f"{where}: '{candidate.name}' is top1_only and cannot be "
                    "calibrated; set calibrator: none"
                )
            if not isinstance(view, LabelsView):
                raise ConfigError(
                    f"{where}: '{candidate.name}' is top1_only, so the view must be "
                    "a labels view"
                )

    label_map = raw.get("label_map")
    if label_map is not None and not (
        isinstance(label_map, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in label_map.items())
    ):
        raise ConfigError(f"{where}.label_map: a mapping of strings")
    tau = raw.get("unconstrained_tau", 0.0)
    if not isinstance(tau, int | float) or not 0.0 <= tau <= 1.0:
        raise ConfigError(f"{where}.unconstrained_tau: a number in [0, 1]")
    return DpConfig(
        dp_id=dp_id,
        view=view,
        candidates=candidates,
        calibrator=calibrator,
        scope=scope,
        constraint=_constraint(raw.get("constraint"), labels, f"{where}.constraint"),
        label_map=label_map,
        unconstrained_tau=float(tau),
        data=data,
        enabled=bool(raw.get("enabled", True)),
        always_on=bool(raw.get("always_on", True)),
        note=raw.get("note"),
    )


def parse_run_config(text: str, path: str = "<config>") -> RunConfig:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: the top level must be a mapping")
    if loaded.get("task") != "decision-points":
        raise ConfigError(
            f"{path}: task must be 'decision-points' (got {loaded.get('task')!r}); "
            "the decision and embedding tasks have their own configs"
        )
    run_data = _data_paths(_require(loaded, "data", path), f"{path}: data")
    languages = tuple(loaded.get("languages", DEFAULT_LANGUAGES))
    if not languages or not all(
        isinstance(lang, str) and len(lang) == 2 for lang in languages
    ):
        raise ConfigError(f"{path}: languages must be two-letter codes")
    min_rows = loaded.get("calibrator_min_rows", 30)
    if not isinstance(min_rows, int) or min_rows < 2:
        raise ConfigError(
            f"{path}: calibrator_min_rows must be an integer of 2 or more"
        )
    named = loaded.get("backends") or {}
    if not isinstance(named, dict):
        raise ConfigError(f"{path}: backends must be a mapping of name to candidate")
    raw_dps = _require(loaded, "decision_points", path)
    if not isinstance(raw_dps, dict) or not raw_dps:
        raise ConfigError(f"{path}: decision_points must be a non-empty mapping")
    dps = {
        dp_id: _dp(dp_id, raw, named, run_data, f"{path}: decision_points.{dp_id}")
        for dp_id, raw in raw_dps.items()
    }
    return RunConfig(
        path=path,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        languages=languages,
        artifact=str(loaded.get("artifact", DEFAULT_ARTIFACT)),
        data=run_data,
        calibrator_min_rows=min_rows,
        dps=dps,
    )


def load_run_config(path: Path | str) -> RunConfig:
    file = Path(path)
    try:
        data = file.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read the calibration config {file}: {exc}") from exc
    config = parse_run_config(data.decode("utf-8"), str(path))
    # The hash is of the bytes on disk, not of a re-encoding.
    return RunConfig(**{**config.__dict__, "sha256": hashlib.sha256(data).hexdigest()})


def select_dps(config: RunConfig, wanted: list[str] | None) -> list[DpConfig]:
    """The DPs a run covers: ``wanted`` (in config order) or all of them."""
    if not wanted:
        return list(config.dps.values())
    unknown = sorted(set(wanted) - set(config.dps))
    if unknown:
        raise ConfigError(
            f"unknown decision point {unknown}; the config defines "
            f"{', '.join(config.dps)}"
        )
    return [dp for dp_id, dp in config.dps.items() if dp_id in wanted]


__all__ = [
    "Candidate",
    "ConfigError",
    "Constraint",
    "DataPaths",
    "DpConfig",
    "RunConfig",
    "load_run_config",
    "parse_run_config",
    "select_dps",
    "view_labels_of",
]
