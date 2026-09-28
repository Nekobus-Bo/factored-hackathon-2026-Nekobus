import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # table-fit · transaction disputes

    **Question:** Which LATAM Bank tables should the transaction-disputes workflow use, and does each one hold up in the data?

    **Data:** `customers`, `products`, `transactions` (2026), `daily_exchange_rates`, `complaints` (2026) · **Generated:** 2026-09-28, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type is not in its menu yet)
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What the workflow needs from data

    The customer reports a charge they do not recognise and asks to dispute it. The system verifies them, finds the charge,
    and hands the dispute to a person; it never resolves it (`docs/00-problem.md` §3, ADR-0003).

    | Step | Tool | Data it needs | Candidate table |
    |---|---|---|---|
    | 1. Verify the customer | `identity.*`, OTP | An identity with a registered channel | `customers` |
    | 2. Find their cards | `card.list` | Cards owned by that customer | `products` |
    | 3. Pick the disputed charge | `transaction.list_recent` (`is_disputable`) | Card charges the customer owns, recent and settled, with a merchant they can recognise | `transactions` |
    | 4. Apply the amount policy | policy engine | The threshold in the charge's currency | `daily_exchange_rates` |
    | 5. Hand off to the disputes queue | `handoff.create` (`DISPUTE_CLAIM`) | Nothing from the dataset: the ticket is built from steps 1–4 | `complaints` looks like a fit; section 5 tests it |

    Each section below states one need and shows the query that supports or rejects it.
    """)
    return


@app.cell
def _():
    import os

    import altair as alt
    import duckdb
    import marimo as mo

    return alt, duckdb, mo, os


@app.cell
def _(mo, os):
    # Settings: change these, the rest of the notebook follows
    DATA_DIR = os.environ.get("DATA_DIR", str(mo.notebook_dir().parents[1] / "data" / "raw" / "latam_bank"))
    YEAR = "2026"  # fact-table partitions to read; must contain the dispute window below
    # Dispute rules, mirrored from apps/banking-core/src/banking_core/seed/ingest/sources/factored.json
    DATASET_CUTOFF = "2026-06-18"
    DISPUTE_WINDOW_DAYS = 90
    CARD_PRODUCTS = "'Tarjeta Crédito', 'Tarjeta Débito'"
    DISPUTE_TYPES = "'Purchase'"  # dispute_eligible_types
    SETTLED_STATUS = "'Approved'"  # Approved -> SETTLED; Reversed is dropped; Pending/Declined are not settled
    POLICY_THRESHOLD_USD = 500  # policy_threshold_equivalents.base_amount_minor = 50000
    return (
        CARD_PRODUCTS,
        DATASET_CUTOFF,
        DATA_DIR,
        DISPUTE_TYPES,
        DISPUTE_WINDOW_DAYS,
        POLICY_THRESHOLD_USD,
        SETTLED_STATUS,
        YEAR,
    )


@app.cell
def _(DATA_DIR, YEAR, duckdb, mo, os):
    mo.stop(
        not os.path.isdir(DATA_DIR),
        mo.md(f"**Dataset not found at `{DATA_DIR}`.** Link it into `data/raw/latam_bank` or set `DATA_DIR`."),
    )
    con = duckdb.connect()
    for _table in ["transactions", "complaints"]:
        con.sql(f"""
            CREATE VIEW {_table} AS
            SELECT * FROM read_csv('{DATA_DIR}/{_table}/year={YEAR}/*/*/*.csv', hive_partitioning = true)
        """)
    for _table in ["customers", "products", "daily_exchange_rates"]:
        con.sql(f"CREATE VIEW {_table} AS SELECT * FROM read_csv('{DATA_DIR}/{_table}.csv')")
    return (con,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats** (from `lab/dataset-characterization.md`)

    - `amount_usd` is null whenever `currency = 'USD'`; there is no MXN, Mexican accounts are in USD (§3).
    - "México" and "Mexico" both appear in `transaction_country` (§3).
    - 18.7% of transactions happen before their product's opening date; only Active products transact (§3).
    - `is_fraud` cannot be learned from behaviour and `fraud_score` is a leaked label; neither links to later complaints or calls (§6.1).
    - `complaints.origin_interaction_id` is always null and `affected_product_id` is never owned by the complaining customer (§3, §4).
    - `complaints.description` has 5 template values and `resolution_days` is uniform 1–30 for every priority (§6.5, §7).
    - A complaint matches a prior transaction by amount at chance level (0.2–0.4%), in every subcategory (§6.5).
    - Transcripts are 42 template texts, Spanish only, with no dispute or card-compromise content (§7).
    - Nulls are injected at fixed round rates per column, e.g. `mobile_phone` (§2.4).
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Verify the customer → `customers`

    Verification needs an active customer with a registered mobile phone for the OTP (`otp_channel = sms` in the mapping).
    """)
    return


@app.cell
def _(con, mo):
    mo.sql(
        """
        SELECT customer_status, count(*) AS n, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
               round(100.0 * avg((mobile_phone IS NOT NULL)::INT), 2) AS pct_with_mobile
        FROM customers GROUP BY 1 ORDER BY n DESC
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Find the customer's cards → `products`

    Cards are the two card product types. Each card must have an owner in `customers`, so `card.list` can be scoped to the verified customer.
    """)
    return


@app.cell
def _(CARD_PRODUCTS, con, mo):
    mo.sql(
        f"""
        SELECT p.product_type, p.product_status, count(*) AS n,
               round(100.0 * avg((c.customer_id IS NOT NULL)::INT), 2) AS pct_owner_found
        FROM products p LEFT JOIN customers c USING (customer_id)
        WHERE p.product_type IN ({CARD_PRODUCTS})
        GROUP BY ALL ORDER BY ALL
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Find the disputed charge → `transactions`

    **3a. Ownership.** The charge must sit on a product the verified customer owns, otherwise the system could discuss another customer's charge.
    """)
    return


@app.cell
def _(con, mo):
    mo.sql(
        """
        SELECT count(*) AS n_transactions,
               round(100.0 * avg((p.product_id IS NOT NULL)::INT), 2) AS pct_product_found,
               round(100.0 * avg((p.customer_id = t.customer_id)::INT), 2) AS pct_same_owner
        FROM transactions t LEFT JOIN products p USING (product_id)
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **3b. Which transaction types live on cards.** A dispute is about a card charge, so the eligible type must be one that only cards carry.
    """)
    return


@app.cell
def _(CARD_PRODUCTS, con, mo):
    mo.sql(
        f"""
        SELECT t.transaction_type,
               count(*) FILTER (WHERE p.product_type IN ({CARD_PRODUCTS})) AS on_card,
               count(*) FILTER (WHERE p.product_type NOT IN ({CARD_PRODUCTS})) AS on_account
        FROM transactions t JOIN products p USING (product_id)
        GROUP BY 1 ORDER BY 1
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **3c. How many charges are disputable.** Each column adds one rule from the mapping, inside the dispute window before the dataset cutoff.
    """)
    return


@app.cell
def _(
    CARD_PRODUCTS,
    DATASET_CUTOFF,
    DISPUTE_TYPES,
    DISPUTE_WINDOW_DAYS,
    SETTLED_STATUS,
    con,
    mo,
):
    mo.sql(
        f"""
        SELECT count(*) AS in_window,
               count(*) FILTER (WHERE p.product_type IN ({CARD_PRODUCTS})) AS on_card,
               count(*) FILTER (WHERE p.product_type IN ({CARD_PRODUCTS}) AND t.transaction_type IN ({DISPUTE_TYPES})) AS purchase,
               count(*) FILTER (WHERE p.product_type IN ({CARD_PRODUCTS}) AND t.transaction_type IN ({DISPUTE_TYPES})
                                  AND t.transaction_status IN ({SETTLED_STATUS})) AS disputable
        FROM transactions t JOIN products p USING (product_id)
        WHERE t.transaction_date >= TIMESTAMP '{DATASET_CUTOFF}' - INTERVAL {DISPUTE_WINDOW_DAYS} DAY
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **3d. Can the customer recognise the charge?** They identify it by merchant, category and place, so those fields must be filled on disputable charges.
    """)
    return


@app.cell
def _(DATASET_CUTOFF, DISPUTE_TYPES, DISPUTE_WINDOW_DAYS, SETTLED_STATUS, con, mo):
    # Purchases only occur on cards (3b), so the card join is not repeated here
    mo.sql(
        f"""
        SELECT count(*) AS disputable,
               round(100.0 * avg((merchant_name IS NOT NULL)::INT), 2) AS pct_merchant,
               round(100.0 * avg((merchant_category IS NOT NULL)::INT), 2) AS pct_category,
               round(100.0 * avg((transaction_city IS NOT NULL)::INT), 2) AS pct_city
        FROM transactions
        WHERE transaction_type IN ({DISPUTE_TYPES}) AND transaction_status IN ({SETTLED_STATUS})
          AND transaction_date >= TIMESTAMP '{DATASET_CUTOFF}' - INTERVAL {DISPUTE_WINDOW_DAYS} DAY
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Apply the amount policy → `daily_exchange_rates`

    The threshold is set once in USD; a disputed amount above it forces a priority handoff (`control/policy.py`).
    Charges are in ARS, COP and USD, so the threshold needs a per-currency equivalent.

    **4a. Is the rates table consistent with the transactions?** If `amount_usd` equals `amount × rate` for the same day, the table can convert the threshold.
    """)
    return


@app.cell
def _(con, mo):
    mo.sql(
        """
        SELECT t.currency, count(*) AS n,
               round(median(t.amount_usd / (t.amount * r.exchange_rate)), 4) AS median_ratio,
               round(100.0 * avg((abs(t.amount_usd / (t.amount * r.exchange_rate) - 1) < 0.05)::INT), 2) AS pct_within_5pct
        FROM transactions t
        JOIN daily_exchange_rates r
          ON r.date = t.transaction_date::DATE AND r.source_currency = t.currency AND r.target_currency = 'USD'
        WHERE t.amount_usd IS NOT NULL  -- §3: null whenever currency = 'USD'
        GROUP BY 1
        """,
        engine=con,
    )
    return


@app.cell
def _(DATASET_CUTOFF, POLICY_THRESHOLD_USD, con, mo):
    mo.sql(
        f"""
        SELECT target_currency AS currency, date AS rate_date, exchange_rate,
               round({POLICY_THRESHOLD_USD} * exchange_rate) AS threshold_equivalent
        FROM daily_exchange_rates
        WHERE source_currency = 'USD' AND target_currency IN ('ARS', 'COP')
          AND date = (SELECT max(date) FROM daily_exchange_rates WHERE date < DATE '{DATASET_CUTOFF}')
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **4b. Where disputable amounts fall against the threshold.**
    """)
    return


@app.cell
def _(
    DATASET_CUTOFF,
    DISPUTE_TYPES,
    DISPUTE_WINDOW_DAYS,
    POLICY_THRESHOLD_USD,
    SETTLED_STATUS,
    con,
    mo,
):
    mo.sql(
        f"""
        SELECT count(*) AS disputable, round(median(amount_usd), 2) AS median_usd, round(max(amount_usd), 2) AS max_usd,
               round(100.0 * avg((amount_usd > {POLICY_THRESHOLD_USD})::INT), 4) AS pct_over_threshold
        FROM (
            SELECT coalesce(amount_usd, CASE WHEN currency = 'USD' THEN amount END) AS amount_usd  -- §3
            FROM transactions
            WHERE transaction_type IN ({DISPUTE_TYPES}) AND transaction_status IN ({SETTLED_STATUS})
              AND transaction_date >= TIMESTAMP '{DATASET_CUTOFF}' - INTERVAL {DISPUTE_WINDOW_DAYS} DAY
        )
        """,
        engine=con,
    )
    return


@app.cell
def _(
    DATASET_CUTOFF,
    DISPUTE_TYPES,
    DISPUTE_WINDOW_DAYS,
    POLICY_THRESHOLD_USD,
    SETTLED_STATUS,
    alt,
    con,
):
    _amounts = con.sql(f"""
        SELECT coalesce(amount_usd, CASE WHEN currency = 'USD' THEN amount END) AS amount_usd  -- §3
        FROM transactions
        WHERE transaction_type IN ({DISPUTE_TYPES}) AND transaction_status IN ({SETTLED_STATUS})
          AND transaction_date >= TIMESTAMP '{DATASET_CUTOFF}' - INTERVAL {DISPUTE_WINDOW_DAYS} DAY
        USING SAMPLE 5000 ROWS
    """).pl()
    _bars = alt.Chart(_amounts, title="Disputable amount in USD (sample of 5,000 rows)").mark_bar().encode(
        alt.X("amount_usd", bin=alt.Bin(maxbins=40)), y="count()"
    )
    _rule = alt.Chart().mark_rule(color="red").encode(x=alt.datum(POLICY_THRESHOLD_USD))
    _bars + _rule
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. The candidate that looks right → `complaints`

    `complaints` has a *Cargo no reconocido* (unrecognised charge) subcategory, which reads like a dispute log.
    It could serve as history for the disputes queue only if a complaint points to the charge, the card and the conversation.

    **5a. Volume by case type.**
    """)
    return


@app.cell
def _(con, mo):
    mo.sql(
        """
        SELECT category, subcategory, case_type, count(*) AS n
        FROM complaints WHERE category = 'Transactions'
        GROUP BY ALL ORDER BY n DESC
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **5b. Can a complaint be linked to its charge, card and conversation?** There is no transaction column, so the only links are the product, the interaction and the amount.
    """)
    return


@app.cell
def _(con, mo):
    mo.sql(
        """
        SELECT count(*) AS unrecognised_charge_complaints,
               (SELECT count(*) FROM (DESCRIBE complaints) WHERE column_name ILIKE '%transaction%') AS transaction_columns,
               round(100.0 * avg((c.origin_interaction_id IS NULL)::INT), 2) AS pct_no_interaction,
               round(100.0 * avg((c.claimed_amount IS NULL)::INT), 2) AS pct_no_amount,
               round(100.0 * avg((p.customer_id = c.customer_id)::INT), 2) AS pct_product_owned_by_complainant
        FROM complaints c LEFT JOIN products p ON p.product_id = c.affected_product_id
        WHERE c.subcategory = 'Cargo no reconocido'
        """,
        engine=con,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Verdict

    | Table | Decision | Why (evidence above, or characterization §) |
    |---|---|---|
    | `customers` | **Use** | Step 1. Status and mobile phone for the OTP (section 1). Closed customers are dropped at ingest. |
    | `products` | **Use** | Step 2. The two card types, each with an owner in `customers` (section 2). |
    | `transactions` | **Use** | Step 3. Owned by the customer's product (3a); purchases occur only on cards (3b); the rules leave a disputable set in the window (3c) that customers can recognise by merchant (3d). |
    | `daily_exchange_rates` | **Use** | Step 4. Matches `amount_usd` (4a), so it converts the USD threshold to ARS and COP. |
    | `complaints` | **Do not use** | Has the right subcategory (5a) but cannot be linked to a charge, a card or a conversation (5b; §4, §6.5). Only its aggregate volume can serve as a sizing reference. |
    | `call_center_interactions` | Do not use | No dispute contact reason; outcomes do not link to transactions (§6.1, §6.2). |
    | `call_transcripts` | Do not use | 42 template texts, Spanish only, no dispute content (§7). Evaluation uses team-generated utterances. |
    | `service_agents` | Do not use | The `DISPUTES` queue is a back-office department; banking-core seeds no agents from this table. |
    | `satisfaction_surveys`, `digital_events`, `campaign_sends`, `marketing_campaigns`, `branches` | Do not use | No step needs them; `branches` is orphaned from customers (§4). |

    `is_fraud` and `fraud_score` stay out: a dispute is the customer's claim, and neither column links to later complaints or calls (§6.1).

    Consequence of 4b: disputable purchases never exceed the default threshold, so on seeded data the priority-handoff branch
    of the policy is reached only by lowering the threshold or by team-generated scenarios.
    """)
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
