"""Operator-only API for live policy configuration and demo fixture resets."""

from __future__ import annotations

import hmac
import os
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy.orm import Session

from banking_core.api.routes_sessions import get_session_store
from banking_core.audit.service import append
from banking_core.control.attempt_limits import AttemptLimitStore
from banking_core.control.loader import (
    load_policy_config,
    record_to_policy_config,
    save_policy_config,
)
from banking_core.control.policy import PolicyConfig
from banking_core.crypto import compute_blind_index
from banking_core.db.session import get_session_maker
from banking_core.identity.config import IdentityConfig
from banking_core.models.config import PolicyConfigRecord
from banking_core.models.core_bank import Card
from banking_core.seed.fixtures import create_scenario_fixtures

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")

# What infra/compose/docker-compose.yml defaults ADMIN_API_TOKEN to, so the back
# office demo steps work with no .env. Public by construction: startup refuses
# it under APP_ENV=production. A test keeps the two spellings in step.
DEVELOPMENT_ADMIN_TOKEN = "dev-only-admin-token"


class AdminPolicyConfigRequest(BaseModel):
    """Editable policy fields accepted at the administrator boundary."""

    model_config = ConfigDict(extra="forbid")

    amount_mode: Literal["flag", "block"]
    thresholds_minor: dict[str, StrictInt] = Field(min_length=1)

    @field_validator("amount_mode", mode="before")
    @classmethod
    def normalize_amount_mode(cls, value: object) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"flag", "block"}:
                return normalized
        raise ValueError("amount_mode must be 'flag' or 'block'")

    @field_validator("thresholds_minor")
    @classmethod
    def validate_thresholds(cls, values: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for currency, threshold in values.items():
            code = currency.strip().upper()
            if not _CURRENCY_CODE.fullmatch(code):
                raise ValueError(f"invalid ISO currency code: {currency!r}")
            if threshold <= 0:
                raise ValueError(f"threshold for {code} must be greater than zero")
            if code in normalized:
                raise ValueError(f"duplicate ISO currency code: {code}")
            normalized[code] = threshold
        return normalized


class PolicyConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_mode: Literal["flag", "block"]
    thresholds_minor: dict[str, int]
    version: int


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards_reset: int
    cards_changed: int
    cards_missing: int
    attempt_limits_cleared: int


def _environment_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _running_in_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def admin_api_enabled() -> bool:
    return _environment_flag("ADMIN_API_ENABLED")


def validate_admin_api_settings() -> None:
    """Fail startup rather than expose an enabled API without a real token.

    A missing token is refused everywhere. The development token is accepted
    outside production only: it is published in this repository, so under
    APP_ENV=production it would be a known password.
    """
    if not admin_api_enabled():
        return
    token = os.getenv("ADMIN_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ADMIN_API_TOKEN is required when ADMIN_API_ENABLED=true")
    if token == DEVELOPMENT_ADMIN_TOKEN and _running_in_production():
        raise RuntimeError(
            "ADMIN_API_TOKEN is the public development token; set a secret of "
            "your own when APP_ENV=production"
        )


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected_token = os.getenv("ADMIN_API_TOKEN", "")
    expected_header = f"Bearer {expected_token}".encode()
    supplied_header = authorization.encode() if authorization is not None else b""
    if not expected_token or not hmac.compare_digest(supplied_header, expected_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _active_policy_record(session: Session) -> PolicyConfigRecord:
    statement = (
        sa.select(PolicyConfigRecord)
        .where(PolicyConfigRecord.is_active.is_(True))
        .order_by(PolicyConfigRecord.version.desc())
        .limit(1)
    )
    record = session.execute(statement).scalar_one_or_none()
    if record is None:
        load_policy_config(session)
        record = session.execute(statement).scalar_one_or_none()
    if record is None:
        raise RuntimeError("Active policy configuration is unavailable")
    return record


def _response(record: PolicyConfigRecord) -> PolicyConfigResponse:
    config = record_to_policy_config(record)
    return PolicyConfigResponse(
        amount_mode=config.amount_mode,
        thresholds_minor=config.thresholds_minor,
        version=record.version,
    )


@router.get(
    "/policy-config",
    response_model=PolicyConfigResponse,
    dependencies=[Depends(require_admin)],
)
def get_policy_config() -> PolicyConfigResponse:
    with get_session_maker()() as session:
        return _response(_active_policy_record(session))


@router.put(
    "/policy-config",
    response_model=PolicyConfigResponse,
    dependencies=[Depends(require_admin)],
)
def put_policy_config(request: AdminPolicyConfigRequest) -> PolicyConfigResponse:
    with get_session_maker()() as session:
        # Serialize admin writes so the returned version and audit entry match.
        _active_policy_record(session)
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtext('admin.policy_config'))")
        )
        current_record = _active_policy_record(session)
        current_config = record_to_policy_config(current_record)
        new_config = PolicyConfig.model_validate(
            {
                **current_config.model_dump(),
                "amount_mode": request.amount_mode,
                "thresholds_minor": request.thresholds_minor,
                # The current single-currency copy would overwrite the requested
                # threshold of the default currency; it is derived from the map.
                "amount_threshold_minor": None,
            }
        )
        next_version = (
            session.execute(
                sa.select(sa.func.coalesce(sa.func.max(PolicyConfigRecord.version), 0))
            ).scalar_one()
            + 1
        )
        before = {
            "amount_mode": current_config.amount_mode,
            "thresholds_minor": current_config.thresholds_minor,
        }
        after = {
            "amount_mode": new_config.amount_mode,
            "thresholds_minor": new_config.thresholds_minor,
        }
        append(
            session,
            actor_type="agent",
            actor_ref="admin",
            action="admin.policy_config.updated",
            decision="allowed",
            reason_code=None,
            payload={"before": before, "after": after, "version": next_version},
        )
        saved_record = save_policy_config(new_config, session=session)
        return _response(saved_record)


def get_attempt_limit_store() -> AttemptLimitStore:
    """The cross-session attempt-limit counters, on the same redis-core."""
    return AttemptLimitStore(redis_client=get_session_store().client)


def _clear_fixture_attempt_limits(store: AttemptLimitStore) -> int:
    """Forget the failures and locks of the scenario fixture customers.

    They are the customers an evaluation run signs in as, over and over from one
    address: without this a run would inherit the last one's failed verifies and
    matches, and its outcome would depend on what ran before. Documents of
    people who are not fixtures are not touched.
    """
    identity = IdentityConfig.from_env()
    cleared = 0
    for customer in create_scenario_fixtures().customers:
        cleared += store.clear_customer(str(customer["id"]))
        cleared += store.clear_documents(
            [
                compute_blind_index(
                    value=str(customer["document_number"]),
                    field_name="document_number",
                    document_type=document_type,
                )
                for document_type in identity.resolve_equivalent_document_types(
                    str(customer["document_type"])
                )
            ]
        )
    return cleared


def _demo_card_states() -> dict[UUID, tuple[str, datetime | None, str | None]]:
    states: dict[UUID, tuple[str, datetime | None, str | None]] = {}
    for fixture_card in create_scenario_fixtures().cards:
        fixture_id = fixture_card["id"]
        fixture_status = fixture_card["status"]
        blocked_at_value = fixture_card["blocked_at"]
        blocked_reason_value = fixture_card["blocked_reason"]
        if not isinstance(fixture_id, str) or not isinstance(fixture_status, str):
            raise TypeError("Invalid demo card fixture")
        blocked_at = (
            datetime.fromisoformat(blocked_at_value)
            if isinstance(blocked_at_value, str)
            else None
        )
        blocked_reason = (
            blocked_reason_value if isinstance(blocked_reason_value, str) else None
        )
        states[UUID(fixture_id)] = (fixture_status, blocked_at, blocked_reason)
    return states


@router.post(
    "/demo/reset-fixtures",
    response_model=DemoResetResponse,
    dependencies=[Depends(require_admin)],
)
def reset_demo_fixtures(
    limits: Annotated[AttemptLimitStore, Depends(get_attempt_limit_store)],
) -> DemoResetResponse:
    if os.getenv(
        "APP_ENV", "development"
    ).strip().lower() == "production" and not _environment_flag("DEMO_RESET_ENABLED"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo fixture reset is disabled in production",
        )

    seed_states = _demo_card_states()
    attempt_limits_cleared = _clear_fixture_attempt_limits(limits)
    with get_session_maker()() as session:
        cards = session.scalars(
            sa.select(Card).where(Card.id.in_(tuple(seed_states)))
        ).all()
        changed = 0
        for card in cards:
            seed_status, seed_blocked_at, seed_blocked_reason = seed_states[card.id]
            if (
                card.status != seed_status
                or card.blocked_at != seed_blocked_at
                or card.blocked_reason != seed_blocked_reason
            ):
                changed += 1
                card.status = seed_status
                card.blocked_at = seed_blocked_at
                card.blocked_reason = seed_blocked_reason

        result = DemoResetResponse(
            cards_reset=len(cards),
            cards_changed=changed,
            cards_missing=len(seed_states) - len(cards),
            attempt_limits_cleared=attempt_limits_cleared,
        )
        append(
            session,
            actor_type="agent",
            actor_ref="admin",
            action="admin.demo.fixtures.reset",
            decision="allowed",
            reason_code=None,
            payload=result.model_dump(),
        )
        session.commit()
        return result
