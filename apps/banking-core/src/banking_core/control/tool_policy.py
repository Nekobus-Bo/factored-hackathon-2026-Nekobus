"""Versioned tool policy: the state x tool matrix as runtime configuration (ADR-0002).

``config.tool_policy`` keeps one document per version, like ``config.policy_config``:
the active row is the policy in force, and a change is a new row plus an audit row
in the same transaction. Nothing here widens a tool beyond
``contracts.tools.CODE_FLOOR``: a change that names a state outside the floor is
rejected, never clamped, and a stored row that somehow exceeds it is refused at
authorization time.

A tool the policy leaves out takes its catalog default, and ``[]`` disables it.
The first read of an empty table seeds version 1 from the environment
(``POLICY_SEED_DISABLED_TOOLS``); the environment is only that initial seed and is
never read again once a version exists, except by the demo reset, which returns to
it on purpose.

There is deliberately no cache: authorization reads the active version on every
call, so a change reaches the next call of every process without a restart.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from contracts.envelope import VerificationState
from contracts.tools import (
    CODE_FLOOR,
    TOOL_CATALOG,
    CodeFloorViolation,
    get_effective_permitted_states,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from banking_core.audit.service import append
from banking_core.models.config import ToolPolicyRecord

logger = logging.getLogger(__name__)

SEED_DISABLED_TOOLS_ENV = "POLICY_SEED_DISABLED_TOOLS"
# account.get_summary is the second workflow's tool: it is enabled live (ADR-0002).
DEFAULT_SEED_DISABLED_TOOLS: tuple[str, ...] = ("account.get_summary",)
TOOL_POLICY_AUDIT_ACTION = "admin.tool_policy.updated"
_WRITE_LOCK = "admin.tool_policy"

Matrix = dict[str, frozenset[VerificationState]]
StoredMatrix = dict[str, list[str]]


class ToolPolicyRejected(CodeFloorViolation):
    """A requested change is not acceptable: unknown tool or state beyond the floor.

    ``problems`` has one entry per offending tool, ready to show to the operator.
    """

    def __init__(self, problems: list[dict[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(problem["message"] for problem in problems))


@dataclass(frozen=True)
class ToolPolicyChange:
    """The outcome of a save: plain values, still valid after the session commits.

    `version` is the active version afterwards; `changes` lists the tools that
    differ from `previous_version` and is empty when nothing was written.
    """

    version: int
    previous_version: int
    matrix: StoredMatrix
    changes: list[dict[str, Any]]

    @property
    def changed(self) -> bool:
        return bool(self.changes)


# --------------------------------------------------------------------- matrices


def _sorted_states(states: Iterable[VerificationState]) -> list[str]:
    return sorted(state.value for state in states)


def baseline_matrix() -> Matrix:
    """The catalog defaults: what a tool the policy does not mention gets."""
    return {name: tool.permitted_states for name, tool in TOOL_CATALOG.items()}


def seed_disabled_tools() -> frozenset[str]:
    """Tools the environment seed starts disabled (POLICY_SEED_DISABLED_TOOLS).

    Comma separated. Unset means the default (account.get_summary); an empty value
    means none. An unknown name fails loudly, like a malformed seed threshold.
    """
    raw = os.getenv(SEED_DISABLED_TOOLS_ENV)
    if raw is None:
        names = list(DEFAULT_SEED_DISABLED_TOOLS)
    else:
        names = [name.strip() for name in raw.split(",") if name.strip()]
    unknown = sorted(set(names) - set(TOOL_CATALOG))
    if unknown:
        raise ValueError(
            f"{SEED_DISABLED_TOOLS_ENV} names unknown tool(s) {unknown}; "
            f"known tools: {sorted(TOOL_CATALOG)}"
        )
    return frozenset(names)


def seed_matrix() -> StoredMatrix:
    """The document version 1 is seeded with, and the demo reset returns to.

    It only disables tools from the catalog defaults, so it can never exceed the floor.
    """
    disabled = seed_disabled_tools()
    return {
        name: [] if name in disabled else _sorted_states(states)
        for name, states in baseline_matrix().items()
    }


def _stored(record: ToolPolicyRecord) -> StoredMatrix:
    """The stored document with every catalog tool present (missing means default)."""
    stored = record.matrix or {}
    full: StoredMatrix = {}
    for name, states in baseline_matrix().items():
        full[name] = (
            sorted(str(s) for s in stored[name])
            if name in stored
            else _sorted_states(states)
        )
    return full


def effective_states(
    tool_name: str, raw_states: Iterable[str]
) -> frozenset[VerificationState]:
    """Parse stored states for a tool and check them against the code floor.

    Raises CodeFloorViolation for a state beyond the floor and ValueError for a
    value that is not a verification state: the caller refuses closed.
    """
    parsed = {VerificationState(value) for value in raw_states}
    return get_effective_permitted_states(tool_name, parsed)


def effective_matrix(record: ToolPolicyRecord) -> Matrix:
    """The matrix a stored version enforces, strictly validated (raises if invalid)."""
    return {
        name: effective_states(name, states) for name, states in _stored(record).items()
    }


# ------------------------------------------------------------------- validation


def validate_changes(
    changes: Mapping[str, Iterable[VerificationState]],
) -> dict[str, frozenset[VerificationState]]:
    """Check a requested change against the catalog and the code floor.

    Collects every problem before raising ToolPolicyRejected, so the operator sees
    all of them at once. Nothing is clamped: a state outside the floor is refused.
    """
    problems: list[dict[str, str]] = []
    accepted: dict[str, frozenset[VerificationState]] = {}
    for tool_name, states in changes.items():
        if tool_name not in TOOL_CATALOG:
            problems.append(
                {
                    "tool": tool_name,
                    "type": "unknown_tool",
                    "message": f"Unknown tool '{tool_name}'",
                }
            )
            continue
        try:
            accepted[tool_name] = get_effective_permitted_states(
                tool_name, frozenset(states)
            )
        except CodeFloorViolation as exc:
            floor = _sorted_states(CODE_FLOOR[tool_name])
            problems.append(
                {
                    "tool": tool_name,
                    "type": "code_floor_violation",
                    "message": f"{exc} Code floor allows {floor}.",
                }
            )
    if problems:
        raise ToolPolicyRejected(problems)
    return accepted


# ------------------------------------------------------------------------ reads


def _active_statement() -> sa.Select[tuple[ToolPolicyRecord]]:
    return (
        sa.select(ToolPolicyRecord)
        .where(ToolPolicyRecord.is_active.is_(True))
        .order_by(ToolPolicyRecord.version.desc())
        .limit(1)
    )


def _seed_if_empty(session: Session) -> None:
    """Insert version 1 from the environment when the table has no versions.

    Concurrent first seeds race on two unique indexes: the version and the single
    active row. The loser inserts nothing and audits nothing. The winner audits the
    seed, as the change from the catalog defaults it is, in the same transaction.
    Flushes only: the caller owns the transaction.

    The conflict has no target on purpose. ``ON CONFLICT (version)`` only arbitrates
    that one index; a loser that gets past its check before the winner's row is
    visible still reaches the partial unique index on ``is_active``, which is not an
    arbiter and raises instead of doing nothing. Which index trips first depends on
    timing, so the failure was intermittent. Without a target every unique index is
    an arbiter, so any losing insert is a no-op.
    """
    exists = session.execute(sa.select(ToolPolicyRecord.id).limit(1)).first()
    if exists is not None:
        return
    seeded = seed_matrix()
    inserted = session.execute(
        pg_insert(ToolPolicyRecord)
        .values(version=1, is_active=True, matrix=seeded)
        .on_conflict_do_nothing()
        .returning(ToolPolicyRecord.id)
    ).first()
    if inserted is None:
        return
    baseline = {name: _sorted_states(s) for name, s in baseline_matrix().items()}
    append(
        session,
        actor_type="system",
        actor_ref="seed",
        action=TOOL_POLICY_AUDIT_ACTION,
        decision="allowed",
        reason_code=None,
        payload={
            "version": 1,
            "previous_version": None,
            "source": "seed",
            "changes": [
                {"tool": name, "before": baseline[name], "after": seeded[name]}
                for name in seeded
                if baseline[name] != seeded[name]
            ],
        },
    )
    logger.info("Seeded initial tool policy (v1) in database from environment")


def active_tool_policy(session: Session) -> ToolPolicyRecord:
    """The active version, seeding version 1 from the environment on an empty table.

    Fails loudly if the database is unreachable or no active version can be loaded;
    never falls back to environment or catalog configuration. A seed written here is
    committed, so call it before any other pending work in the session.
    """
    record = session.execute(_active_statement()).scalar_one_or_none()
    if record is not None:
        return record
    _seed_if_empty(session)
    session.commit()
    record = session.execute(_active_statement()).scalar_one_or_none()
    if record is None:
        raise RuntimeError("Failed to load or seed tool policy from database")
    return record


def load_tool_permitted_states(
    session: Session, tool_name: str
) -> frozenset[VerificationState]:
    """Effective states of one tool in the active version, checked against the floor."""
    record = active_tool_policy(session)
    stored = record.matrix or {}
    if tool_name in stored:
        return effective_states(tool_name, stored[tool_name])
    if tool_name in TOOL_CATALOG:
        return TOOL_CATALOG[tool_name].permitted_states
    return CODE_FLOOR[tool_name]


# ----------------------------------------------------------------------- writes


def _save_version(
    session: Session,
    current: ToolPolicyRecord,
    document: StoredMatrix,
    *,
    actor_ref: str,
    source: str,
) -> ToolPolicyChange:
    """Insert `document` as the new active version and audit it. Does not commit."""
    before = _stored(current)
    changes = [
        {"tool": name, "before": before[name], "after": document[name]}
        for name in document
        if before[name] != document[name]
    ]
    next_version = (
        session.execute(
            sa.select(sa.func.coalesce(sa.func.max(ToolPolicyRecord.version), 0))
        ).scalar_one()
        + 1
    )
    session.execute(
        sa.update(ToolPolicyRecord)
        .where(ToolPolicyRecord.is_active.is_(True))
        .values(is_active=False)
    )
    record = ToolPolicyRecord(version=next_version, is_active=True, matrix=document)
    session.add(record)
    session.flush()
    append(
        session,
        actor_type="agent",
        actor_ref=actor_ref,
        action=TOOL_POLICY_AUDIT_ACTION,
        decision="allowed",
        reason_code=None,
        payload={
            "version": next_version,
            "previous_version": current.version,
            "source": source,
            "changes": changes,
        },
    )
    return ToolPolicyChange(
        version=next_version,
        previous_version=current.version,
        matrix=document,
        changes=changes,
    )


def _lock_and_load(session: Session) -> ToolPolicyRecord:
    """Serialize writers, then read the active version they will build on."""
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:name))"),
        {"name": _WRITE_LOCK},
    )
    _seed_if_empty(session)
    session.flush()
    record = session.execute(_active_statement()).scalar_one_or_none()
    if record is None:
        raise RuntimeError("Failed to load or seed tool policy from database")
    return record


def save_tool_policy(
    session: Session,
    changes: Mapping[str, Iterable[VerificationState]],
    *,
    actor_ref: str = "admin",
    source: str = "admin_api",
) -> ToolPolicyChange:
    """Save `changes` on top of the active version as a new, audited version.

    Only the tools named change; the others carry over. Raises ToolPolicyRejected,
    before anything is written, for an unknown tool or a state beyond the code
    floor. Does not commit: the caller commits (or rolls back) with the audit row.
    """
    accepted = validate_changes(changes)
    current = _lock_and_load(session)
    document = _stored(current)
    for name, states in accepted.items():
        document[name] = _sorted_states(states)
    return _save_version(session, current, document, actor_ref=actor_ref, source=source)


def reset_tool_policy_to_seed(
    session: Session,
    *,
    actor_ref: str = "admin",
    source: str = "demo_reset",
) -> ToolPolicyChange:
    """Return to the environment seed as a new version, unless it already is the seed.

    When the active version already equals the seed nothing is written (the result
    has no changes), so repeated resets do not pile up identical versions.
    """
    current = _lock_and_load(session)
    document = seed_matrix()
    if _stored(current) == document:
        return ToolPolicyChange(
            version=current.version,
            previous_version=current.version,
            matrix=document,
            changes=[],
        )
    return _save_version(session, current, document, actor_ref=actor_ref, source=source)
