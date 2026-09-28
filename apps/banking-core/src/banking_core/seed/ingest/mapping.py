"""Per-source mapping contract for dataset ingestion (docs/data.md §2.1)."""

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from banking_core.models.enums import BlockReason, DocumentType

SOURCES_DIR = Path(__file__).resolve().parent / "sources"


class CountryMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    phone_code: str = Field(pattern=r"^\d{1,3}$")


class ProductMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["account", "card"]
    account_type: str | None = None
    card_type: Literal["DEBIT", "CREDIT"] | None = None


class ProductStatusMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ACTIVE", "BLOCKED"]
    blocked_reason: BlockReason | None = None


class ThresholdEquivalents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_currency: str
    base_amount_minor: int = Field(gt=0)
    currencies: list[str]


class SourceMapping(BaseModel):
    """Everything source-specific that is configuration rather than code.

    Values absent from a mapping table are dropped and counted, never guessed.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^[a-z0-9_]+$")
    adapter: str
    description: str = ""
    dataset_cutoff: date
    history_days: int = Field(gt=0, le=120)
    dispute_window_days: int = Field(gt=0)
    locale: Literal["es", "pt", "en"]
    otp_channel: Literal["sms", "email", "NONE"]
    document_types: dict[str, DocumentType]
    countries: dict[str, CountryMapping]
    mobile_prefix_by_phone_code: dict[str, str] = Field(default_factory=dict)
    customer_status_dropped: list[str] = Field(default_factory=list)
    products: dict[str, ProductMapping]
    debit_card_account_preference: list[str]
    product_status: dict[str, ProductStatusMapping | None]
    card_brand_by_first_digit: dict[str, str]
    transaction_status: dict[str, Literal["SETTLED", "PENDING", "DECLINED"] | None]
    dispute_eligible_types: list[str]
    mcc_by_category: dict[str, str]
    mcc_by_type: dict[str, str]
    default_mcc: str
    merchant_fallback_by_channel: dict[str, str]
    default_merchant: str
    policy_threshold_equivalents: ThresholdEquivalents | None = None


def available_sources() -> list[str]:
    """Names of the sources that have a mapping file."""
    return sorted(p.stem for p in SOURCES_DIR.glob("*.json"))


def load_mapping(source: str) -> SourceMapping:
    path = SOURCES_DIR / f"{source}.json"
    if not path.is_file():
        raise ValueError(
            f"no ingest mapping for source '{source}' "
            f"(available: {', '.join(available_sources()) or 'none'})"
        )
    mapping = SourceMapping.model_validate(json.loads(path.read_text("utf-8")))
    if mapping.source != source:
        raise ValueError(f"{path.name} declares source '{mapping.source}'")
    return mapping
