"""Typed HTTP client for the local encoder service (POST /v1/analyze)."""

import logging
from typing import Any, Literal

import httpx
from contracts.encoder import AnalyzeRequest, AnalyzeResponse
from pydantic import ValidationError

from orchestrator.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EncoderUnavailableError(Exception):
    """The encoder could not produce an analysis (503, timeout, bad payload)."""


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
    ) -> AnalyzeResponse:
        """Call POST /v1/analyze and return the validated response."""
        try:
            request = AnalyzeRequest(text=text, lang=lang)
        except ValidationError as exc:
            raise EncoderUnavailableError("text outside the encoder contract") from exc

        try:
            response = await self._get_client().post(
                f"{self.base_url}/v1/analyze",
                json=request.model_dump(mode="json"),
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise EncoderUnavailableError("encoder timed out") from exc
        except httpx.RequestError as exc:
            raise EncoderUnavailableError(
                f"encoder unreachable: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            raise EncoderUnavailableError(f"encoder HTTP {response.status_code}")

        try:
            payload: Any = response.json()
            return AnalyzeResponse.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise EncoderUnavailableError(
                "encoder returned an invalid payload"
            ) from exc
