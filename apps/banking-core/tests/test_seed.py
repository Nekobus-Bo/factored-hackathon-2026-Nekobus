import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest
from banking_core.identity.tools.otp_send import _mask_email
from banking_core.models.enums import DocumentType
from banking_core.seed.cli import check_raw_directory, main
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import (
    BLOCKED_CARD_DOCUMENT_EN,
    BLOCKED_CARD_DOCUMENT_ES,
    BLOCKED_CARD_DOCUMENT_PT,
    DEMO_CUSTOMER_DOCUMENT_EN,
    DEMO_CUSTOMER_DOCUMENT_ES,
    DEMO_CUSTOMER_DOCUMENT_PT,
    NO_OTP_DOCUMENT_EN,
    NO_OTP_DOCUMENT_ES,
    NO_OTP_DOCUMENT_PT,
    create_scenario_fixtures,
    default_base_time,
)
from banking_core.seed.generator import generate_synthetic_dataset
from banking_core.seed.quality import generate_quality_report
from banking_core.seed.staging import (
    StagingDataset,
    StagingValidationError,
    load_and_validate_staging,
)
from contracts.envelope import MASKED_EMAIL_PATTERN
from sqlalchemy.orm import Session


def test_generator_determinism_and_counts() -> None:
    """Test synthetic generator produces expected counts and is deterministic."""
    with TemporaryDirectory() as tmp_dir1, TemporaryDirectory() as tmp_dir2:
        dir1 = Path(tmp_dir1)
        dir2 = Path(tmp_dir2)

        counts1 = generate_synthetic_dataset(dir1, seed=42)
        generate_synthetic_dataset(dir2, seed=42)

        # 1. Total counts check
        assert counts1["customers.jsonl"] == 300
        assert 300 <= counts1["accounts.jsonl"] <= 600
        assert 300 <= counts1["cards.jsonl"] <= 1800
        assert 14000 <= counts1["transactions.jsonl"] <= 16000

        # 2. Determinism check (exact bit-for-bit file match across runs)
        for fname in [
            "customers.jsonl",
            "accounts.jsonl",
            "cards.jsonl",
            "transactions.jsonl",
        ]:
            content1 = (dir1 / fname).read_bytes()
            content2 = (dir2 / fname).read_bytes()
            assert content1 == content2, f"Determinism mismatch in {fname}"

        # 3. Fixture existence checks
        cust_lines = (dir1 / "customers.jsonl").read_text(encoding="utf-8").splitlines()
        cust_docs = {json.loads(line)["document_number"] for line in cust_lines}

        # Demo walkthrough customers
        assert DEMO_CUSTOMER_DOCUMENT_ES in cust_docs
        assert DEMO_CUSTOMER_DOCUMENT_PT in cust_docs
        assert DEMO_CUSTOMER_DOCUMENT_EN in cust_docs
        assert DEMO_CUSTOMER_DOCUMENT_EN == "P12345678"
        assert NO_OTP_DOCUMENT_PT == "98765432199"

        # Check demo customer document types and neutral names
        all_custs = [json.loads(line) for line in cust_lines]
        cust_by_doc = {c["document_number"]: c for c in all_custs}

        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_EN]["document_type"] == "PASSPORT"
        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_EN]["full_name"] == "Alice Johnson"
        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_ES]["document_type"] == "NATIONAL_ID"
        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_ES]["full_name"] == "Carlos Gomez"
        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_PT]["document_type"] == "NATIONAL_ID"
        assert cust_by_doc[DEMO_CUSTOMER_DOCUMENT_PT]["full_name"] == "Mariana Silva"

        # Neutral names check across all customers (no real bank or brand names)
        for c in all_custs:
            for forbidden in ["santander", "bbva", "chase", "itau", "banco"]:
                assert forbidden not in c["full_name"].lower(), (
                    f"Real bank name found in customer: {c['full_name']}"
                )

        # Blocked card customers
        assert BLOCKED_CARD_DOCUMENT_ES in cust_docs
        assert BLOCKED_CARD_DOCUMENT_PT in cust_docs
        assert BLOCKED_CARD_DOCUMENT_EN in cust_docs

        # No OTP channel customers
        assert NO_OTP_DOCUMENT_ES in cust_docs
        assert NO_OTP_DOCUMENT_PT in cust_docs
        assert NO_OTP_DOCUMENT_EN in cust_docs

        # Verify no OTP customer has registered_otp_channel='NONE'
        no_otp_set = {
            NO_OTP_DOCUMENT_ES,
            NO_OTP_DOCUMENT_PT,
            NO_OTP_DOCUMENT_EN,
        }
        no_otp_custs = [
            json.loads(line)
            for line in cust_lines
            if json.loads(line)["document_number"] in no_otp_set
        ]
        assert len(no_otp_custs) == 3
        for c in no_otp_custs:
            assert c["registered_otp_channel"] == "NONE"

        # Verify demo customer has dispute_eligible transaction
        tx_lines = (
            (dir1 / "transactions.jsonl").read_text(encoding="utf-8").splitlines()
        )
        demo_unrec_txs = [
            json.loads(line)
            for line in tx_lines
            if json.loads(line).get("merchant") == "Global Electronics Megastore"
        ]
        assert len(demo_unrec_txs) == 3  # 1 per locale
        for tx in demo_unrec_txs:
            assert tx["dispute_eligible"] is True
            assert tx["status"] == "SETTLED"


def test_staging_validation_and_quality_report() -> None:
    """Test staging layer validates synthetic data and produces quality report."""
    with TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir) / "synthetic"
        generate_synthetic_dataset(raw_path, seed=42)

        # Staging validation passes
        staging_data = load_and_validate_staging(raw_path)
        assert len(staging_data.customers) == 300
        assert len(staging_data.transactions) >= 14000

        # Quality report generates valid markdown
        report_path = Path(tmp_dir) / "reports" / "data-quality.md"
        report_text = generate_quality_report(staging_data, report_path)

        assert "# Data Quality Report" in report_text
        assert "core_bank.customer" in report_text
        assert "core_bank.transaction" in report_text
        assert "Intentionally Not Cleaned" in report_text
        assert report_path.exists()


def test_seed_dates_follow_the_run_day() -> None:
    """Generated dates sit inside the staging window on any day the seed runs.

    The anchor used to be a fixed date: 125 days later the oldest transactions
    fell out of the window and every seed failed. Now it is today's UTC midnight.
    """
    anchor = default_base_time()
    now = datetime.now(UTC)
    assert anchor == now.replace(hour=0, minute=0, second=0, microsecond=0)

    with TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir)
        generate_synthetic_dataset(raw_path, seed=42)
        occurred = [
            datetime.fromisoformat(json.loads(line)["occurred_at"])
            for line in (raw_path / "transactions.jsonl").read_text().splitlines()
        ]

    assert max(occurred) <= now
    assert min(occurred) >= now - timedelta(days=125)


def test_demo_customers_get_the_code_by_email_and_others_keep_their_channel() -> None:
    """The demo simulates "you got an email with the code" (ADR-0007 amendment)."""
    demo = {
        DEMO_CUSTOMER_DOCUMENT_ES,
        DEMO_CUSTOMER_DOCUMENT_PT,
        DEMO_CUSTOMER_DOCUMENT_EN,
    }
    blocked = {
        BLOCKED_CARD_DOCUMENT_ES,
        BLOCKED_CARD_DOCUMENT_PT,
        BLOCKED_CARD_DOCUMENT_EN,
    }
    no_otp = {NO_OTP_DOCUMENT_ES, NO_OTP_DOCUMENT_PT, NO_OTP_DOCUMENT_EN}
    expected = (
        {doc: "email" for doc in demo}
        | {doc: "sms" for doc in blocked}
        | {doc: "NONE" for doc in no_otp}
    )

    fixtures = create_scenario_fixtures().customers
    assert {c["document_number"]: c["registered_otp_channel"] for c in fixtures} == (
        expected
    )
    # An email channel needs an address that masks into a valid destination.
    for customer in fixtures:
        if customer["document_number"] in demo:
            masked = _mask_email(str(customer["email"]))
            assert re.fullmatch(MASKED_EMAIL_PATTERN, masked), masked
            assert masked.startswith(str(customer["email"])[0] + "***@example.")

    # Staging accepts the channel: the synthetic dataset carries these fixtures.
    with TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir) / "synthetic"
        generate_synthetic_dataset(raw_path, seed=42)
        staged = load_and_validate_staging(raw_path)
    channels = {c.document_number: c.registered_otp_channel for c in staged.customers}
    assert {doc: channels[doc] for doc in expected} == expected


def test_staging_fails_loudly_on_violations() -> None:
    """Test staging layer raises StagingValidationError on corrupted data."""
    with TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir) / "synthetic"
        generate_synthetic_dataset(raw_path, seed=42)

        # 1. Test missing file fails loudly
        (raw_path / "accounts.jsonl").unlink()
        with pytest.raises(
            StagingValidationError,
            match="Missing required staging file: accounts.jsonl",
        ):
            load_and_validate_staging(raw_path)


def test_staging_fails_on_duplicate_doc() -> None:
    """Test staging layer catches duplicate customer documents."""
    with TemporaryDirectory() as tmp_dir:
        raw_path = Path(tmp_dir) / "synthetic"
        generate_synthetic_dataset(raw_path, seed=42)

        cust_file = raw_path / "customers.jsonl"
        lines = cust_file.read_text(encoding="utf-8").splitlines()
        # Duplicate first line
        lines.append(lines[0])
        cust_file.write_text("\n".join(lines), encoding="utf-8")

        with pytest.raises(StagingValidationError, match="Uniqueness violation"):
            load_and_validate_staging(raw_path)


def test_raw_directory_check_fails_on_unexpected_files() -> None:
    """check_raw_directory permits README.md, synthetic/ and mapped sources only."""
    with TemporaryDirectory() as tmp_dir:
        raw_dir = Path(tmp_dir)
        (raw_dir / "README.md").write_text("dataset info")
        (raw_dir / "synthetic").mkdir()
        # A delivered dataset with an ingest mapping is accepted
        (raw_dir / "factored").mkdir()

        check_raw_directory(raw_dir)

        # Anything without a mapping fails loudly, naming it
        (raw_dir / "customer_raw.csv").write_text("col1,col2")
        with pytest.raises(
            RuntimeError,
            match="no ingest mapping for data/raw/customer_raw.csv",
        ):
            check_raw_directory(raw_dir)


def test_curated_production_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test load_curated_data refuses to seed in production without --force."""
    mock_staging = MagicMock(spec=StagingDataset)
    monkeypatch.setenv("APP_ENV", "production")

    # Refuses when force=False
    with pytest.raises(
        RuntimeError,
        match="Refusing to seed database in production.*Pass --force to override",
    ):
        load_curated_data(mock_staging, force=False)


def test_curated_atomicity_rollback() -> None:
    """Test load_curated_data rolls back transaction if any error occurs."""
    mock_staging = MagicMock(spec=StagingDataset)
    mock_customer = MagicMock()
    mock_customer.id = uuid.uuid4()
    mock_customer.document_number = "1020304050"
    mock_customer.document_type = DocumentType.NATIONAL_ID
    mock_customer.full_name = "Carlos Gomez"
    mock_customer.email = "carlos@example.com"
    mock_customer.phone = "+573001234567"
    mock_customer.birth_date = date(1985, 1, 1)
    mock_customer.preferred_locale = "es"
    mock_customer.registered_otp_channel = "sms"
    mock_staging.customers = [mock_customer]
    mock_staging.accounts = []
    mock_staging.cards = []
    mock_staging.transactions = []

    mock_session = MagicMock(spec=Session)
    # Simulate DB error during transaction commit
    mock_session.commit.side_effect = RuntimeError(
        "Database deadlock or connection drop"
    )

    with pytest.raises(RuntimeError, match="Database deadlock or connection drop"):
        load_curated_data(
            staging=mock_staging,
            session=mock_session,
            master_key="00" * 32,
            blind_index_salt="test-salt",
            force=True,
        )

    # Verify rollback was called and no unhandled commit succeeded
    mock_session.rollback.assert_called_once()


def test_cli_seed_production_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Test CLI seed command respects APP_ENV=production and --force flag."""
    monkeypatch.setenv("APP_ENV", "production")

    with TemporaryDirectory() as tmp_dir:
        raw_dir = Path(tmp_dir)
        synth_dir = raw_dir / "synthetic"
        generate_synthetic_dataset(synth_dir, seed=42)

        # 1. Without --force -> exits with code 1 and prints refusal explanation
        rc = main(["seed", "--raw-dir", str(raw_dir)])
        assert rc == 1
        captured = capsys.readouterr()
        assert "Refusing to seed database in production" in captured.err
        assert "--force" in captured.err
