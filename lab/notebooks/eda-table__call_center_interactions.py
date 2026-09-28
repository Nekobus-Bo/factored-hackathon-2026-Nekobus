import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # eda-table · call_center_interactions

    **Question:** What is in `call_center_interactions`, the contact-centre interaction log?

    **Data:** `call_center_interactions` (2025) · **Generated:** 2026-09-28 from `lab/NOTEBOOK_GUIDE.md`
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
    YEAR = "2025"  # fact-table partitions to read; "*" for all years
    return DATA_DIR, YEAR


@app.cell
def _(DATA_DIR, YEAR, duckdb, mo, os):
    mo.stop(
        not os.path.isdir(DATA_DIR),
        mo.md(f"**Dataset not found at `{DATA_DIR}`.** Link it into `data/raw/latam_bank` or set `DATA_DIR`."),
    )
    con = duckdb.connect()
    con.sql(f"""
        CREATE VIEW call_center_interactions AS
        SELECT * FROM read_csv('{DATA_DIR}/call_center_interactions/year={YEAR}/*/*/*.csv', hive_partitioning = true)
    """)
    return (con,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats** (from `lab/dataset-characterization.md`)

    - The full table has 686k rows, 85.8% of what the dictionary states. The gap is lower daily volume, not missing days (§2.2).
    - No duplicate keys, no late arrivals and one schema across every file. Nulls are injected at fixed round rates per column (§2.4).
    - `interaction_date` runs up to 6–8 hours past its `process_date` partition day, consistent with UTC timestamps partitioned by local date (§2.4).
    - `reason_category` duplicates `contact_reason` (§5).
    - `detected_sentiment` is a fixed binning of `sentiment_score`: leaky as a pair (§5, §9).
    - Demand is flat by hour of day. It varies by day of week (Sunday lowest, Tuesday–Friday highest), with no monthly trend or seasonality (§6.4).
    - Outcomes differ by contact reason, but not by agent experience, agent type, specialty, accent match, segment, country, channel or hour. `was_escalated` shows no signal (AUC 0.50). `wait_time_seconds` is about 120 s for every reason (§6.2).
    - `agent_used_accent` matches the customer's accent in 81% of interactions and has no effect on any outcome (§7).
    """)
    return


@app.cell
def _(con, mo):
    mo.sql("SELECT count(*) AS n_rows FROM call_center_interactions", engine=con)
    return


@app.cell
def _(con, mo):
    profile = mo.sql(
        f"""
        SUMMARIZE call_center_interactions
        """,
        engine=con
    )
    return (profile,)


@app.cell
def _(mo, profile):
    column = mo.ui.dropdown(profile["column_name"].to_list(), value="contact_reason", label="Column")
    column
    return (column,)


@app.cell
def _(column, con, mo):
    mo.sql(
        f"""
        SELECT {column.value} AS value, count(*) AS n, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
        FROM call_center_interactions GROUP BY 1 ORDER BY n DESC LIMIT 20
        """,
        engine=con,
    )
    return


@app.cell
def _(alt, con):
    _sample = con.sql("SELECT duration_seconds FROM call_center_interactions USING SAMPLE 5000 ROWS").pl()
    alt.Chart(_sample, title="duration_seconds (sample of 5,000 rows)").mark_bar().encode(
        alt.X("duration_seconds", bin=alt.Bin(maxbins=40)), y="count()"
    )
    return


@app.cell
def _(alt, con):
    _daily = con.sql("SELECT process_date AS day, count(*) AS n FROM call_center_interactions GROUP BY 1 ORDER BY 1").pl()
    alt.Chart(_daily, title="Rows per day").mark_line().encode(x="day:T", y="n:Q")
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
