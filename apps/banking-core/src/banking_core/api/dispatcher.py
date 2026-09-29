"""Tool execution dispatcher for banking-core.

Coordinates the end-to-end tool execution pipeline:
0. Per-session lock: the whole dispatch (read session, execute, save) is serialized
1. Input validation & IDOR check (validate_no_holder_tampering)
2. Records verification_state_before for audit trail
3. Authorizer evaluation (FSM + Matrix + Policy + Rate limits)
4. Idempotency store deduplication for state-mutating tools (scope strictly required)
5. Tool execution & FSM state mutation, computed on a copy of the session
6. Tamper-evident audit logging with PII safety
7. DB commit, and only then the new session state is saved to Redis
8. Return contracts.envelope.ToolResult envelope
"""

import logging
import os
from typing import Any

from contracts.audit import AuditDetail, AuditPayload
from contracts.envelope import (
    ReasonCode,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    VerificationState,
)
from contracts.tools import TOOL_CATALOG
from contracts.tools.account_get_summary import AccountGetSummaryInput
from contracts.tools.card_block import CardBlockInput, CardBlockOutput
from contracts.tools.card_list import CardListInput
from contracts.tools.customer_match import CustomerMatchInput
from contracts.tools.handoff_create import HandoffCreateInput, HandoffCreateOutput
from contracts.tools.identity_verify_document import IdentityVerifyDocumentInput
from contracts.tools.kb_search import KbSearchInput
from contracts.tools.otp_send import OtpSendInput
from contracts.tools.otp_verify import OtpVerifyInput
from contracts.tools.transaction_list_recent import TransactionListRecentInput
from sqlalchemy.orm import Session

from banking_core.accounts.tools import execute_account_get_summary
from banking_core.audit.service import append as append_audit
from banking_core.cards.tools import (
    execute_card_block,
    execute_card_list,
    reread_card_block_output,
)
from banking_core.control.attempt_limits import AttemptLimits, AttemptLimitStore
from banking_core.control.authorize import Authorizer
from banking_core.control.config import (
    ControlConfigRepository,
    get_control_config_repository,
)
from banking_core.control.fsm import VerificationFSM
from banking_core.control.policy import Decision, PolicyConfig
from banking_core.control.session import (
    RedisSessionStore,
    SessionState,
    validate_no_holder_tampering,
)
from banking_core.handoff.tools import (
    execute_handoff_create,
    reread_handoff_create_result,
)
from banking_core.idempotency.exceptions import IdempotencyConflictError
from banking_core.idempotency.service import get_or_run
from banking_core.identity.challenge_store import (
    OtpChallengeStore,
    get_challenge_store,
)
from banking_core.identity.config import IdentityConfig
from banking_core.identity.ports import OtpDeliveryPort, get_delivery_port
from banking_core.identity.tools import (
    CustomerLockedError,
    NoOtpChannelError,
    OtpResendLimitError,
    execute_identity_verify_document,
    execute_limited_customer_match,
    execute_otp_send,
    execute_otp_verify,
)
from banking_core.knowledge.tools.kb_search import execute_kb_search
from banking_core.transactions.tools import execute_transaction_list_recent

logger = logging.getLogger(__name__)


class SessionNotFoundError(LookupError):
    """Raised when the X-Session-Id does not resolve to a live session."""


def _format_audit_id(entry: Any) -> str:
    """Format audit entry reference to satisfy Receipt audit_id constraints.

    Requires at least 8 characters.
    """
    if hasattr(entry, "id") and isinstance(entry.id, int):
        return f"aud_{entry.id:08d}"
    eid = str(getattr(entry, "id", ""))
    return eid if len(eid) >= 8 else f"aud_{eid.zfill(8)}"


class ToolDispatcher:
    """Central dispatcher for banking-core /v1/tools/call endpoint."""

    def __init__(
        self,
        session_store: RedisSessionStore,
        config_repo: ControlConfigRepository | None = None,
        authorizer: Authorizer | None = None,
        identity_config: IdentityConfig | None = None,
        delivery_port: OtpDeliveryPort | None = None,
        challenge_store: OtpChallengeStore | None = None,
        attempt_limit_store: AttemptLimitStore | None = None,
        lock_ttl_ms: int | None = None,
        lock_wait_ms: int | None = None,
    ) -> None:
        self.session_store = session_store
        # DB-backed by default (ADR-0002); InMemory only via explicit injection.
        self.config_repo = config_repo or get_control_config_repository()
        self.authorizer = authorizer or Authorizer(config_repo=self.config_repo)
        self.identity_config = identity_config or IdentityConfig.from_env()
        self.delivery_port = delivery_port or get_delivery_port()
        self.challenge_store = challenge_store or get_challenge_store()
        # Cross-session limits live on redis-core, like the session itself.
        self.attempt_limit_store = attempt_limit_store or AttemptLimitStore(
            redis_client=session_store.client
        )
        self.lock_ttl_ms = (
            lock_ttl_ms
            if lock_ttl_ms is not None
            else int(os.getenv("SESSION_LOCK_TTL_MS", "10000"))
        )
        self.lock_wait_ms = (
            lock_wait_ms
            if lock_wait_ms is not None
            else int(os.getenv("SESSION_LOCK_WAIT_MS", "2000"))
        )

    def _resolve_policy_config(self) -> PolicyConfig:
        """Single entry point for policy configuration used during execution."""
        return self.config_repo.get_policy_config()

    def _attempt_limits(self, policy_config: PolicyConfig) -> AttemptLimits:
        """The cross-session limits bound to the policy config in force."""
        return AttemptLimits.from_config(self.attempt_limit_store, policy_config)

    def _audit_limit_event(
        self,
        db_session: Session,
        session_id: str,
        action: str,
        state_before: VerificationState,
        state_after: VerificationState,
        reason: str,
        details: dict[str, AuditDetail],
    ) -> None:
        """Audit the moment a cross-session limit starts to act, without PII.

        Written in the transaction of the call that tripped it. Details carry an
        internal customer UUID or a blind-index reference plus the thresholds in
        force, never a document, a name or a contact.
        """
        append_audit(
            session=db_session,
            actor_type="system",
            actor_ref=session_id,
            action=action,
            decision="refused",
            reason_code=ReasonCode.RATE_LIMITED.value,
            payload=AuditPayload(
                verification_state_before=state_before,
                verification_state_after=state_after,
                status=ToolResultStatus.REFUSED,
                reason=reason,
                details=details,
            ),
        )

    def _refuse(
        self,
        tool_call: ToolCall,
        session_id: str,
        reason_code: ReasonCode,
        db_session: Session,
        verification_state_before: VerificationState,
        verification_state_after: VerificationState,
        reason: str | None = None,
        details: dict[str, AuditDetail] | None = None,
        session_after: SessionState | None = None,
        session_ttl_seconds: int | None = None,
    ) -> ToolResult:
        """Audit a refused call and return the refusal envelope.

        session_after is a state the refusal itself causes (a lock). It is saved
        only once the refusal's audit row is committed, so the stored session
        never moves ahead of the audit trail; if either step fails the session
        simply does not advance.
        """
        tool_def = TOOL_CATALOG.get(tool_call.tool)
        idempotency_scope = (
            session_id if tool_def is not None and tool_def.mutates_state else None
        )
        audited = False
        try:
            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session_id,
                action=tool_call.tool,
                decision="refused",
                reason_code=reason_code.value,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=verification_state_after,
                    status=ToolResultStatus.REFUSED,
                    reason=reason or reason_code.value,
                    idempotency_scope=idempotency_scope,
                    details=details or {},
                ),
            )
            db_session.commit()
            audited = True
        except Exception as exc:
            logger.warning(
                "Failed to record audit log for refused call: %s",
                type(exc).__name__,
            )
            db_session.rollback()
        if audited and session_after is not None:
            try:
                self._save_session_after_commit(session_after, session_ttl_seconds)
            except Exception as exc:
                logger.error(
                    "Failed to save session after refused '%s': %s",
                    tool_call.tool,
                    type(exc).__name__,
                )
        return ToolResult(
            tool=tool_call.tool,
            status=ToolResultStatus.REFUSED,
            reason_code=reason_code,
            data=None,
        )

    def _audit_error(
        self,
        tool_name: str,
        session_id: str,
        verification_state_before: VerificationState,
        verification_state_after: VerificationState,
        db_session: Session,
        error: Exception,
    ) -> None:
        """Audit one failed tool execution without exposing exception text."""
        tool_def = TOOL_CATALOG.get(tool_name)
        idempotency_scope = (
            session_id if tool_def is not None and tool_def.mutates_state else None
        )
        try:
            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session_id,
                action=tool_name,
                decision="error",
                reason_code=ReasonCode.INTERNAL_ERROR.value,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=verification_state_after,
                    status=ToolResultStatus.ERROR,
                    reason=type(error).__name__,
                    idempotency_scope=idempotency_scope,
                    details={"exception_type": type(error).__name__},
                ),
            )
            db_session.commit()
        except Exception as audit_error:
            logger.warning(
                "Failed to record tool error audit row: %s",
                type(audit_error).__name__,
            )
            db_session.rollback()

    def _save_session_after_commit(
        self, session: SessionState, ttl_seconds: int | None
    ) -> None:
        """Persist a session state to Redis; call it only after the DB commit.

        Order matters: the audit row and the idempotency record must exist before
        the session moves. Committing first and saving second fails closed: if the
        save fails after the commit, the session simply did not advance (the call
        reports an error and the caller starts the step again), whereas saving
        first would leave Redis ahead of a database that rolled back, e.g.
        VERIFIED with no audit row.

        ttl_seconds is the session TTL of the policy config in force for this call;
        None leaves it to the store's configured default.
        """
        self.session_store.save(session, ttl_seconds=ttl_seconds)

    def dispatch_in_session(
        self,
        tool_call: ToolCall,
        session_id: str,
        db_session: Session,
    ) -> ToolResult:
        """Load the session and dispatch under its exclusive lock.

        A call that cannot take the lock within lock_wait_ms is refused with
        SESSION_BUSY, which the caller may retry.

        Raises:
            SessionNotFoundError: If the session does not exist or expired.
        """
        with self.session_store.lock(
            session_id, ttl_ms=self.lock_ttl_ms, wait_ms=self.lock_wait_ms
        ) as acquired:
            if not acquired:
                session = self.session_store.get(session_id)
                if session is None:
                    raise SessionNotFoundError(session_id)
                return self._refuse(
                    tool_call,
                    session_id,
                    ReasonCode.SESSION_BUSY,
                    db_session,
                    verification_state_before=session.state,
                    verification_state_after=session.state,
                    reason="session_lock_busy",
                )
            session = self.session_store.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            return self.dispatch(tool_call, session, db_session)

    def dispatch(
        self,
        tool_call: ToolCall,
        session: SessionState,
        db_session: Session,
    ) -> ToolResult:
        """Process and execute a ToolCall.

        Callers must hold the session lock (see dispatch_in_session).
        """
        # 1. Enforce ADR-0004 IDOR mitigation: no holder tampering in args
        try:
            validate_no_holder_tampering(tool_call.args)
        except ValueError:
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.REFUSED,
                reason_code=ReasonCode.INVALID_ARGUMENTS,
                data=None,
            )

        # 2. Capture session verification state BEFORE execution (required for U1 check)
        verification_state_before = session.state

        # 3. Deterministic authorization (FSM + Matrix + Policy + per-session limits)
        decision = self.authorizer.authorize(tool_call=tool_call, session=session)

        if not decision.allowed:
            return self._refuse(
                tool_call,
                session.session_id,
                decision.reason_code or ReasonCode.POLICY_BLOCKED,
                db_session,
                verification_state_before=verification_state_before,
                verification_state_after=session.state,
                details={"flags": decision.flags},
            )

        # 4. Resolve policy & FSM for execution (fail closed if config is gone)
        try:
            policy_config = self._resolve_policy_config()
        except Exception as exc:
            logger.error(
                "Policy configuration unavailable for tool '%s': %s: %s",
                tool_call.tool,
                type(exc).__name__,
                exc,
            )
            return self._refuse(
                tool_call,
                session.session_id,
                ReasonCode.INTERNAL_ERROR,
                db_session,
                verification_state_before=verification_state_before,
                verification_state_after=session.state,
                details={"flags": ["POLICY_CONFIG_UNAVAILABLE"]},
            )
        fsm = VerificationFSM.from_config(policy_config)

        tool_def = TOOL_CATALOG.get(tool_call.tool)
        if tool_def is None:
            return ToolResult(
                tool=tool_call.tool,
                status=ToolResultStatus.REFUSED,
                reason_code=ReasonCode.INVALID_ARGUMENTS,
                data=None,
            )

        # 5. Handle tools: mutating vs non-mutating
        if tool_def.mutates_state:
            # Mutating tool requires idempotency key and session-scoped execution
            if not tool_call.idempotency_key:
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.REFUSED,
                    reason_code=ReasonCode.INVALID_ARGUMENTS,
                    data=None,
                )

            # The session state the runner computed, saved only after the commit.
            # It stays None on an idempotent replay, where the runner never runs:
            # a replay must not re-apply the transition.
            advanced_session: SessionState | None = None

            def runner() -> dict[str, Any]:
                nonlocal advanced_session
                data, advanced_session = self._execute_mutating_tool(
                    tool_name=tool_call.tool,
                    tool_args=tool_call.args,
                    session=session,
                    fsm=fsm,
                    policy_config=policy_config,
                    db_session=db_session,
                    policy_decision=decision,
                    verification_state_before=verification_state_before,
                )
                return data

            try:
                result_data, was_replayed = get_or_run(
                    session=db_session,
                    key=tool_call.idempotency_key,
                    tool=tool_call.tool,
                    args=tool_call.args,
                    runner=runner,
                    scope=session.session_id,
                    require_scope=True,
                    ttl_seconds=policy_config.session_ttl_seconds,
                )
                db_session.commit()
                # Commit first, save second (see _save_session_after_commit).
                if advanced_session is not None:
                    self._save_session_after_commit(
                        advanced_session, policy_config.session_ttl_seconds
                    )
                if tool_call.tool == "handoff.create":
                    self._save_session_after_commit(
                        fsm.on_handoff_create(session),
                        policy_config.session_ttl_seconds,
                    )
                if not was_replayed:
                    try:
                        if tool_call.tool == "card.block":
                            if session.pinned_holder_id is None:
                                raise RuntimeError(
                                    "committed card.block has no session holder"
                                )
                            output = CardBlockOutput.model_validate(result_data)
                            refreshed = reread_card_block_output(
                                db_session,
                                session.pinned_holder_id,
                                output.card_ref,
                                int(output.receipt.audit_id.removeprefix("aud_")),
                            ).model_dump(mode="json")
                        elif tool_call.tool == "handoff.create":
                            output = HandoffCreateOutput.model_validate(result_data)
                            refreshed = reread_handoff_create_result(
                                db_session, output
                            ).output.model_dump(mode="json")
                        else:
                            refreshed = result_data
                        if refreshed != result_data:
                            logger.warning(
                                "Committed tool receipt changed during re-read: %s",
                                tool_call.tool,
                            )
                        else:
                            result_data = refreshed
                    except Exception as reread_error:
                        db_session.rollback()
                        logger.error(
                            "Committed tool receipt re-read failed for '%s': %s",
                            tool_call.tool,
                            type(reread_error).__name__,
                        )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.OK,
                    data=result_data,
                )
            except IdempotencyConflictError:
                # A key reused with different arguments is a caller error, not a
                # server fault: nothing ran, and the caller must use a new key.
                db_session.rollback()
                return self._refuse(
                    tool_call,
                    session.session_id,
                    ReasonCode.INVALID_ARGUMENTS,
                    db_session,
                    verification_state_before=verification_state_before,
                    verification_state_after=session.state,
                    reason="idempotency_key_reused_with_different_arguments",
                )
            except NoOtpChannelError as exc:
                db_session.rollback()
                return self._refuse(
                    tool_call,
                    session.session_id,
                    ReasonCode.POLICY_BLOCKED,
                    db_session,
                    verification_state_before=verification_state_before,
                    verification_state_after=session.state,
                    reason=exc.audit_reason,
                )
            except CustomerLockedError as exc:
                # The customer is locked across sessions: nothing was delivered,
                # stored or compared, and this session goes to a human.
                db_session.rollback()
                return self._refuse(
                    tool_call,
                    session.session_id,
                    ReasonCode.RATE_LIMITED,
                    db_session,
                    verification_state_before=verification_state_before,
                    verification_state_after=exc.locked_session.state,
                    reason="customer_otp_locked",
                    details={
                        "flags": ["CUSTOMER_OTP_LOCKED"],
                        "customer_id": exc.customer_id,
                    },
                    session_after=exc.locked_session,
                    session_ttl_seconds=policy_config.session_ttl_seconds,
                )
            except OtpResendLimitError as exc:
                # Nothing was delivered or stored: the resend that would have
                # tripped the limit is refused and locks the session instead.
                db_session.rollback()
                return self._refuse(
                    tool_call,
                    session.session_id,
                    ReasonCode.RATE_LIMITED,
                    db_session,
                    verification_state_before=verification_state_before,
                    verification_state_after=exc.locked_session.state,
                    reason="otp_resend_limit_exceeded",
                    details={"flags": ["OTP_RESEND_LIMIT_EXCEEDED"]},
                    session_after=exc.locked_session,
                    session_ttl_seconds=policy_config.session_ttl_seconds,
                )
            except Exception as exc:
                db_session.rollback()
                logger.error(
                    "Error executing mutating tool '%s': %s",
                    tool_call.tool,
                    type(exc).__name__,
                )
                self._audit_error(
                    tool_call.tool,
                    session.session_id,
                    verification_state_before,
                    session.state,
                    db_session,
                    exc,
                )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INTERNAL_ERROR,
                    data=None,
                )

        else:
            # Non-mutating tool (customer.match, identity.verify_document)
            try:
                result_data, advanced_session = self._execute_read_tool(
                    tool_name=tool_call.tool,
                    tool_args=tool_call.args,
                    session=session,
                    fsm=fsm,
                    policy_config=policy_config,
                    db_session=db_session,
                    verification_state_before=verification_state_before,
                )
                db_session.commit()
                # Commit first, save second (see _save_session_after_commit).
                if advanced_session is not None:
                    self._save_session_after_commit(
                        advanced_session, policy_config.session_ttl_seconds
                    )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.OK,
                    data=result_data,
                )
            except Exception as exc:
                db_session.rollback()
                logger.error(
                    "Error executing read tool '%s': %s",
                    tool_call.tool,
                    type(exc).__name__,
                )
                self._audit_error(
                    tool_call.tool,
                    session.session_id,
                    verification_state_before,
                    session.state,
                    db_session,
                    exc,
                )
                return ToolResult(
                    tool=tool_call.tool,
                    status=ToolResultStatus.ERROR,
                    reason_code=ReasonCode.INTERNAL_ERROR,
                    data=None,
                )

    def _execute_mutating_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session: SessionState,
        fsm: VerificationFSM,
        policy_config: PolicyConfig,
        policy_decision: Decision,
        db_session: Session,
        verification_state_before: VerificationState,
    ) -> tuple[dict[str, Any], SessionState | None]:
        """Execute a write inside get_or_run's idempotency transaction.

        Returns the response data and the session state to persist after the
        commit (None when the tool does not move the session here). The session
        passed in is never modified and nothing is saved to Redis in here.
        """
        if tool_name == "otp.send":
            input_args = OtpSendInput.model_validate(tool_args)
            output, updated_session = execute_otp_send(
                db_session=db_session,
                args=input_args,
                session=session,
                fsm=fsm,
                limits=self._attempt_limits(policy_config),
                delivery_port=self.delivery_port,
                challenge_store=self.challenge_store,
                ttl_seconds=policy_config.otp_ttl_seconds,
            )
            audit_entry = append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=updated_session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    idempotency_scope=session.session_id,
                    details={
                        "challenge_id": output.challenge_id,
                        "channel": output.channel.value,
                        "destination_masked": output.destination_masked,
                    },
                ),
            )
            data = output.model_dump(mode="json")
            data["receipt"]["audit_id"] = _format_audit_id(audit_entry)
            return data, updated_session

        if tool_name == "otp.verify":
            input_args = OtpVerifyInput.model_validate(tool_args)
            verify = execute_otp_verify(
                args=input_args,
                session=session,
                fsm=fsm,
                limits=self._attempt_limits(policy_config),
                challenge_store=self.challenge_store,
            )
            output, updated_session = verify.output, verify.session
            audit_entry = append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    idempotency_scope=session.session_id,
                    verification_state_before=verification_state_before,
                    verification_state_after=updated_session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    details={
                        "verified": output.verified,
                        "attempts_remaining": output.attempts_remaining,
                    },
                ),
            )
            if verify.customer_locked and session.pinned_holder_id:
                self._audit_limit_event(
                    db_session,
                    session.session_id,
                    action="security.customer_otp_locked",
                    state_before=verification_state_before,
                    state_after=updated_session.state,
                    reason="customer_otp_failure_limit_reached",
                    details={
                        "customer_id": session.pinned_holder_id,
                        "max_failures": policy_config.customer_otp_max_failures,
                        "window_seconds": policy_config.customer_otp_window_seconds,
                        "lock_seconds": policy_config.customer_otp_lock_seconds,
                    },
                )
            data = output.model_dump(mode="json")
            data["receipt"]["audit_id"] = _format_audit_id(audit_entry)
            return data, updated_session

        if tool_name == "card.block":
            if session.pinned_holder_id is None:
                raise ValueError("card.block requires a pinned verified holder")
            result = execute_card_block(
                db_session=db_session,
                holder_customer_id=session.pinned_holder_id,
                args=CardBlockInput.model_validate(tool_args),
                policy_decision=policy_decision,
                idempotency_scope=session.session_id,
                verification_state_before=verification_state_before,
                verification_state_after=session.state,
                session_id=session.session_id,
                commit=False,
            )
            return result.output.model_dump(mode="json"), None

        if tool_name == "handoff.create":
            updated_session = fsm.on_handoff_create(session.model_copy())
            result = execute_handoff_create(
                db_session=db_session,
                holder_customer_id=session.pinned_holder_id,
                args=HandoffCreateInput.model_validate(tool_args),
                policy_decision=policy_decision,
                idempotency_scope=session.session_id,
                verification_state_before=verification_state_before,
                verification_state_after=updated_session.state,
                session_id=session.session_id,
                commit=False,
            )

            # handoff.create moves the session in dispatch, after the commit and
            # also on a replay, so a committed handoff always ends in HANDED_OFF.
            return result.output.model_dump(mode="json"), None

        raise ValueError(f"Unsupported mutating tool '{tool_name}'")

    def _execute_read_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session: SessionState,
        fsm: VerificationFSM,
        policy_config: PolicyConfig,
        db_session: Session,
        verification_state_before: VerificationState,
    ) -> tuple[dict[str, Any], SessionState | None]:
        """Execute one holder-scoped or public read tool.

        Returns the response data and the session state to persist after the
        commit (only customer.match moves the session). Nothing is saved to
        Redis in here and the session passed in is never modified.
        """
        if tool_name == "customer.match":
            input_args = CustomerMatchInput.model_validate(tool_args)
            match = execute_limited_customer_match(
                db_session=db_session,
                args=input_args,
                limits=self._attempt_limits(policy_config),
                identity_config=self.identity_config,
            )
            output, matched_customer_id = match.output, match.customer_id
            if output.matched and matched_customer_id:
                updated_session = fsm.on_customer_match(
                    session=session.model_copy(),
                    matched=True,
                    holder_id=matched_customer_id,
                )
            else:
                updated_session = fsm.on_customer_match(
                    session=session.model_copy(), matched=False
                )
            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=updated_session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    # A call the per-document limit answered without looking is
                    # flagged for forensics; it is the same for a document that
                    # exists and one that does not.
                    details=(
                        {"matched": output.matched, "limited": True}
                        if match.limited
                        else {"matched": output.matched}
                    ),
                ),
            )
            if match.limit_reached_ref:
                self._audit_limit_event(
                    db_session,
                    session.session_id,
                    action="security.document_match_limited",
                    state_before=verification_state_before,
                    state_after=updated_session.state,
                    reason="document_match_failure_limit_reached",
                    details={
                        "document_ref": match.limit_reached_ref,
                        "max_failures": policy_config.document_match_max_failures,
                        "window_seconds": policy_config.document_match_window_seconds,
                    },
                )
            return output.model_dump(mode="json"), updated_session

        if tool_name == "identity.verify_document":
            input_args = IdentityVerifyDocumentInput.model_validate(tool_args)
            output = execute_identity_verify_document(args=input_args, session=session)
            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    details={
                        "decision": output.decision.value,
                        "reasons": output.reasons,
                        "score": output.score,
                    },
                ),
            )
            return output.model_dump(mode="json"), None

        if tool_name in {
            "account.get_summary",
            "card.list",
            "transaction.list_recent",
        }:
            holder_id = session.pinned_holder_id
            if holder_id is None:
                raise ValueError(f"{tool_name} requires a pinned verified holder")

            if tool_name == "account.get_summary":
                output = execute_account_get_summary(
                    db_session,
                    holder_id,
                    AccountGetSummaryInput.model_validate(tool_args),
                )
                result_count = len(output.accounts)
            elif tool_name == "card.list":
                output = execute_card_list(
                    db_session,
                    holder_id,
                    CardListInput.model_validate(tool_args),
                )
                result_count = len(output.cards)
            else:
                output = execute_transaction_list_recent(
                    db_session,
                    holder_id,
                    TransactionListRecentInput.model_validate(tool_args),
                )
                result_count = len(output.transactions)

            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    details={"result_count": result_count},
                ),
            )
            return output.model_dump(mode="json"), None

        if tool_name == "kb.search":
            output = execute_kb_search(KbSearchInput.model_validate(tool_args))
            append_audit(
                session=db_session,
                actor_type="customer_session",
                actor_ref=session.session_id,
                action=tool_name,
                decision="allowed",
                reason_code=None,
                payload=AuditPayload(
                    verification_state_before=verification_state_before,
                    verification_state_after=session.state,
                    status=ToolResultStatus.OK,
                    reason=None,
                    details={"result_count": len(output.results)},
                ),
            )
            return output.model_dump(mode="json"), None

        raise ValueError(f"Unsupported read tool '{tool_name}'")
