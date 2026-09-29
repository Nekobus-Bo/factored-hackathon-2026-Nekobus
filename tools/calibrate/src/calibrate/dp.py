"""``make calibrate TASK=decision-points``: calibrate decision points (ADR-0012).

For each decision point (DP) and each candidate backend the run:

1. builds the backend through ``encoder.registry`` (the same call the encoder service
   makes at startup, so a backend that calibrates here is a backend that loads there);
2. fits a temperature per language on **validation** and applies it, as the service
   will;
3. chooses tau on validation: maximum coverage subject to the precision constraint on
   the labels the engine acts on (``calibrate.thresholds``), per language, per label,
   or pooled across languages, as the DP's ``threshold_scope`` says;
4. scores **test** at that tau: coverage, precision with its Wilson 95% lower bound,
   recall, ECE before and after calibration, a confusion matrix, and whether the
   constraint is *certified* (the lower bound reaches ``p_min``);
5. picks the best candidate, writes one report, and merges the DP's entry into the
   artifact without touching other DPs.

Every confidence and decision is produced by ``encoder.decision_points.decide``, the
function the service runs, so a number in the report is the number it will serve.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
from encoder import registry
from encoder.decision_points import (
    BackendSpec,
    CalibratorSpec,
    DecisionPointSpec,
    LabelsView,
    decide,
)
from encoder.models import DecisionExample

from calibrate.artifact import (
    ArtifactMergeError,
    RunMeta,
    compute_run_id,
    diff_entries,
    fragment,
    fragment_of,
    fragment_text,
    load_raw,
    merge_fragments,
    write_artifact,
)
from calibrate.benchmark import BenchmarkResult, benchmark_cpu_inference
from calibrate.calibrators import CalibratorError, TemperatureFit, TemperatureScaler
from calibrate.dpconfig import (
    Candidate,
    ConfigError,
    DataPaths,
    DpConfig,
    RunConfig,
    load_run_config,
    select_dps,
)
from calibrate.metrics.decision import (
    ReliabilityBin,
    expected_calibration_error,
    reliability_bins,
    wilson_lower_bound,
    zero_error_sample_size,
)
from calibrate.report import file_sha256
from calibrate.runner import guard_fixture_output, load_decision_dataset
from calibrate.thresholds import (
    LabelFit,
    ScalarFit,
    ScoredRow,
    fit_label_threshold,
    fit_scalar_threshold,
)

logger = logging.getLogger(__name__)

# Truth of an utterance that belongs to no label of the DP's view.
OUTSIDE = "(outside the view)"
ABSTAINED = "(abstained)"
# The F.5 target for calibration quality on test.
ECE_TARGET = 0.10
PROVENANCE_ORDER = ["synthetic-provisional", "synthetic", "human"]


class RunError(RuntimeError):
    """A calibration run cannot proceed. The message says what to fix."""


# --- Rows ---


@dataclass(frozen=True)
class Raw:
    """What a backend said about one text."""

    probabilities: dict[str, float] | None = None
    top1: tuple[str, float] | None = None


@dataclass(frozen=True)
class Row:
    example: DecisionExample
    raw: Raw
    backend_truth: str  # the label the backend is trained to predict
    view_truth: str  # the DP label of the row, or OUTSIDE

    @property
    def lang(self) -> str:
        return self.example.lang


@dataclass(frozen=True)
class Outcome:
    """A row after calibration: the DP's top label, and what tau makes of it."""

    lang: str
    truth: str
    top_label: str
    top_confidence: float
    raw_top_label: str
    raw_top_confidence: float
    decided: str | None  # the label if decided at the final tau, else None


# --- Metrics ---


@dataclass
class LabelMetrics:
    label: str
    acted: bool
    support: int
    accepted: int
    tp: int
    p_min: float | None

    @property
    def precision(self) -> float | None:
        return self.tp / self.accepted if self.accepted else None

    @property
    def wilson(self) -> float | None:
        return wilson_lower_bound(self.tp, self.accepted) if self.accepted else None

    @property
    def recall(self) -> float | None:
        return self.tp / self.support if self.support else None


@dataclass
class SplitMetrics:
    n: int
    decided: int
    acted_decided: int
    labels: dict[str, LabelMetrics]
    macro_f1: float
    ece_pre: float
    ece_post: float
    bins: list[ReliabilityBin]
    confusion: dict[str, dict[str, int]]

    @property
    def coverage(self) -> float:
        return self.decided / self.n if self.n else 0.0

    @property
    def acted_coverage(self) -> float:
        return self.acted_decided / self.n if self.n else 0.0


def macro_f1_over(
    labels: Sequence[str], truth: Sequence[str], pred: Sequence[str]
) -> float:
    """Macro F1 over the ``labels`` that occur in ``truth``.

    A row whose truth is outside the view has no recall to lose, but whatever label was
    predicted for it counts against that label's precision.
    """
    scores = []
    for label in labels:
        tp = sum(1 for t, p in zip(truth, pred, strict=True) if t == p == label)
        fp = sum(
            1 for t, p in zip(truth, pred, strict=True) if p == label and t != label
        )
        fn = sum(
            1 for t, p in zip(truth, pred, strict=True) if t == label and p != label
        )
        if tp + fn == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn)
        scores.append(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(scores) / len(scores) if scores else 0.0


def split_metrics(
    outcomes: Sequence[Outcome], labels: Sequence[str], p_min: Mapping[str, float]
) -> SplitMetrics:
    truth = [o.truth for o in outcomes]
    top = [o.top_label for o in outcomes]
    per_label: dict[str, LabelMetrics] = {}
    for label in labels:
        decided_here = [o for o in outcomes if o.decided == label]
        per_label[label] = LabelMetrics(
            label=label,
            acted=label in p_min,
            support=sum(1 for o in outcomes if o.truth == label),
            accepted=len(decided_here),
            tp=sum(1 for o in decided_here if o.truth == label),
            p_min=p_min.get(label),
        )
    confusion: dict[str, dict[str, int]] = defaultdict(Counter)  # type: ignore[assignment]
    for o in outcomes:
        confusion[o.truth][o.decided or ABSTAINED] += 1
    decided = [o for o in outcomes if o.decided is not None]
    return SplitMetrics(
        n=len(outcomes),
        decided=len(decided),
        acted_decided=sum(1 for o in decided if o.decided in p_min),
        labels=per_label,
        macro_f1=macro_f1_over(labels, truth, top),
        ece_pre=expected_calibration_error(
            truth,
            [o.raw_top_label for o in outcomes],
            [o.raw_top_confidence for o in outcomes],
        ),
        ece_post=expected_calibration_error(
            truth, top, [o.top_confidence for o in outcomes]
        ),
        bins=reliability_bins(
            [o.truth == o.top_label for o in outcomes],
            [o.top_confidence for o in outcomes],
        ),
        confusion={k: dict(v) for k, v in confusion.items()},
    )


# --- Backend ---


@dataclass
class BuiltBackend:
    name: str
    spec: dict[str, Any]
    adapter: Any
    bench: BenchmarkResult
    ram_mb: float
    intents: list[str]  # what predict() is asked to choose among


def _file_sha(path: str) -> str:
    file = Path(path)
    if not file.is_file():
        raise RunError(
            f"train data {path} not found (paths are relative to the working "
            "directory: run from the repository root)"
        )
    return file_sha256(file)


def view_members_of(dp: DpConfig) -> list[str]:
    """The backend labels a DP's view reads, in a stable order."""
    view = dp.view
    if isinstance(view, LabelsView):
        return sorted(view.labels)
    return sorted({m for members in view.groups.values() for m in members})


def intents_for(dp: DpConfig, candidate: Candidate) -> list[str]:
    """The ``candidate_intents`` the service passes to ``predict`` for this backend:
    its declared labels, else what the DP's view reads."""
    if candidate.labels:
        return list(candidate.labels)
    if candidate.probability_kind == "top1_only":
        return dp.labels
    return view_members_of(dp)


def candidate_spec(
    candidate: Candidate, label_map: Mapping[str, str] | None, dp: DpConfig
) -> dict[str, Any]:
    """The artifact's backend entry for a candidate.

    ``labels`` is written when the artifact must state it (a ``top1_only`` backend
    serves exactly the DP's labels; an explicit ``labels`` in the config); a
    ``tfidf_lr`` backend adds its trained classes after the fit.
    """
    spec: dict[str, Any] = {
        "kind": candidate.kind,
        "probability_kind": candidate.probability_kind,
        "local_only": True,
        "cost_class": candidate.cost_class,
        "timeout_ms": candidate.timeout_ms,
        "params": dict(candidate.params),
    }
    if candidate.labels or candidate.probability_kind == "top1_only":
        spec["labels"] = intents_for(dp, candidate)
    if candidate.kind == "tfidf_lr":
        if not candidate.train:
            raise RunError(f"candidate '{candidate.name}': tfidf_lr needs a train path")
        sha = _file_sha(candidate.train)
        train: dict[str, Any] = {"path": candidate.train, "sha256": sha}
        if label_map:
            train["label_map"] = dict(label_map)
        spec["train"] = train
        spec["model_id"] = registry.tfidf_model_id(sha, label_map)
    else:
        if not candidate.model_id:
            raise RunError(f"candidate '{candidate.name}': set model_id")
        spec["model_id"] = candidate.model_id
        if candidate.revision:
            spec["revision"] = candidate.revision
        if candidate.weights_sha256:
            spec["weights_sha256"] = candidate.weights_sha256
    return spec


def build_backend(
    candidate: Candidate, dp: DpConfig, test_texts: Sequence[str]
) -> BuiltBackend:
    """Build a candidate through the registry and benchmark it on CPU."""
    spec = candidate_spec(candidate, dp.label_map, dp)
    intents = intents_for(dp, candidate)
    baseline = psutil.Process().memory_info().rss / (1024 * 1024)
    try:
        adapter = registry.build(BackendSpec.model_validate(spec))
    except registry.BackendPendingError as exc:
        raise RunError(str(exc)) from exc
    except Exception as exc:
        raise RunError(
            f"candidate '{candidate.name}' ({candidate.kind}) cannot be built: {exc}"
        ) from exc
    bench = benchmark_cpu_inference(
        infer_fn=lambda text: adapter.predict([text], candidate_intents=intents),
        items=list(test_texts),
        warmup=1,
        baseline_ram_mb=baseline,
    )
    return BuiltBackend(
        candidate.name, spec, adapter, bench, bench.peak_ram_mb, intents
    )


def predict_all(built: BuiltBackend, texts: Sequence[str], kind: str) -> list[Raw]:
    predictions = built.adapter.predict(list(texts), candidate_intents=built.intents)
    if len(predictions) != len(texts):
        raise RunError(
            f"backend '{built.name}' returned the wrong number of predictions"
        )
    if kind == "distribution":
        return [Raw(probabilities=dict(p.probabilities)) for p in predictions]
    return [Raw(top1=(p.intent, p.confidence)) for p in predictions]


# --- Truth ---


def view_truth(dp: DpConfig, intent: str) -> str:
    label = registry.relabel(intent, dp.label_map)
    view = dp.view
    if isinstance(view, LabelsView):
        return label if label in view.labels else OUTSIDE
    for name, members in view.groups.items():
        if label in members:
            return name
    return OUTSIDE


def backend_truth(spec: Mapping[str, Any], intent: str) -> str:
    train = spec.get("train") or {}
    return registry.relabel(intent, train.get("label_map"))


# --- One candidate on one DP ---


@dataclass
class Certification:
    """Whether one acted label, in one scope, clears its floor by the Wilson bound."""

    scope: str  # a language, or "pooled (es, pt)"
    langs: tuple[str, ...]  # the languages whose test rows it counts
    label: str
    tp: int
    accepted: int
    wilson: float | None
    p_min: float

    @property
    def certified(self) -> bool:
        return self.wilson is not None and self.wilson >= self.p_min

    @property
    def point(self) -> float | None:
        return self.tp / self.accepted if self.accepted else None

    @property
    def below_floor(self) -> bool:
        """Under the floor even by the point estimate (the tau did not hold)."""
        return self.point is not None and self.point < self.p_min

    @property
    def needs(self) -> int:
        return zero_error_sample_size(self.p_min)


@dataclass
class CandidateResult:
    candidate: Candidate
    backend: BuiltBackend
    calibrator: dict[str, Any]
    calibration: dict[str, TemperatureFit | str | None]
    thresholds: dict[str, Any]
    tau_scopes: dict[str, dict[str, str | None]]  # lang -> label -> "language"|"pooled"
    label_fits: dict[str, dict[str, LabelFit]]
    scalar_fits: dict[str, ScalarFit]
    status: str
    val: dict[str, SplitMetrics]  # by language, and "all"
    test: dict[str, SplitMetrics]
    certifications: list[Certification]
    n_val: dict[str, int]
    n_test: dict[str, int]
    # "lang/label" of acted labels with no threshold: the DP abstains there.
    uncovered: list[str] = field(default_factory=list)

    @property
    def certified(self) -> bool:
        return bool(self.certifications) and all(
            c.certified for c in self.certifications
        )

    @property
    def certified_scopes(self) -> int:
        return sum(1 for c in self.certifications if c.certified)


def _make_spec(
    dp: DpConfig,
    backend_id: str,
    calibrator: CalibratorSpec,
    thresholds: Mapping[str, Any],
    status: str = "calibrated",
) -> DecisionPointSpec:
    return DecisionPointSpec.model_validate(
        {
            "backend": backend_id,
            "view": dp.view.model_dump(mode="json"),
            "calibrator": calibrator.model_dump(mode="json"),
            "thresholds": dict(thresholds),
            "status": status,
        }
    )


def _top(
    spec: DecisionPointSpec, dp_id: str, row: Row, probability_kind: str
) -> tuple[str, float]:
    """Top label and calibrated confidence of a row, through ``decide``."""
    try:
        decision = decide(
            dp_id,
            spec,
            probabilities=row.raw.probabilities,
            top1=row.raw.top1,
            lang=row.lang,
            probability_kind=probability_kind,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise RunError(
            f"backend broke its contract on {row.example.id} ({dp_id}): {exc}"
        ) from exc
    assert decision.label is not None, "tau 0 decides every row that has a calibrator"
    return decision.label, decision.confidence


def _decision_label(
    spec: DecisionPointSpec, dp_id: str, row: Row, probability_kind: str
) -> str | None:
    decision = decide(
        dp_id,
        spec,
        probabilities=row.raw.probabilities,
        top1=row.raw.top1,
        lang=row.lang,
        probability_kind=probability_kind,  # type: ignore[arg-type]
    )
    return decision.label if decision.outcome == "decided" else None


def evaluate_candidate(
    dp: DpConfig,
    built: BuiltBackend,
    val_rows: Mapping[str, list[Row]],
    test_rows: Mapping[str, list[Row]],
    config: RunConfig,
) -> CandidateResult:
    candidate = next(c for c in dp.candidates if c.name == built.name)
    kind = candidate.probability_kind
    p_min = dp.constraint.p_min
    labels = dp.labels

    # 1. Calibrator, per language, on validation.
    by_lang: dict[str, dict[str, float]] = {}
    calibration: dict[str, TemperatureFit | str | None] = {}
    for lang in config.languages:
        rows = val_rows.get(lang, [])
        if dp.calibrator == "none":
            calibration[lang] = None
        elif len(rows) < config.calibrator_min_rows:
            calibration[lang] = (
                f"{len(rows)} validation rows, calibrator_min_rows is "
                f"{config.calibrator_min_rows}: no calibrator, so the DP abstains here"
            )
        else:
            try:
                scaler = TemperatureScaler()
                fit = scaler.fit(
                    [r.raw.probabilities or {} for r in rows],
                    [r.backend_truth for r in rows],
                )
            except CalibratorError as exc:
                raise RunError(
                    f"{dp.dp_id}/{lang}: cannot fit a temperature: {exc}"
                ) from exc
            by_lang[lang] = {"T": fit.temperature}
            calibration[lang] = fit
    calibrator = CalibratorSpec(kind=dp.calibrator, by_lang=by_lang)
    usable = [
        lang for lang in config.languages if dp.calibrator == "none" or lang in by_lang
    ]

    # 2. Score validation with tau 0: the DP's top label and calibrated confidence.
    scoring = _make_spec(dp, built.name, calibrator, {"*": 0.0})
    raw_spec = _make_spec(dp, built.name, CalibratorSpec(kind="none"), {"*": 0.0})
    scored: dict[str, list[ScoredRow]] = {}
    for lang in usable:
        scored[lang] = []
        for row in val_rows.get(lang, []):
            label, confidence = _top(scoring, dp.dp_id, row, kind)
            scored[lang].append(
                ScoredRow(lang, label, confidence, _none_if_outside(row.view_truth))
            )

    # 3. Choose tau under the constraint.
    thresholds, tau_scopes, label_fits, scalar_fits = choose_thresholds(
        dp, scored, usable, config
    )
    decided_somewhere = any(_has_tau(entry) for entry in thresholds.values())
    status = "calibrated" if decided_somewhere else "infeasible"
    final = _make_spec(dp, built.name, calibrator, thresholds, status)

    # 4. Score both splits at the final tau, through decide().
    def outcomes(rows_by_lang: Mapping[str, list[Row]]) -> dict[str, list[Outcome]]:
        result: dict[str, list[Outcome]] = {}
        for lang in usable:
            result[lang] = []
            for row in rows_by_lang.get(lang, []):
                top_label, top_conf = _top(scoring, dp.dp_id, row, kind)
                raw_label, raw_conf = _top(raw_spec, dp.dp_id, row, kind)
                result[lang].append(
                    Outcome(
                        lang=lang,
                        truth=row.view_truth,
                        top_label=top_label,
                        top_confidence=top_conf,
                        raw_top_label=raw_label,
                        raw_top_confidence=raw_conf,
                        decided=_decision_label(final, dp.dp_id, row, kind),
                    )
                )
        return result

    val_out, test_out = outcomes(val_rows), outcomes(test_rows)
    val_metrics = _metrics_by_lang(val_out, labels, p_min)
    test_metrics = _metrics_by_lang(test_out, labels, p_min)
    certifications = certify(dp, test_out, tau_scopes, thresholds)

    return CandidateResult(
        uncovered=uncovered_scopes(dp, config.languages, tau_scopes),
        candidate=candidate,
        backend=built,
        calibrator=calibrator.model_dump(mode="json"),
        calibration=calibration,
        thresholds=thresholds,
        tau_scopes=tau_scopes,
        label_fits=label_fits,
        scalar_fits=scalar_fits,
        status=status,
        val=val_metrics,
        test=test_metrics,
        certifications=certifications,
        n_val={lang: len(val_rows.get(lang, [])) for lang in config.languages},
        n_test={lang: len(test_rows.get(lang, [])) for lang in config.languages},
    )


def _none_if_outside(truth: str) -> str | None:
    return None if truth == OUTSIDE else truth


def _has_tau(entry: Any) -> bool:
    if isinstance(entry, dict):
        return any(tau is not None for tau in entry.values())
    return entry is not None


def _metrics_by_lang(
    outcomes: Mapping[str, list[Outcome]],
    labels: Sequence[str],
    p_min: Mapping[str, float],
) -> dict[str, SplitMetrics]:
    metrics = {
        lang: split_metrics(rows, labels, p_min)
        for lang, rows in outcomes.items()
        if rows
    }
    everything = [o for rows in outcomes.values() for o in rows]
    if everything:
        metrics["all"] = split_metrics(everything, labels, p_min)
    return metrics


# --- Choosing thresholds by scope ---


def choose_thresholds(
    dp: DpConfig,
    scored: Mapping[str, list[ScoredRow]],
    usable: Sequence[str],
    config: RunConfig,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, str | None]],
    dict[str, dict[str, LabelFit]],
    dict[str, ScalarFit],
]:
    """The artifact's ``thresholds`` for a DP, and how each was found."""
    constraint = dp.constraint
    thresholds: dict[str, Any] = {}
    scopes: dict[str, dict[str, str | None]] = {}
    label_fits: dict[str, dict[str, LabelFit]] = {}
    scalar_fits: dict[str, ScalarFit] = {}

    if dp.scope == "per_language":
        for lang in config.languages:
            if lang not in usable:
                thresholds[lang] = None
                scopes[lang] = dict.fromkeys(dp.labels)
                continue
            fit = fit_scalar_threshold(
                scored[lang], constraint.p_min, ci=constraint.ci, n_min=constraint.n_min
            )
            scalar_fits[lang] = fit
            thresholds[lang] = fit.tau
            scopes[lang] = dict.fromkeys(
                dp.labels, "language" if fit.feasible else None
            )
        return thresholds, scopes, label_fits, scalar_fits

    pooled_rows = [r for lang in usable for r in scored[lang]]
    pooled: dict[str, LabelFit] = {}
    if dp.scope == "per_label_pooled":
        for label in constraint.p_min:
            pooled[label] = fit_label_threshold(
                pooled_rows,
                label,
                p_min=constraint.p_min[label],
                ci=constraint.ci,
                n_min=constraint.n_min,
                scope="pooled",
            )
        label_fits["*"] = pooled
        thresholds["*"] = {
            label: (pooled[label].tau if label in pooled else dp.unconstrained_tau)
            for label in dp.labels
        }

    for lang in config.languages:
        if lang not in usable:
            thresholds[lang] = None
            scopes[lang] = dict.fromkeys(dp.labels)
            continue
        entry: dict[str, float | None] = {}
        lang_scopes: dict[str, str | None] = {}
        label_fits[lang] = {}
        for label in dp.labels:
            if label not in constraint.p_min:
                entry[label] = dp.unconstrained_tau
                lang_scopes[label] = "language"
                continue
            own = fit_label_threshold(
                scored[lang],
                label,
                p_min=constraint.p_min[label],
                ci=constraint.ci,
                n_min=constraint.n_min,
                scope="language",
            )
            chosen = own
            if dp.scope == "per_label_pooled" and own.support < constraint.n_min:
                chosen = pooled[label]
            label_fits[lang][label] = chosen
            entry[label] = chosen.tau
            lang_scopes[label] = chosen.scope if chosen.feasible else None
        acted_taus = [entry[label] for label in constraint.p_min]
        thresholds[lang] = entry if any(t is not None for t in acted_taus) else None
        scopes[lang] = lang_scopes
    return thresholds, scopes, label_fits, scalar_fits


# --- Certification ---


def uncovered_scopes(
    dp: DpConfig,
    languages: Sequence[str],
    tau_scopes: Mapping[str, Mapping[str, str | None]],
) -> list[str]:
    """Acted labels with no threshold in a language, as ``lang/label``. The DP
    abstains there (the LLM decides), which is safe but not certified, and belongs in
    ``docs/limitations.md`` (F.5)."""
    return [
        f"{lang}/{label}"
        for lang in languages
        for label in dp.constraint.p_min
        if tau_scopes.get(lang, {}).get(label) is None
    ]


def certify(
    dp: DpConfig,
    test_outcomes: Mapping[str, list[Outcome]],
    tau_scopes: Mapping[str, Mapping[str, str | None]],
    thresholds: Mapping[str, Any],
) -> list[Certification]:
    """Wilson-bound certification of every acted label in every scope that has a tau.

    A scope is a language whose tau was fitted on that language, or the pool of the
    languages that share a pooled tau. Certification never uses the selection rule
    (``constraint.ci``): it is always the Wilson 95% lower bound against ``p_min``.
    """
    results: list[Certification] = []
    for label, p_min in dp.constraint.p_min.items():
        pooled_langs: list[str] = []
        for lang, rows in test_outcomes.items():
            scope = tau_scopes.get(lang, {}).get(label)
            if scope == "language" and thresholds.get(lang) is not None:
                accepted = [o for o in rows if o.decided == label]
                tp = sum(1 for o in accepted if o.truth == label)
                results.append(
                    Certification(
                        lang,
                        (lang,),
                        label,
                        tp,
                        len(accepted),
                        wilson_lower_bound(tp, len(accepted)) if accepted else None,
                        p_min,
                    )
                )
            elif scope == "pooled":
                pooled_langs.append(lang)
        if pooled_langs:
            accepted = [
                o
                for lang in pooled_langs
                for o in test_outcomes[lang]
                if o.decided == label
            ]
            tp = sum(1 for o in accepted if o.truth == label)
            results.append(
                Certification(
                    "pooled (" + ", ".join(pooled_langs) + ")",
                    tuple(pooled_langs),
                    label,
                    tp,
                    len(accepted),
                    wilson_lower_bound(tp, len(accepted)) if accepted else None,
                    p_min,
                )
            )
    return results


# --- Choosing a candidate ---


def rank_key(result: CandidateResult) -> tuple[Any, ...]:
    """F.3 step 4: feasible first, then certified scopes, then test coverage on the
    acted labels; ties go to lower p95, then lower RAM."""
    everything = result.test.get("all")
    return (
        result.status == "calibrated",
        result.certified_scopes,
        everything.acted_coverage if everything else 0.0,
        -result.backend.bench.p95_latency_ms,
        -result.backend.ram_mb,
    )


def choose(results: Sequence[CandidateResult]) -> tuple[CandidateResult, str]:
    if len(results) == 1:
        only = results[0]
        return only, f"'{only.candidate.name}' is the only candidate."
    ranked = sorted(results, key=rank_key, reverse=True)
    best = ranked[0]
    feasible = [r for r in results if r.status == "calibrated"]
    if not feasible:
        return best, "No candidate is feasible in any language; the DP is infeasible."
    return best, (
        f"'{best.candidate.name}' ranks first among {len(results)} candidates: "
        "feasible, then the most Wilson-certified scopes, then the highest test "
        "coverage on the acted labels, then the lowest p95 and RAM (Appendix F.3)."
    )


# --- The entry written to the artifact ---


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def provenance_of(rows: Sequence[Row]) -> str:
    sources = {r.example.source for r in rows}
    known = [s for s in PROVENANCE_ORDER if s in sources]
    if not known or len(sources - set(PROVENANCE_ORDER)) > 0:
        raise RunError(
            f"test rows have sources {sorted(sources)}; expected "
            f"{', '.join(PROVENANCE_ORDER)}"
        )
    return known[0]  # the weakest present


def entry_for(
    dp: DpConfig,
    result: CandidateResult,
    data: DataPaths,
    data_hashes: Mapping[str, str],
    provenance: str,
    config: RunConfig,
) -> dict[str, Any]:
    """The DP's artifact entry, without ``run_id`` and ``report`` (added last)."""
    test = result.test
    per_lang: dict[str, Any] = {}
    for lang in config.languages:
        metrics = test.get(lang)
        val = result.val.get(lang)
        if metrics is None or val is None:
            per_lang[lang] = {
                "n_val": result.n_val[lang],
                "n_test": result.n_test[lang],
                "usable": False,
            }
            continue
        applicable = [c for c in result.certifications if lang in c.langs]
        per_lang[lang] = {
            "n_val": val.n,
            "n_test": metrics.n,
            "coverage_val": _round(val.coverage),
            "coverage_test": _round(metrics.coverage),
            "acted_coverage_test": _round(metrics.acted_coverage),
            "precision_test": {
                label: [m.tp, m.accepted, _round(m.wilson)]
                for label, m in metrics.labels.items()
                if m.acted
            },
            "recall_test": {
                label: _round(m.recall)
                for label, m in metrics.labels.items()
                if m.acted
            },
            "ece_pre": _round(metrics.ece_pre),
            "ece_post": _round(metrics.ece_post),
            "certified": bool(applicable) and all(c.certified for c in applicable),
        }
    evidence: dict[str, Any] = {
        "candidate": result.candidate.name,
        "split": "test",
        "provenance": provenance,
        "certified": result.certified,
        "uncovered": result.uncovered,
        "data": {
            split: {"path": getattr(data, split), "sha256": data_hashes[split]}
            for split in ("train", "validation", "test")
        },
        "config": {"path": config.path, "sha256": config.sha256},
        "per_lang": per_lang,
    }
    pooled = [c for c in result.certifications if c.scope.startswith("pooled")]
    if pooled:
        evidence["pooled_test"] = {
            c.label: [c.tp, c.accepted, _round(c.wilson), c.scope] for c in pooled
        }
    return {
        "backend": result.candidate.name,
        "view": dp.view_dict(),
        "enabled": dp.enabled,
        "always_on": dp.always_on,
        "calibrator": result.calibrator,
        "thresholds": result.thresholds,
        "constraint": dp.constraint.as_artifact(),
        "status": result.status,
        "evidence": evidence,
    }


# --- Provenance of the run ---


def git_state(repo_root: Path) -> str | None:
    """HEAD, with ``-dirty`` if tracked files differ. None outside a git checkout."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{head}-dirty" if dirty else head


@dataclass
class DpResult:
    dp: DpConfig
    chosen: CandidateResult
    others: list[CandidateResult]
    rationale: str
    entry: dict[str, Any]
    provenance: str
    data_hashes: dict[str, str]
    previous: dict[str, Any] | None
    diff: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    report_path: Path
    artifact_path: Path
    artifact_id: str
    run_id: str
    dp_ids: list[str]
    official: bool
    dps: list[DpResult]
    text: str = ""


def _report_name(date: str, selected: Sequence[str], every: Sequence[str]) -> str:
    suffix = "" if set(selected) == set(every) else "-" + "+".join(sorted(selected))
    return f"calibration-decision-points-{date}{suffix}.md"


def under_reports(out_dir: Path, repo_root: Path) -> bool:
    out = out_dir.resolve()
    reports = (repo_root / "reports").resolve()
    return out == reports or reports in out.parents


def run_decision_points_calibration(
    config_path: Path | str,
    out_dir: Path | str,
    *,
    dp_ids: Sequence[str] | None = None,
    artifact_path: Path | str | None = None,
    now: datetime | None = None,
    repo_root: Path | str | None = None,
) -> RunResult:
    """Calibrate ``dp_ids`` (default: every DP of the config); see the module doc.

    **Official run:** ``out_dir`` is the repository's ``reports/`` directory. The
    report goes there and the DPs are merged into the committed artifact.
    **Dev run:** any other ``out_dir``. The report goes there and the merged artifact
    is written to ``<out_dir>/decision_points.json`` (starting from the committed
    one), so it can be tried with ``DECISION_POINTS_FILE`` without touching git.
    ``artifact_path`` overrides the target of either.
    """
    from calibrate.dp_report import render_report

    root = (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[4]
    )
    out = Path(out_dir)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        config = load_run_config(config_path)
        # Recorded relative to the repo when it is inside it: a report and an
        # artifact are read on other machines.
        config = replace(config, path=_report_reference(Path(config_path), root))
        selected = select_dps(config, list(dp_ids) if dp_ids else None)
    except ConfigError as exc:
        raise RunError(str(exc)) from exc

    data_files: list[str] = []
    for dp in selected:
        paths = dp.data or config.data
        data_files += [paths.train, paths.validation, paths.test]
        data_files += [c.train for c in dp.candidates if c.train]
    guard_fixture_output(sorted(set(data_files)), out)

    official = under_reports(out, root)
    committed = root / config.artifact
    if artifact_path is not None:
        target = Path(artifact_path)
    elif official:
        target = committed
    else:
        target = out / "decision_points.json"
    base_path = target if target.is_file() else committed
    try:
        existing = load_raw(base_path)
    except ArtifactMergeError as exc:
        raise RunError(str(exc)) from exc

    dataset: dict[str, list[DecisionExample]] = {}

    def examples(path: str, split: str) -> list[DecisionExample]:
        if path not in dataset:
            dataset[path] = load_decision_dataset(path)
        rows = [e for e in dataset[path] if e.split == split]
        if not rows:
            raise RunError(f"{path} has no rows with split={split}")
        return rows

    built_cache: dict[str, BuiltBackend] = {}
    results: list[DpResult] = []
    for dp in selected:
        paths = dp.data or config.data
        data_hashes = {
            split: _file_sha(getattr(paths, split))
            for split in ("train", "validation", "test")
        }
        val_examples = examples(paths.validation, "validation")
        test_examples = examples(paths.test, "test")
        candidate_results: list[CandidateResult] = []
        provenance = ""
        for candidate in dp.candidates:
            logger.info(
                "%s: candidate %s (%s)", dp.dp_id, candidate.name, candidate.kind
            )
            key = compact_key(candidate_spec(candidate, dp.label_map, dp), paths)
            built = built_cache.get(key)
            if built is None:
                built = build_backend(candidate, dp, [e.text for e in test_examples])
                built_cache[key] = built
            val_rows = _rows(
                dp, built, val_examples, candidate.probability_kind, config
            )
            test_rows = _rows(
                dp, built, test_examples, candidate.probability_kind, config
            )
            provenance = provenance_of([r for rows in test_rows.values() for r in rows])
            candidate_results.append(
                evaluate_candidate(dp, built, val_rows, test_rows, config)
            )
        chosen, rationale = choose(candidate_results)
        _state_backend_labels(chosen)
        entry = entry_for(dp, chosen, paths, data_hashes, provenance, config)
        previous = (existing or {}).get("decision_points", {}).get(dp.dp_id)
        results.append(
            DpResult(
                dp=dp,
                chosen=chosen,
                others=[r for r in candidate_results if r is not chosen],
                rationale=rationale,
                entry=entry,
                provenance=provenance,
                data_hashes=data_hashes,
                previous=previous,
                diff=diff_entries(previous, entry),
            )
        )

    run_id = compute_run_id(
        {
            "config_sha256": config.sha256,
            "decision_points": {
                r.dp.dp_id: {
                    "entry": r.entry,
                    "backend": _stable_backend(r.chosen.backend.spec),
                }
                for r in results
            },
        }
    )
    date = moment.strftime("%Y-%m-%d")
    report_name = _report_name(date, [r.dp.dp_id for r in results], list(config.dps))
    report_path = out / report_name
    report_ref = _report_reference(report_path, root)
    fragments = []
    for r in results:
        r.entry["evidence"]["run_id"] = run_id
        r.entry["evidence"]["report"] = report_ref
        fragments.append(
            fragment(
                r.dp.dp_id, r.entry, r.chosen.candidate.name, r.chosen.backend.spec
            )
        )

    meta = RunMeta(
        created_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        git_sha=git_state(root),
        config_path=config.path,
        config_sha256=config.sha256,
    )
    try:
        merged = merge_fragments(existing, fragments, meta)
        artifact_id = write_artifact(target, merged)
    except ArtifactMergeError as exc:
        raise RunError(str(exc)) from exc

    # Embed the fragments exactly as the artifact now holds them.
    embedded = {
        r.dp.dp_id: fragment_text(fragment_of(merged, r.dp.dp_id)) for r in results
    }
    text = render_report(
        results=results,
        config=config,
        run_id=run_id,
        artifact_id=artifact_id,
        artifact_target=_report_reference(target, root),
        official=official,
        date=date,
        embedded=embedded,
        selected=[r.dp.dp_id for r in results],
        partial=set(r.dp.dp_id for r in results) != set(config.dps),
    )
    out.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    logger.info("report %s, artifact %s (%s)", report_path, target, artifact_id)
    return RunResult(
        report_path=report_path,
        artifact_path=target,
        artifact_id=artifact_id,
        run_id=run_id,
        dp_ids=[r.dp.dp_id for r in results],
        official=official,
        dps=results,
        text=text,
    )


def compact_key(spec: Mapping[str, Any], paths: DataPaths) -> str:
    return json.dumps([spec, paths.validation, paths.test], sort_keys=True)


def _stable_backend(spec: Mapping[str, Any]) -> dict[str, Any]:
    return dict(spec)


def _report_reference(report_path: Path, root: Path) -> str:
    try:
        return report_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(report_path.resolve())


def _rows(
    dp: DpConfig,
    built: BuiltBackend,
    examples: Sequence[DecisionExample],
    probability_kind: str,
    config: RunConfig,
) -> dict[str, list[Row]]:
    raws = predict_all(built, [e.text for e in examples], probability_kind)
    by_lang: dict[str, list[Row]] = {lang: [] for lang in config.languages}
    for example, raw in zip(examples, raws, strict=True):
        if example.lang not in by_lang:
            continue
        by_lang[example.lang].append(
            Row(
                example=example,
                raw=raw,
                backend_truth=backend_truth(built.spec, example.intent),
                view_truth=view_truth(dp, example.intent),
            )
        )
    return by_lang


def _state_backend_labels(result: CandidateResult) -> None:
    """A trained ``tfidf_lr`` backend states the classes it learned, so the loader can
    check the DP's labels against them."""
    classes = getattr(result.backend.adapter, "classes_", None)
    if result.candidate.kind == "tfidf_lr" and classes:
        result.backend.spec["labels"] = sorted(str(c) for c in classes)


__all__ = ["RunError", "RunResult", "run_decision_points_calibration"]
