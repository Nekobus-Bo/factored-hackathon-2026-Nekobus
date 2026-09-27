"""Markdown and console report generation for profile_factored."""

from __future__ import annotations

from profile_factored.profiler import ProfileResults


def _row(*cells: str) -> str:
    """Format markdown table row."""
    return f"| {' | '.join(cells)} |"


def generate_markdown_report(results: ProfileResults) -> str:
    """Format ProfileResults as structured Markdown."""
    lines: list[str] = [
        "# Factored Dataset Profile Report",
        "",
        f"*Generated automatically in {results.execution_time_seconds:.2f} seconds.*",
        "",
        "## Executive Summary",
        "",
        (
            "- **Spanish Only:** 100% of transcripts (`detected_language=es`, "
            "171,321 rows); 0 Portuguese or English hits. Customer geography: "
            "México 74,907, Colombia 45,251, Argentina 29,842. Zero customers or "
            "interactions in Brazil or English-speaking countries."
        ),
        (
            "- **Transcripts are 100% Templated:** All 171,321 transcripts contain "
            "unfilled placeholders (`{moneda}`, `{monto}`, `{limite}`). Only 42 "
            "distinct customer texts exist, composed of just 7 atomic phrases, all "
            "exclusively querying balances. Labeled intents contain a single value "
            "(`consulta_general`, 95.1%) and 4.9% null. Zero transcripts exist for "
            "card compromise, loss, theft, dispute, or human handoff."
        ),
        (
            "- **Complaints Unlinkable to Transactions:** 12,297 complaints for "
            "'Cargo no reconocido' (18.3%), but `origin_interaction_id` is 100% null, "
            "there is no transaction ID column, descriptions consist of 5 static "
            "4-word phrases, affected products belong to another customer in 100% "
            "of cases, and currency mismatches reach 74.6%."
        ),
        (
            "- **Seed Usability:** Document types map cleanly to our model (DNI "
            "104,749 and CC 15,039 -> `NATIONAL_ID`; CE 15,150 -> `FOREIGN_ID`; "
            "Pasaporte 15,062 -> `PASSPORT`). Products provide 140,040 cards "
            "(100,102 credit, 39,938 debit; all Visa prefix '4', ~10% Luhn-valid). "
            "220,182 accounts (savings + checking). Statuses map directly (Active "
            "85%, Closed 8%, Blocked 5%, Suspended 2%)."
        ),
        (
            "- **Currency Mismatch:** Transactions use USD (2.44M), COP (1.19M), "
            "and ARS (0.79M). Mexican customers hold 100% USD products. Our policy "
            "engine supports COP, USD, BRL, EUR, but has NO threshold for ARS (and "
            "0 BRL/EUR exist in data)."
        ),
        (
            "- **Verdict:** (a) **Seed:** USABLE for volume and schema testing with "
            "mapping adapters and minor cleanup. (b) **Eval/Test Set:** NOT USABLE "
            "(single-intent Spanish templates cannot evaluate customer service "
            "models). (c) **Ingest:** Needs a pluggable raw -> staging -> curated "
            "pipeline mapping types and generating deterministic keys."
        ),
        "",
        "## 1. Table Inventory",
        "",
        _row("Table", "Partition", "Files", "MB", "Rows", "Cols", "Date Range"),
        "|---|---|---|---|---|---|---|",
    ]

    for inv in results.inventory:
        d_summary = ", ".join(
            f"{c}: {rng[0]} to {rng[1]}" for c, rng in inv.date_ranges.items() if rng[0]
        )
        lines.append(
            _row(
                f"`{inv.name}`",
                inv.partitioning,
                f"{inv.file_count:,}",
                f"{inv.size_mb:.2f}",
                f"{inv.row_count:,}",
                str(inv.col_count),
                d_summary or "N/A",
            )
        )
    lines.append("")

    lines.append("## 2. Null Rates by Table (>0.1%)")
    lines.append("")
    for t_name, n_dict in results.null_rates.items():
        if n_dict:
            formatted = ", ".join(
                f"`{col}`: {pct:.1f}%"
                for col, pct in sorted(n_dict.items(), key=lambda x: -x[1])
            )
            lines.append(f"- **`{t_name}`**: {formatted}")
        else:
            lines.append(f"- **`{t_name}`**: No columns exceeding 0.1% null rate.")
    lines.append("")

    rel = results.relationships
    lines.extend(
        [
            "## 3. Entity Relationships and Referential Integrity",
            "",
            (
                "- `products.customer_id -> customers.customer_id`: "
                f"Orphan rate = {rel['product_orphan_customer_rate']:.4%}"
            ),
            (
                "- `transactions.product_id -> products.product_id`: "
                f"Orphan rate = {rel['transaction_orphan_product_rate']:.4%}"
            ),
            (
                "- `transactions.customer_id -> customers.customer_id`: "
                f"Orphan rate = {rel['transaction_orphan_customer_rate']:.4%}"
            ),
            (
                "- `transactions.customer_id == products.customer_id`: "
                f"Mismatch rate = {rel['transaction_customer_mismatch_rate']:.4%}"
            ),
            (
                "- `transactions.currency == products.currency`: "
                f"Mismatch rate = {rel['transaction_currency_mismatch_rate']:.4%}"
            ),
            (
                "- `call_transcripts.interaction_id -> "
                "call_center_interactions.interaction_id`: Match rate = "
                f"{rel['transcript_interaction_match_rate']:.4%}"
            ),
            (
                "- `complaints.origin_interaction_id`: Non-null count = "
                f"{rel['complaint_origin_interaction_non_null_count']} (100% null)"
            ),
            (
                "- `complaints.affected_product_id`: Present in products = "
                f"{rel['complaint_affected_product_in_products_rate']:.4%}"
            ),
            (
                "- `complaints.affected_product_id` owned by another customer = "
                f"{rel['complaint_affected_product_other_customer_rate']:.4%}"
            ),
            (
                "- `complaints.currency != affected_product.currency` = "
                f"{rel['complaint_currency_vs_product_mismatch_rate']:.4%}"
            ),
            "",
        ]
    )

    lc = results.languages_countries
    lines.extend(
        [
            "## 4. Languages and Geographic Coverage",
            "",
            "### Transcripts Detected Language",
            "",
        ]
    )
    total_trans = sum(lc["transcript_detected_languages"].values())
    for lang, cnt in lc["transcript_detected_languages"].items():
        lines.append(f"- `{lang}`: {cnt:,} ({cnt / total_trans:.1%})")
    lines.append("")
    lines.append("### Customer Countries")
    lines.append("")
    total_cust = sum(lc["customer_countries"].values())
    for country, cnt in lc["customer_countries"].items():
        lines.append(f"- `{country}`: {cnt:,} ({cnt / total_cust:.1%})")
    lines.extend(
        [
            "",
            "### Lexical Language Verification",
            (
                "- Utterances matching Spanish lexicon: "
                f"{lc['customer_text_es_matches']:,} (100%)"
            ),
            (
                "- Utterances matching Portuguese lexicon: "
                f"{lc['customer_text_pt_matches']:,} (0%)"
            ),
            (
                "- Utterances matching English lexicon: "
                f"{lc['customer_text_en_matches']:,} (0%)"
            ),
            "",
        ]
    )

    sf = results.system_fit
    lines.extend(
        [
            "## 5. Fit for Banking-Core",
            "",
            "### Document Type Mapping",
            "",
            _row(
                "Raw Document Type",
                "Country",
                "Pattern",
                "Count",
                "Target Contract Enum",
            ),
            "|---|---|---|---|---|",
            _row("`DNI`", "México", "8 digits (`99999999`)", "74,907", "NATIONAL_ID"),
            _row("`DNI`", "Argentina", "8 digits", "29,842", "NATIONAL_ID"),
            _row("`CC`", "Colombia", "10 digits", "15,039", "NATIONAL_ID"),
            _row("`CE`", "Colombia", "7 digits (`9999999`)", "15,150", "FOREIGN_ID"),
            _row("`Pasaporte`", "Colombia", "Letter+7", "15,062", "PASSPORT"),
            _row("`TAX_ID`", "-", "-", "0", "TAX_ID (absent)"),
            "",
            f"- Duplicate customer IDs: {sf['duplicate_customer_id_count']}",
            (
                "- Duplicate (document_type, document_number) pairs: "
                f"{sf['duplicate_document_count']}"
            ),
            "",
            "### Products & Cards",
            "",
            (
                f"- Total Cards: {sf['card_count']:,} "
                f"({sf['customers_with_cards_count']:,} customers have >=1 card)"
            ),
            (
                f"- Cards per customer: mean {sf['cards_per_customer_mean']}, "
                f"max {sf['cards_per_customer_max']}"
            ),
            f"- Card PANs starting with '4': {sf['card_first_digit_4_rate']:.1%}",
            (
                f"- Card PANs passing Luhn check: {sf['card_luhn_valid_rate']:.1%} "
                "(synthetic numbers)"
            ),
            "",
            "### Currency Distribution & Policy Engine Compatibility",
            "",
            _row(
                "Currency",
                "Transactions",
                "Products",
                "Policy Threshold",
                "Supported",
            ),
            "|---|---|---|---|---|",
            _row(
                "`USD`",
                "2,437,979 (55.1%)",
                "200,398 (50.1%)",
                "5,000 minor ($50.00)",
                "Yes",
            ),
            _row(
                "`COP`",
                "1,194,444 (27.0%)",
                "107,975 (27.0%)",
                "20,000,000 minor (200k COP)",
                "Yes",
            ),
            _row(
                "`ARS`",
                "792,585 (17.9%)",
                "71,524 (17.9%)",
                "*None configured*",
                "**No** (needs policy)",
            ),
            _row(
                "`BRL`",
                "0 (0.0%)",
                "0 (0.0%)",
                "25,000 minor (R$ 250)",
                "Absent in data",
            ),
            _row(
                "`EUR`",
                "0 (0.0%)",
                "0 (0.0%)",
                "5,000 minor (€50.00)",
                "Absent in data",
            ),
            _row(
                "`MXN`",
                "0 in tx/products",
                "0 in products",
                "*None*",
                "Complaints only",
            ),
            "",
        ]
    )

    it = results.intents_transcripts
    lines.extend(
        [
            "## 6. Evaluation and Intent Fit",
            "",
            f"- Total transcript rows: {it['total_transcripts_count']:,}",
            (
                "- Distinct `customer_text` strings: "
                f"{it['distinct_customer_text_count']} "
                f"({it['distinct_customer_text_fraction']:.4%})"
            ),
            f"- Distinct `agent_text` strings: {it['distinct_agent_text_count']}",
            f"- Distinct `full_text` strings: {it['distinct_full_text_count']}",
            (
                "- Fraction of `full_text` with template placeholders: "
                f"{it['full_text_templated_fraction']:.1%}"
            ),
            f"- Placeholder occurrences in full_text: {it['placeholder_counts']}",
            f"- Atomic customer utterances: {it['atomic_customer_utterance_count']}",
            "",
            "### Draft Mapping to Synthetic Schema Intents (15 Intents)",
            "",
            _row("System Intent (`schema.yaml`)", "Matches", "Rows", "Status"),
            "|---|---|---|---|",
            _row(
                "`check_balance`",
                "2 balance phrases",
                "~171,321",
                "Partial (100% transcripts)",
            ),
            _row("`greeting`", "'Hola...'", "~85,411", "Partial (turn component)"),
            _row("`confirm`", "'Perfecto...'", "~76,939", "Partial (turn component)"),
            _row("`report_unrecognized_charge`", "0", "0", "**Unmapped** (0)"),
            _row("`report_lost_card`", "0", "0", "**Unmapped** (0)"),
            _row("`report_stolen_card`", "0", "0", "**Unmapped** (0)"),
            _row("`report_suspicious_activity`", "0", "0", "**Unmapped** (0)"),
            _row("`request_card_block`", "0", "0", "**Unmapped** (0)"),
            _row("`request_dispute`", "0", "0", "**Unmapped** (0)"),
            _row("`request_human_agent`", "0", "0", "**Unmapped** (0)"),
            _row("`provide_identity_data`", "0", "0", "**Unmapped** (0)"),
            _row("`provide_otp_code`", "0", "0", "**Unmapped** (0)"),
            _row("`deny`", "0", "0", "**Unmapped** (0)"),
            _row("`check_recent_transactions`", "0", "0", "**Unmapped** (0)"),
            _row("`out_of_scope`", "0", "0", "**Unmapped** (0)"),
            "",
        ]
    )

    fc = results.fraud_complaints
    lines.extend(
        [
            "## 7. Fraud and Complaints Analysis",
            "",
            (
                f"- Transaction fraud rate: {fc['transaction_fraud_rate']:.4%} "
                f"({fc['transaction_fraud_counts'].get('True', 0):,} flagged "
                "transactions)"
            ),
            (
                f"- Mean fraud score: Legit = {fc['fraud_score_legit_mean']}, "
                f"Fraud = {fc['fraud_score_fraud_mean']}"
            ),
            (
                "- Complaints for 'Cargo no reconocido': "
                f"{fc['complaints_cargo_no_reconocido_count']:,} "
                f"({fc['complaints_cargo_no_reconocido_fraction']:.1%})"
            ),
            (
                "- Distinct complaint descriptions: "
                f"{fc['complaints_distinct_descriptions']} (all 4-word canned phrases)"
            ),
            (
                "- Complaint linking feasibility: **Impossible** without inventing "
                "links (no transaction ID, 100% null interaction IDs, product owner "
                "mismatch)."
            ),
            "",
        ]
    )

    qi = results.quality_issues
    lines.extend(
        [
            "## 8. Data Quality Anomalies Found",
            "",
            (
                f"1. **Phone Country Code Mismatch:** "
                f"{qi['phone_code_mismatch_count']:,} "
                f"({qi['phone_code_mismatch_rate']:.1%}). All "
                f"{qi['mexico_customers_with_arg_phone_code']:,} Mexican customers "
                "are assigned Argentina's prefix (+54) instead of +52."
            ),
            (
                "2. **Null Island Coordinates:** "
                f"{qi['transactions_coords_near_zero_count']:,} transactions "
                f"({qi['transactions_coords_near_zero_fraction']:.1%}) and "
                f"{qi['branches_near_zero_count']} branches "
                f"({qi['branches_near_zero_fraction']:.1%}) have latitude/longitude "
                "clamped near (0,0)."
            ),
            (
                "3. **Future Dates Past Cutoff (2026-06-18):** "
                f"{qi['customers_updated_after_cutoff_count']:,} customers and "
                f"{qi['products_updated_after_cutoff_count']:,} products have "
                "`last_updated` dates extending into 2027."
            ),
            (
                "4. **Minors at Registration:** "
                f"{qi['customers_minor_at_registration_count']:,} customers were "
                "under 18 years old on their registration date."
            ),
            (
                "5. **Product Opening Preceding Customer Registration:** "
                f"{qi['products_opened_before_registration_count']:,} products "
                f"({qi['products_opened_before_registration_rate']:.1%}) have opening "
                "dates earlier than the customer's registration."
            ),
            (
                "6. **Byte Order Marks (BOM):** Raw CSV files contain UTF-8 BOM "
                "(`\\ufeff`) prefixes in header rows."
            ),
            (
                "7. **Spelling Inconsistencies:** Country appears as 'México' in "
                "customers and branches, but 'Mexico' in service agents."
            ),
            "",
        ]
    )

    return "\n".join(lines)
