"""Aggregate statistical profiling logic for the Factored dataset."""

from __future__ import annotations

import collections
import glob
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from profile_factored.loader import (
    ALL_TABLES,
    load_table,
    scan_table,
)


@dataclass
class TableInventory:
    name: str
    partitioning: str
    file_count: int
    size_mb: float
    row_count: int
    col_count: int
    date_ranges: dict[str, tuple[str, str]]


@dataclass
class ProfileResults:
    inventory: list[TableInventory]
    null_rates: dict[str, dict[str, float]]
    relationships: dict[str, float | int | str]
    languages_countries: dict[str, int | float | dict[str, int]]
    system_fit: dict[str, int | float | dict[str, int] | dict[str, str]]
    intents_transcripts: dict[str, int | float | dict[str, int] | list[str]]
    fraud_complaints: dict[str, int | float | dict[str, int]]
    quality_issues: dict[str, int | float | dict[str, int]]
    execution_time_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def format_doc_pattern(text: str | None) -> str:
    """Mask letters with A and digits with 9."""
    if text is None:
        return ""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", text))


def is_luhn_valid(pan: str) -> bool:
    """Check Luhn mod-10 validity of a 16-digit card number."""
    if not pan.isdigit() or len(pan) != 16:
        return False
    digits = [int(x) for x in pan][::-1]
    checksum = sum(digits[0::2]) + sum(sum(divmod(2 * d, 10)) for d in digits[1::2])
    return checksum % 10 == 0


def profile_inventory(
    data_dir: Path, cache_dir: Path | None = None
) -> list[TableInventory]:
    """Compute file, size, row, and date boundaries across all 10 tables."""
    results: list[TableInventory] = []
    for table in ALL_TABLES:
        part_type = "flat CSV"
        file_count = 1
        size_mb = 0.0

        single_csv = data_dir / f"{table}.csv"
        part_dir = data_dir / table
        if single_csv.exists():
            size_mb = os.path.getsize(single_csv) / (1024 * 1024)
        elif part_dir.exists():
            part_type = "year=YYYY/month=MM/day=DD"
            files = glob.glob(str(part_dir / "**" / "*.csv"), recursive=True)
            file_count = len(files)
            size_mb = sum(os.path.getsize(f) for f in files) / (1024 * 1024)

        if table == "transactions":
            lf = scan_table(data_dir, table, cache_dir)
            schema = lf.collect_schema()
            row_count = lf.select(pl.len()).collect().item()
            col_count = len(schema.names())
            date_cols = [c for c in schema.names() if "date" in c]
            exprs = [
                pl.col(c).drop_nulls().min().alias(f"{c}_min") for c in date_cols
            ] + [pl.col(c).drop_nulls().max().alias(f"{c}_max") for c in date_cols]
            d_res = lf.select(exprs).collect().to_dicts()[0]
            date_ranges = {
                c: (str(d_res.get(f"{c}_min") or ""), str(d_res.get(f"{c}_max") or ""))
                for c in date_cols
            }
        else:
            df = load_table(data_dir, table, cache_dir)
            row_count = df.height
            col_count = df.width
            date_cols = [c for c in df.columns if "date" in c]
            date_ranges = {
                c: (
                    str(df[c].drop_nulls().min() or ""),
                    str(df[c].drop_nulls().max() or ""),
                )
                for c in date_cols
            }

        results.append(
            TableInventory(
                name=table,
                partitioning=part_type,
                file_count=file_count,
                size_mb=round(size_mb, 2),
                row_count=row_count,
                col_count=col_count,
                date_ranges=date_ranges,
            )
        )
    return results


def run_full_profile(data_dir: Path, cache_dir: Path | None = None) -> ProfileResults:
    """Execute complete aggregate profiling of the Factored dataset."""
    import time

    start_time = time.time()

    # 1. Inventory
    inventory = profile_inventory(data_dir, cache_dir)

    # 2. Load tables
    customers = load_table(data_dir, "customers", cache_dir)
    products = load_table(data_dir, "products", cache_dir)
    branches = load_table(data_dir, "branches", cache_dir)
    agents = load_table(data_dir, "service_agents", cache_dir)
    rates = load_table(data_dir, "daily_exchange_rates", cache_dir)
    transcripts = load_table(data_dir, "call_transcripts", cache_dir)
    interactions = load_table(data_dir, "call_center_interactions", cache_dir)
    complaints = load_table(data_dir, "complaints", cache_dir)
    surveys = load_table(data_dir, "satisfaction_surveys", cache_dir)
    tx_lazy = scan_table(data_dir, "transactions", cache_dir)

    # 3. Null rates per table (>0.1%)
    null_rates: dict[str, dict[str, float]] = {}
    eager_tables = {
        "customers": customers,
        "products": products,
        "branches": branches,
        "service_agents": agents,
        "daily_exchange_rates": rates,
        "call_transcripts": transcripts,
        "call_center_interactions": interactions,
        "complaints": complaints,
        "satisfaction_surveys": surveys,
    }
    for t_name, df in eager_tables.items():
        n_dict: dict[str, float] = {}
        for c in df.columns:
            rate = float(
                (
                    df[c].is_null() | (df[c].cast(pl.String).str.strip_chars() == "")
                ).mean()
            )
            if rate > 0.001:
                n_dict[c] = round(rate * 100, 2)
        null_rates[t_name] = n_dict

    # Transactions null rates
    tx_schema = tx_lazy.collect_schema()
    tx_exprs = [
        (pl.col(c).is_null() | (pl.col(c).cast(pl.String).str.strip_chars() == ""))
        .mean()
        .alias(c)
        for c in tx_schema.names()
    ]
    tx_nulls_raw = tx_lazy.select(tx_exprs).collect().to_dicts()[0]
    null_rates["transactions"] = {
        c: round(float(v) * 100, 2) for c, v in tx_nulls_raw.items() if float(v) > 0.001
    }

    # 4. Key Relationships
    cust_id_set = customers["customer_id"].implode()
    prod_id_set = products["product_id"].implode()
    inter_id_set = interactions["interaction_id"].implode()

    prod_cust_orphan = float((~products["customer_id"].is_in(cust_id_set)).mean())
    transcript_inter_in = float(
        (transcripts["interaction_id"].is_in(inter_id_set)).mean()
    )

    inter_has_trans = interactions["has_transcript"].value_counts().to_dicts()
    has_transcript_counts = {
        str(d["has_transcript"]): int(d["count"]) for d in inter_has_trans
    }

    # Transactions integrity
    tx_eval = tx_lazy.select(
        "transaction_id", "product_id", "customer_id", "currency", "is_fraud"
    ).collect()
    tx_orphan_prod = float((~tx_eval["product_id"].is_in(prod_id_set)).mean())
    tx_orphan_cust = float((~tx_eval["customer_id"].is_in(cust_id_set)).mean())

    tx_prod_join = tx_eval.join(
        products.select(
            "product_id",
            pl.col("customer_id").alias("prod_cust"),
            pl.col("currency").alias("prod_curr"),
        ),
        on="product_id",
        how="left",
    )
    tx_cust_mismatch = float(
        (tx_prod_join["customer_id"] != tx_prod_join["prod_cust"]).mean()
    )
    tx_curr_mismatch = float(
        (tx_prod_join["currency"] != tx_prod_join["prod_curr"]).mean()
    )

    # Complaints relationships
    complaint_origin_nonnull = complaints.filter(
        pl.col("origin_interaction_id").is_not_null()
        & (pl.col("origin_interaction_id").str.strip_chars() != "")
    ).height
    has_aff_prod = (
        complaints.filter(pl.col("affected_product_id").is_not_null()).height > 0
    )
    complaint_affected_in_prod = (
        float(
            complaints.filter(pl.col("affected_product_id").is_not_null())
            .select(pl.col("affected_product_id").is_in(prod_id_set).mean())
            .item()
        )
        if has_aff_prod
        else 0.0
    )

    complaint_prod_join = complaints.filter(
        pl.col("affected_product_id").is_not_null()
    ).join(
        products.select(
            "product_id",
            pl.col("customer_id").alias("prod_cust"),
            pl.col("currency").alias("prod_curr"),
        ),
        left_on="affected_product_id",
        right_on="product_id",
        how="left",
    )
    complaint_cust_mismatch = float(
        (complaint_prod_join["customer_id"] != complaint_prod_join["prod_cust"]).mean()
    )
    complaint_curr_mismatch = float(
        complaint_prod_join.filter(pl.col("currency").is_not_null())
        .select((pl.col("currency") != pl.col("prod_curr")).mean())
        .item()
    )

    relationships = {
        "product_orphan_customer_rate": prod_cust_orphan,
        "transaction_orphan_product_rate": tx_orphan_prod,
        "transaction_orphan_customer_rate": tx_orphan_cust,
        "transaction_customer_mismatch_rate": tx_cust_mismatch,
        "transaction_currency_mismatch_rate": tx_curr_mismatch,
        "transcript_interaction_match_rate": transcript_inter_in,
        "interactions_has_transcript_counts": has_transcript_counts,
        "complaint_origin_interaction_non_null_count": complaint_origin_nonnull,
        "complaint_affected_product_in_products_rate": complaint_affected_in_prod,
        "complaint_affected_product_other_customer_rate": complaint_cust_mismatch,
        "complaint_currency_vs_product_mismatch_rate": complaint_curr_mismatch,
    }

    # 5. Languages & Countries
    trans_lang = {
        str(d["detected_language"]): int(d["count"])
        for d in transcripts["detected_language"].value_counts().to_dicts()
    }
    cust_country = {
        str(d["country"]): int(d["count"])
        for d in customers["country"].value_counts().to_dicts()
    }

    pt_regex = (
        r"\b(você|obrigad[oa]|não|cartão|conta|estou|meu|minha|"
        r"roubado|perdi|bom dia|olá)\b"
    )
    en_regex = r"(?i)\b(the|my|card|please|thank you|stolen|account|hello|charge)\b"
    es_regex = r"(?i)\b(tarjeta|cuenta|gracias|quiero|por favor|robaron|hola)\b"

    ct_series = transcripts["customer_text"].fill_null("").str.to_lowercase()
    pt_matches = int(ct_series.str.contains(pt_regex).sum())
    en_matches = int(ct_series.str.contains(en_regex).sum())
    es_matches = int(ct_series.str.contains(es_regex).sum())

    languages_countries = {
        "transcript_detected_languages": trans_lang,
        "customer_countries": cust_country,
        "customer_text_pt_matches": pt_matches,
        "customer_text_en_matches": en_matches,
        "customer_text_es_matches": es_matches,
    }

    # 6. Fit for Banking-Core
    # Document types
    doc_types = (
        customers.group_by("document_type", "country")
        .len()
        .sort("len", descending=True)
        .to_dicts()
    )
    doc_type_summary = {
        f"{d['document_type']} ({d['country']})": int(d["len"]) for d in doc_types
    }

    cust_with_pat = customers.with_columns(
        pl.col("document_number")
        .map_elements(format_doc_pattern, return_dtype=pl.String)
        .alias("pat")
    )
    doc_patterns = {
        f"{d['document_type']} [{d['pat']}]": int(d["len"])
        for d in cust_with_pat.group_by("document_type", "pat")
        .len()
        .sort("len", descending=True)
        .to_dicts()
    }

    dup_cust_id = int(customers.height - customers["customer_id"].n_unique())
    dup_doc = int(
        customers.height
        - customers.select("document_type", "document_number").n_unique()
    )

    # Products & Cards
    prod_counts = {
        str(d["product_type"]): int(d["count"])
        for d in products["product_type"].value_counts().to_dicts()
    }
    prod_status = {
        str(d["product_status"]): int(d["count"])
        for d in products["product_status"].value_counts().to_dicts()
    }

    cards = products.filter(pl.col("product_type").str.starts_with("Tarjeta"))
    luhn_rate = float(
        cards["product_number"]
        .map_elements(is_luhn_valid, return_dtype=pl.Boolean)
        .mean()
    )
    card_prefix_4 = float((cards["product_number"].str.slice(0, 1) == "4").mean())
    cards_per_cust = cards.group_by("customer_id").len()["len"]
    cust_with_cards = int(cards["customer_id"].n_unique())

    # Currencies
    tx_curr = {
        str(d["currency"]): int(d["len"])
        for d in tx_eval.group_by("currency")
        .len()
        .sort("len", descending=True)
        .to_dicts()
    }
    prod_curr = {
        str(d["currency"]): int(d["len"])
        for d in products.group_by("currency")
        .len()
        .sort("len", descending=True)
        .to_dicts()
    }
    mx_prod_curr = {
        str(d["currency"]): int(d["len"])
        for d in products.join(
            customers.select("customer_id", "country"), on="customer_id"
        )
        .filter(pl.col("country") == "México")
        .group_by("currency")
        .len()
        .to_dicts()
    }

    # Merchant null rate on cards vs overall
    tx_full = tx_lazy.select("product_id", "merchant_name").collect()
    tx_with_prod = tx_full.join(
        products.select("product_id", "product_type"), on="product_id", how="left"
    )
    card_tx = tx_with_prod.filter(pl.col("product_type").str.starts_with("Tarjeta"))
    card_merch_null = float(card_tx["merchant_name"].is_null().mean())
    overall_merch_null = float(tx_full["merchant_name"].is_null().mean())

    system_fit = {
        "doc_type_distribution": doc_type_summary,
        "doc_type_patterns": doc_patterns,
        "duplicate_customer_id_count": dup_cust_id,
        "duplicate_document_count": dup_doc,
        "product_type_distribution": prod_counts,
        "product_status_distribution": prod_status,
        "card_count": cards.height,
        "card_luhn_valid_rate": round(luhn_rate, 4),
        "card_first_digit_4_rate": round(card_prefix_4, 4),
        "customers_with_cards_count": cust_with_cards,
        "cards_per_customer_mean": round(float(cards_per_cust.mean()), 2),
        "cards_per_customer_max": int(cards_per_cust.max()),
        "transaction_currency_distribution": tx_curr,
        "product_currency_distribution": prod_curr,
        "mexico_product_currencies": mx_prod_curr,
        "card_tx_merchant_name_null_rate": round(card_merch_null, 4),
        "overall_tx_merchant_name_null_rate": round(overall_merch_null, 4),
    }

    # 7. Intents and Transcripts
    detected_intents_counts = {
        str(d["detected_intents"]): int(d["count"])
        for d in transcripts["detected_intents"].value_counts().to_dicts()
    }
    distinct_cust_text = int(transcripts["customer_text"].n_unique())
    distinct_agent_text = int(transcripts["agent_text"].n_unique())
    distinct_full_text = int(transcripts["full_text"].n_unique())

    # Placeholder counts in full_text
    full_text_list = transcripts["full_text"].fill_null("").to_list()
    placeholder_counter = collections.Counter()
    for s in full_text_list:
        for p in re.findall(r"\{([^}]*)\}", s):
            placeholder_counter[p] += 1
    has_placeholder_rate = float(
        transcripts["full_text"].fill_null("").str.contains(r"\{[^}]*\}").mean()
    )

    # Distinct atomic customer utterances
    cust_utterances = collections.Counter()
    for s in transcripts["customer_text"].fill_null("").to_list():
        for u in re.split(r"(?<=[.?!])\s+|\s*\|\s*|\n", s):
            clean_u = u.strip()
            if clean_u:
                cust_utterances[clean_u] += 1

    intents_transcripts = {
        "detected_intents": detected_intents_counts,
        "distinct_customer_text_count": distinct_cust_text,
        "total_transcripts_count": transcripts.height,
        "distinct_customer_text_fraction": round(
            distinct_cust_text / transcripts.height, 6
        ),
        "distinct_agent_text_count": distinct_agent_text,
        "distinct_full_text_count": distinct_full_text,
        "full_text_templated_fraction": has_placeholder_rate,
        "placeholder_counts": dict(placeholder_counter.most_common(10)),
        "atomic_customer_utterance_count": len(cust_utterances),
        "top_customer_utterances": [
            f"{cnt}x: {utt}" for utt, cnt in cust_utterances.most_common(10)
        ],
    }

    # 8. Fraud & Complaints
    tx_fraud_counts = {
        str(d["is_fraud"]): int(d["len"])
        for d in tx_eval.group_by("is_fraud").len().to_dicts()
    }
    tx_fraud_total = tx_fraud_counts.get("True", 0)
    tx_fraud_rate = tx_fraud_total / tx_eval.height

    f_score_stats = tx_lazy.select(
        pl.col("fraud_score").cast(pl.Float64).alias("fs"), "is_fraud"
    ).collect()
    fs_legit_mean = float(
        f_score_stats.filter(pl.col("is_fraud") != "True")["fs"].mean() or 0.0
    )
    fs_fraud_mean = float(
        f_score_stats.filter(pl.col("is_fraud") == "True")["fs"].mean() or 0.0
    )

    # Complaints cargo no reconocido
    complaints_cargo = complaints.filter(
        pl.col("subcategory") == "Cargo no reconocido"
    ).height
    complaints_desc_distinct = int(complaints["description"].n_unique())

    fraud_complaints = {
        "transaction_fraud_counts": tx_fraud_counts,
        "transaction_fraud_rate": round(tx_fraud_rate, 6),
        "fraud_score_legit_mean": round(fs_legit_mean, 2),
        "fraud_score_fraud_mean": round(fs_fraud_mean, 2),
        "complaints_cargo_no_reconocido_count": complaints_cargo,
        "complaints_cargo_no_reconocido_fraction": round(
            complaints_cargo / complaints.height, 4
        ),
        "complaints_distinct_descriptions": complaints_desc_distinct,
    }

    # 9. Data Quality Issues
    # Phone mismatch
    def extract_phone_code(p_str: str | None) -> str | None:
        if not p_str:
            return None
        m = re.match(r"^\+(\d{1,3})", p_str)
        return m.group(1) if m else None

    c_phone = customers.filter(pl.col("mobile_phone").is_not_null()).with_columns(
        pl.col("mobile_phone")
        .map_elements(extract_phone_code, return_dtype=pl.String)
        .alias("code"),
        pl.col("country")
        .replace_strict(
            {"México": "52", "Colombia": "57", "Argentina": "54"}, default="0"
        )
        .alias("expected_code"),
    )
    phone_mismatches = int((c_phone["code"] != c_phone["expected_code"]).sum())
    phone_mismatch_rate = float((c_phone["code"] != c_phone["expected_code"]).mean())
    mx_with_54 = int(
        c_phone.filter(
            (pl.col("country") == "México") & (pl.col("code") == "54")
        ).height
    )

    # Coordinates near 0,0
    tx_coords = (
        tx_lazy.select(
            pl.col("latitude").cast(pl.Float64).alias("la"),
            pl.col("longitude").cast(pl.Float64).alias("lo"),
        )
        .drop_nulls("la")
        .collect()
    )
    tx_near_zero = int(
        ((tx_coords["la"].abs() < 1) & (tx_coords["lo"].abs() < 1)).sum()
    )

    branch_coords = branches.with_columns(
        pl.col("latitude").cast(pl.Float64).alias("la"),
        pl.col("longitude").cast(pl.Float64).alias("lo"),
    )
    branches_near_zero = int(
        ((branch_coords["la"].abs() < 1) & (branch_coords["lo"].abs() < 1)).sum()
    )

    # Cutoff 2026-06-18
    cutoff_date = date(2026, 6, 18)
    cust_updated_after_cutoff = customers.filter(
        pl.col("last_updated").str.slice(0, 10).str.to_date(strict=False) > cutoff_date
    ).height
    prod_updated_after_cutoff = products.filter(
        pl.col("last_updated").str.slice(0, 10).str.to_date(strict=False) > cutoff_date
    ).height
    complaints_resolved_after_cutoff = complaints.filter(
        pl.col("resolution_date").str.slice(0, 10).str.to_date(strict=False)
        > cutoff_date
    ).height
    complaints_closed_after_cutoff = complaints.filter(
        pl.col("closing_date").str.slice(0, 10).str.to_date(strict=False) > cutoff_date
    ).height

    # Minors at registration
    minors_at_reg = (
        customers.with_columns(
            dob=pl.col("date_of_birth").str.to_date(strict=False),
            reg=pl.col("registration_date").str.slice(0, 10).str.to_date(strict=False),
        )
        .filter((pl.col("reg") - pl.col("dob")).dt.total_days() / 365.25 < 18)
        .height
    )

    # Products opened before customer registered
    prod_reg_join = products.join(
        customers.select("customer_id", "registration_date"), on="customer_id"
    )
    prod_before_reg = prod_reg_join.filter(
        pl.col("opening_date") < pl.col("registration_date").str.slice(0, 10)
    ).height

    quality_issues = {
        "phone_code_mismatch_count": phone_mismatches,
        "phone_code_mismatch_rate": round(phone_mismatch_rate, 4),
        "mexico_customers_with_arg_phone_code": mx_with_54,
        "transactions_coords_near_zero_count": tx_near_zero,
        "transactions_coords_near_zero_fraction": round(
            tx_near_zero / tx_coords.height, 4
        ),
        "branches_near_zero_count": branches_near_zero,
        "branches_near_zero_fraction": round(branches_near_zero / branches.height, 4),
        "customers_updated_after_cutoff_count": cust_updated_after_cutoff,
        "products_updated_after_cutoff_count": prod_updated_after_cutoff,
        "complaints_resolved_after_cutoff_count": complaints_resolved_after_cutoff,
        "complaints_closed_after_cutoff_count": complaints_closed_after_cutoff,
        "customers_minor_at_registration_count": minors_at_reg,
        "products_opened_before_registration_count": prod_before_reg,
        "products_opened_before_registration_rate": round(
            prod_before_reg / products.height, 4
        ),
    }

    elapsed = round(time.time() - start_time, 2)

    return ProfileResults(
        inventory=inventory,
        null_rates=null_rates,
        relationships=relationships,
        languages_countries=languages_countries,
        system_fit=system_fit,
        intents_transcripts=intents_transcripts,
        fraud_complaints=fraud_complaints,
        quality_issues=quality_issues,
        execution_time_seconds=elapsed,
    )
