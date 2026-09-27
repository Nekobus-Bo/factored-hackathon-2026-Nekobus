"""Encoder service entrypoint."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="encoder")


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", service="encoder")
