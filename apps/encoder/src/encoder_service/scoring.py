"""Run one decision backend for one request (ADR-0012, Appendix C.1).

* One forward pass per backend per request: the decision points that share a
  backend (``turn_intent`` and ``block_reason``) read the same scores.
* A per-backend time budget (``timeout_ms``), enforced from a worker thread.
* A failure (timeout, error, contract violation, stale pin) costs only the
  decision points on that backend, as ``unavailable``. Never the whole request.

An adapter's exception can carry the text it was given (GLiNER's does), so an
error is recorded as its class name only and nothing here logs a message.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Executor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from encoder.base import DecisionAdapter
from encoder.decision_points import BackendSpec
from encoder.models import DecisionPrediction

from encoder_service.backend import RawAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class RequestScores:
    """Everything one request shares between its decision points."""

    text: str
    lang: str | None
    # The legacy backend's result for this text, already computed by /v1/analyze.
    legacy: RawAnalysisResult | None = None
    legacy_latency_ms: float = 0.0
    cache: dict[str, BackendScore] = field(default_factory=dict)
    # Backends whose latency an earlier decision point already reported.
    reported: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class BackendScore:
    """What one backend said about one text, or why it said nothing."""

    ok: bool
    probabilities: dict[str, float] | None = None
    top1: tuple[str, float] | None = None
    latency_ms: float = 0.0
    # Exception class name or 'timeout' or 'stale'. Never a message.
    error: str | None = None
    # The message, only for the startup probe, whose text is a constant and so cannot
    # echo a customer's. Never set for a request.
    detail: str | None = None


class ScoringBackend:
    """A built decision backend with its time budget."""

    def __init__(
        self,
        backend_id: str,
        spec: BackendSpec,
        adapter: DecisionAdapter | None,
        labels: list[str],
        executor: Executor | None,
        *,
        stale: bool = False,
    ) -> None:
        self.backend_id = backend_id
        self.spec = spec
        self.adapter = adapter
        self.labels = labels
        self._executor = executor
        # A backend whose model does not match its pin (DECISION_POINTS_ALLOW_STALE)
        # is never called.
        self.stale = stale

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    def score(self, request: RequestScores) -> BackendScore:
        cached = request.cache.get(self.backend_id)
        if cached is not None:
            return cached
        result = self._score(request)
        request.cache[self.backend_id] = result
        return result

    def warm(self, text: str) -> BackendScore:
        """Score ``text`` inline, without the time budget. For the startup probe,
        where a cold first call is expected to be slow."""
        if self.adapter is None:
            return BackendScore(ok=False, error="stale")
        started = time.perf_counter()
        try:
            prediction = self._predict(text)
        except Exception as exc:
            return BackendScore(
                ok=False, error=type(exc).__name__, detail=str(exc)[:300]
            )
        return self._to_score(prediction, (time.perf_counter() - started) * 1000.0)

    def _to_score(self, prediction: DecisionPrediction, latency: float) -> BackendScore:
        if self.spec.probability_kind == "distribution":
            return BackendScore(
                ok=True,
                probabilities=dict(prediction.probabilities),
                latency_ms=latency,
            )
        return BackendScore(
            ok=True, top1=(prediction.intent, prediction.confidence), latency_ms=latency
        )

    def _score(self, request: RequestScores) -> BackendScore:
        if self.stale or self.adapter is None or self._executor is None:
            return BackendScore(ok=False, error="stale")
        started = time.perf_counter()
        future = self._executor.submit(self._predict, request.text)
        try:
            prediction = future.result(timeout=self.spec.timeout_ms / 1000.0)
        except FutureTimeout:
            future.cancel()
            logger.warning(
                "decision backend %s exceeded its %d ms budget",
                self.backend_id,
                self.spec.timeout_ms,
            )
            return BackendScore(ok=False, error="timeout")
        except Exception as exc:
            logger.warning(
                "decision backend %s failed: %s", self.backend_id, type(exc).__name__
            )
            return BackendScore(ok=False, error=type(exc).__name__)
        return self._to_score(prediction, (time.perf_counter() - started) * 1000.0)

    def _predict(self, text: str) -> DecisionPrediction:
        assert self.adapter is not None
        predictions = self.adapter.predict([text], candidate_intents=self.labels)
        if len(predictions) != 1:
            raise ValueError("backend returned the wrong number of predictions")
        return predictions[0]


class LegacyScoring:
    """The seed backend: the legacy encoder result /v1/analyze already computed.

    Reuses that one forward pass, so seed mode costs nothing extra and is, by
    construction, what the endpoint returned before decision points existed.
    """

    def __init__(self, spec: BackendSpec) -> None:
        self.backend_id = "legacy"
        self.spec = spec
        self.stale = False

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    def score(self, request: RequestScores) -> BackendScore:
        legacy = request.legacy
        if legacy is None or legacy.intent is None:
            return BackendScore(ok=False, error="no_result")
        return BackendScore(
            ok=True,
            top1=(legacy.intent, legacy.confidence),
            latency_ms=request.legacy_latency_ms,
        )
