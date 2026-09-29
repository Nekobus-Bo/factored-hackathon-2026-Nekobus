"""The handoff requirement a card.block policy decision turns into.

The policy engine speaks in advisory flags (HANDOFF_RECOMMENDED,
HANDOFF_REQUIRED, PRIORITY) that only the audit log used to see. This module
turns a decision into the HandoffRequirement contract model that card.block
returns to its caller and that banking-core remembers in the session
(ADR-0003 amendment 2026-09-29):

- Level: HANDOFF_REQUIRED -> REQUIRED, HANDOFF_RECOMMENDED -> RECOMMENDED,
  neither -> NONE.
- Priority: the one handoff.create already maps flags to (resolve_priority):
  URGENT with the PRIORITY flag, HIGH with only HANDOFF_REQUIRED, else NORMAL.
  The mapping is that function, not a copy of it.
- Reason and department follow the block reason, see _ROUTING.
"""

from contracts.envelope import VerificationState
from contracts.tools.card_block import BlockReason
from contracts.tools.handoff_create import (
    Department,
    HandoffPriority,
    HandoffReason,
    HandoffRequirement,
    HandoffRequirementLevel,
)

from banking_core.control.policy import Decision
from banking_core.handoff.tools.handoff_create import resolve_priority

_ROUTING: dict[BlockReason, tuple[HandoffReason, Department]] = {
    BlockReason.UNRECOGNIZED_CHARGE: (
        HandoffReason.UNRECOGNIZED_TRANSACTION,
        Department.DISPUTES,
    ),
    BlockReason.SUSPICIOUS_ACTIVITY: (
        HandoffReason.SUSPECTED_FRAUD,
        Department.FRAUD_OPERATIONS,
    ),
    # Misuse of a lost or stolen card is fraud, whatever the charge.
    BlockReason.LOST: (HandoffReason.SUSPECTED_FRAUD, Department.FRAUD_OPERATIONS),
    BlockReason.STOLEN: (HandoffReason.SUSPECTED_FRAUD, Department.FRAUD_OPERATIONS),
    BlockReason.CUSTOMER_REQUEST: (
        HandoffReason.DISPUTE_CLAIM,
        Department.DISPUTES,
    ),
}

_LEVEL_ORDER = [
    HandoffRequirementLevel.NONE,
    HandoffRequirementLevel.RECOMMENDED,
    HandoffRequirementLevel.REQUIRED,
]
_PRIORITY_ORDER = [
    HandoffPriority.LOW,
    HandoffPriority.NORMAL,
    HandoffPriority.HIGH,
    HandoffPriority.URGENT,
]


def requirement_for(
    decision: Decision, block_reason: BlockReason
) -> HandoffRequirement:
    """The requirement a card.block decision carries for this block reason."""
    if decision.requires_handoff:
        level = HandoffRequirementLevel.REQUIRED
    elif decision.recommends_handoff:
        level = HandoffRequirementLevel.RECOMMENDED
    else:
        return HandoffRequirement()
    reason, department = _ROUTING[block_reason]
    return HandoffRequirement(
        level=level,
        priority=resolve_priority(
            HandoffPriority.NORMAL, decision, VerificationState.VERIFIED
        ),
        department=department,
        reason=reason,
    )


def _rank(requirement: HandoffRequirement) -> tuple[int, int]:
    priority = requirement.priority
    return (
        _LEVEL_ORDER.index(requirement.level),
        _PRIORITY_ORDER.index(priority) if priority is not None else -1,
    )


def stronger(
    remembered: HandoffRequirement | None, new: HandoffRequirement
) -> HandoffRequirement | None:
    """What a session should remember once `new` is decided: never a weaker one.

    A higher level replaces the remembered requirement; at the same level the
    higher priority wins; a tie keeps the remembered one. NONE remembers nothing.
    """
    if new.level is HandoffRequirementLevel.NONE:
        return remembered
    if remembered is None or _rank(new) > _rank(remembered):
        return new
    return remembered
