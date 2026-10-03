"""Operator-only API: live configuration, the handoff queue, metrics, demo resets."""

from __future__ import annotations

import hmac
import os
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from contracts.envelope import VerificationState
from contracts.tools import CODE_FLOOR
from contracts.tools.handoff_create import Department, HandoffPriority, HandoffStatus
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)
from sqlalchemy.orm import Session

from banking_core.api.routes_sessions import get_session_store
from banking_core.audit.metrics import (
    FeedbackCounts,
    MetricsSnapshot,
    OtpCounts,
    collect_metrics,
)
from banking_core.audit.service import append
from banking_core.control.attempt_limits import AttemptLimitStore
from banking_core.control.loader import (
    load_policy_config,
    record_to_policy_config,
    save_policy_config,
)
from banking_core.control.policy import PolicyConfig
from banking_core.control.tool_policy import (
    ToolPolicyRejected,
    active_tool_policy,
    effective_matrix,
    reset_tool_policy_to_seed,
    save_tool_policy,
)
from banking_core.crypto import compute_blind_index
from banking_core.db.session import get_session_maker
from banking_core.handoff.decisions import (
    AlreadyClosedError,
    DecisionNotAllowedError,
    HandoffOutcome,
    RejectReason,
    allowed_decisions,
    close_handoff,
    escalate_handoff,
)
from banking_core.handoff.feedback import read_feedback
from banking_core.handoff.queue import (
    ClaimedByAnotherAgentError,
    HandoffNotFoundError,
    claim_handoff,
    priority_rank,
    queue_position_expression,
)
from banking_core.identity.config import IdentityConfig
from banking_core.models.config import PolicyConfigRecord
from banking_core.models.core_bank import Card
from banking_core.models.ops import Handoff
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


class AdminToolPolicyRequest(BaseModel):
    """Tools to change, each with the verification states that enable it.

    `[]` disables a tool. Tools not listed keep their current states. A state
    outside the tool's code floor is refused, never dropped.
    """

    model_config = ConfigDict(extra="forbid")

    tools: dict[str, list[VerificationState]] = Field(min_length=1)


class ToolPolicyResponse(BaseModel):
    """The tool policy in force: what each tool is enabled in, and the ceiling."""

    model_config = ConfigDict(extra="forbid")

    version: int
    tools: dict[str, list[str]]
    disabled: list[str]
    code_floor: dict[str, list[str]]


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cards_reset: int
    cards_changed: int
    cards_missing: int
    attempt_limits_cleared: int
    tool_policy_version: int
    tool_policy_changed: bool


class DisputedAmount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int
    currency: str


class HandoffItem(BaseModel):
    """One case in the back-office queue."""

    model_config = ConfigDict(extra="forbid")

    handoff_ref: str
    status: HandoffStatus
    priority: HandoffPriority
    department: Department
    reason: str
    created_at: datetime
    # Only while QUEUED, by the rule the customer's handoff receipt uses.
    queue_position: int | None
    assigned_agent: str | None
    assigned_at: datetime | None
    session_ref: str
    # Set when an agent closed the case (ADR-0018).
    outcome: HandoffOutcome | None = None
    outcome_reason: RejectReason | None = None
    closed_by: str | None = None
    closed_at: datetime | None = None
    # The disputed charge's amount, read from the stored summary, if it has one.
    disputed_amount: DisputedAmount | None = None

    @field_validator("created_at", "assigned_at", "closed_at")
    @classmethod
    def in_utc(cls, value: datetime | None) -> datetime | None:
        # The database session may hand times back in its own zone.
        return value.astimezone(UTC) if value is not None else None


class HandoffListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HandoffItem]


class HandoffFeedback(BaseModel):
    """The customer's answer to "did the assistant help?" (ADR-0017)."""

    model_config = ConfigDict(extra="forbid")

    helpful: bool
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class HandoffDecisions(BaseModel):
    """What the case allows now (ADR-0018); empty lists once it is closed."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[HandoffOutcome]
    reject_reasons: list[RejectReason]
    escalate_to: list[Department]
    # Outcome -> language (es, pt, en) -> the message the customer receives.
    closing_messages: dict[HandoffOutcome, dict[str, str]]


class HandoffDetail(HandoffItem):
    """A queue item with the summary exactly as handoff.create stored it."""

    summary: dict[str, Any]
    feedback: HandoffFeedback | None
    decisions: HandoffDecisions


class AdminHandoffClaimRequest(BaseModel):
    """The agent taking a handoff, as the back office identifies them.

    The email is the audit actor, and `ops.audit_log.actor_ref` holds 128
    characters, so that is the cap, not the 254 of the address format.
    """

    model_config = ConfigDict(extra="forbid")

    agent_ref: str = Field(min_length=3, max_length=128, pattern=r"^[^@\s]+@[^@\s]+$")


_AgentRef = Field(min_length=3, max_length=128, pattern=r"^[^@\s]+@[^@\s]+$")


class AdminHandoffCloseRequest(BaseModel):
    """An agent closing a case: the outcome, and the reason when rejecting."""

    model_config = ConfigDict(extra="forbid")

    agent_ref: str = _AgentRef
    outcome: HandoffOutcome
    reason: RejectReason | None = None


class AdminHandoffEscalateRequest(BaseModel):
    """An agent sending a case back to the queue, elsewhere or more urgent."""

    model_config = ConfigDict(extra="forbid")

    agent_ref: str = _AgentRef
    department: Department
    raise_to_urgent: StrictBool = False


class ToolCallMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    decision: str
    reason_code: str | None
    count: int


class HandoffMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_department: dict[str, int]
    by_outcome: dict[str, int]


class OtpMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sent: int
    verified: int
    failed: int


class FeedbackMetrics(BaseModel):
    """Answers to "did the assistant help?" of the handoffs created in the window."""

    model_config = ConfigDict(extra="forbid")

    helpful: int
    not_helpful: int


class NotHelpfulMetric(BaseModel):
    """A case whose customer answered no: an opaque ref and an enum, no PII."""

    model_config = ConfigDict(extra="forbid")

    handoff_ref: str
    reason: str
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class QueueMetrics(BaseModel):
    """The queue as the metrics are read, whatever the window."""

    model_config = ConfigDict(extra="forbid")

    waiting: int
    urgent: int
    oldest_created_at: datetime | None

    @field_validator("oldest_created_at")
    @classmethod
    def in_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class WindowSummaryMetrics(BaseModel):
    """The headline numbers of the window just before this one."""

    model_config = ConfigDict(extra="forbid")

    cards_blocked: int
    otp: OtpMetrics
    handoffs_total: int
    feedback: FeedbackMetrics


class MetricsResponse(BaseModel):
    """Counts over the window; names, enums and numbers only, no PII."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    window_hours: int
    tool_calls: list[ToolCallMetric]
    handoffs: HandoffMetrics
    cards_blocked: int
    otp: OtpMetrics
    feedback: FeedbackMetrics
    recent_not_helpful: list[NotHelpfulMetric]
    queue: QueueMetrics
    previous: WindowSummaryMetrics


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


def _tool_policy_response(
    version: int, matrix: dict[str, list[str]]
) -> ToolPolicyResponse:
    return ToolPolicyResponse(
        version=version,
        tools=matrix,
        disabled=sorted(name for name, states in matrix.items() if not states),
        code_floor={
            name: sorted(state.value for state in states)
            for name, states in CODE_FLOOR.items()
        },
    )


@router.get(
    "/tool-policy",
    response_model=ToolPolicyResponse,
    dependencies=[Depends(require_admin)],
)
def get_tool_policy() -> ToolPolicyResponse:
    with get_session_maker()() as session:
        record = active_tool_policy(session)
        try:
            matrix = effective_matrix(record)
        except ValueError as exc:
            # A stored version beyond the floor is refused by the authorizer too.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Active tool policy v{record.version} is invalid: {exc}",
            ) from exc
        return _tool_policy_response(
            record.version,
            {
                name: sorted(state.value for state in states)
                for name, states in matrix.items()
            },
        )


@router.put(
    "/tool-policy",
    response_model=ToolPolicyResponse,
    dependencies=[Depends(require_admin)],
)
def put_tool_policy(request: AdminToolPolicyRequest) -> ToolPolicyResponse:
    """Save the tools named as a new active version, audited; refuse any widening."""
    with get_session_maker()() as session:
        try:
            change = save_tool_policy(
                session, request.tools, actor_ref="admin", source="admin_api"
            )
        except ToolPolicyRejected as exc:
            # Same shape as FastAPI's own 422 body, so a client parses one format.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    {
                        "loc": ["body", "tools", problem["tool"]],
                        "msg": problem["message"],
                        "type": problem["type"],
                    }
                    for problem in exc.problems
                ],
            ) from exc
        session.commit()
        return _tool_policy_response(change.version, change.matrix)


def _disputed_amount(summary: dict[str, Any] | None) -> DisputedAmount | None:
    """The amount handoff.create stored with the disputed charge, if any."""
    facts = (summary or {}).get("verified_facts")
    disputed = facts.get("disputed_transaction") if isinstance(facts, dict) else None
    if not isinstance(disputed, dict):
        return None
    amount, currency = disputed.get("amount_minor"), disputed.get("currency")
    if isinstance(amount, int) and not isinstance(amount, bool):
        if isinstance(currency, str) and _CURRENCY_CODE.fullmatch(currency):
            return DisputedAmount(amount_minor=amount, currency=currency)
    return None


def _handoff_fields(row: Handoff, position: int | None) -> dict[str, Any]:
    return {
        "handoff_ref": row.handoff_ref,
        "status": HandoffStatus(row.status),
        "priority": HandoffPriority(row.priority),
        "department": Department(row.department),
        "reason": row.reason,
        "created_at": row.created_at,
        "queue_position": position,
        "assigned_agent": row.assigned_agent,
        "assigned_at": row.assigned_at,
        "session_ref": row.session_ref,
        "outcome": HandoffOutcome(row.outcome) if row.outcome else None,
        "outcome_reason": RejectReason(row.outcome_reason)
        if row.outcome_reason
        else None,
        "closed_by": row.closed_by,
        "closed_at": row.closed_at,
        "disputed_amount": _disputed_amount(row.summary),
    }


def _load_handoff(session: Session, handoff_ref: str) -> HandoffDetail:
    """The handoff as stored, with its place in line and its feedback, read now."""
    found = session.execute(
        sa.select(Handoff, queue_position_expression(Handoff)).where(
            Handoff.handoff_ref == handoff_ref
        )
    ).one_or_none()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="handoff_not_found"
        )
    row, position = found
    stored = read_feedback(session, handoff_ref)
    allowed = allowed_decisions(row)
    return HandoffDetail(
        **_handoff_fields(row, position),
        summary=row.summary,
        feedback=HandoffFeedback(helpful=stored.helpful, recorded_at=stored.recorded_at)
        if stored
        else None,
        decisions=HandoffDecisions(
            outcomes=allowed.outcomes,
            reject_reasons=allowed.reject_reasons,
            escalate_to=allowed.escalate_to,
            closing_messages=allowed.closing_messages,
        ),
    )


def _decision_error(exc: Exception) -> HTTPException:
    """The HTTP answer for a refused decision, claim or close alike."""
    if isinstance(exc, HandoffNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="handoff_not_found")
    if isinstance(exc, ClaimedByAnotherAgentError):
        return HTTPException(
            status.HTTP_409_CONFLICT, detail="claimed_by_another_agent"
        )
    if isinstance(exc, AlreadyClosedError):
        return HTTPException(status.HTTP_409_CONFLICT, detail="already_closed")
    if isinstance(exc, DecisionNotAllowedError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=exc.code)
    raise exc


@router.get(
    "/handoffs",
    response_model=HandoffListResponse,
    dependencies=[Depends(require_admin)],
)
def list_handoffs(
    statuses: Annotated[list[HandoffStatus] | None, Query(alias="status")] = None,
) -> HandoffListResponse:
    """Cases most urgent first, then oldest first; QUEUED and ASSIGNED by default."""
    wanted = statuses or [HandoffStatus.QUEUED, HandoffStatus.ASSIGNED]
    with get_session_maker()() as session:
        rows = session.execute(
            sa.select(Handoff, queue_position_expression(Handoff))
            .where(Handoff.status.in_([item.value for item in wanted]))
            .order_by(
                priority_rank(Handoff.priority).desc(),
                Handoff.created_at,
                Handoff.id,
            )
        ).all()
        return HandoffListResponse(
            items=[
                HandoffItem(**_handoff_fields(row, position)) for row, position in rows
            ]
        )


@router.get(
    "/handoffs/{handoff_ref}",
    response_model=HandoffDetail,
    dependencies=[Depends(require_admin)],
)
def get_handoff(handoff_ref: str) -> HandoffDetail:
    with get_session_maker()() as session:
        return _load_handoff(session, handoff_ref)


@router.post(
    "/handoffs/{handoff_ref}/claim",
    response_model=HandoffDetail,
    dependencies=[Depends(require_admin)],
)
def claim_handoff_for_agent(
    handoff_ref: str, request: AdminHandoffClaimRequest
) -> HandoffDetail:
    """Assign the case to the agent, audited in the same transaction.

    Idempotent for the agent who holds it; 409 for any other. The response is
    read back after the commit.
    """
    with get_session_maker()() as session:
        try:
            claim_handoff(session, handoff_ref, request.agent_ref)
        except HandoffNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="handoff_not_found"
            ) from exc
        except ClaimedByAnotherAgentError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="claimed_by_another_agent",
            ) from exc
        session.commit()
        session.expire_all()
        return _load_handoff(session, handoff_ref)


@router.post(
    "/handoffs/{handoff_ref}/close",
    response_model=HandoffDetail,
    dependencies=[Depends(require_admin)],
)
def close_handoff_for_agent(
    handoff_ref: str, request: AdminHandoffCloseRequest
) -> HandoffDetail:
    """Close the case with an outcome (ADR-0018), audited, claiming it if queued.

    The same close by the same agent again is a no-op. 409 `claimed_by_another_agent`,
    `already_closed`, or a code for an outcome or reason the case does not allow.
    The response is read back after the commit.
    """
    with get_session_maker()() as session:
        try:
            close_handoff(
                session, handoff_ref, request.agent_ref, request.outcome, request.reason
            )
        except (
            HandoffNotFoundError,
            ClaimedByAnotherAgentError,
            AlreadyClosedError,
            DecisionNotAllowedError,
        ) as exc:
            raise _decision_error(exc) from exc
        session.commit()
        session.expire_all()
        return _load_handoff(session, handoff_ref)


@router.post(
    "/handoffs/{handoff_ref}/escalate",
    response_model=HandoffDetail,
    dependencies=[Depends(require_admin)],
)
def escalate_handoff_for_agent(
    handoff_ref: str, request: AdminHandoffEscalateRequest
) -> HandoffDetail:
    """Put the case back in the queue, in another department or more urgent.

    409 `claimed_by_another_agent`, `already_closed` or `nothing_to_escalate`.
    The response is read back after the commit.
    """
    with get_session_maker()() as session:
        try:
            escalate_handoff(
                session,
                handoff_ref,
                request.agent_ref,
                request.department,
                request.raise_to_urgent,
            )
        except (
            HandoffNotFoundError,
            ClaimedByAnotherAgentError,
            AlreadyClosedError,
            DecisionNotAllowedError,
        ) as exc:
            raise _decision_error(exc) from exc
        session.commit()
        session.expire_all()
        return _load_handoff(session, handoff_ref)


def _otp(counts: OtpCounts) -> OtpMetrics:
    return OtpMetrics(sent=counts.sent, verified=counts.verified, failed=counts.failed)


def _feedback(counts: FeedbackCounts) -> FeedbackMetrics:
    return FeedbackMetrics(helpful=counts.helpful, not_helpful=counts.not_helpful)


def _metrics_response(snapshot: MetricsSnapshot) -> MetricsResponse:
    previous = snapshot.previous
    if previous is None:  # collect_metrics always fills it for this route
        raise RuntimeError("metrics snapshot without the previous window")
    return MetricsResponse(
        generated_at=snapshot.generated_at.astimezone(UTC),
        window_hours=snapshot.window_hours,
        tool_calls=[
            ToolCallMetric(
                action=call.action,
                decision=call.decision,
                reason_code=call.reason_code,
                count=call.count,
            )
            for call in snapshot.tool_calls
        ],
        handoffs=HandoffMetrics(
            total=snapshot.handoffs.total,
            by_status=snapshot.handoffs.by_status,
            by_priority=snapshot.handoffs.by_priority,
            by_department=snapshot.handoffs.by_department,
            by_outcome=snapshot.handoffs.by_outcome,
        ),
        cards_blocked=snapshot.cards_blocked,
        otp=_otp(snapshot.otp),
        feedback=_feedback(snapshot.feedback),
        recent_not_helpful=[
            NotHelpfulMetric(
                handoff_ref=case.handoff_ref,
                reason=case.reason,
                recorded_at=case.recorded_at,
            )
            for case in snapshot.recent_not_helpful
        ],
        queue=QueueMetrics(
            waiting=snapshot.queue.waiting,
            urgent=snapshot.queue.urgent,
            oldest_created_at=snapshot.queue.oldest_created_at,
        ),
        previous=WindowSummaryMetrics(
            cards_blocked=previous.cards_blocked,
            otp=_otp(previous.otp),
            handoffs_total=previous.handoffs_total,
            feedback=_feedback(previous.feedback),
        ),
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    dependencies=[Depends(require_admin)],
)
def get_metrics(hours: Annotated[int, Query(ge=1, le=720)] = 24) -> MetricsResponse:
    """Counts from the audit log and the queue over the last `hours` hours."""
    with get_session_maker()() as session:
        return _metrics_response(collect_metrics(session, hours))


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

        # After the card updates, so this transaction takes the card row locks
        # before the audit lock, the order card.block takes them in.
        session.flush()
        tool_policy = reset_tool_policy_to_seed(session)
        result = DemoResetResponse(
            cards_reset=len(cards),
            cards_changed=changed,
            cards_missing=len(seed_states) - len(cards),
            attempt_limits_cleared=attempt_limits_cleared,
            tool_policy_version=tool_policy.version,
            tool_policy_changed=tool_policy.changed,
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
