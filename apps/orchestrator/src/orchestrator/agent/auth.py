"""Bearer authentication of the agent API and its startup guard.

Mirrors banking-core's admin API (`require_admin`, `validate_admin_api_settings`):
one shared token, compared in constant time, and a startup that refuses to
expose the API without a real one.
"""

import hmac

from fastapi import Header, HTTPException, Request, status

from orchestrator.config import Settings

# What infra/compose/docker-compose.yml defaults AGENT_API_TOKEN to, so the back
# office works locally with no .env. Public by construction: startup refuses it
# under APP_ENV=production. A test keeps the two spellings in step.
DEVELOPMENT_AGENT_TOKEN = "dev-only-agent-token"


def validate_agent_api_settings(settings: Settings) -> None:
    """Fail startup rather than expose an enabled API without a real token.

    A missing token is refused everywhere. The development token is accepted
    outside production only: it is published in this repository, so under
    APP_ENV=production it would be a known password.
    """
    if not settings.agent_api_enabled:
        return
    token = settings.effective_agent_api_token
    if not token:
        raise RuntimeError("AGENT_API_TOKEN is required when AGENT_API_ENABLED=true")
    production = settings.app_env.strip().casefold() == "production"
    if token == DEVELOPMENT_AGENT_TOKEN and production:
        raise RuntimeError(
            "AGENT_API_TOKEN is the public development token; set a secret of "
            "your own when APP_ENV=production"
        )


def require_agent(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """401 unless the request carries `Authorization: Bearer <AGENT_API_TOKEN>`."""
    expected_token: str = request.app.state.agent_api_token
    expected_header = f"Bearer {expected_token}".encode()
    supplied_header = authorization.encode() if authorization is not None else b""
    if not expected_token or not hmac.compare_digest(supplied_header, expected_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent token",
            headers={"WWW-Authenticate": "Bearer"},
        )
