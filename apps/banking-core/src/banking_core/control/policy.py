"""Policy engine and rule models for banking-core.

Rules are structured as validated Pydantic configuration models, seeded
from environment variables (such as POLICY_SEED_AMOUNT_THRESHOLD) and
backoffice configuration.

Every evaluation produces a Decision(allowed: bool, reason_code, flags).
"""

import json
import os
from typing import Any, Literal

from contracts.envelope import ReasonCode
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from banking_core.control.session import SessionState

# Verification tools subject to per-session rate limits.
# ADR-0003 Appendix A: handoff.create and kb.search are NEVER rate-limited
# so a customer (even locked or rate-limited) can always reach a human or search KB.
RATE_LIMITED_TOOLS: frozenset[str] = frozenset(
    {
        "customer.match",
        "otp.send",
        "otp.verify",
        "identity.verify_document",
    }
)

DEFAULT_THRESHOLDS_MINOR: dict[str, int] = {
    "COP": 20000000,
    "USD": 5000,
    "BRL": 25000,
    "EUR": 5000,
}


class Decision(BaseModel):
    """Deterministic authorization decision emitted by banking-core policy engine."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = Field(..., description="Whether the tool execution is permitted")
    reason_code: ReasonCode | None = Field(
        default=None,
        description="Standardized rejection/flag code from contracts.envelope",
    )
    flags: list[str] = Field(
        default_factory=list,
        description=(
            "Advisory flags (e.g. HANDOFF_RECOMMENDED, HANDOFF_REQUIRED, PRIORITY)"
        ),
    )

    @property
    def is_flagged(self) -> bool:
        """True if any advisory flags are set or reason_code is POLICY_FLAGGED."""
        return len(self.flags) > 0 or self.reason_code == ReasonCode.POLICY_FLAGGED

    @property
    def requires_handoff(self) -> bool:
        """True if HANDOFF_REQUIRED is in flags."""
        return "HANDOFF_REQUIRED" in self.flags

    @property
    def recommends_handoff(self) -> bool:
        """True if HANDOFF_RECOMMENDED is in flags."""
        return "HANDOFF_RECOMMENDED" in self.flags

    @property
    def is_priority(self) -> bool:
        """True if PRIORITY is in flags."""
        return "PRIORITY" in self.flags


class PolicyConfig(BaseModel):
    """Validated policy configuration for banking-core guardrails."""

    model_config = ConfigDict(extra="forbid")

    thresholds_minor: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_THRESHOLDS_MINOR),
        description="Thresholds per ISO 4217 currency code in minor currency units",
    )
    amount_threshold_minor: int | None = Field(
        default=None,
        ge=0,
        description="Optional single threshold override in minor currency units",
    )
    currency: str = Field(
        default="COP",
        pattern=r"^[A-Z]{3}$",
        description="Default ISO 4217 currency code",
    )
    amount_mode: Literal["flag", "block"] = Field(
        default="flag",
        description="Action when amount exceeds threshold: 'flag' or 'block'",
    )
    rate_limit_attempts_per_session: int = Field(
        default=5,
        ge=1,
        description="Max allowed attempts per customer session before rejection",
    )
    otp_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Max failed OTP verification attempts before session lock",
    )
    otp_max_resends: int = Field(
        default=3,
        ge=1,
        description="Max allowed OTP resends before session lock",
    )
    otp_ttl_seconds: int = Field(
        default=300,
        ge=10,
        description="Time-to-live for OTP challenges in seconds",
    )
    session_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="Time-to-live for customer session in seconds",
    )

    @field_validator("amount_mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: Any) -> str:
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("flag", "block"):
                return v_lower
        raise ValueError(f"Invalid amount_mode '{v}'; must be 'flag' or 'block'")

    @field_validator("thresholds_minor", mode="before")
    @classmethod
    def normalize_thresholds(cls, v: Any) -> dict[str, int]:
        if isinstance(v, str):
            v = json.loads(v)
        if isinstance(v, dict):
            return {str(k).strip().upper(): int(val) for k, val in v.items()}
        raise ValueError("thresholds_minor must be a dict or valid JSON string")

    @model_validator(mode="after")
    def sync_thresholds(self) -> "PolicyConfig":
        if self.amount_threshold_minor is not None:
            self.thresholds_minor[self.currency.upper()] = self.amount_threshold_minor
        elif self.currency.upper() in self.thresholds_minor:
            self.amount_threshold_minor = self.thresholds_minor[self.currency.upper()]
        return self

    @classmethod
    def from_env(cls) -> "PolicyConfig":
        """Load seed policy configuration from environment variables."""
        thresholds_dict: dict[str, int] = dict(DEFAULT_THRESHOLDS_MINOR)

        raw_thresholds = os.getenv("POLICY_SEED_THRESHOLDS_MINOR")
        if raw_thresholds is not None and raw_thresholds.strip():
            try:
                parsed = json.loads(raw_thresholds)
                if isinstance(parsed, dict):
                    thresholds_dict.update(
                        {str(k).strip().upper(): int(v) for k, v in parsed.items()}
                    )
            except (json.JSONDecodeError, ValueError):
                pass

        for env_key, env_val in os.environ.items():
            if env_key.startswith("POLICY_SEED_THRESHOLD_MINOR_") and env_val.strip():
                curr = env_key[len("POLICY_SEED_THRESHOLD_MINOR_") :].upper()
                try:
                    thresholds_dict[curr] = int(env_val)
                except ValueError:
                    pass

        default_curr = os.getenv("DEFAULT_CURRENCY", "COP").strip().upper()
        raw_minor = os.getenv("POLICY_SEED_AMOUNT_THRESHOLD_MINOR")
        if raw_minor is not None and raw_minor.strip():
            amount_minor = int(raw_minor)
            thresholds_dict[default_curr] = amount_minor
        elif os.getenv("POLICY_SEED_AMOUNT_THRESHOLD") is not None:
            amount_minor = int(
                float(os.getenv("POLICY_SEED_AMOUNT_THRESHOLD", "50")) * 100
            )
            thresholds_dict[default_curr] = amount_minor
        else:
            amount_minor = thresholds_dict.get(default_curr, 5000)

        return cls(
            thresholds_minor=thresholds_dict,
            amount_threshold_minor=amount_minor,
            currency=default_curr,
            amount_mode=os.getenv("POLICY_SEED_AMOUNT_MODE", "flag").strip().lower(),  # type: ignore[arg-type]
            rate_limit_attempts_per_session=int(
                os.getenv("RATE_LIMIT_ATTEMPTS_PER_SESSION", "5")
            ),
            otp_max_attempts=int(os.getenv("OTP_MAX_ATTEMPTS", "3")),
            otp_max_resends=int(os.getenv("OTP_MAX_RESENDS", "3")),
            otp_ttl_seconds=int(os.getenv("OTP_TTL_SECONDS", "300")),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
        )


class PolicyEngine:
    """Evaluates business policies and rate limits against tool calls."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig.from_env()

    def evaluate(
        self,
        tool: str,
        session: SessionState,
        args: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        """Evaluate policy rules for a tool call.

        Evaluates:
        1. Rate limits per session: applies ONLY to verification tools.
           handoff.create and kb.search are never rate limited.
        2. Amount threshold rule for card.block:
           - ALWAYS returns allowed=True (other rules: FSM state, code floor apply).
           - amount <= threshold(currency) -> allowed, no flags.
           - above threshold, mode flag -> allowed +
             [POLICY_FLAGGED, HANDOFF_RECOMMENDED].
           - above threshold, mode block -> allowed +
             [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
           - unknown currency, or malformed/missing/negative amount ->
             treated as above threshold in block semantics: allowed +
             [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
        """
        args = args or {}
        context = context or {}

        # 1. Rate limit per session applies ONLY to verification tools
        if (
            tool in RATE_LIMITED_TOOLS
            and session.attempts >= self.config.rate_limit_attempts_per_session
        ):
            return Decision(
                allowed=False,
                reason_code=ReasonCode.RATE_LIMITED,
                flags=["RATE_LIMIT_EXCEEDED"],
            )

        # 2. Risk threshold rule for card.block
        if tool == "card.block":
            merged = {**args, **context}

            matched_key = None
            for key in (
                "disputed_amount_minor",
                "amount_minor",
                "disputed_amount",
                "amount",
            ):
                if key in merged:
                    matched_key = key
                    break

            reason = merged.get("reason")
            is_dispute_reason = reason in (
                "UNRECOGNIZED_CHARGE",
                "SUSPICIOUS_ACTIVITY",
            )
            has_currency = "currency" in merged

            # If amount context is provided, currency is specified,
            # or reason is dispute:
            if matched_key is not None or has_currency or is_dispute_reason:
                # Currency check
                raw_currency = merged.get("currency")
                if raw_currency is None:
                    currency = self.config.currency.upper()
                else:
                    currency = str(raw_currency).strip().upper()

                # Unknown currency -> block semantics (allowed + PRIORITY handoff)
                if not currency or currency not in self.config.thresholds_minor:
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
                    )

                # Amount check
                if matched_key is None or merged.get(matched_key) is None:
                    # Missing amount -> block semantics (allowed + PRIORITY handoff)
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
                    )

                raw_amount = merged.get(matched_key)
                try:
                    if "minor" in matched_key:
                        amount_minor = int(raw_amount)
                    else:
                        amount_minor = int(float(raw_amount) * 100)
                except (ValueError, TypeError):
                    # Malformed amount -> block semantics (allowed + PRIORITY handoff)
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
                    )

                if amount_minor < 0:
                    # Negative amount -> block semantics (allowed + PRIORITY handoff)
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
                    )

                # Valid amount and known currency: check against threshold
                threshold = self.config.thresholds_minor[currency]
                if amount_minor <= threshold:
                    return Decision(allowed=True, reason_code=None, flags=[])

                # Above threshold
                if self.config.amount_mode == "flag":
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"],
                    )
                else:  # mode "block"
                    return Decision(
                        allowed=True,
                        reason_code=ReasonCode.POLICY_FLAGGED,
                        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
                    )

        # Default: allowed, no flags
        return Decision(allowed=True, reason_code=None, flags=[])
