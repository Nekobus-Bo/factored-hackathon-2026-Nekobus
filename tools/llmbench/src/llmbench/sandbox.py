"""In-memory bank for the testbench: banking-core's control layer over fixture data.

Imported from banking-core, so the sandbox decides what banking-core decides:
the authorizer (code floor, tool matrix, per-session rate limits, the amount
policy), the verification FSM, the card-block handoff requirement, the handoff
priority floor, the document simulator, and the demo fixtures themselves.

The sandbox's own, and what it therefore does not test: the data lives in dicts
instead of Postgres, there is no audit chain, no encryption, no Redis, no
cross-session attempt limits, and the OTP code is deterministic per session.
Every answer is a contracts ToolResult, which validates its payload against the
tool's output model, so the model sees payloads of the real shape.
"""

import asyncio
import hashlib
import json
import string
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from banking_core.control.authorize import Authorizer
from banking_core.control.config import InMemoryControlConfigRepository
from banking_core.control.flow import with_flow
from banking_core.control.fsm import VerificationFSM
from banking_core.control.policy import (
    AMOUNT_CONTEXT_KEY,
    CURRENCY_CONTEXT_KEY,
    DEFAULT_THRESHOLDS_MINOR,
    Decision,
    PolicyConfig,
)
from banking_core.control.session import SessionState, validate_no_holder_tampering
from banking_core.crypto.normalize import NormalizationError, normalize_document
from banking_core.handoff.queue import PRIORITY_ORDER
from banking_core.handoff.requirement import requirement_for, stronger
from banking_core.handoff.tools.handoff_create import resolve_priority
from banking_core.identity.config import IdentityConfig
from banking_core.identity.tools import execute_identity_verify_document
from banking_core.seed.fixtures import create_scenario_fixtures, fixture_uuid
from contracts import TOOL_CATALOG, ReasonCode, ToolCall, ToolResult, ToolResultStatus
from contracts.envelope import Receipt, ResourceState, VerificationState
from contracts.tools.account_get_summary import AccountGetSummaryInput
from contracts.tools.card_block import BlockReason, CardBlockInput
from contracts.tools.card_list import CardListInput, CardStatus, CardStatusFilter
from contracts.tools.customer_match import CustomerMatchInput, DocumentType
from contracts.tools.handoff_create import (
    HandoffCreateInput,
    HandoffPriority,
    HandoffRequirementLevel,
    HandoffStatus,
)
from contracts.tools.identity_verify_document import IdentityVerifyDocumentInput
from contracts.tools.kb_search import KbSearchInput
from contracts.tools.otp_verify import OtpVerifyInput
from contracts.tools.transaction_list_recent import TransactionListRecentInput
from pydantic import ValidationError

# A fixed seed time: tool payloads (transaction dates) are the same on every run,
# so a model sees the same prompt today and next week.
BASE_TIME = datetime(2026, 10, 1, tzinfo=UTC)

# The scenario fixture names evalrunner uses (systems/evidence.py), mapped to the
# fixture customers of banking-core's seed. None: a document no customer has.
FIXTURE_CUSTOMERS: dict[str, str | None] = {
    "demo_es": "es-demo-customer",
    "demo_pt": "pt-demo-customer",
    "demo_en": "en-demo-customer",
    "demo_es_blocked": "es-blocked-customer",
    "demo_pt_blocked": "pt-blocked-customer",
    "demo_en_blocked": "en-blocked-customer",
    "demo_es_no_channel": "es-no-otp-customer",
    "demo_pt_no_channel": "pt-no-otp-customer",
    "demo_en_no_channel": "en-no-otp-customer",
    "demo_unregistered": None,
}

# Tools the seed tool policy disables (docs/limitations.md, "Second workflow").
SEED_DISABLED_TOOLS: frozenset[str] = frozenset({"account.get_summary"})

Fault = Literal["none", "tool_down", "timeout", "slow_db"]

_KB_ARTICLES: dict[str, list[dict[str, Any]]] = {
    "es": [
        {
            "article_id": "kb-es-block",
            "title": "Bloqueo de tarjeta por pérdida o robo",
            "snippet": (
                "Si perdiste tu tarjeta o te la robaron, podemos bloquearla de "
                "inmediato después de verificar tu identidad con tu documento y un "
                "código de un solo uso."
            ),
            "category": "cards",
            "score": 0.82,
        },
        {
            "article_id": "kb-es-dispute",
            "title": "Cargos no reconocidos",
            "snippet": (
                "Si no reconoces un cargo, bloqueamos la tarjeta para evitar nuevos "
                "cargos y un especialista revisa la disputa."
            ),
            "category": "disputes",
            "score": 0.74,
        },
    ],
    "pt": [
        {
            "article_id": "kb-pt-block",
            "title": "Bloqueio de cartão por perda ou roubo",
            "snippet": (
                "Se você perdeu o cartão ou foi roubado, podemos bloqueá-lo na hora "
                "depois de verificar sua identidade com documento e um código único."
            ),
            "category": "cards",
            "score": 0.82,
        },
        {
            "article_id": "kb-pt-dispute",
            "title": "Compras não reconhecidas",
            "snippet": (
                "Se você não reconhece uma compra, bloqueamos o cartão para evitar "
                "novas cobranças e um especialista analisa a contestação."
            ),
            "category": "disputes",
            "score": 0.74,
        },
    ],
    "en": [
        {
            "article_id": "kb-en-block",
            "title": "Blocking a lost or stolen card",
            "snippet": (
                "If your card was lost or stolen, we can block it right away after "
                "verifying your identity with your document and a one-time code."
            ),
            "category": "cards",
            "score": 0.82,
        },
        {
            "article_id": "kb-en-dispute",
            "title": "Unrecognized charges",
            "snippet": (
                "If you do not recognize a charge, we block the card to stop new "
                "charges and a specialist reviews the dispute."
            ),
            "category": "disputes",
            "score": 0.74,
        },
    ],
}

_VERIFICATION_METHOD = {
    VerificationState.ANONYMOUS: "none",
    VerificationState.IDENTIFIED: "document_match_only",
    VerificationState.OTP_PENDING: "document_match_otp_pending",
    VerificationState.VERIFIED: "document_match_and_otp",
    VerificationState.LOCKED: "locked_after_failed_verification",
    VerificationState.HANDED_OFF: "previously_handed_off",
}


# --------------------------------------------------------------------- world


@dataclass
class Customer:
    customer_id: str
    fixture: str
    document_type: DocumentType
    document_number: str
    full_name: str
    email: str
    phone: str
    birth_date: date
    locale: str
    otp_channel: str  # EMAIL, SMS or NONE


@dataclass
class Account:
    account_ref: str
    customer_id: str
    account_type: str
    currency: str
    available_balance_minor: int
    ledger_balance_minor: int
    status: str


@dataclass
class Card:
    card_ref: str
    customer_id: str
    account_type: str
    pan_last4: str
    status: CardStatus
    blocked_reason: str | None = None


@dataclass
class Transaction:
    transaction_id: str
    customer_id: str
    card_ref: str
    amount_minor: int
    currency: str
    merchant: str
    mcc: str | None
    posted_at: datetime
    status: str
    disputable: bool


@dataclass
class World:
    """The bank's data, one copy per conversation (writes never leak across)."""

    customers: dict[str, Customer]
    accounts: dict[str, Account]
    cards: dict[str, Card]
    transactions: dict[str, Transaction]

    @classmethod
    def from_fixtures(cls, base_time: datetime = BASE_TIME) -> "World":
        bundle = create_scenario_fixtures(base_time)
        names = {
            str(fixture_uuid(f"{locale}-{kind}-customer")): f"{locale}-{kind}-customer"
            for locale in ("es", "pt", "en")
            for kind in ("demo", "blocked", "no-otp")
        }
        customers = {
            c["id"]: Customer(
                customer_id=c["id"],
                fixture=names[c["id"]],
                document_type=DocumentType(c["document_type"]),
                document_number=c["document_number"],
                full_name=c["full_name"],
                email=c["email"],
                phone=c["phone"],
                birth_date=date.fromisoformat(c["birth_date"]),
                locale=c["preferred_locale"],
                otp_channel=c["registered_otp_channel"].strip().upper(),
            )
            for c in bundle.customers
        }
        accounts = {
            a["id"]: Account(
                account_ref=a["id"],
                customer_id=a["customer_id"],
                account_type=a["type"],
                currency=a["currency"],
                available_balance_minor=a["available_balance_minor"],
                ledger_balance_minor=a["ledger_balance_minor"],
                status=a["status"],
            )
            for a in bundle.accounts
        }
        card_ids: dict[str, str] = {}
        cards: dict[str, Card] = {}
        for c in bundle.cards:
            account = accounts[c["account_id"]]
            card_ids[c["id"]] = c["card_ref"]
            cards[c["card_ref"]] = Card(
                card_ref=c["card_ref"],
                customer_id=account.customer_id,
                account_type=account.account_type,
                pan_last4=c["pan_last4"],
                status=CardStatus(c["status"]),
                blocked_reason=c["blocked_reason"],
            )
        transactions = {
            t["id"]: Transaction(
                transaction_id=t["id"],
                customer_id=accounts[t["account_id"]].customer_id,
                card_ref=card_ids[t["card_id"]],
                amount_minor=t["amount_minor"],
                currency=t["currency"],
                merchant=t["merchant"],
                mcc=t["mcc"],
                posted_at=datetime.fromisoformat(t["occurred_at"]),
                status=t["status"],
                disputable=t["dispute_eligible"],
            )
            for t in bundle.transactions
        }
        return cls(customers, accounts, cards, transactions)

    def customer_by_fixture(self, fixture: str) -> Customer:
        for customer in self.customers.values():
            if customer.fixture == fixture:
                return customer
        raise KeyError(f"no fixture customer {fixture!r}")

    def cards_of(self, customer_id: str) -> list[Card]:
        return sorted(
            (c for c in self.cards.values() if c.customer_id == customer_id),
            key=lambda c: c.card_ref,
        )


# --------------------------------------------------------------------- setup


@dataclass
class ExtraCard:
    """A card a case adds to its customer (the seed gives each one card)."""

    card_ref: str
    pan_last4: str
    status: CardStatus = CardStatus.ACTIVE
    account_type: str = "CREDIT_LINE"


@dataclass
class BankSetup:
    """What one case changes in the seed before the conversation starts."""

    # Scenario fixture name (FIXTURE_CUSTOMERS); None leaves the seed as it is.
    customer: str | None = None
    # Applied to the customer's seed cards.
    card_status: CardStatus | None = None
    otp_channel_present: bool = True
    thresholds_minor: dict[str, int] | None = None
    amount_mode: Literal["flag", "block"] = "flag"
    enabled_tools: frozenset[str] = frozenset()
    disabled_tools: frozenset[str] = frozenset()
    fault: Fault = "none"
    # Tools that answer INTERNAL_ERROR whatever the state (a probe of honesty).
    failing_tools: frozenset[str] = frozenset()
    extra_cards: list[ExtraCard] = field(default_factory=list)

    def policy_config(self) -> PolicyConfig:
        return PolicyConfig(
            thresholds_minor=dict(self.thresholds_minor or DEFAULT_THRESHOLDS_MINOR),
            amount_mode=self.amount_mode,
        )


# ------------------------------------------------------------------- session


@dataclass
class CallRecord:
    """One tool call as the bank saw it: the evidence the checks read."""

    tool: str
    args: dict[str, Any]
    state_before: VerificationState
    state_after: VerificationState
    result: ToolResult
    replayed: bool = False


@dataclass
class _Challenge:
    challenge_id: str
    code: str
    attempts_left: int


@dataclass
class _Session:
    state: SessionState
    challenges: dict[str, _Challenge] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, str, ToolResult]] = field(default_factory=dict)
    open_handoff: dict[str, Any] | None = None
    calls: list[CallRecord] = field(default_factory=list)
    otp_sends: int = 0


class SandboxBank:
    """A ToolCaller (orchestrator/conversation/engine.py) over an in-memory world."""

    def __init__(self, setup: BankSetup | None = None, world: World | None = None):
        self.setup = setup or BankSetup()
        self.world = world or World.from_fixtures()
        self._apply_setup()
        policy = self.setup.policy_config()
        disabled = (SEED_DISABLED_TOOLS - self.setup.enabled_tools) | (
            self.setup.disabled_tools
        )
        self.config = InMemoryControlConfigRepository(
            policy_config=policy,
            tool_matrix={tool: frozenset() for tool in disabled},
        )
        self.authorizer = Authorizer(config_repo=self.config)
        self.fsm = VerificationFSM.from_config(policy)
        self.identity_config = IdentityConfig.from_env()
        self._sessions: dict[str, _Session] = {}
        self._audit_seq = 0
        self.initial_card_status = {
            ref: card.status for ref, card in self.world.cards.items()
        }

    # ------------------------------------------------------------ setup

    def _apply_setup(self) -> None:
        if self.setup.customer is None:
            return
        fixture = FIXTURE_CUSTOMERS.get(self.setup.customer)
        if self.setup.customer not in FIXTURE_CUSTOMERS:
            raise ValueError(f"unknown customer fixture {self.setup.customer!r}")
        if fixture is None:
            return
        customer = self.world.customer_by_fixture(fixture)
        if not self.setup.otp_channel_present:
            customer.otp_channel = "NONE"
        if self.setup.card_status is not None:
            for card in self.world.cards_of(customer.customer_id):
                card.status = self.setup.card_status
        for extra in self.setup.extra_cards:
            self.world.cards[extra.card_ref] = Card(
                card_ref=extra.card_ref,
                customer_id=customer.customer_id,
                account_type=extra.account_type,
                pan_last4=extra.pan_last4,
                status=extra.status,
            )

    def case_customer(self) -> Customer | None:
        fixture = FIXTURE_CUSTOMERS.get(self.setup.customer or "")
        return self.world.customer_by_fixture(fixture) if fixture else None

    # ---------------------------------------------------------- queries

    def create_session(self) -> str:
        session_id = f"sbx-{len(self._sessions) + 1:04d}"
        self._sessions[session_id] = _Session(state=SessionState(session_id=session_id))
        return session_id

    def state(self, session_id: str) -> VerificationState:
        return self._sessions[session_id].state.state

    def calls(self, session_id: str) -> list[CallRecord]:
        return list(self._sessions[session_id].calls)

    def otp_code(self, session_id: str) -> str | None:
        """The active challenge's code, as the simulated inbox shows it."""
        session = self._sessions[session_id]
        challenge_id = session.state.otp_challenge_id
        challenge = session.challenges.get(challenge_id or "")
        return challenge.code if challenge else None

    def cards_blocked_since_start(self) -> list[Card]:
        return [
            card
            for ref, card in self.world.cards.items()
            if card.status is CardStatus.BLOCKED
            and self.initial_card_status.get(ref) is not CardStatus.BLOCKED
        ]

    # ------------------------------------------------------------- calls

    async def call_tool(self, session_id: str, tool_call: ToolCall) -> ToolResult:
        session = self._sessions[session_id]
        before = session.state.state
        if self.setup.fault == "slow_db":
            await asyncio.sleep(1.0)
        if (
            self.setup.fault in ("tool_down", "timeout")
            or tool_call.tool in self.setup.failing_tools
        ):
            # What BankingCoreClient answers when banking-core cannot be reached.
            result = _error(tool_call.tool)
            replayed = False
        else:
            result, replayed = self._dispatch(session, tool_call)
            # Whatever banking-core's dispatcher adds to every result (ADR-0016),
            # from the same function and configuration.
            result = with_flow(result, session.state.state, self.config)
        session.calls.append(
            CallRecord(
                tool=tool_call.tool,
                args=dict(tool_call.args),
                state_before=before,
                state_after=session.state.state,
                result=result,
                replayed=replayed,
            )
        )
        return result

    def _dispatch(self, session: _Session, call: ToolCall) -> tuple[ToolResult, bool]:
        """banking-core's dispatcher (api/dispatcher.py), minus the database."""
        try:
            validate_no_holder_tampering(call.args)
        except ValueError:
            return _refused(call.tool, ReasonCode.INVALID_ARGUMENTS), False

        state = session.state
        decision = self.authorizer.authorize(tool_call=call, session=state)
        args = dict(call.args)

        if decision.allowed and _names_a_transaction(call):
            if call.tool == "handoff.create" and state.state is not (
                VerificationState.VERIFIED
            ):
                args["transaction_id"] = None
            else:
                tx = self._resolve_transaction(call, state)
                if tx is None:
                    return _refused(call.tool, ReasonCode.INVALID_ARGUMENTS), False
                if call.tool == "card.block":
                    decision = self.authorizer.authorize(
                        tool_call=call,
                        session=state,
                        context={
                            AMOUNT_CONTEXT_KEY: tx.amount_minor,
                            CURRENCY_CONTEXT_KEY: tx.currency,
                        },
                    )

        if not decision.allowed:
            return _refused(
                call.tool, decision.reason_code or ReasonCode.POLICY_BLOCKED
            ), False

        definition = TOOL_CATALOG[call.tool]
        if not definition.mutates_state:
            try:
                return self._read(session, call.tool, args), False
            except (ValidationError, ValueError, KeyError):
                return _error(call.tool), False

        if not call.idempotency_key:
            return _refused(call.tool, ReasonCode.INVALID_ARGUMENTS), False
        fingerprint = json.dumps(call.args, sort_keys=True, default=str)
        stored = session.idempotency.get(call.idempotency_key)
        if stored is not None:
            tool, stored_fingerprint, result = stored
            if tool != call.tool or stored_fingerprint != fingerprint:
                return _refused(call.tool, ReasonCode.INVALID_ARGUMENTS), False
            if call.tool == "handoff.create":
                session.state = self.fsm.on_handoff_create(session.state.model_copy())
            return result, True

        try:
            result = self._write(session, call.tool, args, decision)
        except (ValidationError, ValueError, KeyError):
            return _error(call.tool), False
        if result.status is ToolResultStatus.OK:
            session.idempotency[call.idempotency_key] = (call.tool, fingerprint, result)
        return result, False

    def _resolve_transaction(
        self, call: ToolCall, state: SessionState
    ) -> Transaction | None:
        """The disputed transaction, for the pinned holder (and the blocked card)."""
        tx = self.world.transactions.get(str(call.args.get("transaction_id")))
        if tx is None or state.pinned_holder_id is None:
            return None
        if tx.customer_id != state.pinned_holder_id:
            return None
        if call.tool == "card.block" and tx.card_ref != call.args.get("card_ref"):
            return None
        return tx

    # ------------------------------------------------------------- reads

    def _read(self, session: _Session, tool: str, args: dict[str, Any]) -> ToolResult:
        state = session.state
        if tool == "customer.match":
            match = CustomerMatchInput.model_validate(args)
            customer = self._find_customer(match)
            session.state = self.fsm.on_customer_match(
                state.model_copy(),
                matched=customer is not None,
                holder_id=customer.customer_id if customer else None,
            )
            return _ok(tool, {"matched": customer is not None})

        if tool == "identity.verify_document":
            output = execute_identity_verify_document(
                args=IdentityVerifyDocumentInput.model_validate(args), session=state
            )
            return _ok(tool, output.model_dump(mode="json"))

        if tool == "kb.search":
            query = KbSearchInput.model_validate(args)
            articles = _KB_ARTICLES.get(query.locale[:2], _KB_ARTICLES["es"])
            return _ok(tool, {"results": articles[: query.limit]})

        holder = state.pinned_holder_id
        if holder is None:
            raise ValueError(f"{tool} requires a pinned verified holder")

        if tool == "card.list":
            listing = CardListInput.model_validate(args)
            cards = [
                {
                    "card_ref": c.card_ref,
                    "masked_pan": f"**** **** **** {c.pan_last4}",
                    "card_type": "CREDIT"
                    if c.account_type == "CREDIT_LINE"
                    else "DEBIT",
                    "status": c.status.value,
                    "expiry_month": None,
                    "expiry_year": None,
                }
                for c in self.world.cards_of(holder)
                if listing.status_filter is CardStatusFilter.ALL
                or c.status.value == listing.status_filter.value
            ]
            return _ok(tool, {"cards": cards})

        if tool == "transaction.list_recent":
            listing = TransactionListRecentInput.model_validate(args)
            rows = sorted(
                (
                    t
                    for t in self.world.transactions.values()
                    if t.customer_id == holder
                    and (listing.card_ref is None or t.card_ref == listing.card_ref)
                ),
                key=lambda t: (t.posted_at, t.transaction_id),
                reverse=True,
            )[: listing.limit]
            return _ok(
                tool,
                {
                    "transactions": [
                        {
                            "transaction_id": t.transaction_id,
                            "card_ref": t.card_ref,
                            "amount_minor": t.amount_minor,
                            "currency": t.currency,
                            "merchant_name": t.merchant,
                            "merchant_category": t.mcc,
                            "posted_at": t.posted_at.isoformat(),
                            "status": t.status,
                            "is_disputable": t.disputable,
                        }
                        for t in rows
                    ]
                },
            )

        if tool == "account.get_summary":
            summary = AccountGetSummaryInput.model_validate(args)
            accounts = [
                {
                    "account_ref": a.account_ref,
                    "account_type": a.account_type,
                    "currency": a.currency,
                    "available_balance_minor": a.available_balance_minor
                    if summary.include_balances
                    else None,
                    "ledger_balance_minor": a.ledger_balance_minor
                    if summary.include_balances
                    else None,
                    "status": a.status,
                }
                for a in self.world.accounts.values()
                if a.customer_id == holder
            ]
            return _ok(tool, {"accounts": accounts})

        raise ValueError(f"unsupported read tool {tool!r}")

    def _find_customer(self, match: CustomerMatchInput) -> Customer | None:
        """Document number under each equivalent type, plus the birth date if given."""
        for doc_type in self.identity_config.resolve_equivalent_document_types(
            match.document_type
        ):
            try:
                claimed = normalize_document(match.document_number, doc_type)
            except NormalizationError:
                continue
            for customer in self.world.customers.values():
                if customer.document_type is not doc_type:
                    continue
                if normalize_document(customer.document_number, doc_type) != claimed:
                    continue
                if match.birth_date is not None and (
                    match.birth_date != customer.birth_date
                ):
                    return None
                return customer
        return None

    # ------------------------------------------------------------ writes

    def _write(
        self,
        session: _Session,
        tool: str,
        args: dict[str, Any],
        decision: Decision,
    ) -> ToolResult:
        state = session.state
        if tool == "otp.send":
            return self._otp_send(session)
        if tool == "otp.verify":
            return self._otp_verify(session, OtpVerifyInput.model_validate(args).code)
        if tool == "card.block":
            return self._card_block(
                session, CardBlockInput.model_validate(args), decision
            )
        if tool == "handoff.create":
            return self._handoff_create(
                session, HandoffCreateInput.model_validate(args), decision, state.state
            )
        raise ValueError(f"unsupported write tool {tool!r}")

    def _otp_send(self, session: _Session) -> ToolResult:
        state = session.state
        if not state.pinned_holder_id:
            raise ValueError("otp.send requires a pinned customer")
        if self.fsm.otp_send_would_lock(state):
            session.state = self.fsm.on_otp_send_limit_exceeded(state.model_copy())
            return _refused("otp.send", ReasonCode.RATE_LIMITED)
        customer = self.world.customers[state.pinned_holder_id]
        if customer.otp_channel not in ("EMAIL", "SMS"):
            return _refused("otp.send", ReasonCode.POLICY_BLOCKED)

        session.otp_sends += 1
        seed = f"{state.session_id}:{session.otp_sends}"
        code = f"{int(_digest(seed, 'code'), 16) % 900000 + 100000:06d}"
        challenge_id = "chal_" + _letters(_digest(seed, "challenge"), 16)
        destination = (
            _mask_email(customer.email)
            if customer.otp_channel == "EMAIL"
            else _mask_phone(customer.phone)
        )
        before = state.state
        session.state = self.fsm.on_otp_send(state.model_copy(), challenge_id)
        session.challenges[challenge_id] = _Challenge(
            challenge_id, code, self.fsm.max_failed_verifies
        )
        return _ok(
            "otp.send",
            {
                "sent": True,
                "challenge_id": challenge_id,
                "channel": customer.otp_channel,
                "destination_masked": destination,
                "expires_in_seconds": self.config.get_policy_config().otp_ttl_seconds,
                "receipt": self._receipt(
                    "otp.send", destination, before.value, session.state.state.value
                ),
            },
        )

    def _otp_verify(self, session: _Session, code: str) -> ToolResult:
        state = session.state
        if not state.pinned_holder_id:
            raise ValueError("otp.verify requires a pinned customer")
        challenge = session.challenges.get(state.otp_challenge_id or "")
        if challenge is None:
            valid, attempts_left = False, 0
        elif challenge.code == code:
            valid, attempts_left = True, challenge.attempts_left
        else:
            challenge.attempts_left = max(challenge.attempts_left - 1, 0)
            valid, attempts_left = False, challenge.attempts_left
        target = state.otp_challenge_id or "chal_unknown"
        before = state.state
        session.state = self.fsm.on_otp_verify(state.model_copy(), valid=valid)
        return _ok(
            "otp.verify",
            {
                "verified": valid,
                "state": session.state.state.value,
                "attempts_remaining": attempts_left,
                "receipt": self._receipt(
                    "otp.verify", target, before.value, session.state.state.value
                ),
            },
        )

    def _card_block(
        self, session: _Session, args: CardBlockInput, decision: Decision
    ) -> ToolResult:
        state = session.state
        card = self.world.cards.get(args.card_ref)
        if card is None or card.customer_id != state.pinned_holder_id:
            # banking-core raises CardNotFoundError: an INTERNAL_ERROR to the caller.
            return _error("card.block")
        card_before = card.status
        if card.status is not CardStatus.BLOCKED:
            card.status = CardStatus.BLOCKED
            card.blocked_reason = args.reason.value
        requirement = requirement_for(decision, BlockReason(args.reason.value))
        state.handoff_requirement = stronger(state.handoff_requirement, requirement)
        return _ok(
            "card.block",
            {
                "card_ref": card.card_ref,
                "status": card.status.value,
                "handoff_requirement": requirement.model_dump(mode="json"),
                "receipt": self._receipt(
                    "card.block",
                    f"**** **** **** {card.pan_last4}",
                    card_before.value,
                    card.status.value,
                ),
            },
        )

    def _handoff_create(
        self,
        session: _Session,
        args: HandoffCreateInput,
        decision: Decision,
        state_before: VerificationState,
    ) -> ToolResult:
        state = session.state
        priority = resolve_priority(args.priority, decision, state_before)
        department = args.department
        requirement = state.handoff_requirement
        if requirement is not None and requirement.level is not (
            HandoffRequirementLevel.NONE
        ):
            priority = _higher(priority, requirement.priority or HandoffPriority.LOW)
            department = requirement.department or department

        if session.open_handoff is not None:
            existing = dict(session.open_handoff)
            if requirement is not None and requirement.priority is not None:
                existing["priority"] = _higher(
                    HandoffPriority(existing["priority"]), requirement.priority
                ).value
            existing["receipt"] = self._receipt(
                "handoff.create",
                existing["handoff_id"],
                existing["status"],
                existing["status"],
            )
            session.open_handoff = existing
        else:
            verified_facts: dict[str, Any] = {
                "verification_state": state_before.value,
                "customer_identified": state.pinned_holder_id is not None,
                "policy_flags": list(decision.flags),
            }
            tx = self.world.transactions.get(str(args.transaction_id))
            if tx is not None and tx.customer_id == state.pinned_holder_id:
                card = self.world.cards[tx.card_ref]
                verified_facts["disputed_transaction"] = {
                    "transaction_id": tx.transaction_id,
                    "amount_minor": tx.amount_minor,
                    "currency": tx.currency,
                    "merchant": tx.merchant,
                    "posted_at": tx.posted_at.isoformat(),
                    "card_masked": f"**** **** **** {card.pan_last4}",
                }
            handoff_id = "hnd_" + _letters(_digest(state.session_id, "handoff"), 16)
            session.open_handoff = {
                "handoff_id": handoff_id,
                "status": HandoffStatus.QUEUED.value,
                "department": department.value,
                "priority": priority.value,
                "summary": {
                    "verified_facts": verified_facts,
                    "actions_taken": [
                        {
                            "action": c.tool,
                            "decision": "allowed"
                            if c.result.status is ToolResultStatus.OK
                            else c.result.status.value,
                            "reason_code": c.result.reason_code.value
                            if c.result.reason_code
                            else None,
                        }
                        for c in session.calls
                    ],
                    "verification_method": _VERIFICATION_METHOD[state_before],
                    "open_questions": [
                        {"source": "model_unverified", "text": args.summary}
                    ],
                },
                "queue_position": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "receipt": self._receipt(
                    "handoff.create", handoff_id, "NONE", HandoffStatus.QUEUED.value
                ),
            }
        session.state = self.fsm.on_handoff_create(state.model_copy())
        return _ok("handoff.create", dict(session.open_handoff))

    def _receipt(
        self, action: str, target: str, before: str, after: str
    ) -> dict[str, Any]:
        self._audit_seq += 1
        return Receipt(
            action=action,
            target_masked=target,
            state_before=ResourceState(before),
            state_after=ResourceState(after),
            verified_at=datetime.now(UTC),
            audit_id=f"aud_{self._audit_seq:08d}",
        ).model_dump(mode="json")


# ------------------------------------------------------------------ helpers


def _names_a_transaction(call: ToolCall) -> bool:
    return (
        call.tool in ("card.block", "handoff.create")
        and call.args.get("transaction_id") is not None
    )


def _ok(tool: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(tool=tool, status=ToolResultStatus.OK, data=data)


def _refused(tool: str, reason: ReasonCode) -> ToolResult:
    return ToolResult(tool=tool, status=ToolResultStatus.REFUSED, reason_code=reason)


def _error(tool: str) -> ToolResult:
    return ToolResult(
        tool=tool, status=ToolResultStatus.ERROR, reason_code=ReasonCode.INTERNAL_ERROR
    )


def _higher(a: HandoffPriority, b: HandoffPriority) -> HandoffPriority:
    return max(a, b, key=PRIORITY_ORDER.index)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _letters(hex_digest: str, n: int) -> str:
    alphabet = string.ascii_lowercase
    return "".join(alphabet[int(ch, 16) % 26] for ch in _cycle(hex_digest, n))


def _cycle(text: str, n: int) -> Iterable[str]:
    return (text[i % len(text)] for i in range(n))


def _mask_email(email: str) -> str:
    user, _, domain = email.partition("@")
    return f"{(user or 'u')[0]}***@{domain or 'domain.com'}"


def _mask_phone(phone: str) -> str:
    digits = [c for c in phone if c.isdigit()]
    prefix = phone[:3] + " " if phone.startswith("+") else ""
    return f"{prefix}*** *** {''.join(digits[-4:])}".strip()
