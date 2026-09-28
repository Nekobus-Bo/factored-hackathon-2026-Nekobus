"""Banking Core service entrypoint."""

import logging

from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from banking_core.api import (
    admin_api_enabled,
    admin_router,
    dev_router,
    sessions_router,
    tools_router,
    validate_admin_api_settings,
)
from banking_core.control.config import get_control_config_repository

logger = logging.getLogger(__name__)

app = FastAPI(title="banking-core")
app.include_router(sessions_router)
app.include_router(tools_router)
app.include_router(dev_router)
app.router.add_event_handler("startup", validate_admin_api_settings)


def mount_admin_router_if_enabled(application: FastAPI) -> None:
    if admin_api_enabled():
        application.include_router(admin_router)


mount_admin_router_if_enabled(app)


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadinessResponse(BaseModel):
    status: str
    service: str
    reason: str | None = None


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", service="banking-core")


@app.get("/ready", response_model=ReadinessResponse)
def ready(response: Response) -> ReadinessResponse:
    """Readiness probe checking that database policy configuration is accessible."""
    try:
        repo = get_control_config_repository()
        repo.get_policy_config()
        return ReadinessResponse(status="ready", service="banking-core")
    except Exception as exc:
        logger.error(
            "Readiness check failed: policy config unavailable: %s: %s",
            type(exc).__name__,
            exc,
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            service="banking-core",
            reason=f"policy config unavailable ({type(exc).__name__})",
        )
