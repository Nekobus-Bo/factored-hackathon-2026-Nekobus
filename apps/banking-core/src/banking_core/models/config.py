"""SQLAlchemy models for configuration tables: policy config and tool policy."""

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from banking_core.models.base import Base


class PolicyConfigRecord(Base):
    """Persistent storage for business policy configuration."""

    __tablename__ = "policy_config"
    __table_args__ = (
        sa.CheckConstraint(
            "amount_mode IN ('flag', 'block')",
            name="ck_policy_config_amount_mode",
        ),
        {"schema": "config"},
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, unique=True, default=1
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, index=True
    )
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False, default="COP")
    amount_mode: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default="flag"
    )
    thresholds_minor: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    rate_limit_attempts_per_session: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=5
    )
    otp_max_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)
    otp_max_resends: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)
    otp_ttl_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=300
    )
    session_ttl_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=3600
    )
    customer_otp_max_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=5
    )
    customer_otp_window_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=3600
    )
    customer_otp_lock_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1800
    )
    document_match_max_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=10
    )
    document_match_window_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=3600
    )
    handoff_reasons_requiring_identity_attempt: Mapped[list[str]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(
            '\'["DISPUTE_CLAIM", "UNRECOGNIZED_TRANSACTION", '
            '"VERIFICATION_FAILED"]\'::jsonb'
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


class ToolPolicyRecord(Base):
    """One version of the tool authorization matrix (ADR-0002).

    Same shape as PolicyConfigRecord: the active row is the policy in force and
    every change is a new row. ``matrix`` maps a tool name to the verification
    states that enable it; ``[]`` disables the tool and a tool missing from it
    takes its catalog default. It can only restrict contracts.tools.CODE_FLOOR.
    """

    __tablename__ = "tool_policy"
    __table_args__ = (
        sa.Index(
            "ux_config_tool_policy_one_active",
            "is_active",
            unique=True,
            postgresql_where=sa.text("is_active"),
        ),
        {"schema": "config"},
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, unique=True, default=1
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    matrix: Mapped[dict[str, list[str]]] = mapped_column(
        postgresql.JSONB(astext_type=sa.Text()), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
