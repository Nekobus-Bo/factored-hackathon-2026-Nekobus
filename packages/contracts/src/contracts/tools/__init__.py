"""Tools catalog and definitions for Pattern Blue."""

from dataclasses import dataclass
from typing import Type

from contracts.envelope import VerificationState
from contracts.tools.account_get_summary import (
    AccountGetSummaryInput,
    AccountGetSummaryOutput,
    AccountStatus,
    AccountSummaryItem,
    AccountType,
)
from contracts.tools.base import BaseToolInput, BaseToolModel, BaseToolOutput
from contracts.tools.card_block import BlockReason, CardBlockInput, CardBlockOutput
from contracts.tools.card_list import (
    CardItem,
    CardListInput,
    CardListOutput,
    CardStatus,
    CardStatusFilter,
    CardType,
)
from contracts.tools.customer_match import (
    CustomerMatchInput,
    CustomerMatchOutput,
    DocumentType,
)
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffCreateOutput,
    HandoffPriority,
    HandoffReason,
    HandoffStatus,
)
from contracts.tools.identity_verify_document import (
    DocumentDecision,
    IdentityVerifyDocumentInput,
    IdentityVerifyDocumentOutput,
)
from contracts.tools.kb_search import (
    KbSearchInput,
    KbSearchOutput,
    KbSearchResultItem,
)
from contracts.tools.otp_send import OtpChannel, OtpSendInput, OtpSendOutput
from contracts.tools.otp_verify import OtpVerifyInput, OtpVerifyOutput
from contracts.tools.transaction_list_recent import (
    TransactionItem,
    TransactionListRecentInput,
    TransactionListRecentOutput,
    TransactionStatus,
)

ALL_STATES: frozenset[VerificationState] = frozenset(VerificationState)

# Non-configurable architectural floor (ADR-0003 Appendix A):
# No runtime configuration or policy can widen permissions beyond these maximal permitted states.
# Customer-data reads and card.block are ONLY permitted in VERIFIED.
# In LOCKED and HANDED_OFF, ONLY handoff.create and kb.search are permitted.
CODE_FLOOR: dict[str, frozenset[VerificationState]] = {
    "customer.match": frozenset({VerificationState.ANONYMOUS, VerificationState.IDENTIFIED}),
    "otp.send": frozenset({VerificationState.IDENTIFIED, VerificationState.OTP_PENDING}),
    "otp.verify": frozenset({VerificationState.OTP_PENDING}),
    "identity.verify_document": frozenset({VerificationState.IDENTIFIED}),
    "card.list": frozenset({VerificationState.VERIFIED}),
    "transaction.list_recent": frozenset({VerificationState.VERIFIED}),
    "account.get_summary": frozenset({VerificationState.VERIFIED}),
    "card.block": frozenset({VerificationState.VERIFIED}),
    "handoff.create": ALL_STATES,
    "kb.search": ALL_STATES,
}


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata and type bindings for a banking tool."""

    name: str
    description: str
    input_model: Type[BaseToolInput]
    output_model: Type[BaseToolOutput]
    mutates_state: bool
    permitted_states: frozenset[VerificationState]

    def __post_init__(self) -> None:
        """Enforces that permitted_states cannot exceed the non-configurable CODE_FLOOR."""
        if self.name not in CODE_FLOOR:
            raise ValueError(
                f"ToolDefinition '{self.name}' is missing from CODE_FLOOR. "
                "Every tool must define a non-configurable code floor (fail-closed)."
            )
        max_allowed = CODE_FLOOR[self.name]
        if not self.permitted_states.issubset(max_allowed):
            illegal = self.permitted_states - max_allowed
            raise ValueError(
                f"ToolDefinition '{self.name}' permitted_states exceeds CODE_FLOOR. "
                f"Forbidden states: {sorted([s.value for s in illegal])}"
            )

    @property
    def is_write(self) -> bool:
        """Backwards-compatible alias for mutates_state."""
        return self.mutates_state

    @property
    def requires_idempotency(self) -> bool:
        """Alias indicating this tool requires an idempotency key."""
        return self.mutates_state


TOOL_CATALOG: dict[str, ToolDefinition] = {
    "customer.match": ToolDefinition(
        name="customer.match",
        description=(
            "Matches claimed customer identification data against records without disclosing PII."
        ),
        input_model=CustomerMatchInput,
        output_model=CustomerMatchOutput,
        mutates_state=False,
        permitted_states=frozenset({VerificationState.ANONYMOUS, VerificationState.IDENTIFIED}),
    ),
    "otp.send": ToolDefinition(
        name="otp.send",
        description=(
            "Dispatches an OTP challenge to customer registered channel. Mutates challenge state."
        ),
        input_model=OtpSendInput,
        output_model=OtpSendOutput,
        mutates_state=True,
        permitted_states=frozenset({VerificationState.IDENTIFIED, VerificationState.OTP_PENDING}),
    ),
    "otp.verify": ToolDefinition(
        name="otp.verify",
        description="Verifies customer-submitted OTP code and mutates verification FSM state.",
        input_model=OtpVerifyInput,
        output_model=OtpVerifyOutput,
        mutates_state=True,
        permitted_states=frozenset({VerificationState.OTP_PENDING}),
    ),
    "identity.verify_document": ToolDefinition(
        name="identity.verify_document",
        description="Simulated document verification provider (ADR-0007).",
        input_model=IdentityVerifyDocumentInput,
        output_model=IdentityVerifyDocumentOutput,
        mutates_state=False,
        permitted_states=frozenset({VerificationState.IDENTIFIED}),
    ),
    "card.list": ToolDefinition(
        name="card.list",
        description=(
            "Lists cards with masked PANs and opaque card references for verified customer."
        ),
        input_model=CardListInput,
        output_model=CardListOutput,
        mutates_state=False,
        permitted_states=frozenset({VerificationState.VERIFIED}),
    ),
    "transaction.list_recent": ToolDefinition(
        name="transaction.list_recent",
        description="Lists recent transaction history in minor currency units.",
        input_model=TransactionListRecentInput,
        output_model=TransactionListRecentOutput,
        mutates_state=False,
        permitted_states=frozenset({VerificationState.VERIFIED}),
    ),
    "account.get_summary": ToolDefinition(
        name="account.get_summary",
        description="Retrieves balance summaries in minor currency units for verified customer.",
        input_model=AccountGetSummaryInput,
        output_model=AccountGetSummaryOutput,
        mutates_state=False,
        permitted_states=frozenset({VerificationState.VERIFIED}),
    ),
    "card.block": ToolDefinition(
        name="card.block",
        description="Blocks a payment card by opaque card_ref. Requires idempotency key.",
        input_model=CardBlockInput,
        output_model=CardBlockOutput,
        mutates_state=True,
        permitted_states=frozenset({VerificationState.VERIFIED}),
    ),
    "handoff.create": ToolDefinition(
        name="handoff.create",
        description=(
            "Escalates session to human agent queue. Mutates queue state and returns receipt."
        ),
        input_model=HandoffCreateInput,
        output_model=HandoffCreateOutput,
        mutates_state=True,
        permitted_states=ALL_STATES,
    ),
    "kb.search": ToolDefinition(
        name="kb.search",
        description="Lexical search, with a dense component only if it beats BM25 (ADR-0006).",
        input_model=KbSearchInput,
        output_model=KbSearchOutput,
        mutates_state=False,
        permitted_states=ALL_STATES,
    ),
}


class CodeFloorViolation(ValueError):
    """Configured states would widen a tool beyond its non-configurable CODE_FLOOR."""


def get_effective_permitted_states(
    tool_name: str,
    configured_states: set[VerificationState] | frozenset[VerificationState] | None = None,
) -> frozenset[VerificationState]:
    """Return the effective permitted states for a tool after applying configuration.

    Configuration can only RESTRICT the seed matrix and code floor, NEVER widen it.
    If configured_states includes states not permitted by CODE_FLOOR, CodeFloorViolation
    (a ValueError) is raised.
    """
    if tool_name not in CODE_FLOOR:
        raise ValueError(f"Unknown tool '{tool_name}'")

    max_allowed = CODE_FLOOR[tool_name]
    if configured_states is None:
        return TOOL_CATALOG[tool_name].permitted_states

    configured_frozen = frozenset(configured_states)
    if not configured_frozen.issubset(max_allowed):
        illegal = configured_frozen - max_allowed
        raise CodeFloorViolation(
            f"Configuration cannot widen tool '{tool_name}' permitted states beyond CODE_FLOOR. "
            f"Forbidden states: {sorted([s.value for s in illegal])}"
        )

    return configured_frozen


__all__ = [
    "ALL_STATES",
    "AccountGetSummaryInput",
    "AccountGetSummaryOutput",
    "AccountStatus",
    "AccountSummaryItem",
    "AccountType",
    "BaseToolInput",
    "BaseToolModel",
    "BaseToolOutput",
    "BlockReason",
    "CODE_FLOOR",
    "CodeFloorViolation",
    "CardBlockInput",
    "CardBlockOutput",
    "CardItem",
    "CardListInput",
    "CardListOutput",
    "CardStatus",
    "CardStatusFilter",
    "CardType",
    "CustomerMatchInput",
    "CustomerMatchOutput",
    "Department",
    "DocumentDecision",
    "DocumentType",
    "HandoffCreateInput",
    "HandoffCreateOutput",
    "HandoffPriority",
    "HandoffReason",
    "HandoffStatus",
    "IdentityVerifyDocumentInput",
    "IdentityVerifyDocumentOutput",
    "KbSearchInput",
    "KbSearchOutput",
    "KbSearchResultItem",
    "OtpChannel",
    "OtpSendInput",
    "OtpSendOutput",
    "OtpVerifyInput",
    "OtpVerifyOutput",
    "TOOL_CATALOG",
    "ToolDefinition",
    "TransactionItem",
    "TransactionListRecentInput",
    "TransactionListRecentOutput",
    "TransactionStatus",
    "get_effective_permitted_states",
]
