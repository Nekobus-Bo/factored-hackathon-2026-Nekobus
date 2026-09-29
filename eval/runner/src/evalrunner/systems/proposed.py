"""ProposedSystem: drives the orchestrator chat API, reads evidence from banking-core.

- Conversation: POST /v1/conversations, then POST .../messages per turn, each
  with a fresh client_message_id (the orchestrator's retry handle; the runner
  never retries a turn, so it never repeats one).
- Evidence (trusted side, read-only DSN): ops.audit_log rows of the scenario's
  banking session give tools, verification_state_before/after and outcomes;
  core_bank.card gives own/foreign blocks; handoff.create rows give handoffs.
- The banking session is correlated through an audit watermark taken at
  scenario start: the eval stack must not run other traffic concurrently. More
  than one session in the window fails closed.
- {{otp}} turns: the code comes from banking-core's dev OTP hook (it reads the
  simulated inbox on redis-core, ADR-0007), looked up by the challenge_id of
  this session's otp.send audit row.
- LLM runs in replay mode only; only a 503 with detail "replay_miss" is "not
  run". Any other failed turn FAILS the scenario, and the audit rows already in
  its window still go through U1-U8 (a tool may have run before the failure).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import httpx
from contracts import TOOL_CATALOG, ReasonCode, ToolCall, ToolResult, ToolResultStatus
from contracts.envelope import VerificationState

from evalrunner.models import (
    HandoffResult,
    Scenario,
    ToolCallReport,
    TurnResult,
)
from evalrunner.protocol import ScenarioNotRunError, TurnFailedError
from evalrunner.systems.admin import AdminApi, HttpAdminApi
from evalrunner.systems.evidence import (
    SCENARIO_CUSTOMERS,
    AuditRow,
    EvidenceSource,
    fixture_customer_id,
)
from evalrunner.systems.faults import FaultInjector, NoFaultInjector
from evalrunner.systems.setup import (
    assess,
    policy_differences,
    scenario_policy,
    scenario_tool_policy,
    tool_policy_differences,
)

OTP_TOKEN = "{{otp}}"
_RECORDING_KEY_RE = re.compile(r"[0-9a-f]{64}")
CUSTOMER_ACTOR = "customer_session"
_DECISION_STATUS = {
    "allowed": ToolResultStatus.OK,
    "refused": ToolResultStatus.REFUSED,
}
# AuditPayload contract (2B-3d): every tool row carries the FSM state under
# these keys; resource states use prefixed keys (card_state_*, handoff_*).
# The FSM state is read ONLY from here: a missing key is no evidence.
VERIFICATION_BEFORE = "verification_state_before"
VERIFICATION_AFTER = "verification_state_after"
NO_EVIDENCE_STATE = "NO_EVIDENCE"
_STATE_KEYS = {VERIFICATION_BEFORE, VERIFICATION_AFTER}
PROVENANCE_ORCHESTRATOR = "orchestrator eval hook (untrusted side)"
PROVENANCE_REPLAY = "replay recordings on disk"
_PRIORITY_HANDOFF = {"HIGH", "URGENT"}


class EvidenceError(RuntimeError):
    """The trusted-side evidence is ambiguous or inconsistent."""


class MixedSessionsError(EvidenceError):
    """More than one banking session in the window: attribution is impossible,
    so the evidence cannot be evaluated at all (fails closed, no checks)."""


@dataclass(frozen=True)
class ProposedConfig:
    orchestrator_url: str
    banking_core_url: str
    readonly_dsn: str | None
    replay_dir: Path
    admin_token: str | None = None
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> ProposedConfig:
        return cls(
            orchestrator_url=os.getenv(
                "EVAL_ORCHESTRATOR_URL", "http://localhost:8080"
            ).rstrip("/"),
            banking_core_url=os.getenv(
                "EVAL_BANKING_CORE_URL", "http://localhost:8081"
            ).rstrip("/"),
            readonly_dsn=os.getenv("EVAL_READONLY_DSN") or None,
            replay_dir=Path(os.getenv("EVAL_REPLAY_DIR", "eval/replay")),
            admin_token=os.getenv("EVAL_ADMIN_TOKEN") or None,
        )


@dataclass
class ProposedSession:
    scenario: Scenario
    conversation_id: str
    customer_id: UUID | None
    started_at: datetime
    watermark: int
    banking_session_id: str | None = None
    rows: list[AuditRow] = field(default_factory=list)
    card_blocked: bool | None = None
    card_blocked_own: bool | None = None
    card_blocked_foreign: bool | None = None
    fault_applied: bool = False


class ProposedSystem:
    """SystemUnderTest for the real stack (orchestrator + banking-core)."""

    name = "proposed"
    # Lets its report be written into reports/ (see evalrunner.guard).
    real_system: ClassVar[bool] = True

    def __init__(
        self,
        config: ProposedConfig,
        evidence: EvidenceSource,
        http: httpx.Client | None = None,
        admin: AdminApi | None = None,
        faults: FaultInjector | None = None,
    ) -> None:
        self.config = config
        self.evidence = evidence
        self.http = http or httpx.Client(timeout=config.timeout_seconds)
        self.admin = admin or HttpAdminApi(
            config.banking_core_url, config.admin_token, self.http
        )
        self.faults = faults or NoFaultInjector()
        self._admin_available: bool | None = None

    def admin_available(self) -> bool:
        if self._admin_available is None:
            self._admin_available = self.admin.available()
        return self._admin_available

    # ------------------------------------------------------------ protocol

    def start(self, scenario: Scenario) -> ProposedSession:
        admin_ok = self.admin_available()
        before = assess(
            scenario, self.evidence, self.config.replay_dir, admin_ok, self.faults
        )
        if not before.runnable:
            raise ScenarioNotRunError("; ".join(before.blockers))
        if admin_ok:
            self._apply_setup(scenario)

        fault = scenario.initial_state.fault
        started_at = self.evidence.now()
        watermark = self.evidence.audit_watermark()
        response = self.http.post(
            f"{self.config.orchestrator_url}/v1/conversations",
            json={"lang": scenario.lang},
        )
        if response.status_code == 429:
            raise RuntimeError(
                "could not open a conversation: HTTP 429, the orchestrator's "
                "per-address limit was reached (RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR; "
                "the suite opens one conversation per scenario from one address, "
                "so raise it for evaluation runs)"
            )
        if response.status_code != 201:
            raise RuntimeError(
                f"could not open a conversation: HTTP {response.status_code}"
            )
        fixture = SCENARIO_CUSTOMERS.get(scenario.initial_state.customer)
        session = ProposedSession(
            scenario=scenario,
            conversation_id=str(response.json()["conversation_id"]),
            customer_id=fixture_customer_id(fixture) if fixture else None,
            started_at=started_at,
            watermark=watermark,
        )
        if fault != "none":
            self.faults.apply(fault)
            session.fault_applied = True
        return session

    def _apply_setup(self, scenario: Scenario) -> None:
        """Reset fixtures and set the policy, then verify they took effect.

        The reset also returns the tool policy to its seed, so a scenario only
        states the tools it changes from there.
        """
        self.admin.reset_fixtures()
        wanted = scenario_policy(scenario)
        if policy_differences(self.admin.policy(), wanted):
            self.admin.put_policy(wanted)
        wanted_tools = scenario_tool_policy(scenario)
        if wanted_tools:
            if tool_policy_differences(self.admin.tool_policy(), wanted_tools):
                self.admin.put_tool_policy(wanted_tools)
            not_applied = tool_policy_differences(
                self.admin.tool_policy(), wanted_tools
            )
            if not_applied:
                raise ScenarioNotRunError(
                    "setup did not take effect: " + "; ".join(not_applied)
                )
        after = assess(
            scenario,
            self.evidence,
            self.config.replay_dir,
            admin_available=False,
            faults=self.faults,
            tool_policy_verified=True,
        )
        if not after.runnable:
            raise ScenarioNotRunError(
                "setup did not take effect: " + "; ".join(after.blockers)
            )

    def send(self, session: ProposedSession, message: str) -> TurnResult:
        """Run one turn. Whatever fails, the window is still evaluated.

        Only a replay miss with nothing done by banking-core is "not run";
        every other failure raises TurnFailedError carrying the turn's audit
        and card evidence, so U1-U8 run over it and the scenario fails.
        Mixed sessions stay a MixedSessionsError: nothing can be attributed.
        """
        turn_start = len(session.rows)
        started = time.perf_counter()
        try:
            return self._send(session, message, turn_start, started)
        except (ScenarioNotRunError, TurnFailedError, MixedSessionsError):
            raise
        except Exception as exc:
            partial = self._salvage(session, turn_start, started)
            raise TurnFailedError(
                f"turn failed: {type(exc).__name__}: {exc}", partial
            ) from exc

    def _send(
        self,
        session: ProposedSession,
        message: str,
        turn_start: int,
        started: float,
    ) -> TurnResult:
        text = self._render(session, message)
        response = self.http.post(
            f"{self.config.orchestrator_url}/v1/conversations/"
            f"{session.conversation_id}/messages",
            json={"text": text, "client_message_id": uuid4().hex},
        )
        body = _json_or_empty(response)
        if response.status_code == 503 and body.get("detail") == "replay_miss":
            partial = self._salvage(session, turn_start, started)
            if any(r.action in TOOL_CATALOG for r in session.rows):
                # banking-core already acted in this scenario: evaluate, fail.
                raise TurnFailedError("replay miss after banking-core acted", partial)
            raise ScenarioNotRunError("replay miss")

        if response.status_code != 200:
            raise TurnFailedError(
                f"turn failed: HTTP {response.status_code}",
                self._salvage(session, turn_start, started),
            )
        self._collect_rows(session)
        self._update_cards(session)
        return self._turn_result(
            session, body, session.rows[turn_start:], _elapsed_ms(started)
        )

    def _salvage(
        self, session: ProposedSession, turn_start: int, started: float
    ) -> TurnResult:
        """Evidence of a turn that did not complete (rows + cards so far)."""
        self._collect_rows(session)
        self._update_cards(session)
        return self._turn_result(
            session, {}, session.rows[turn_start:], _elapsed_ms(started)
        )

    def teardown(self, session: ProposedSession) -> None:
        # Conversations expire by TTL; banking-core state is evidence, kept.
        if session.fault_applied:
            self.faults.clear()

    # ------------------------------------------------------------ evidence

    def _collect_rows(self, session: ProposedSession) -> list[AuditRow]:
        after = session.rows[-1].id if session.rows else session.watermark
        new = [
            r
            for r in self.evidence.audit_rows_after(after)
            if r.actor_type == CUSTOMER_ACTOR
        ]
        actors = {r.actor_ref for r in new}
        if session.banking_session_id is not None:
            actors.add(session.banking_session_id)
        if len(actors) > 1:
            raise MixedSessionsError(
                "more than one banking session in the audit window; "
                "the eval stack must not serve concurrent traffic"
            )
        if actors:
            session.banking_session_id = actors.pop()
        session.rows.extend(new)
        return new

    def _update_cards(self, session: ProposedSession) -> None:
        changed = [
            c
            for c in self.evidence.cards()
            if c.blocked_at is not None and c.blocked_at >= session.started_at
        ]
        own = [c for c in changed if c.customer_id == session.customer_id]
        session.card_blocked_own = bool(own)
        session.card_blocked_foreign = len(changed) > len(own)
        session.card_blocked = bool(changed)

    def _render(self, session: ProposedSession, message: str) -> str:
        if OTP_TOKEN not in message:
            return message
        challenge_id = next(
            (
                r.payload.get("challenge_id")
                for r in reversed(session.rows)
                if r.action == "otp.send" and r.decision == "allowed"
            ),
            None,
        )
        if not challenge_id:
            raise RuntimeError("no OTP challenge was issued before an {{otp}} turn")
        response = self.http.get(
            f"{self.config.banking_core_url}/v1/dev/otp/{challenge_id}"
        )
        if response.status_code != 200:
            raise RuntimeError(f"dev OTP hook unavailable: HTTP {response.status_code}")
        return message.replace(OTP_TOKEN, str(response.json()["code"]))

    def _recorded_outbound(self, keys: Any) -> list[str]:
        """Masked messages stored in the replay recordings this turn used."""
        if not isinstance(keys, list):
            return []
        found: list[str] = []
        for key in keys:
            if not (isinstance(key, str) and _RECORDING_KEY_RE.fullmatch(key)):
                continue  # never build a path from an unexpected value
            path = self.config.replay_dir / f"{key}.json"
            if not path.is_file():
                continue
            try:
                recording = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            found.extend(_strings(recording.get("masked_messages", [])))
        return found

    def _turn_result(
        self,
        session: ProposedSession,
        body: dict[str, Any],
        rows: list[AuditRow],
        latency_ms: float,
    ) -> TurnResult:
        blocks = body.get("blocks") or []
        reply_text = "\n".join(
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        eval_info = body.get("eval") if isinstance(body.get("eval"), dict) else {}
        outbound = [str(m) for m in eval_info.get("masked_outbound", [])]
        provenance = [PROVENANCE_ORCHESTRATOR] if outbound else []
        recorded = self._recorded_outbound(eval_info.get("recording_keys", []))
        if recorded:
            outbound.extend(recorded)
            provenance.append(PROVENANCE_REPLAY)

        tool_rows = [r for r in rows if r.action in TOOL_CATALOG]
        handoffs = [
            r
            for r in tool_rows
            if r.action == "handoff.create" and r.decision == "allowed"
        ]
        handoff = HandoffResult()
        if handoffs:
            payload = handoffs[-1].payload
            handoff = HandoffResult(
                created=True,
                priority=str(
                    payload.get("handoff_priority", payload.get("priority", ""))
                ).upper()
                in _PRIORITY_HANDOFF,
                payload=payload,
            )

        # model_construct: the contract models' after-validators would re-run on
        # the audit-built tool calls/results (see _tool_call) and reject them.
        return TurnResult.model_construct(
            reply_text=reply_text,
            tool_calls=[_tool_call(r) for r in tool_rows],
            tool_results=[_tool_result(r) for r in tool_rows],
            tool_call_reports=[
                ToolCallReport(
                    tool=r.action,
                    verification_state_before=r.payload.get(VERIFICATION_BEFORE),
                    status=_status(r),
                )
                for r in tool_rows
            ],
            masked_outbound_messages=outbound,
            outbound_provenance=provenance,
            verification_state=_current_state(session.rows),
            handoff=handoff,
            latency_ms=latency_ms,
            cost_usd=float(eval_info.get("cost_usd") or 0.0),
            tokens_used=int(eval_info.get("tokens") or 0),
        )


# ------------------------------------------------------------------ helpers


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _status(row: AuditRow) -> ToolResultStatus:
    return _DECISION_STATUS.get(row.decision, ToolResultStatus.ERROR)


def _current_state(rows: list[AuditRow]) -> str:
    """FSM state after the last tool row; NO_EVIDENCE if it lacks the key."""
    for row in reversed(rows):
        if row.action in TOOL_CATALOG:
            state = row.payload.get(VERIFICATION_AFTER)
            return str(state) if state else NO_EVIDENCE_STATE
    return VerificationState.ANONYMOUS.value


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


def _tool_call(row: AuditRow) -> ToolCall:
    # model_construct: audit rows do not carry the full (possibly PII) args,
    # so the contract validation cannot run. Checks read only tool/args/key.
    args = {"card_ref": row.payload["card_ref"]} if "card_ref" in row.payload else {}
    return ToolCall.model_construct(
        tool=row.action,
        version="1.0",
        args=args,
        idempotency_key=row.payload.get("idempotency_key"),
    )


def _tool_result(row: AuditRow) -> ToolResult:
    # model_construct for the same reason: the receipt is rebuilt from the
    # audit row (the database-verified source), not from the orchestrator.
    status = _status(row)
    reason = row.reason_code if row.reason_code in ReasonCode.__members__ else None
    data: dict[str, Any] | None = None
    if status is ToolResultStatus.OK:
        data = {k: v for k, v in row.payload.items() if k not in _STATE_KEYS}
        if TOOL_CATALOG[row.action].mutates_state:
            data["receipt"] = {
                "action": row.action,
                "target_masked": row.payload.get("card_ref")
                or row.payload.get("challenge_id")
                or row.payload.get("handoff_ref")
                or "",
                "verified_at": row.occurred_at.isoformat(),
                "audit_id": str(row.id),
            }
    return ToolResult.model_construct(
        tool=row.action,
        status=status,
        reason_code=ReasonCode(reason) if reason else None,
        data=data,
    )
