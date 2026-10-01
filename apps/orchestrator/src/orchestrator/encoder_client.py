"""Typed HTTP client for the local encoder service (the model server).

POST /v1/analyze gives the PII spans the masking unions in and, since ADR-0012,
the decisions of the decision points the caller names. GET /v1/decision-points
lists the ids the service knows, because an unknown id fails the whole analyze
call with a 422 and would also lose the PII spans.
"""

import logging
from typing import Any, Literal

import httpx
from contracts.encoder import (
    AnalyzeRequest,
    AnalyzeResponse,
    DecisionPointsResponse,
)
from contracts.locale import Locale
from pydantic import ValidationError

from orchestrator.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EncoderUnavailableError(Exception):
    """The encoder could not produce an analysis (503, timeout, bad payload).

    `status_code` is the HTTP status when the encoder answered with one.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EncoderClient:
    """Async client for the encoder. Every failure maps to EncoderUnavailableError.

    The encoder is an optional signal: callers are expected to degrade to an
    LLM-only turn instead of failing.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self.base_url = (base_url or cfg.encoder_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.encoder_timeout_seconds
        self._external_client = client
        self._client: httpx.AsyncClient | None = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._client and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def analyze(
        self,
        text: str,
        lang: Literal["es", "pt", "en"] | None = None,
        decision_points: list[str] | None = None,
        locale: Locale | None = None,
    ) -> AnalyzeResponse:
        """Call POST /v1/analyze and return the validated response.

        `decision_points` names the decision points to evaluate; None leaves the
        choice to the service (every enabled, always-on one). Only ids listed by
        `decision_points()` are safe to name: the service answers 422 to any other.
        `locale` (ADR-0014) selects per-market thresholds; it is sent only when set,
        so an encoder that predates it never sees the key.
        """
        try:
            request = AnalyzeRequest(
                text=text, lang=lang, locale=locale, decision_points=decision_points
            )
        except ValidationError as exc:
            raise EncoderUnavailableError("text outside the encoder contract") from exc

        body = request.model_dump(mode="json")
        if body["decision_points"] is None:
            del body["decision_points"]  # the request stays what it was before
        if body["locale"] is None:
            del body["locale"]
        try:
            response = await self._get_client().post(
                f"{self.base_url}/v1/analyze",
                json=body,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise EncoderUnavailableError("encoder timed out") from exc
        except httpx.RequestError as exc:
            raise EncoderUnavailableError(
                f"encoder unreachable: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            raise EncoderUnavailableError(
                f"encoder HTTP {response.status_code}", response.status_code
            )

        try:
            payload: Any = response.json()
            return AnalyzeResponse.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise EncoderUnavailableError(
                "encoder returned an invalid payload"
            ) from exc

    async def decision_points(self) -> DecisionPointsResponse:
        """Call GET /v1/decision-points: the ids and labels the service evaluates."""
        try:
            response = await self._get_client().get(
                f"{self.base_url}/v1/decision-points", timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            raise EncoderUnavailableError("encoder timed out") from exc
        except httpx.RequestError as exc:
            raise EncoderUnavailableError(
                f"encoder unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise EncoderUnavailableError(
                f"encoder HTTP {response.status_code}", response.status_code
            )
        try:
            return DecisionPointsResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise EncoderUnavailableError(
                "encoder returned an invalid payload"
            ) from exc
