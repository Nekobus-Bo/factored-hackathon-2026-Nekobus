"""Policy engine and rule models for banking-core.

Rules are structured as validated Pydantic configuration models, seeded
from environment variables (such as POLICY_SEED_AMOUNT_THRESHOLD) and
backoffice configuration.

Every evaluation produces a Decision(allowed: bool, reason_code, flags).
"""

import json
import os
import re
from typing import Any, Literal

from contracts.envelope import ReasonCode
from contracts.tools.otp_send import OtpSendOutput
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


def _otp_ttl_bounds() -> tuple[int, int]:
    """Bounds of OtpSendOutput.expires_in_seconds: the contract is the source of truth.

    A configured TTL outside them would let otp.send deliver a code and then fail
    validating its own output, so the policy config accepts exactly this range.
    """
    metadata = OtpSendOutput.model_fields["expires_in_seconds"].metadata
    lower = next(m.ge for m in metadata if hasattr(m, "ge"))
    upper = next(m.le for m in metadata if hasattr(m, "le"))
    return int(lower), int(upper)


OTP_TTL_MIN_SECONDS, OTP_TTL_MAX_SECONDS = _otp_ttl_bounds()

# Sanity bounds for the cross-session window and lock durations: a window shorter
# than a minute barely counts anything, one longer than a week is a permanent ban.
ATTEMPT_WINDOW_MIN_SECONDS = 60
ATTEMPT_WINDOW_MAX_SECONDS = 7 * 24 * 3600

# Keys of the trusted context the dispatcher builds for card.block from the
# database row of the disputed transaction (ADR-0003 amendment 2026-09-29).
# They are never read from tool arguments.
AMOUNT_CONTEXT_KEY = "disputed_amount_minor"
CURRENCY_CONTEXT_KEY = "currency"

# Block reasons that assert a disputed charge: with no amount to compare, the
# outcome fails safe into a required handoff.
DISPUTE_REASONS: frozenset[str] = frozenset(
    {"UNRECOGNIZED_CHARGE", "SUSPICIOUS_ACTIVITY"}
)

DEFAULT_THRESHOLDS_MINOR: dict[str, int] = {
    "USD": 50000,
    "EUR": 50000,
    "BRL": 250000,
    "COP": 200000000,
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


def _handoff_required() -> Decision:
    """Above the threshold in block semantics, or an amount that cannot be trusted."""
    return Decision(
        allowed=True,
        reason_code=ReasonCode.POLICY_FLAGGED,
        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
    )


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
        ge=OTP_TTL_MIN_SECONDS,
        le=OTP_TTL_MAX_SECONDS,
        description=(
            "Time-to-live for OTP challenges in seconds; bounded by the otp.send "
            "contract"
        ),
    )
    session_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="Time-to-live for customer session in seconds",
    )
    customer_otp_max_failures: int = Field(
        default=5,
        ge=1,
        description=(
            "Failed otp.verify evaluations per customer, across all sessions, "
            "within the window before the customer is locked"
        ),
    )
    customer_otp_window_seconds: int = Field(
        default=3600,
        ge=ATTEMPT_WINDOW_MIN_SECONDS,
        le=ATTEMPT_WINDOW_MAX_SECONDS,
        description=(
            "Fixed window, opened by the first failure, in which the failed "
            "otp.verify evaluations of one customer are counted"
        ),
    )
    customer_otp_lock_seconds: int = Field(
        default=1800,
        ge=ATTEMPT_WINDOW_MIN_SECONDS,
        le=ATTEMPT_WINDOW_MAX_SECONDS,
        description=(
            "How long a customer stays locked out of OTP once the failure "
            "maximum is reached"
        ),
    )
    document_match_max_failures: int = Field(
        default=10,
        ge=1,
        description=(
            "Failed customer.match attempts per claimed document, across all "
            "sessions, within the window before further matches answer "
            "matched=false without checking"
        ),
    )
    document_match_window_seconds: int = Field(
        default=3600,
        ge=ATTEMPT_WINDOW_MIN_SECONDS,
        le=ATTEMPT_WINDOW_MAX_SECONDS,
        description=(
            "Fixed window, opened by the first failure, in which the failed "
            "customer.match attempts on one claimed document are counted"
        ),
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
            normalized: dict[str, int] = {}
            for currency, raw_threshold in v.items():
                code = str(currency).strip().upper()
                if not re.fullmatch(r"[A-Z]{3}", code):
                    raise ValueError(f"Invalid ISO currency code '{currency}'")
                try:
                    threshold = int(raw_threshold)
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Non-integer threshold value for currency '{code}'"
                    ) from exc
                if threshold <= 0:
                    raise ValueError(
                        f"Threshold for currency '{code}' must be greater than zero"
                    )
                normalized[code] = threshold
            return normalized
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
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed JSON in POLICY_SEED_THRESHOLDS_MINOR: {raw_thresholds}"
                ) from exc
            if not isinstance(parsed, dict):
                raise ValueError(
                    "POLICY_SEED_THRESHOLDS_MINOR must be a JSON object mapping "
                    "currency codes to integer thresholds, got: "
                    f"{type(parsed).__name__}"
                )
            for k, v in parsed.items():
                curr_key = str(k).strip().upper()
                try:
                    int_val = int(v)
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Non-integer threshold value for currency '{curr_key}' "
                        f"in POLICY_SEED_THRESHOLDS_MINOR: {v!r}"
                    ) from exc
                thresholds_dict[curr_key] = int_val

        for env_key, env_val in os.environ.items():
            if env_key.startswith("POLICY_SEED_THRESHOLD_MINOR_") and env_val.strip():
                curr = env_key[len("POLICY_SEED_THRESHOLD_MINOR_") :].upper()
                try:
                    thresholds_dict[curr] = int(env_val)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid integer value for {env_key}: '{env_val}'"
                    ) from exc

        default_curr = os.getenv("DEFAULT_CURRENCY", "COP").strip().upper()
        raw_minor = os.getenv("POLICY_SEED_AMOUNT_THRESHOLD_MINOR")
        raw_legacy = os.getenv("POLICY_SEED_AMOUNT_THRESHOLD")

        if raw_minor is not None and raw_minor.strip():
            try:
                amount_minor = int(raw_minor)
            except ValueError as exc:
                raise ValueError(
                    "Invalid integer value for "
                    f"POLICY_SEED_AMOUNT_THRESHOLD_MINOR: '{raw_minor}'"
                ) from exc
            thresholds_dict[default_curr] = amount_minor
        elif raw_legacy is not None and raw_legacy.strip():
            try:
                amount_minor = int(float(raw_legacy) * 100)
            except ValueError as exc:
                raise ValueError(
                    "Invalid numeric value for "
                    f"POLICY_SEED_AMOUNT_THRESHOLD: '{raw_legacy}'"
                ) from exc
            thresholds_dict[default_curr] = amount_minor
        else:
            amount_minor = thresholds_dict.get(
                default_curr, DEFAULT_THRESHOLDS_MINOR.get(default_curr, 50000)
            )

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
            customer_otp_max_failures=int(
                os.getenv("RATE_LIMIT_CUSTOMER_OTP_MAX_FAILURES", "5")
            ),
            customer_otp_window_seconds=int(
                os.getenv("RATE_LIMIT_CUSTOMER_OTP_WINDOW_SECONDS", "3600")
            ),
            customer_otp_lock_seconds=int(
                os.getenv("RATE_LIMIT_CUSTOMER_OTP_LOCK_SECONDS", "1800")
            ),
            document_match_max_failures=int(
                os.getenv("RATE_LIMIT_DOCUMENT_MATCH_MAX_FAILURES", "10")
            ),
            document_match_window_seconds=int(
                os.getenv("RATE_LIMIT_DOCUMENT_MATCH_WINDOW_SECONDS", "3600")
            ),
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

        `context` is trusted: banking-core builds it, never the model. `args` is
        the model's tool arguments and never feeds an amount.

        Evaluates:
        1. Rate limits per session: applies ONLY to verification tools.
           handoff.create and kb.search are never rate limited.
        2. Amount threshold rule for card.block, from the trusted context
           (`disputed_amount_minor` and `currency`, the disputed transaction's
           row in the database):
           - ALWAYS returns allowed=True (other rules: FSM state, code floor apply).
           - amount <= threshold(currency) -> allowed, no flags.
           - above threshold, mode flag -> allowed +
             [POLICY_FLAGGED, HANDOFF_RECOMMENDED].
           - above threshold, mode block -> allowed +
             [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
           - unknown currency, or malformed/missing/negative amount ->
             treated as above threshold in block semantics: allowed +
             [POLICY_FLAGGED, HANDOFF_REQUIRED, PRIORITY].
           - no amount context: a dispute reason (UNRECOGNIZED_CHARGE,
             SUSPICIOUS_ACTIVITY) fails safe the same way; any other reason has
             no charge to compare and carries no flags.
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
            return self._card_block_decision(args, context)

        # Default: allowed, no flags
        return Decision(allowed=True, reason_code=None, flags=[])

    def _card_block_decision(
        self, args: dict[str, Any], context: dict[str, Any]
    ) -> Decision:
        """Risk threshold rule for card.block; the card block itself is never refused.

        The amount and currency come ONLY from `context`, which banking-core
        builds from the database row of the disputed transaction (ADR-0003
        amendment 2026-09-29). Amount keys in `args` are model output derived
        from customer text and are ignored: they can neither raise nor lower
        the outcome.

        Amount context present (the key is there even when its value is not
        usable): compared to the threshold of its currency, whatever the block
        reason is (safe outcome U8). Absent: a dispute reason has no known
        amount and fails safe; any other reason has no charge to compare.
        """
        if AMOUNT_CONTEXT_KEY in context:
            return self._amount_decision(
                context[AMOUNT_CONTEXT_KEY], context.get(CURRENCY_CONTEXT_KEY)
            )

        reason = context.get("reason", args.get("reason"))
        if reason in DISPUTE_REASONS:
            return _handoff_required()
        return Decision(allowed=True, reason_code=None, flags=[])

    def _amount_decision(self, raw_amount: Any, raw_currency: Any) -> Decision:
        """Compare a trusted amount to the threshold of its currency, failing safe.

        Unknown or missing currency, a non-integer or negative amount: treated
        as above the threshold in block semantics.
        """
        currency = str(raw_currency).strip().upper() if raw_currency else ""
        if currency not in self.config.thresholds_minor:
            return _handoff_required()
        # bool is an int subclass: True must not read as an amount of 1.
        if not isinstance(raw_amount, int) or isinstance(raw_amount, bool):
            return _handoff_required()
        if raw_amount < 0:
            return _handoff_required()

        if raw_amount <= self.config.thresholds_minor[currency]:
            return Decision(allowed=True, reason_code=None, flags=[])
        if self.config.amount_mode == "flag":
            return Decision(
                allowed=True,
                reason_code=ReasonCode.POLICY_FLAGGED,
                flags=["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"],
            )
        return _handoff_required()
