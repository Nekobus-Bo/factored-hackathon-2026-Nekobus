"""Tests for the Factored dataset profiler."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from profile_factored.cli import main
from profile_factored.loader import clean_column_names, clean_lazy_column_names
from profile_factored.profiler import (
    ProfileResults,
    TableInventory,
    format_doc_pattern,
    is_luhn_valid,
)
from profile_factored.reporter import generate_markdown_report


def test_clean_column_names_bom() -> None:
    df = pl.DataFrame({"﻿customer_id": [1], "name": ["test"]})
    cleaned = clean_column_names(df)
    assert "customer_id" in cleaned.columns
    assert "﻿customer_id" not in cleaned.columns
    assert "name" in cleaned.columns


def test_clean_lazy_column_names_bom() -> None:
    lf = pl.LazyFrame({"﻿tx_id": [1], "amount": [10.5]})
    cleaned_lf = clean_lazy_column_names(lf)
    schema = cleaned_lf.collect_schema()
    assert "tx_id" in schema.names()
    assert "﻿tx_id" not in schema.names()


def test_format_doc_pattern() -> None:
    assert format_doc_pattern("12345678") == "99999999"
    assert format_doc_pattern("A1234567") == "A9999999"
    assert format_doc_pattern("CC-99887766") == "AA-99999999"
    assert format_doc_pattern(None) == ""


def test_is_luhn_valid() -> None:
    # Standard valid test card numbers (Luhn mod-10)
    assert is_luhn_valid("4111111111111111") is True
    # Invalid card number
    assert is_luhn_valid("4111111111111112") is False
    # Non-digit or wrong length
    assert is_luhn_valid("4111") is False
    assert is_luhn_valid("411111111111111a") is False


def test_generate_markdown_report() -> None:
    sample_inventory = [
        TableInventory(
            name="customers",
            partitioning="flat CSV",
            file_count=1,
            size_mb=44.72,
            row_count=150000,
            col_count=27,
            date_ranges={"registration_date": ("2018-06-18", "2026-06-17")},
        )
    ]
    results = ProfileResults(
        inventory=sample_inventory,
        null_rates={"customers": {"email": 2.0}},
        relationships={
            "product_orphan_customer_rate": 0.0,
            "transaction_orphan_product_rate": 0.0,
            "transaction_orphan_customer_rate": 0.0,
            "transaction_customer_mismatch_rate": 0.0,
            "transaction_currency_mismatch_rate": 0.0,
            "transcript_interaction_match_rate": 1.0,
            "interactions_has_transcript_counts": {"True": 171321, "False": 514975},
            "complaint_origin_interaction_non_null_count": 0,
            "complaint_affected_product_in_products_rate": 1.0,
            "complaint_affected_product_other_customer_rate": 1.0,
            "complaint_currency_vs_product_mismatch_rate": 0.746,
        },
        languages_countries={
            "transcript_detected_languages": {"es": 171321},
            "customer_countries": {
                "México": 74907,
                "Colombia": 45251,
                "Argentina": 29842,
            },
            "customer_text_pt_matches": 0,
            "customer_text_en_matches": 0,
            "customer_text_es_matches": 171321,
        },
        system_fit={
            "doc_type_distribution": {"DNI (México)": 74907},
            "doc_type_patterns": {"DNI [99999999]": 74907},
            "duplicate_customer_id_count": 0,
            "duplicate_document_count": 0,
            "product_type_distribution": {"Tarjeta Crédito": 100102},
            "product_status_distribution": {"Active": 339965},
            "card_count": 140040,
            "card_luhn_valid_rate": 0.1002,
            "card_first_digit_4_rate": 1.0,
            "customers_with_cards_count": 91084,
            "cards_per_customer_mean": 1.54,
            "cards_per_customer_max": 8,
            "transaction_currency_distribution": {"USD": 2437979},
            "product_currency_distribution": {"USD": 200398},
            "mexico_product_currencies": {"USD": 200398},
            "card_tx_merchant_name_null_rate": 0.335,
            "overall_tx_merchant_name_null_rate": 0.767,
        },
        intents_transcripts={
            "detected_intents": {"consulta_general": 162864, "null": 8457},
            "distinct_customer_text_count": 42,
            "total_transcripts_count": 171321,
            "distinct_customer_text_fraction": 0.000245,
            "distinct_agent_text_count": 42,
            "distinct_full_text_count": 546,
            "full_text_templated_fraction": 1.0,
            "placeholder_counts": {"moneda": 257231, "monto": 171321},
            "atomic_customer_utterance_count": 7,
            "top_customer_utterances": ["85910x: Buenas tardes..."],
        },
        fraud_complaints={
            "transaction_fraud_counts": {"True": 4316, "False": 4420692},
            "transaction_fraud_rate": 0.000975,
            "fraud_score_legit_mean": 15.03,
            "fraud_score_fraud_mean": 49.5,
            "complaints_cargo_no_reconocido_count": 12297,
            "complaints_cargo_no_reconocido_fraction": 0.1833,
            "complaints_distinct_descriptions": 5,
        },
        quality_issues={
            "phone_code_mismatch_count": 72548,
            "phone_code_mismatch_rate": 0.499,
            "mexico_customers_with_arg_phone_code": 72548,
            "transactions_coords_near_zero_count": 407656,
            "transactions_coords_near_zero_fraction": 0.475,
            "branches_near_zero_count": 167,
            "branches_near_zero_fraction": 0.477,
            "customers_updated_after_cutoff_count": 9258,
            "products_updated_after_cutoff_count": 24996,
            "complaints_resolved_after_cutoff_count": 200,
            "complaints_closed_after_cutoff_count": 44,
            "customers_minor_at_registration_count": 3831,
            "products_opened_before_registration_count": 199596,
            "products_opened_before_registration_rate": 0.499,
        },
        execution_time_seconds=1.23,
    )

    md = generate_markdown_report(results)
    assert "# Factored Dataset Profile Report" in md
    assert "171,321" in md
    assert "104,749" in md
    assert "Cargo no reconocido" in md
    assert "Null Island Coordinates" in md


def test_cli_missing_data_dir_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"
    assert main(["--data-dir", str(missing), "--quiet"]) == 1
    assert "data directory not found" in capsys.readouterr().err


def test_cli_missing_cache_dir_exits_1(tmp_path: Path) -> None:
    missing_cache = tmp_path / "no-cache"
    assert main(["--data-dir", str(tmp_path), "--cache-dir", str(missing_cache)]) == 1
