"""Encoder service (the model server) entrypoint and FastAPI endpoints."""

import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from contracts.encoder import (
    AnalyzeRequest,
    AnalyzeResponse,
    DecisionPointsResponse,
    DecisionResult,
    EmbedRequest,
    EmbedResponse,
    PiiSpan,
    Slot,
)
from contracts.labels import Intent, PiiType, SlotType
from encoder.decision_points import (
    ArtifactError,
    check_tau_raise,
    seed_backend_and_dp,
)
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from encoder_service.backend import (
    ModelUnavailableError,
    get_backend,
    set_backend,
)
from encoder_service.config import (
    get_abstention_threshold,
    get_backend_settings,
    get_decision_point_settings,
    get_embedding_settings,
)
from encoder_service.decisions import (
    TURN_INTENT,
    DecisionRuntime,
    get_runtime,
    load_runtime,
    set_runtime,
)
from encoder_service.embedding import (
    build_embedding_backend,
    get_embedding,
    readiness,
    set_embedding,
)
from encoder_service.model_backends import BackendConfigError, build_backend
from encoder_service.scoring import RequestScores

logger = logging.getLogger(__name__)

UNCALIBRATED = "uncalibrated: ABSTENTION_THRESHOLD not set (ADR-0010)"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager enforcing startup invariants."""
    # Fails loud at startup if ABSTENTION_THRESHOLD is present but invalid
    get_abstention_threshold()
    # Fails loud at startup if ENCODER_BACKEND is set but cannot be built;
    # unset keeps the default UnavailableBackend (503).
    backend = build_backend(get_backend_settings())
    if backend is not None:
        set_backend(backend)
    # Fails loud if the calibration artifact is invalid, a backend cannot be built
    # or does not match its pin. No artifact file: legacy seed mode (get_runtime()
    # stays None and ABSTENTION_THRESHOLD stands for a one-DP artifact).
    settings = get_decision_point_settings()
    runtime = load_runtime(settings)
    set_runtime(runtime)
    if runtime is None:
        _check_seed_tau_raise(settings.tau_raise)
        logger.info("decision points: legacy seed mode (ABSTENTION_THRESHOLD)")
    else:
        logger.info("decision points: artifact %s", runtime.config_version)
        if get_abstention_threshold() is not None:
            logger.info(
                "ABSTENTION_THRESHOLD is set but a calibration artifact exists: "
                "the artifact's thresholds win; the environment value is ignored"
            )
    # The embedding model of kb.search (POST /v1/embed). Unset = not served. Configured
    # with a bad pin or weights that do not match it: the service stops here. Pinned
    # but not cached yet: it starts and /v1/embed says why it cannot answer.
    embedding = build_embedding_backend(get_embedding_settings())
    set_embedding(embedding)
    try:
        yield
    finally:
        if runtime is not None:
            runtime.close()
        set_runtime(None)
        set_embedding(None)


app = FastAPI(title="encoder", lifespan=lifespan)


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint for smoke checks."""
    return HealthResponse(status="ok", service="encoder")


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness endpoint indicating if inference backend is ready and calibrated."""
    tau = get_abstention_threshold()
    runtime = get_runtime()
    if tau is None and runtime is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "ready": False,
                "reason": UNCALIBRATED,
                "service": "encoder",
            },
        )

    backend = get_backend()
    is_ready = backend.is_ready()
    status_code = (
        status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    if is_ready:
        payload: dict[str, Any] = {
            "status": "ok",
            "ready": True,
            "backend": getattr(backend, "model_id", "unknown"),
            "service": "encoder",
            "decision_points": _decision_points_readiness(runtime),
            "embedding": readiness(get_embedding()),
        }
    else:
        payload = {
            "status": "unavailable",
            "ready": False,
            "reason": "Encoder model backend is not configured or unavailable",
            "service": "encoder",
            "decision_points": _decision_points_readiness(runtime),
            "embedding": readiness(get_embedding()),
        }
    return JSONResponse(status_code=status_code, content=payload)


def _check_seed_tau_raise(tau_raise: Mapping[tuple[str, str], float]) -> None:
    """A raise-only override in seed mode must raise the seed's threshold, or stop."""
    if not tau_raise:
        return
    tau = get_abstention_threshold()
    if tau is None:
        raise BackendConfigError(
            "DECISION_POINTS_TAU_RAISE is set but there is no threshold to raise: "
            "set ABSTENTION_THRESHOLD or provide a calibration artifact"
        )
    _, seed_dp = seed_backend_and_dp(tau, [i.value for i in Intent], "seed")
    try:
        check_tau_raise({TURN_INTENT: seed_dp}, tau_raise)
    except ArtifactError as exc:
        raise BackendConfigError(str(exc)) from exc


def _decision_points_readiness(runtime: DecisionRuntime | None) -> dict[str, Any]:
    """Source, artifact id and the state of each decision point, for /ready."""
    if runtime is None:
        return {
            "source": "legacy_seed",
            "config_version": None,
            "states": {TURN_INTENT: "ready"},
        }
    return {
        "source": runtime.source,
        "config_version": runtime.config_version,
        "states": {dp_id: runtime.state(dp_id) for dp_id in runtime.decision_points},
    }


def _seed_runtime(raw_model_id: str) -> DecisionRuntime:
    """Legacy seed mode: ABSTENTION_THRESHOLD as a one-DP artifact (uncalibrated)."""
    tau = get_abstention_threshold()
    if tau is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNCALIBRATED
        )
    return DecisionRuntime.seed(
        tau, raw_model_id, get_decision_point_settings().tau_raise
    )


@app.get("/v1/decision-points", response_model=DecisionPointsResponse)
def decision_points() -> DecisionPointsResponse:
    """The decision points this service evaluates and how calibrated they are."""
    runtime = get_runtime()
    if runtime is None:
        runtime = _seed_runtime(getattr(get_backend(), "model_id", "unavailable"))
    return runtime.info()


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze customer message for intent, extracted slots, and PII spans."""
    tau = get_abstention_threshold()
    runtime = get_runtime()
    if runtime is None and tau is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNCALIBRATED,
        )
    known = runtime.known_ids() if runtime is not None else {TURN_INTENT}
    unknown = sorted(set(request.decision_points or []) - known)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown decision points {unknown}; known: {sorted(known)}",
        )

    start_time = time.perf_counter()
    backend = get_backend()

    try:
        raw_result = backend.analyze(request.text, request.lang)
    except ModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    legacy_ms = (time.perf_counter() - start_time) * 1000.0

    # Validate intent against typed Intent enum
    if raw_result.intent is not None:
        if raw_result.intent not in {i.value for i in Intent}:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Backend returned unknown intent: '{raw_result.intent}'",
            )

    # Validate and convert slots
    slots: list[Slot] = []
    valid_slots = {st.value for st in SlotType}
    for s in raw_result.slots:
        if s.type not in valid_slots:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Backend returned unknown slot type: '{s.type}'",
            )
        slots.append(
            Slot(
                type=s.type,
                value=s.value,
                start=s.start,
                end=s.end,
                normalized=s.normalized,
            )
        )

    # Validate and convert PII spans against typed PiiType enum
    pii_spans: list[PiiSpan] = []
    for p in raw_result.pii_spans:
        try:
            pii_type = PiiType(p.type)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Backend returned unknown PII type: '{p.type}'",
            ) from exc
        pii_spans.append(PiiSpan(type=pii_type, start=p.start, end=p.end))

    # Decision points. The legacy fields follow turn_intent (ADR-0012, Appendix D).
    active = runtime if runtime is not None else _seed_runtime(raw_result.model_id)
    scores = RequestScores(
        text=request.text,
        lang=request.lang,
        locale=request.locale,
        legacy=raw_result,
        legacy_latency_ms=legacy_ms,
    )
    requested = (
        request.decision_points
        if request.decision_points is not None
        else active.default_ids()
    )
    to_run = list(dict.fromkeys([*requested, *_legacy_source(active)]))
    results = active.evaluate(to_run, scores)
    decisions = {dp_id: results[dp_id] for dp_id in requested}

    if active.turn_intent_enabled():
        intent, confidence, abstain = _legacy_from_turn_intent(results[TURN_INTENT])
    else:
        # The artifact has no enabled turn_intent: the legacy fields fall back to the
        # legacy backend and ABSTENTION_THRESHOLD.
        if tau is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "uncalibrated: the calibration artifact has no enabled turn_intent "
                    "and ABSTENTION_THRESHOLD is not set (ADR-0012)"
                ),
            )
        confidence = raw_result.confidence
        abstain = confidence < tau
        intent = None if abstain else raw_result.intent

    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    return AnalyzeResponse(
        intent=intent,
        confidence=confidence,
        abstain=abstain,
        slots=slots,
        pii_spans=pii_spans,
        model_id=raw_result.model_id,
        latency_ms=latency_ms,
        decisions=decisions,
        config_version=active.config_version,
    )


def _legacy_source(runtime: DecisionRuntime) -> list[str]:
    """turn_intent is always evaluated when enabled: the legacy fields come from it."""
    return [TURN_INTENT] if runtime.turn_intent_enabled() else []


def _legacy_from_turn_intent(result: DecisionResult) -> tuple[str | None, float, bool]:
    """(intent, confidence, abstain) from turn_intent. Anything but decided abstains."""
    if result.label is not None:
        return result.label, result.confidence, False
    return None, result.confidence, True


@app.post("/v1/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    """Embed texts with the pinned embedding model (ADR-0012, Appendix J).

    The response names the model and revision that produced the vectors; the caller
    compares them with its own pin on every answer. Nothing is logged about the texts.
    """
    backend = get_embedding()
    if backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "embedding is not configured on this model server: set EMBEDDING_MODEL "
                "and EMBEDDING_REVISION"
            ),
        )
    if not backend.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=getattr(backend, "reason", "the embedding model is not ready"),
        )
    if len(request.texts) > backend.max_batch:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"a batch of {len(request.texts)} texts exceeds the limit of "
                f"{backend.max_batch} (EMBEDDING_MAX_BATCH)"
            ),
        )
    try:
        vectors = backend.embed(request.texts)
    except ModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return EmbedResponse(
        model_id=backend.model_id,
        revision=backend.revision,
        dim=backend.dim,
        vectors=vectors,
    )
