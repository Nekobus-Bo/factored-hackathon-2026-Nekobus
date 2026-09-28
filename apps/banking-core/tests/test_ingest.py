"""Dataset ingest (ADR-0011) against a tiny, fictitious Factored-shaped fixture."""

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from banking_core.models.core_bank import Card, Customer
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import DEMO_CUSTOMER_DOCUMENT_ES
from banking_core.seed.generator import generate_synthetic_dataset
from banking_core.seed.ingest import run_ingest
from banking_core.seed.ingest.factored import IngestOptions, normalize_phone
from banking_core.seed.ingest.mapping import load_mapping
from banking_core.seed.staging import (
    StagingValidationError,
    load_and_validate_staging,
)
from sqlalchemy.orm import Session

# Staging validates dates against the real clock, so the anchor is today.
ANCHOR = datetime.now(UTC).date()
SHIFT = ANCHOR - date(2026, 6, 18)
SALT = "test-salt"
TEST_PAN_CREDIT = "4111111111111111"
TEST_PAN_DEBIT = "4012888888881881"

CUSTOMERS = [
    # id, doc, type, first, last, email, phone, country, status, registered
    (
        "C1",
        "20111222",
        "DNI",
        "Ana",
        "Prueba",
        "ana.prueba@gmail.com",
        "+54 9 55 1234 5678",
        "México",
        "Active",
        "2021-07-30 05:39:39",
    ),
    (
        "C2",
        "3009998887",
        "CC",
        "Luis",
        "Ficticio",
        "luis.f@hotmail.com",
        "+57 300 999 8887",
        "Colombia",
        "Active",
        "2026-07-01 10:00:00",
    ),
    (
        "C3",
        "30111222",
        "DNI",
        "Eva",
        "Cerrada",
        "eva@yahoo.com",
        "+54 9 11 2222 3333",
        "Argentina",
        "Closed",
        "2020-01-01 00:00:00",
    ),
    (
        "C4",
        DEMO_CUSTOMER_DOCUMENT_ES,
        "CC",
        "Demo",
        "Choque",
        "otra@live.com",
        "+57 301 000 0000",
        "Colombia",
        "Active",
        "2022-02-02 00:00:00",
    ),
    (
        "C5",
        "40111222",
        "DNI",
        "Sin",
        "Telefono",
        "sin@outlook.com",
        "",
        "Argentina",
        "Active",
        "2022-02-02 00:00:00",
    ),
]
PRODUCTS = [
    # id, customer, type, number, currency, balance, limit, status, expiry, updated
    (
        "P1",
        "C1",
        "Cuenta Corriente",
        "1234567890",
        "USD",
        "1500.25",
        "",
        "Active",
        "",
        "2026-01-01",
    ),
    (
        "P2",
        "C1",
        "Tarjeta Débito",
        TEST_PAN_DEBIT,
        "USD",
        "0",
        "",
        "Suspended",
        "2028-03-15",
        "2026-05-01",
    ),
    (
        "P3",
        "C2",
        "Tarjeta Crédito",
        TEST_PAN_CREDIT,
        "COP",
        "200000.00",
        "1000000.00",
        "Active",
        "2027-11-30",
        "2026-06-30",
    ),
    (
        "P4",
        "C2",
        "Préstamo Personal",
        "9999999999",
        "COP",
        "5000",
        "",
        "Active",
        "",
        "2026-01-01",
    ),
    (
        "P5",
        "C1",
        "Cuenta Ahorro",
        "1234567891",
        "USD",
        "10",
        "",
        "Closed",
        "",
        "2026-01-01",
    ),
    (
        "P6",
        "C4",
        "Cuenta Ahorro",
        "1234567892",
        "COP",
        "10",
        "",
        "Active",
        "",
        "2026-01-01",
    ),
]
TRANSACTIONS = [
    # id, date, product, customer, type, category, amount, currency, channel,
    # merchant, merchant_category, status
    (
        "T1",
        "2026-06-10 12:00:00",
        "P2",
        "C1",
        "Purchase",
        "Food",
        "12.34",
        "USD",
        "POS",
        "Tienda Uno",
        "Food",
        "Approved",
    ),
    (
        "T2",
        "2026-06-11 09:30:00",
        "P1",
        "C1",
        "Withdrawal",
        "",
        "50.00",
        "USD",
        "ATM",
        "",
        "",
        "Approved",
    ),
    (
        "T3",
        "2026-06-12 08:00:00",
        "P3",
        "C2",
        "Purchase",
        "Health",
        "99.99",
        "COP",
        "Web",
        "",
        "Health",
        "Reversed",
    ),
    (
        "T4",
        "2026-06-12 18:00:00",
        "P3",
        "C2",
        "Purchase",
        "Other",
        "80.00",
        "COP",
        "POS",
        "Comercio Dos",
        "",
        "Declined",
    ),
    (
        "T5",
        "2026-01-05 10:00:00",
        "P1",
        "C1",
        "Deposit",
        "",
        "10.00",
        "USD",
        "Branch",
        "",
        "",
        "Approved",
    ),
]


def _write_csv(path: Path, header: list[str], rows: list[tuple[str, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def raw_root(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "factored"
    _write_csv(
        raw / "customers.csv",
        [
            "customer_id",
            "document_number",
            "document_type",
            "first_name",
            "last_name",
            "email",
            "mobile_phone",
            "country",
            "customer_status",
            "registration_date",
            "date_of_birth",
        ],
        [(*c, "1990-04-02") for c in CUSTOMERS],
    )
    _write_csv(
        raw / "products.csv",
        [
            "product_id",
            "customer_id",
            "product_type",
            "product_number",
            "currency",
            "current_balance",
            "credit_limit",
            "product_status",
            "expiration_date",
            "last_updated",
            "opening_date",
        ],
        [(*p, "2020-01-01") for p in PRODUCTS],
    )
    _write_csv(
        raw / "daily_exchange_rates.csv",
        ["date", "source_currency", "target_currency", "exchange_rate"],
        [
            ("2026-06-16", "USD", "ARS", "350.0"),
            ("2026-06-17", "USD", "ARS", "355.912847"),
            ("2026-06-18", "USD", "ARS", "999.0"),  # on the cutoff: ignored
        ],
    )
    header = [
        "transaction_id",
        "transaction_date",
        "product_id",
        "customer_id",
        "transaction_type",
        "transaction_category",
        "amount",
        "currency",
        "channel",
        "merchant_name",
        "merchant_category",
        "transaction_status",
    ]
    for tx in TRANSACTIONS:
        y, m, d = tx[1][:10].split("-")
        _write_csv(
            raw
            / "transactions"
            / f"year={y}"
            / f"month={m}"
            / f"day={d}"
            / f"transactions_{y}{m}{d}.csv",
            header,
            [tx],
        )
    return tmp_path / "raw"


def _ingest(raw_root: Path, tmp_path: Path, cap: int = 0) -> Path:
    run_ingest(
        "factored",
        raw_root,
        tmp_path / "staging",
        tmp_path / "reports" / "data-quality-factored.md",
        IngestOptions(max_customers=cap, anchor=ANCHOR, salt=SALT),
    )
    return tmp_path / "staging" / "factored"


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_mapping_file_loads() -> None:
    mapping = load_mapping("factored")
    assert mapping.document_types["CE"].value == "FOREIGN_ID"
    assert mapping.product_status["Closed"] is None


def test_unknown_source_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="no ingest mapping for source 'acme'"):
        load_mapping("acme")


def test_ingest_maps_customers_and_never_emits_raw_email(
    raw_root: Path, tmp_path: Path
) -> None:
    staged = _ingest(raw_root, tmp_path)
    customers = {c["document_number"]: c for c in _read(staged / "customers.jsonl")}
    # C3 closed and C5 without phone are dropped; C4 is kept here (the demo
    # collision is resolved at seed time).
    assert set(customers) == {"20111222", "3009998887", DEMO_CUSTOMER_DOCUMENT_ES}
    ana = customers["20111222"]
    assert ana["document_type"] == "NATIONAL_ID"
    assert ana["phone"] == "+525512345678"  # +54 9 on a Mexican customer repaired
    assert ana["email"].endswith("@example.com")
    assert ana["preferred_locale"] == "es"
    blob = "".join(p.read_text("utf-8") for p in staged.glob("*.jsonl"))
    for raw_email in ("ana.prueba@gmail.com", "luis.f@hotmail.com"):
        assert raw_email not in blob


def test_ingest_never_emits_the_pan(raw_root: Path, tmp_path: Path) -> None:
    staged = _ingest(raw_root, tmp_path)
    blob = "".join(p.read_text("utf-8") for p in staged.glob("*"))
    assert TEST_PAN_CREDIT not in blob and TEST_PAN_DEBIT not in blob
    cards = {c["card_type"]: c for c in _read(staged / "cards.jsonl")}
    assert cards["CREDIT"]["pan"] is None
    assert cards["CREDIT"]["pan_last4"] == "1111"
    assert cards["CREDIT"]["brand"] == "VISA"


def test_ingest_maps_products(raw_root: Path, tmp_path: Path) -> None:
    staged = _ingest(raw_root, tmp_path)
    accounts = _read(staged / "accounts.jsonl")
    cards = {c["card_type"]: c for c in _read(staged / "cards.jsonl")}
    by_type = {a["type"]: a for a in accounts}
    # Checking + credit line for the credit card + C4's savings; the closed
    # savings account and the loan are dropped.
    assert sorted(a["type"] for a in accounts) == ["CHECKING", "CREDIT", "SAVINGS"]
    assert by_type["CHECKING"]["available_balance_minor"] == 150025
    credit = by_type["CREDIT"]
    assert credit["ledger_balance_minor"] == 20000000
    assert credit["available_balance_minor"] == 80000000
    assert cards["CREDIT"]["account_id"] == credit["id"]
    # Debit card links to the customer's checking account; Suspended -> BLOCKED
    debit = cards["DEBIT"]
    assert debit["account_id"] == by_type["CHECKING"]["id"]
    assert debit["status"] == "BLOCKED"
    assert debit["blocked_reason"] == "SUSPICIOUS_ACTIVITY"
    assert debit["blocked_at"] is not None
    # Expiry is shifted by anchor - cutoff and not clamped
    expiry = date(2028, 3, 15) + SHIFT
    assert (debit["expiry_month"], debit["expiry_year"]) == (expiry.month, expiry.year)


def test_ingest_transactions_window_status_and_shift(
    raw_root: Path, tmp_path: Path
) -> None:
    staged = _ingest(raw_root, tmp_path)
    txs = {t["amount_minor"]: t for t in _read(staged / "transactions.jsonl")}
    # T3 reversed dropped; T5 outside the 90-day window dropped
    assert set(txs) == {1234, 5000, 8000}
    purchase = txs[1234]
    assert purchase["occurred_at"].startswith((date(2026, 6, 10) + SHIFT).isoformat())
    assert purchase["status"] == "SETTLED"
    assert purchase["dispute_eligible"] is True
    assert purchase["mcc"] == "5812"
    withdrawal = txs[5000]
    assert withdrawal["merchant"] == "Cajero automático"
    assert withdrawal["mcc"] == "6011"
    assert withdrawal["card_id"] is None
    assert withdrawal["dispute_eligible"] is False
    assert txs[8000]["status"] == "DECLINED"


def test_ingest_cap_and_report(raw_root: Path, tmp_path: Path) -> None:
    staged = _ingest(raw_root, tmp_path, cap=1)
    assert len(_read(staged / "customers.jsonl")) == 1
    report = (tmp_path / "reports" / "data-quality-factored.md").read_text("utf-8")
    assert "over INGEST_MAX_CUSTOMERS" in report
    assert f"| Date shift (anchor − cutoff) | {SHIFT.days} days |" in report
    # ARS threshold: 50000 USD minor × last rate strictly before the cutoff
    assert "355.912847" in report and "17,795,642" in report
    for pii in ("Ana", "Prueba", "20111222", "gmail"):
        assert pii not in report


def test_ingest_is_deterministic(raw_root: Path, tmp_path: Path) -> None:
    first = _ingest(raw_root, tmp_path / "a")
    second = _ingest(raw_root, tmp_path / "b")
    for name in ("customers", "accounts", "cards", "transactions"):
        assert (first / f"{name}.jsonl").read_bytes() == (
            second / f"{name}.jsonl"
        ).read_bytes()


def test_normalize_phone_keeps_argentine_mobile_marker() -> None:
    mobile = {"54": "9"}
    assert normalize_phone("+54 9 11 2222 3333", "54", mobile) == (
        "+5491122223333",
        False,
    )
    assert normalize_phone("+57 300 999 8887", "57", mobile) == ("+573009998887", False)


def test_dataset_staging_rejects_a_pan(raw_root: Path, tmp_path: Path) -> None:
    staged = _ingest(raw_root, tmp_path)
    cards = _read(staged / "cards.jsonl")
    cards[0]["pan"] = TEST_PAN_CREDIT
    (staged / "cards.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cards), encoding="utf-8"
    )
    with pytest.raises(StagingValidationError, match="must not carry a PAN"):
        load_and_validate_staging(staged, origin="dataset")


def test_synthetic_staging_still_requires_the_pan(tmp_path: Path) -> None:
    generate_synthetic_dataset(tmp_path, seed=42)
    cards = _read(tmp_path / "cards.jsonl")
    cards[0]["pan"] = None
    (tmp_path / "cards.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cards), encoding="utf-8"
    )
    with pytest.raises(StagingValidationError, match="16-digit synthetic PAN"):
        load_and_validate_staging(tmp_path)


def test_seed_skips_dataset_customers_colliding_with_demo(
    raw_root: Path, tmp_path: Path
) -> None:
    staged = _ingest(raw_root, tmp_path)
    generate_synthetic_dataset(tmp_path / "synthetic", seed=42)
    synthetic = load_and_validate_staging(tmp_path / "synthetic")
    dataset = load_and_validate_staging(staged, origin="dataset", source="factored")

    session = MagicMock(spec=Session)
    session.scalar.return_value = 0
    counts = load_curated_data(
        staging=synthetic,
        session=session,
        master_key="00" * 32,
        blind_index_salt=SALT,
        force=True,
        dataset_sources=[dataset],
    )

    added = [obj for call in session.add_all.call_args_list for obj in call.args[0]]
    customers = [o for o in added if isinstance(o, Customer)]
    dataset_customers = [c for c in customers if c.data_origin == "dataset"]
    # C4 reuses the demo document: skipped with its savings account
    assert counts["collision_customers_skipped"] == 1
    assert counts["collision_document_number"] == 1
    assert counts["collision_accounts_skipped"] == 1
    assert len(dataset_customers) == 2
    assert {c.source_ref for c in dataset_customers} == {"factored/customers.jsonl"}
    dataset_cards = [
        o for o in added if isinstance(o, Card) and o.data_origin == "dataset"
    ]
    assert dataset_cards and all(c.pan_enc is None for c in dataset_cards)
    assert {c.card_type for c in dataset_cards} == {"DEBIT", "CREDIT"}
    synthetic_cards = [
        o for o in added if isinstance(o, Card) and o.data_origin == "synthetic"
    ]
    assert all(c.pan_enc is not None for c in synthetic_cards)
    session.commit.assert_called_once()
