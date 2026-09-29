"""Configuration for identity tools, OTP delivery and document-type equivalences."""

import json
import os

from pydantic import BaseModel, Field

from banking_core.models.enums import DocumentType

OTP_CHANNEL_MODE_SIMULATED = "simulated"
SUPPORTED_OTP_CHANNEL_MODES = (OTP_CHANNEL_MODE_SIMULATED,)


class UnsupportedOtpChannelModeError(ValueError):
    """OTP_CHANNEL_MODE names a delivery mode that is not implemented."""


def resolve_otp_channel_mode(value: str | None = None) -> str:
    """Return the configured OTP delivery mode, failing on any unknown one.

    Unset or blank means ``simulated``, the seed in ``.env.example`` and compose.
    Only ``simulated`` is implemented: there is no real delivery provider to fall
    back to (ADR-0007, amendment 2026-09-29), so any other value is an error
    instead of a silent downgrade.
    """
    raw = value if value is not None else os.getenv("OTP_CHANNEL_MODE", "")
    mode = raw.strip().lower() or OTP_CHANNEL_MODE_SIMULATED
    if mode not in SUPPORTED_OTP_CHANNEL_MODES:
        raise UnsupportedOtpChannelModeError(
            f"OTP_CHANNEL_MODE={raw.strip()!r} is not supported: no real OTP "
            f"delivery provider is implemented; set "
            f"OTP_CHANNEL_MODE={OTP_CHANNEL_MODE_SIMULATED}"
        )
    return mode


def validate_otp_channel_mode() -> None:
    """Startup check: refuse to run with an OTP delivery mode that does not exist."""
    resolve_otp_channel_mode()


def simulated_inbox_enabled() -> bool:
    """True when OTP delivery goes to the simulated inbox (never raises)."""
    try:
        return resolve_otp_channel_mode() == OTP_CHANNEL_MODE_SIMULATED
    except UnsupportedOtpChannelModeError:
        return False


def _default_document_type_equivalences() -> dict[str, list[str]]:
    """Default document type equivalences for banking markets.

    e.g. In Brazilian Portuguese (pt market), CPF is stored as NATIONAL_ID,
    but user/encoder queries may present it as TAX_ID.
    """
    return {
        "TAX_ID": ["TAX_ID", "NATIONAL_ID"],
        "NATIONAL_ID": ["NATIONAL_ID", "TAX_ID"],
    }


class IdentityConfig(BaseModel):
    """Configuration for customer identity matching and document normalization."""

    document_type_equivalences: dict[str, list[str]] = Field(
        default_factory=_default_document_type_equivalences,
        description="Equivalence mappings between document types across markets",
    )
    allow_dev_otp_hook: bool = Field(
        default=False,
        description="Whether the test/dev-only hook for OTP retrieval is enabled",
    )

    @classmethod
    def from_env(cls) -> "IdentityConfig":
        """Instantiate IdentityConfig seeded from environment variables."""
        equivalences = _default_document_type_equivalences()
        env_equiv = os.getenv("DOCUMENT_TYPE_EQUIVALENCES")
        if env_equiv:
            try:
                parsed = json.loads(env_equiv)
                if isinstance(parsed, dict):
                    equivalences = {
                        k: list(v) if isinstance(v, list) else [v]
                        for k, v in parsed.items()
                    }
            except Exception:
                # Handle comma/colon separated pairs: "TAX_ID:NATIONAL_ID,..."
                for pair in env_equiv.split(","):
                    if ":" in pair:
                        k, v = pair.split(":", 1)
                        equivalences.setdefault(k.strip(), []).append(v.strip())

        dev_otp_hook = os.getenv("ALLOW_DEV_OTP_HOOK", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        return cls(
            document_type_equivalences=equivalences,
            allow_dev_otp_hook=dev_otp_hook,
        )

    def resolve_equivalent_document_types(
        self, doc_type: DocumentType | str
    ) -> list[DocumentType]:
        """Resolve a DocumentType to an ordered list of equivalent types to probe."""
        raw_val = (
            doc_type.value if isinstance(doc_type, DocumentType) else str(doc_type)
        )
        raw_val_clean = raw_val.strip().upper()

        candidates = [raw_val_clean]
        for eq in self.document_type_equivalences.get(raw_val_clean, []):
            if eq.strip().upper() not in candidates:
                candidates.append(eq.strip().upper())

        resolved: list[DocumentType] = []
        for c in candidates:
            try:
                resolved.append(DocumentType(c))
            except ValueError:
                pass
        return resolved
