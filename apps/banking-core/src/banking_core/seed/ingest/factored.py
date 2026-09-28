"""Adapter for the Factored "Banco LATAM" dataset: raw CSV → staging records.

Reads only aggregate-safe inputs into memory for the selected customers; the
PAN is read to take its last four digits and brand, and is never emitted.
"""

import csv
import hashlib
import hmac
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from banking_core.crypto.blind_index import derive_blind_index_key
from banking_core.seed.ingest.mapping import SourceMapping

# card_ref must never contain a digit run that looks like a PAN (PAN guard
# convention), so the hex id is spelled with the letters a-p instead of 0-f.
_HEX_TO_LETTERS = str.maketrans("0123456789abcdef", "abcdefghijklmnop")

StagingRecord = dict[str, Any]


@dataclass
class IngestOptions:
    max_customers: int  # 0 = no cap
    anchor: date
    salt: str | bytes


@dataclass
class IngestResult:
    customers: list[StagingRecord] = field(default_factory=list)
    accounts: list[StagingRecord] = field(default_factory=list)
    cards: list[StagingRecord] = field(default_factory=list)
    transactions: list[StagingRecord] = field(default_factory=list)
    # "<entity>: <rule>" -> rows affected
    counts: Counter[str] = field(default_factory=Counter)
    shift_days: int = 0
    thresholds: list[dict[str, str | int]] = field(default_factory=list)


class DateShift:
    """Clamp source timestamps to the cutoff, then shift them to the anchor."""

    def __init__(self, cutoff: date, anchor: date) -> None:
        self.cutoff = datetime.combine(cutoff, time.min, tzinfo=UTC)
        self.delta = datetime.combine(anchor, time.min, tzinfo=UTC) - self.cutoff

    def shift_only(self, value: str) -> datetime | None:
        """Shift without clamping, for dates that are future by nature (expiry)."""
        parsed = parse_timestamp(value)
        return parsed + self.delta if parsed else None

    def apply(self, value: str, counts: Counter[str], label: str) -> datetime | None:
        parsed = parse_timestamp(value)
        if parsed is None:
            return None
        if parsed >= self.cutoff:
            counts[f"{label}: clamped to the dataset cutoff"] += 1
            parsed = self.cutoff - timedelta(seconds=1)
        return parsed + self.delta


def parse_timestamp(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_minor(value: str) -> int | None:
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def entity_id(source: str, entity: str, raw_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"pattern-blue:{source}:{entity}:{raw_id}")


def read_csv(path: Path) -> Iterator[dict[str, str]]:
    # utf-8-sig strips the BOM the dataset puts in front of the first header.
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def pseudonymous_email(raw_email: str, key: bytes) -> str:
    """Keyed hash of the email: stable per salt, never the raw address."""
    digest = hmac.new(key, raw_email.strip().lower().encode(), hashlib.sha256)
    return f"{digest.hexdigest()[:24]}@example.com"


def normalize_phone(
    raw: str, country_code: str, mobile_prefixes: dict[str, str]
) -> tuple[str | None, bool]:
    """Rewrite a phone to E.164 with the customer's country code.

    Returns (phone, repaired). The dataset puts +54 (and the Argentine mobile
    "9") on Mexican numbers; the national number is kept and the country code
    and mobile marker are rebuilt for the customer's country.
    """
    tokens = raw.strip().split()
    if not tokens or not tokens[0].startswith("+"):
        return None, False
    raw_code = tokens[0][1:]
    rest = tokens[1:]
    raw_prefix = mobile_prefixes.get(raw_code)
    if raw_prefix is not None and rest and rest[0] == raw_prefix:
        rest = rest[1:]
    national = re.sub(r"\D", "", "".join(rest))
    if not national:
        return None, False
    target_prefix = mobile_prefixes.get(country_code, "")
    return f"+{country_code}{target_prefix}{national}", raw_code != country_code


def ingest_factored(
    raw_dir: Path, mapping: SourceMapping, options: IngestOptions
) -> IngestResult:
    result = IngestResult()
    counts = result.counts
    shift = DateShift(mapping.dataset_cutoff, options.anchor)
    result.shift_days = shift.delta.days
    email_key = derive_blind_index_key(options.salt, "ingest_email")
    src = mapping.source

    # 1. Customers ---------------------------------------------------------
    # Rows are deduplicated on document, email and phone before the cap, so
    # every loaded customer is unambiguous for customer.match; collisions with
    # the synthetic demo identities are resolved later, at seed time.
    canonical_country: dict[str, str] = {}
    for name, country in mapping.countries.items():
        canonical_country.setdefault(country.code, name)
    candidates: list[tuple[dict[str, str], str, bool]] = []
    seen_docs: set[tuple[str, str]] = set()
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    raw_customers = read_csv(raw_dir / "customers.csv")
    for row in sorted(raw_customers, key=lambda r: r["customer_id"]):
        counts["customers: read"] += 1
        doc_type = mapping.document_types.get(row["document_type"])
        if doc_type is None:
            counts["customers: dropped, unmapped document type"] += 1
            continue
        if row["customer_status"] in mapping.customer_status_dropped:
            counts["customers: dropped, customer status closed"] += 1
            continue
        country = mapping.countries.get(row["country"])
        if country is None:
            counts["customers: dropped, unmapped country"] += 1
            continue
        if not row["mobile_phone"].strip():
            counts["customers: dropped, no mobile phone"] += 1
            continue
        phone, repaired = normalize_phone(
            row["mobile_phone"], country.phone_code, mapping.mobile_prefix_by_phone_code
        )
        if phone is None:
            counts["customers: dropped, unparseable phone"] += 1
            continue
        clean_doc = re.sub(r"[^A-Za-z0-9]", "", row["document_number"]).upper()
        doc_key = (doc_type.value, clean_doc)
        email_key_raw = row["email"].strip().lower()
        if doc_key in seen_docs:
            counts["customers: dropped, duplicate document"] += 1
            continue
        if not email_key_raw or email_key_raw in seen_emails:
            counts["customers: dropped, missing or duplicate email"] += 1
            continue
        if phone in seen_phones:
            counts["customers: dropped, duplicate phone"] += 1
            continue
        seen_docs.add(doc_key)
        seen_emails.add(email_key_raw)
        seen_phones.add(phone)
        candidates.append((row, phone, repaired))

    if options.max_customers and len(candidates) > options.max_customers:
        counts["customers: not loaded, over INGEST_MAX_CUSTOMERS"] += (
            len(candidates) - options.max_customers
        )
        candidates = candidates[: options.max_customers]

    customer_ids: dict[str, UUID] = {}
    for row, phone, repaired in candidates:
        country = mapping.countries[row["country"]]
        if row["country"] != canonical_country[country.code]:
            counts["customers: country name normalized"] += 1
        if repaired:
            counts["customers: phone country code repaired"] += 1
        birth = row["date_of_birth"].strip()[:10]
        created_at = shift.apply(row["registration_date"], counts, "customers")
        if not birth or created_at is None:
            counts["customers: dropped, missing birth or registration date"] += 1
            continue
        cid = entity_id(src, "customer", row["customer_id"])
        customer_ids[row["customer_id"]] = cid
        result.customers.append(
            {
                "id": str(cid),
                "document_type": mapping.document_types[row["document_type"]].value,
                "document_number": row["document_number"].strip(),
                "full_name": f"{row['first_name'].strip()} {row['last_name'].strip()}",
                "email": pseudonymous_email(row["email"], email_key),
                "phone": phone,
                "birth_date": birth,
                "preferred_locale": mapping.locale,
                "registered_otp_channel": mapping.otp_channel,
                "created_at": created_at.isoformat(),
            }
        )
    counts["customers: loaded"] = len(result.customers)
    counts["customers: email replaced by keyed hash"] = len(result.customers)

    # 2. Products: accounts first, then cards --------------------------------
    account_rows: list[dict[str, str]] = []
    card_rows: list[dict[str, str]] = []
    for row in read_csv(raw_dir / "products.csv"):
        if row["customer_id"] not in customer_ids:
            continue
        counts["products: read (selected customers)"] += 1
        product = mapping.products.get(row["product_type"])
        if product is None:
            counts[f"products: dropped, type {row['product_type']}"] += 1
            continue
        if row["product_status"] not in mapping.product_status:
            counts["products: dropped, unmapped status"] += 1
            continue
        if mapping.product_status[row["product_status"]] is None:
            counts[f"products: dropped, status {row['product_status']}"] += 1
            continue
        (account_rows if product.kind == "account" else card_rows).append(row)

    # raw product_id -> (account id, card id or None, currency)
    products: dict[str, tuple[UUID, UUID | None, str]] = {}
    accounts_by_customer: dict[str, list[tuple[str, str, UUID]]] = {}
    for row in sorted(account_rows, key=lambda r: r["product_id"]):
        product = mapping.products[row["product_type"]]
        status = mapping.product_status[row["product_status"]]
        assert status is not None and product.account_type is not None
        balance = to_minor(row["current_balance"])
        if balance is None:
            counts["accounts: dropped, unparseable balance"] += 1
            continue
        if balance < 0:
            counts["accounts: negative balance clamped to 0"] += 1
            balance = 0
        aid = entity_id(src, "account", row["product_id"])
        currency = row["currency"].strip().upper()
        result.accounts.append(
            {
                "id": str(aid),
                "customer_id": str(customer_ids[row["customer_id"]]),
                "type": product.account_type,
                "currency": currency,
                "available_balance_minor": balance,
                "ledger_balance_minor": balance,
                "status": status.status,
            }
        )
        if row["product_status"] != "Active":
            counts[f"accounts: status {row['product_status']} -> {status.status}"] += 1
        products[row["product_id"]] = (aid, None, currency)
        accounts_by_customer.setdefault(row["customer_id"], []).append(
            (product.account_type, currency, aid)
        )

    for row in sorted(card_rows, key=lambda r: r["product_id"]):
        product = mapping.products[row["product_type"]]
        status = mapping.product_status[row["product_status"]]
        assert status is not None and product.card_type is not None
        number = row["product_number"].strip()
        if len(number) != 16 or not number.isdigit():
            counts["cards: dropped, card number is not 16 digits"] += 1
            continue
        currency = row["currency"].strip().upper()
        if product.card_type == "CREDIT":
            ledger = to_minor(row["current_balance"])
            limit = to_minor(row["credit_limit"]) if row["credit_limit"].strip() else 0
            if ledger is None or limit is None:
                counts["cards: dropped, unparseable balance or limit"] += 1
                continue
            ledger = max(ledger, 0)
            aid = entity_id(src, "card_account", row["product_id"])
            result.accounts.append(
                {
                    "id": str(aid),
                    "customer_id": str(customer_ids[row["customer_id"]]),
                    "type": "CREDIT",
                    "currency": currency,
                    "available_balance_minor": max(limit - ledger, 0),
                    "ledger_balance_minor": ledger,
                    "status": status.status,
                }
            )
            counts["accounts: credit line created for a credit card"] += 1
        else:
            linked = _debit_account(
                accounts_by_customer.get(row["customer_id"], []),
                currency,
                mapping.debit_card_account_preference,
            )
            if linked is None:
                counts["cards: dropped, debit card without account in currency"] += 1
                continue
            aid = linked
        card_id = entity_id(src, "card", row["product_id"])
        expiry = shift.shift_only(row["expiration_date"])
        blocked_at = None
        if status.status == "BLOCKED":
            blocked_at = shift.apply(
                row["last_updated"] or row["opening_date"], counts, "cards"
            ) or datetime.combine(options.anchor, time.min, tzinfo=UTC)
        brand = mapping.card_brand_by_first_digit.get(number[0], "UNKNOWN")
        if brand == "UNKNOWN":
            counts["cards: brand unknown"] += 1
        result.cards.append(
            {
                "id": str(card_id),
                "account_id": str(aid),
                "card_ref": "crd_" + card_id.hex[:20].translate(_HEX_TO_LETTERS),
                "pan": None,
                "pan_last4": number[-4:],
                "brand": brand,
                "status": status.status,
                "blocked_at": blocked_at.isoformat() if blocked_at else None,
                "blocked_reason": status.blocked_reason.value
                if status.blocked_reason
                else None,
                "card_type": product.card_type,
                "expiry_month": expiry.month if expiry else None,
                "expiry_year": expiry.year if expiry else None,
            }
        )
        if row["product_status"] != "Active":
            counts[f"cards: status {row['product_status']} -> {status.status}"] += 1
        products[row["product_id"]] = (aid, card_id, currency)
        counts["cards: PAN discarded, last4 kept"] += 1

    counts["accounts: loaded"] = len(result.accounts)
    counts["cards: loaded"] = len(result.cards)

    # 3. Transactions within the history window ----------------------------
    window_start = mapping.dataset_cutoff - timedelta(days=mapping.history_days)
    dispute_from = datetime.combine(
        options.anchor - timedelta(days=mapping.dispute_window_days),
        time.min,
        tzinfo=UTC,
    )
    seen_tx: set[str] = set()
    for path in _transaction_files(raw_dir, window_start, mapping.dataset_cutoff):
        for row in read_csv(path):
            linked = products.get(row["product_id"])
            if linked is None:
                continue
            counts["transactions: read (loaded products, history window)"] += 1
            tx_date = parse_timestamp(row["transaction_date"])
            if tx_date is None or tx_date.date() < window_start:
                counts["transactions: dropped, outside the history window"] += 1
                continue
            if row["transaction_id"] in seen_tx:
                counts["transactions: dropped, duplicate id"] += 1
                continue
            seen_tx.add(row["transaction_id"])
            account_id, card_id, account_currency = linked
            status = mapping.transaction_status.get(row["transaction_status"])
            if status is None:
                counts[
                    f"transactions: dropped, status {row['transaction_status']}"
                ] += 1
                continue
            currency = row["currency"].strip().upper()
            if currency != account_currency:
                counts["transactions: dropped, currency differs from product"] += 1
                continue
            amount = to_minor(row["amount"])
            if amount is None or amount <= 0:
                counts["transactions: dropped, non-positive amount"] += 1
                continue
            occurred = shift.apply(row["transaction_date"], counts, "transactions")
            assert occurred is not None
            merchant = row["merchant_name"].strip()
            if not merchant:
                merchant = mapping.merchant_fallback_by_channel.get(
                    row["channel"], mapping.default_merchant
                )
                counts["transactions: merchant filled from channel"] += 1
            mcc = mapping.mcc_by_category.get(
                row["merchant_category"] or row["transaction_category"]
            ) or mapping.mcc_by_type.get(row["transaction_type"], mapping.default_mcc)
            result.transactions.append(
                {
                    "id": str(entity_id(src, "transaction", row["transaction_id"])),
                    "account_id": str(account_id),
                    "card_id": str(card_id) if card_id else None,
                    "amount_minor": amount,
                    "currency": currency,
                    "merchant": merchant,
                    "mcc": mcc,
                    "occurred_at": occurred.isoformat(),
                    "status": status,
                    "dispute_eligible": bool(
                        card_id
                        and status == "SETTLED"
                        and row["transaction_type"] in mapping.dispute_eligible_types
                        and occurred >= dispute_from
                    ),
                }
            )
    counts["transactions: loaded"] = len(result.transactions)
    counts["transactions: coordinates not loaded (no column in the model)"] = len(
        result.transactions
    )

    # 4. Policy thresholds equivalent to the base amount ----------------------
    if mapping.policy_threshold_equivalents is not None:
        result.thresholds = _threshold_equivalents(raw_dir, mapping)
    return result


def _debit_account(
    accounts: list[tuple[str, str, UUID]], currency: str, preference: list[str]
) -> UUID | None:
    for account_type in preference:
        for acc_type, acc_currency, aid in accounts:
            if acc_type == account_type and acc_currency == currency:
                return aid
    return None


def _transaction_files(raw_dir: Path, start: date, end: date) -> list[Path]:
    """Daily partition files (year=/month=/day=) with start <= day < end."""
    files: list[Path] = []
    pattern = re.compile(r"year=(\d{4})/month=(\d{2})/day=(\d{2})")
    for path in sorted((raw_dir / "transactions").rglob("*.csv")):
        match = pattern.search(path.as_posix())
        if match is None:
            files.append(path)  # unknown layout: read it, rows are filtered by date
            continue
        day = date(*(int(g) for g in match.groups()))
        if start <= day < end:
            files.append(path)
    return files


def _threshold_equivalents(
    raw_dir: Path, mapping: SourceMapping
) -> list[dict[str, str | int]]:
    """Convert the base threshold with the last rate before the cutoff."""
    spec = mapping.policy_threshold_equivalents
    assert spec is not None
    cutoff = mapping.dataset_cutoff.isoformat()
    latest: dict[str, tuple[str, str]] = {}
    for row in read_csv(raw_dir / "daily_exchange_rates.csv"):
        if row["source_currency"] != spec.base_currency or row["date"] >= cutoff:
            continue
        target = row["target_currency"]
        if target in spec.currencies and (
            target not in latest or row["date"] > latest[target][0]
        ):
            latest[target] = (row["date"], row["exchange_rate"])
    out: list[dict[str, str | int]] = []
    for currency in spec.currencies:
        if currency not in latest:
            raise ValueError(
                f"no {spec.base_currency}->{currency} rate before {cutoff}"
            )
        rate_date, rate = latest[currency]
        minor = int(
            (Decimal(spec.base_amount_minor) * Decimal(rate)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        out.append(
            {
                "currency": currency,
                "base_currency": spec.base_currency,
                "base_amount_minor": spec.base_amount_minor,
                "rate": rate,
                "rate_date": rate_date,
                "threshold_minor": minor,
            }
        )
    return out
