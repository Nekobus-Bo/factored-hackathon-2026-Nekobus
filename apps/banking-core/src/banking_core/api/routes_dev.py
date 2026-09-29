"""Developer and evaluation test-only endpoints."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from banking_core.identity.config import IdentityConfig
from banking_core.identity.simulated_inbox import get_simulated_inbox

router = APIRouter(prefix="/v1/dev", tags=["dev"])


class DevOtpResponse(BaseModel):
    challenge_id: str
    code: str


@router.get("/otp/{challenge_id}", response_model=DevOtpResponse)
def get_dev_otp(challenge_id: str) -> DevOtpResponse:
    """Retrieve a cleartext OTP code for the evaluation runner, if the hook is on.

    Reads the same simulated inbox on redis-core that the customer-facing notice
    is built from, by challenge id and across sessions: that is why the hook is
    off by default, is only mounted when enabled, and startup refuses it in
    production (see ``mount_dev_router_if_enabled``).
    """
    if not IdentityConfig.from_env().allow_dev_otp_hook:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev OTP retrieval hook is disabled by default. "
            "Set ALLOW_DEV_OTP_HOOK=true in evaluation environments.",
        )

    code = get_simulated_inbox().get_code(challenge_id)
    if not code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Challenge '{challenge_id}' not found in the simulated inbox",
        )

    return DevOtpResponse(challenge_id=challenge_id, code=code)
