"""Encoder service entrypoint and FastAPI endpoints."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from contracts.encoder import (
    AnalyzeRequest,
    AnalyzeResponse,
    PiiSpan,
    Slot,
)
from contracts.labels import Intent, PiiType, SlotType
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from encoder_service.backend import (
    ModelUnavailableError,
    get_backend,
)
from encoder_service.config import get_abstention_threshold


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager enforcing startup invariants."""
    # Fails loud at startup if ABSTENTION_THRESHOLD is present but invalid
    get_abstention_threshold()
    yield


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
    if tau is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unavailable",
                "ready": False,
                "reason": "uncalibrated: ABSTENTION_THRESHOLD not set (ADR-0010)",
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
        }
    else:
        payload = {
            "status": "unavailable",
            "ready": False,
            "reason": "Encoder model backend is not configured or unavailable",
            "service": "encoder",
        }
    return JSONResponse(status_code=status_code, content=payload)


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze customer message for intent, extracted slots, and PII spans."""
    tau = get_abstention_threshold()
    if tau is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="uncalibrated: ABSTENTION_THRESHOLD not set (ADR-0010)",
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

    # Evaluate abstention by tau
    abstain = raw_result.confidence < tau
    intent = None if abstain else raw_result.intent

    latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    return AnalyzeResponse(
        intent=intent,
        confidence=raw_result.confidence,
        abstain=abstain,
        slots=slots,
        pii_spans=pii_spans,
        model_id=raw_result.model_id,
        latency_ms=latency_ms,
    )
