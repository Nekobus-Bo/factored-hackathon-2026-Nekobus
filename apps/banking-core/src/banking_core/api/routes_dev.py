"""Developer and evaluation test-only endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from banking_core.identity.config import IdentityConfig
from banking_core.identity.ports import get_dev_sink

router = APIRouter(prefix="/v1/dev", tags=["dev"])


class DevOtpResponse(BaseModel):
    challenge_id: str
    code: str


@router.get("/otp/{challenge_id}", response_model=DevOtpResponse)
def get_dev_otp(challenge_id: str) -> DevOtpResponse:
    """Retrieve cleartext OTP code for evaluation runner only if hook is enabled."""
    config = IdentityConfig.from_env()
    sink = get_dev_sink()

    try:
        code = sink.get_code(challenge_id, allow_hook=config.allow_dev_otp_hook)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Challenge '{challenge_id}' not found in dev sink",
        )

    return DevOtpResponse(challenge_id=challenge_id, code=code)
