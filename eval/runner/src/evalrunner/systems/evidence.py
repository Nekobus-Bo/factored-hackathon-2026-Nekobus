"""Trusted-side evidence for the proposed system: banking-core's database.

The runner reads it through a read-only DSN (EVAL_READONLY_DSN). The
orchestrator never sees this DSN: evidence must not come from the component
under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_DNS, UUID, uuid5


@dataclass(frozen=True)
class AuditRow:
    """One ops.audit_log entry written by banking-core."""

    id: int
    occurred_at: datetime
    actor_type: str
    actor_ref: str
    action: str
    decision: str
    reason_code: str | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CardRow:
    card_ref: str
    customer_id: UUID
    status: str
    blocked_at: datetime | None


@dataclass(frozen=True)
class PolicySnapshot:
    amount_mode: str
    thresholds_minor: dict[str, int]


class EvidenceSource(Protocol):
    """Read-only view of banking-core state used as evaluation evidence."""

    def now(self) -> datetime: ...

    def audit_watermark(self) -> int: ...

    def audit_rows_after(self, watermark: int) -> list[AuditRow]: ...

    def cards(self) -> list[CardRow]: ...

    def customer_exists(self, customer_id: UUID) -> bool: ...

    def customer_otp_channel(self, customer_id: UUID) -> str | None: ...

    def active_policy(self) -> PolicySnapshot | None: ...

    def has_handoff_table(self) -> bool: ...

    def handoff_summary(self, handoff_ref: str) -> dict[str, Any] | None:
        """The server-built summary stored with the ticket (ops.handoff)."""
        ...


def fixture_customer_id(fixture_name: str) -> UUID:
    """Same derivation as banking_core.seed.fixtures.fixture_uuid."""
    return uuid5(NAMESPACE_DNS, f"pattern-blue.fixture.{fixture_name}")


# Scenario `initial_state.customer` -> seed fixture name (None: not in the bank).
SCENARIO_CUSTOMERS: dict[str, str | None] = {
    "demo_es": "es-demo-customer",
    "demo_pt": "pt-demo-customer",
    "demo_en": "en-demo-customer",
    "demo_pt_no_channel": "pt-no-otp-customer",
    "demo_unregistered": None,
}


class PostgresEvidence:
    """EvidenceSource over a read-only Postgres DSN (psycopg)."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # local import: only needed for real runs

        self._conn = psycopg.connect(dsn, autocommit=True)
        # Belt and braces: the role should already be read-only.
        self._conn.execute("SET default_transaction_read_only = on")

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def now(self) -> datetime:
        value: datetime = self._rows("SELECT now()")[0][0]
        return value

    def audit_watermark(self) -> int:
        return int(self._rows("SELECT COALESCE(MAX(id), 0) FROM ops.audit_log")[0][0])

    def audit_rows_after(self, watermark: int) -> list[AuditRow]:
        rows = self._rows(
            "SELECT id, occurred_at, actor_type, actor_ref, action, decision, "
            "reason_code, payload FROM ops.audit_log WHERE id > %s ORDER BY id",
            (watermark,),
        )
        return [AuditRow(*row[:7], payload=row[7] or {}) for row in rows]

    def cards(self) -> list[CardRow]:
        rows = self._rows(
            "SELECT c.card_ref, a.customer_id, c.status, c.blocked_at "
            "FROM core_bank.card c JOIN core_bank.account a ON a.id = c.account_id"
        )
        return [CardRow(*row) for row in rows]

    def customer_exists(self, customer_id: UUID) -> bool:
        return bool(
            self._rows("SELECT 1 FROM core_bank.customer WHERE id = %s", (customer_id,))
        )

    def customer_otp_channel(self, customer_id: UUID) -> str | None:
        rows = self._rows(
            "SELECT registered_otp_channel FROM core_bank.customer WHERE id = %s",
            (customer_id,),
        )
        return str(rows[0][0]) if rows else None

    def active_policy(self) -> PolicySnapshot | None:
        rows = self._rows(
            "SELECT amount_mode, thresholds_minor FROM config.policy_config "
            "WHERE is_active ORDER BY version DESC LIMIT 1"
        )
        if not rows:
            return None
        return PolicySnapshot(amount_mode=rows[0][0], thresholds_minor=rows[0][1] or {})

    def has_handoff_table(self) -> bool:
        return bool(self._rows("SELECT to_regclass('ops.handoff') IS NOT NULL")[0][0])

    def handoff_summary(self, handoff_ref: str) -> dict[str, Any] | None:
        rows = self._rows(
            "SELECT summary FROM ops.handoff WHERE handoff_ref = %s", (handoff_ref,)
        )
        return dict(rows[0][0]) if rows and rows[0][0] else None
