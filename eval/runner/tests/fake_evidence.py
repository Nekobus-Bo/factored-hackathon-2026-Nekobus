"""Test-only in-memory EvidenceSource standing in for banking-core's database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from evalrunner.systems.evidence import (
    AuditRow,
    CardRow,
    PolicySnapshot,
    fixture_customer_id,
)

DEMO_ES = fixture_customer_id("es-demo-customer")
SEED_THRESHOLDS = {"USD": 50000, "COP": 200000000, "BRL": 250000, "EUR": 50000}


@dataclass
class FakeEvidence:
    clock: datetime = field(default_factory=lambda: datetime(2026, 9, 27, tzinfo=UTC))
    rows: list[AuditRow] = field(default_factory=list)
    card_rows: list[CardRow] = field(default_factory=list)
    customers: dict[UUID, str] = field(default_factory=dict)
    policy: PolicySnapshot | None = None
    handoff_table: bool = False

    @classmethod
    def seeded(cls) -> FakeEvidence:
        evidence = cls(
            customers={DEMO_ES: "email"},
            policy=PolicySnapshot(amount_mode="flag", thresholds_minor=SEED_THRESHOLDS),
        )
        evidence.card_rows = [
            CardRow("card_es_demo01", DEMO_ES, "ACTIVE", None),
            CardRow("card_other01", uuid4(), "ACTIVE", None),
        ]
        return evidence

    def tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def audit(
        self,
        session_id: str,
        action: str,
        before: str,
        after: str,
        decision: str = "allowed",
        reason_code: str | None = None,
        **payload: Any,
    ) -> None:
        """A row shaped like the AuditPayload contract (2B-3d)."""
        self.audit_raw(
            session_id,
            action,
            {
                "verification_state_before": before,
                "verification_state_after": after,
                **payload,
            },
            decision=decision,
            reason_code=reason_code,
        )

    def audit_raw(
        self,
        session_id: str,
        action: str,
        payload: dict[str, Any],
        decision: str = "allowed",
        reason_code: str | None = None,
    ) -> None:
        """A row with an arbitrary payload (e.g. pre-contract shapes)."""
        self.rows.append(
            AuditRow(
                id=len(self.rows) + 1,
                occurred_at=self.tick(),
                actor_type="customer_session",
                actor_ref=session_id,
                action=action,
                decision=decision,
                reason_code=reason_code,
                payload=payload,
            )
        )

    def block_card(self, card_ref: str) -> None:
        self.card_rows = [
            CardRow(c.card_ref, c.customer_id, "BLOCKED", self.tick())
            if c.card_ref == card_ref
            else c
            for c in self.card_rows
        ]

    # EvidenceSource -------------------------------------------------------

    def now(self) -> datetime:
        return self.clock

    def audit_watermark(self) -> int:
        return len(self.rows)

    def audit_rows_after(self, watermark: int) -> list[AuditRow]:
        return [r for r in self.rows if r.id > watermark]

    def cards(self) -> list[CardRow]:
        return list(self.card_rows)

    def customer_exists(self, customer_id: UUID) -> bool:
        return customer_id in self.customers

    def customer_otp_channel(self, customer_id: UUID) -> str | None:
        return self.customers.get(customer_id)

    def active_policy(self) -> PolicySnapshot | None:
        return self.policy

    def has_handoff_table(self) -> bool:
        return self.handoff_table


@dataclass
class FakeAdmin:
    """Test-only admin API acting on a FakeEvidence (what banking-core would do)."""

    evidence: FakeEvidence
    is_available: bool = True
    calls: list[str] = field(default_factory=list)
    broken_reset: bool = False

    def available(self) -> bool:
        return self.is_available

    def policy(self) -> PolicySnapshot:
        assert self.evidence.policy is not None
        return self.evidence.policy

    def put_policy(self, policy: PolicySnapshot) -> None:
        self.calls.append(f"put_policy:{policy.amount_mode}")
        self.evidence.policy = policy

    def reset_fixtures(self) -> None:
        self.calls.append("reset_fixtures")
        if self.broken_reset:
            return
        self.evidence.card_rows = [
            CardRow(c.card_ref, c.customer_id, "ACTIVE", None)
            for c in self.evidence.card_rows
        ]
