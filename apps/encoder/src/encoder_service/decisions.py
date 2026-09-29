"""The decision-point runtime of the encoder service (ADR-0012).

``load_runtime`` reads the calibration artifact at startup and builds its backends
through ``encoder.registry``. It fails loudly, with a message that names the fix,
if the schema is invalid, a backend cannot be built, or a backend does not match
its pin. With no artifact file the service runs in *legacy seed mode*:
``ABSTENTION_THRESHOLD`` stands for a one-DP artifact (``turn_intent``,
``uncalibrated_seed``) over the legacy backend's own result, so behavior is what
it was before decision points existed.

``DecisionRuntime.evaluate`` turns one request's scores into ``DecisionResult``s.
It never returns text, and it turns every backend failure into ``unavailable`` for
the decision points on that backend, which is the contract's way of saying "fall
back to the LLM's own argument or withhold" (invariant I2).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from contracts.encoder import (
    DecisionOutcome,
    DecisionPointInfo,
    DecisionPointsResponse,
    DecisionResult,
    RunnerUp,
    TauSource,
)
from contracts.labels import Intent
from encoder import registry
from encoder.decision_points import (
    SEED_BACKEND_ID,
    ArtifactError,
    BackendSpec,
    DecisionPointSpec,
    check_distribution,
    check_tau_raise,
    decide,
    load_artifact,
    seed_backend_and_dp,
    view_labels,
    view_members,
)
from encoder.pinning import PinError, PinMismatchError

from encoder_service.config import DecisionPointSettings, get_backend_settings
from encoder_service.model_backends import (
    CGROUP_MEMORY_MAX,
    BackendConfigError,
    check_memory_budget,
    check_memory_floor,
)
from encoder_service.scoring import (
    BackendScore,
    LegacyScoring,
    RequestScores,
    ScoringBackend,
)

logger = logging.getLogger(__name__)

TURN_INTENT = "turn_intent"
# Sent to a backend once at startup to prove it covers its labels. Not customer text.
_PROBE_TEXT = "probe"

Scorer = ScoringBackend | LegacyScoring


@dataclass(frozen=True)
class DecisionRuntime:
    """Decision points, their backends, and how to evaluate them for a request."""

    source: str  # "artifact" or "legacy_seed"
    config_version: str | None
    decision_points: Mapping[str, DecisionPointSpec]
    backends: Mapping[str, Scorer]
    tau_raise: Mapping[tuple[str, str], float]
    executor: ThreadPoolExecutor | None = None

    # -- construction --

    @classmethod
    def seed(
        cls,
        tau: float,
        model_id: str,
        tau_raise: Mapping[tuple[str, str], float] | None = None,
    ) -> DecisionRuntime:
        """``ABSTENTION_THRESHOLD`` as a one-DP artifact over the legacy result."""
        labels = [intent.value for intent in Intent]
        backend, dp = seed_backend_and_dp(tau, labels, model_id)
        return cls(
            source="legacy_seed",
            config_version=None,
            decision_points={TURN_INTENT: dp},
            backends={SEED_BACKEND_ID: LegacyScoring(backend)},
            tau_raise=dict(tau_raise or {}),
        )

    def close(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)

    # -- reading --

    def known_ids(self) -> set[str]:
        return set(self.decision_points)

    def default_ids(self) -> list[str]:
        """Enabled, always-on decision points, in artifact order."""
        return [
            dp_id
            for dp_id, dp in self.decision_points.items()
            if dp.enabled and dp.always_on
        ]

    def turn_intent_enabled(self) -> bool:
        dp = self.decision_points.get(TURN_INTENT)
        return dp is not None and dp.enabled

    def state(self, dp_id: str) -> str:
        dp = self.decision_points[dp_id]
        if not dp.enabled:
            return "off"
        if dp.status == "infeasible":
            return "infeasible"
        if self.backends[dp.backend].stale:
            return "unavailable"
        return "ready"

    def info(self) -> DecisionPointsResponse:
        points = []
        for dp_id, dp in self.decision_points.items():
            backend = self.backends[dp.backend]
            points.append(
                DecisionPointInfo(
                    id=dp_id,
                    labels=view_labels(dp),
                    backend_kind=backend.spec.kind,
                    backend_model_id=backend.model_id,
                    probability_kind=backend.spec.probability_kind,
                    status=dp.status,
                    state=self.state(dp_id),  # type: ignore[arg-type]
                    enabled=dp.enabled,
                    always_on=dp.always_on,
                    languages_with_tau=sorted(
                        lang for lang, tau in dp.thresholds.items() if tau is not None
                    ),
                )
            )
        return DecisionPointsResponse(
            config_version=self.config_version,
            source=self.source,  # type: ignore[arg-type]
            decision_points=points,
        )

    # -- evaluating --

    def evaluate(
        self, dp_ids: Iterable[str], request: RequestScores
    ) -> dict[str, DecisionResult]:
        """One ``DecisionResult`` per id. Every id must be known."""
        return {dp_id: self._evaluate_one(dp_id, request) for dp_id in dp_ids}

    def _result(
        self,
        dp_id: str,
        backend: Scorer,
        outcome: DecisionOutcome,
        latency_ms: float = 0.0,
        **fields: object,
    ) -> DecisionResult:
        return DecisionResult(
            dp_id=dp_id,
            outcome=outcome,
            confidence=fields.pop("confidence", 0.0),  # type: ignore[arg-type]
            model_id=backend.model_id,
            config_version=self.config_version,
            latency_ms=latency_ms,
            **fields,  # type: ignore[arg-type]
        )

    def _evaluate_one(self, dp_id: str, request: RequestScores) -> DecisionResult:
        dp = self.decision_points[dp_id]
        backend = self.backends[dp.backend]
        if not dp.enabled:
            return self._result(dp_id, backend, DecisionOutcome.OFF)
        if dp.status == "infeasible":
            return self._result(dp_id, backend, DecisionOutcome.INFEASIBLE)

        score = backend.score(request)
        if not score.ok:
            return self._result(dp_id, backend, DecisionOutcome.UNAVAILABLE)
        try:
            decision = decide(
                dp_id,
                dp,
                probabilities=score.probabilities,
                top1=score.top1,
                lang=request.lang,
                raises=self.tau_raise,
                probability_kind=backend.spec.probability_kind,
            )
        except ValueError:
            # The backend broke its contract (bad sum, foreign label, NaN). Say so
            # without the message, which may name values derived from the text.
            logger.error(
                "decision point %s: backend %s broke its contract",
                dp_id,
                dp.backend,
            )
            return self._result(dp_id, backend, DecisionOutcome.UNAVAILABLE)

        latency = self._latency_once(dp.backend, score, request)
        runner_up = (
            RunnerUp(label=decision.runner_up[0], confidence=decision.runner_up[1])
            if decision.runner_up
            else None
        )
        return self._result(
            dp_id,
            backend,
            DecisionOutcome(decision.outcome),
            latency_ms=latency,
            label=decision.label,
            confidence=decision.confidence,
            raw_confidence=decision.raw_confidence,
            runner_up=runner_up,
            tau=decision.tau,
            tau_source=TauSource(decision.tau_source) if decision.tau_source else None,
        )

    @staticmethod
    def _latency_once(
        backend_id: str, score: BackendScore, request: RequestScores
    ) -> float:
        """A shared backend reports its time once per request."""
        if backend_id in request.reported:
            return 0.0
        request.reported.add(backend_id)
        return round(score.latency_ms, 3)


# -- The process-wide runtime (injected in tests, like the legacy backend) --

_active_runtime: DecisionRuntime | None = None


def get_runtime() -> DecisionRuntime | None:
    """The artifact runtime, or None in legacy seed mode."""
    return _active_runtime


def set_runtime(runtime: DecisionRuntime | None) -> None:
    global _active_runtime
    _active_runtime = runtime


# -- Loading the artifact --


def load_runtime(
    settings: DecisionPointSettings,
    *,
    memory_max: Path = CGROUP_MEMORY_MAX,
) -> DecisionRuntime | None:
    """Build the runtime from the artifact file, or return None (legacy seed mode).

    Raises ``BackendConfigError`` so the service stops with the reason.
    """
    path = settings.file
    if not path.is_file():
        if settings.file_explicit and settings.app_env == "production":
            raise BackendConfigError(
                f"DECISION_POINTS_FILE points to {path}, which does not exist; "
                "refusing to fall back to the legacy seed under APP_ENV=production"
            )
        if settings.file_explicit:
            logger.warning(
                "DECISION_POINTS_FILE %s does not exist: legacy seed mode "
                "(ABSTENTION_THRESHOLD)",
                path,
            )
        else:
            logger.info("no calibration artifact at %s: legacy seed mode", path)
        return None

    try:
        artifact = load_artifact(path)
        check_tau_raise(artifact.decision_points, settings.tau_raise)
    except ArtifactError as exc:
        raise BackendConfigError(str(exc)) from exc
    _check_turn_intent_labels(artifact.decision_points)

    needed = _needed_backends(artifact.decision_points)
    _check_budget(artifact.backends, needed, memory_max)

    executor = ThreadPoolExecutor(
        max_workers=settings.max_workers, thread_name_prefix="decision-backend"
    )
    backends: dict[str, Scorer] = {}
    try:
        for backend_id, spec in artifact.backends.items():
            if backend_id not in needed:
                logger.info(
                    "backend %s serves no enabled decision point: not loaded",
                    backend_id,
                )
                backends[backend_id] = ScoringBackend(backend_id, spec, None, [], None)
                continue
            backends[backend_id] = _build_backend(
                backend_id,
                spec,
                artifact.decision_points,
                executor,
                settings.allow_stale,
            )
    except BaseException:
        executor.shutdown(wait=False, cancel_futures=True)
        raise

    logger.info(
        "calibration artifact %s loaded: %d decision points, %d backends",
        artifact.artifact_id,
        len(artifact.decision_points),
        len(needed),
    )
    return DecisionRuntime(
        source="artifact",
        config_version=artifact.artifact_id,
        decision_points=dict(artifact.decision_points),
        backends=backends,
        tau_raise=dict(settings.tau_raise),
        executor=executor,
    )


def _check_turn_intent_labels(decision_points: Mapping[str, DecisionPointSpec]) -> None:
    """The legacy intent field follows turn_intent, so its labels must be intents."""
    dp = decision_points.get(TURN_INTENT)
    if dp is None:
        return
    unknown = set(view_labels(dp)) - {intent.value for intent in Intent}
    if unknown:
        raise BackendConfigError(
            f"{TURN_INTENT} labels {sorted(unknown)} are not in the contract's intents"
        )


def _needed_backends(decision_points: Mapping[str, DecisionPointSpec]) -> set[str]:
    """Backends an enabled, feasible decision point reads. Others are not loaded."""
    return {
        dp.backend
        for dp in decision_points.values()
        if dp.enabled and dp.status != "infeasible"
    }


def _check_budget(
    backends: Mapping[str, BackendSpec], needed: set[str], memory_max: Path
) -> None:
    if any(backends[b].kind == "gliner" for b in needed):
        # The same safety net the legacy gliner backend has: a container below the
        # measured peak (ENCODER_GLINER_MIN_MEMORY_MB) is refused at startup.
        check_memory_floor(get_backend_settings().gliner_min_memory_mb, memory_max)
    required = sum(
        backends[b].resources.ram_mb
        for b in needed
        if backends[b].resources and backends[b].resources.ram_mb  # type: ignore[union-attr]
    )
    if required:
        check_memory_budget(
            int(required), memory_max, "the calibration artifact's backends"
        )


def _labels_of(
    backend_id: str, decision_points: Mapping[str, DecisionPointSpec]
) -> list[str]:
    """Union of the backend labels its decision points read, in a stable order."""
    seen: dict[str, None] = {}
    for dp in decision_points.values():
        if dp.backend == backend_id and dp.enabled and dp.status != "infeasible":
            for label in sorted(view_members(dp)):
                seen[label] = None
    return list(seen)


def _build_backend(
    backend_id: str,
    spec: BackendSpec,
    decision_points: Mapping[str, DecisionPointSpec],
    executor: ThreadPoolExecutor,
    allow_stale: bool,
) -> ScoringBackend:
    labels = spec.labels or _labels_of(backend_id, decision_points)
    try:
        adapter = registry.build(spec)
    except PinMismatchError as exc:
        if not allow_stale:
            raise BackendConfigError(f"backend '{backend_id}': {exc}") from exc
        logger.error(
            "backend '%s' does not match its pin and is UNAVAILABLE "
            "(DECISION_POINTS_ALLOW_STALE): %s",
            backend_id,
            exc,
        )
        return ScoringBackend(backend_id, spec, None, labels, None, stale=True)
    except (PinError, registry.BackendBuildError) as exc:
        raise BackendConfigError(f"backend '{backend_id}': {exc}") from exc

    scoring = ScoringBackend(backend_id, spec, adapter, labels, executor)
    _probe(scoring, decision_points)
    return scoring


def _probe(
    scoring: ScoringBackend, decision_points: Mapping[str, DecisionPointSpec]
) -> None:
    """Prove at startup that the backend covers the labels its decision points read."""
    score = scoring.warm(_PROBE_TEXT)
    if not score.ok:
        reason = f"{score.error}: {score.detail}" if score.detail else score.error
        raise BackendConfigError(
            f"backend '{scoring.backend_id}' failed its startup probe ({reason})"
        )
    for dp_id, dp in decision_points.items():
        if dp.backend != scoring.backend_id or not dp.enabled:
            continue
        try:
            if scoring.spec.probability_kind == "distribution":
                assert score.probabilities is not None
                check_distribution(score.probabilities, view_members(dp))
            else:
                assert score.top1 is not None
                if score.top1[0] not in view_labels(dp):
                    raise ValueError("top label outside the decision point's labels")
        except ValueError as exc:
            raise BackendConfigError(
                f"backend '{scoring.backend_id}' does not fit decision point "
                f"'{dp_id}': {exc}"
            ) from exc


__all__ = ["DecisionRuntime", "get_runtime", "load_runtime", "set_runtime"]
