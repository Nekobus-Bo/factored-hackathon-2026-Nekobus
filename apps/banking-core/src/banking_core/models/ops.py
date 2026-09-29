"""SQLAlchemy models for operations: audit log, idempotency store, handoff queue."""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from banking_core.models.base import Base


class AuditLog(Base):
    """Append-only, hash-chained operations audit log."""

    __tablename__ = "audit_log"
    __table_args__ = (
        sa.CheckConstraint(
            "actor_type IN ('system', 'customer_session', 'agent')",
            name="ck_audit_log_actor_type",
        ),
        sa.CheckConstraint(
            "decision IN ('allowed', 'refused', 'error')",
            name="ck_audit_log_decision",
        ),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_ref: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    prev_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)


class IdempotencyKey(Base):
    """Storage for idempotency keys, request hashes, and cached responses."""

    __tablename__ = "idempotency_key"
    __table_args__ = (
        sa.CheckConstraint(
            "key ~ '^[A-Za-z0-9._:-]{8,128}$'",
            name="ck_idempotency_key_pattern",
        ),
        {"schema": "ops"},
    )

    scoped_key: Mapped[str] = mapped_column(sa.String(256), primary_key=True)
    scope: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class Handoff(Base):
    """Structured escalation to the back-office queue (handoff.create).

    customer_id is nullable: a LOCKED or ANONYMOUS session may have no holder,
    and a locked customer must still reach a human.
    """

    __tablename__ = "handoff"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('QUEUED', 'ASSIGNED', 'PENDING')",
            name="ck_handoff_status",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')",
            name="ck_handoff_priority",
        ),
        sa.CheckConstraint(
            "department IN ('FRAUD_OPERATIONS', 'CUSTOMER_SUPPORT', 'DISPUTES')",
            name="ck_handoff_department",
        ),
        sa.Index("ix_handoff_queue", "status", "priority", "created_at"),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    handoff_ref: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    session_ref: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("core_bank.customer.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    priority: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    department: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default="QUEUED"
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()), nullable=False
    )
    idempotency_scope: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    # Set together by the back-office claim (ADR-0013); empty until then.
    assigned_agent: Mapped[str | None] = mapped_column(sa.String(254), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
