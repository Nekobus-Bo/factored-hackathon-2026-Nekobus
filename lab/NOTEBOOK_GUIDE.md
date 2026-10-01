# Starter notebooks: generation guide

Rules for generating **starter marimo notebooks** for exploring the LATAM Bank dataset. It is written for an AI agent to follow and for an engineer to steer.

- **Engineer:** picks a notebook type and a subject from the [menu](#3-menu) and asks for a notebook.
- **Agent:** reads this guide and [`dataset-characterization.md`](dataset-characterization.md), then writes one notebook that follows the rules below.

A starter notebook is where an experiment **begins**, not where it ends. It loads the data, shows what is there, sets up the minimum for the stated question, and stops.

---

## 1. How to ask for a notebook

```
Following lab/NOTEBOOK_GUIDE.md and the dataset characterization,
generate a <type> notebook for <subject>.
[Optional: year = 2024 · target = ... · features = ... · question = "..."]
```

Examples:

- `eda-table` for `complaints`
- `ml-target` for `was_resolved`, year 2025, question "which interaction attributes relate to first-contact resolution?"
- `join` for `call_transcripts` ↔ `call_center_interactions`
- `text-classifier` on BANKING77 card-related intents
- `llm-zero-shot`: classify BANKING77 texts into our 5 card intents
- `llm-synthetic`: 10 Spanish and 10 Portuguese messages per card intent

If the request leaves out something the type needs (target, key, labels), the agent picks the obvious default from the menu and states it in the header cell. It does not invent a research question.

---

## 2. Principles

1. **One question per notebook.** The header states it in one sentence.
2. **Minimal.** Only the cells listed for the type in §4. No extra analyses, "insights" or conclusions.
3. **Readable first.** Plain SQL and short Python. A person should understand every cell in under a minute.
4. **Self-contained.** No imports from the repository. Each notebook repeats its own few setup lines.
5. **Not opinionated.** Neutral defaults, no conclusions. The one exception is facts already measured in the characterization, which go in the caveats cell as facts.
6. **Everything tunable in one place.** Paths, year, target, cutoff, model names and row caps live in the settings cell.
7. **Stop early.** The last cell is `# next:`, left empty for the engineer.

---

## 3. Menu

Everything below comes from the characterization. Section references (§) point to it.

### 3.1 Tables

| Table | Rows | Grain | Time column | Files |
|---|---:|---|---|---|
| `customers` | 150k | customer | `registration_date` | single CSV |
| `products` | 400k | product (account, card, loan) | `opening_date` | single CSV |
| `branches` | 350 | branch | — | single CSV |
| `service_agents` | 1.2k | agent | `hire_date` | single CSV |
| `marketing_campaigns` | 200 | campaign | `start_date` | single CSV |
| `daily_exchange_rates` | 13k | date × currency pair | `date` | single CSV |
| `transactions` | 4.4M | transaction | `transaction_date` | daily partitions |
| `call_center_interactions` | 686k | interaction | `interaction_date` | daily partitions |
| `call_transcripts` | 171k | transcript (1:1 interaction) | via interaction | daily partitions |
| `satisfaction_surveys` | 213k | survey | `survey_date` | daily partitions |
| `digital_events` | 15.6M | event | `event_date` | daily partitions |
| `complaints` | 67k | complaint | `creation_date` | daily partitions |
| `campaign_sends` | 1.7M | send | `send_date` | daily partitions |

### 3.2 Targets

Measured signal is stated so the engineer knows what to expect, not to steer the choice.

| Target | Table | Type | Measured signal (§6) |
|---|---|---|---|
| `was_resolved` | call_center_interactions | binary, 76.7% | AUC 0.77 |
| `requires_followup` | call_center_interactions | binary, 34.8% | AUC 0.68 |
| `was_escalated` | call_center_interactions | binary, 10.0% | AUC 0.50 |
| `duration_seconds` | call_center_interactions | numeric | R² 0.47 |
| `main_score` (CSAT rows) | satisfaction_surveys | numeric 1–4 | R² 0.37 |
| `is_fraud` | transactions | binary, 0.1% | AUC 0.51 without `fraud_score` |
| `sla_breached` | complaints | binary, 20% | AUC 0.50 |
| `days_past_due >= 30` | products (credit) | binary, 12.4% | AUC 0.50 |
| `had_conversion` | campaign_sends | binary, 0.56% | AUC 0.65 |

### 3.3 Joins that hold (§4)

| Left → right | Key | Notes |
|---|---|---|
| transactions → products → customers | `product_id`, `customer_id` | 100% consistent ownership |
| call_transcripts → call_center_interactions | `interaction_id` | 1:1; `main_topics` is a copy of `contact_reason` |
| satisfaction_surveys → call_center_interactions | `interaction_id` | survey always after the interaction |
| call_center_interactions → service_agents | `agent_id` | 0% orphans |
| complaints → customers | `customer_id` | ⚠ `affected_product_id` is never owned by that customer |
| digital_events → customers | `customer_id` | 24% null `customer_id` |
| campaign_sends → marketing_campaigns | `campaign_id` | — |
| customers → branches | `registration_branch_id` | ⚠ 100% orphaned |

### 3.4 Text sources

| Source | Size | Use | Caveat |
|---|---|---|---|
| `call_transcripts.customer_text` | 42 distinct texts | Only to confirm it carries no signal | Templates; each text appears under all 6 reasons (§7) |
| `satisfaction_surveys.open_comments` | 15 distinct | Same | Tied to score |
| BANKING77 (`mteb/banking77` on Hugging Face) | 9,993 train / 3,076 test, 77 intents, English | Text classification, zero-shot | External, CC BY 4.0; organizer approval pending. `PolyAI/banking77` no longer loads with current `datasets`. |
| Team or LLM-generated utterances | — | Spanish/Portuguese evaluation and training sets | Marked team-generated; needs human review |

---

## 4. Notebook types

Each type is the **shared skeleton (§5) plus the cells listed here, in this order**. Code for each cell is in §8.

| Type | Question it starts | Type-specific cells |
|---|---|---|
| `eda-table` | What is in table X? | size and schema · column profile · top values for a picked column · distribution of a numeric column · volume over time (fact tables only) |
| `ml-target` | Does target Y relate to these features? | target distribution · feature list · load and time split · one baseline model · one metric |
| `join` | How do tables A and B relate through key K? | key coverage · rows per key · joined sample · one crosstab across the join |
| `text-classifier` | How well can texts be classified into labels? | load texts and labels · split · TF-IDF baseline · embedding classifier · macro-F1 for both |
| `llm-zero-shot` | Can an LLM label or extract this? | cached call function · input rows · prompt · run over a capped sample · agreement with labels · token usage |
| `llm-synthetic` | Generate labelled utterances from a spec | cached call function · spec · prompt · generate · provenance columns · save · sample view |

**Every type must not:**

- read more than the tables it needs;
- tune hyperparameters, compare several models (except the two in `text-classifier`), or add feature engineering beyond what the question needs;
- write anywhere other than the paths in §6.4;
- print conclusions.

---

## 5. Shared skeleton

Every notebook has these cells first, in this order:

1. **Header** (markdown, code hidden): type · subject, the question, data used, generation date, "generated from `lab/NOTEBOOK_GUIDE.md`".
2. **Imports:** only what the notebook uses.
3. **Settings:** `DATA_DIR`, `YEAR`, and type-specific settings (target, cutoff, key, model, row cap).
4. **Connection and views:** stops with a clear message if the data folder is missing, then creates DuckDB views over the raw CSVs for the tables used and nothing else.
5. **Caveats** (markdown, code hidden): the characterization facts that apply to these tables and columns, each with its § reference. If none apply, say "No known caveats for these columns."

After the type-specific cells, the notebook ends with the `# next:` cell.

Notebooks on external data only (`text-classifier`, the LLM types) drop `DATA_DIR`, `YEAR` and the connection cell.

---

## 6. Rules

### 6.1 Code style

- **Stack:** DuckDB SQL for reading and aggregating, Polars for frames, Altair for charts, scikit-learn for models. Nothing else unless the type needs it (§7).
- **SQL does the work.** Filtering, joining, aggregating and casting happen in SQL. Python only for splitting, models and charts.
- **No classes. No functions**, except the cached call in LLM notebooks and a parse helper next to it.
- **Short cells:** about 15 lines at most. One purpose per cell.
- **Comments** only where a line isn't self-explanatory, or to cite the characterization (`# §3: amount_usd is null when currency = 'USD'`).
- **Names** in plain English (`train`, `test`, `features`, `interactions`). Constants that the engineer is meant to change are UPPER_CASE.
- **`try/except` only** for the LLM JSON parse.
- **English** for code, comments and markdown (AGENTS.md).

### 6.2 marimo rules

- Every global name is defined in exactly one cell. Names used only inside a cell start with `_` (e.g. `_chart`, `_df`).
- A cell displays its **last expression**. Wrap tables in `mo.ui.table(df)` or let `mo.sql(...)` display them.
- Declare every name another cell uses in the cell's `return`. The agent writes these by hand, matching what marimo would generate.
- Use `mo.stop(condition, mo.md("..."))` to halt on missing inputs. Never use `sys.exit` or `raise`. `mo.stop` halts only the cells that **depend on the cell that calls it**. So put it inside the cell that defines what the rest uses (the connection `con`, the `ask` function), never in a cell of its own.
- At most **two UI elements** (e.g. one dropdown to pick a column). Read `.value` in a *different* cell from the one that defines the element.
- Markdown cells use `@app.cell(hide_code=True)` and `mo.md(r"""` … `""")`, with the text at the cell's own indentation, as in §8.1. Other layouts trigger a `marimo check` warning.
- To show a table and a chart from one cell, end with `mo.hstack([table, chart])`.

### 6.3 Data rules (raw CSV)

- **Paths:** `DATA_DIR` from the environment, else `<repo>/data/raw/factored`, resolved from `mo.notebook_dir()`.
- **Fact tables:** read one year by default, using the partition path, so only those files are opened:
  `read_csv('{DATA_DIR}/transactions/year={YEAR}/*/*/*.csv', hive_partitioning = true)`. `YEAR = "*"` reads everything.
- **Dimension tables:** `read_csv('{DATA_DIR}/customers.csv')`.
- **Never use `union_by_name = true`.** It reads every file header on every query (10 s vs. 0.4 s), and every table has a single schema (§2.4).
- Partition columns: `year` is a number; `month` and `day` are **text** (`month = '01'`).
- **Cast booleans to INT in SQL** (`was_resolved::INT`) before they reach scikit-learn.
- **Handle known defects inline, only when the cell touches that column**, with a § comment:
  - `coalesce(amount_usd, CASE WHEN currency = 'USD' THEN amount END)` (§3)
  - `replace(transaction_country, 'Mexico', 'México')` (§3)
- **Leaky columns stay out of features by default**, listed in the caveats cell: `fraud_score` for `is_fraud`; `sentiment_score` ↔ `detected_sentiment`; `main_score` ↔ `nps_category`; `open_comments` ↔ `main_score`; `main_topics` = `contact_reason`; `resolution_days` = the date difference (§9).
- **Split by time:** one cutoff date in the settings cell. Mark train rows in SQL (`interaction_date < DATE '{CUTOFF}' AS is_train`).
- **Charts:** aggregate in SQL first. For raw-value charts, use `USING SAMPLE 5000 ROWS` (Altair's default row limit) and say so in the chart title.

### 6.4 Where notebooks read and write

| What | Path | Versioned |
|---|---|---|
| Notebooks | `lab/notebooks/<type>__<subject>.py` (e.g. `ml-target__was_resolved.py`, `join__call_transcripts-call_center_interactions.py`) | yes |
| Raw data (read only) | `data/raw/factored/` | no |
| LLM response cache | `lab/.cache/llm/` | no |
| Synthetic outputs | `data/staging/lab/<name>.parquet` | no |

Nothing else is written to disk.

### 6.5 AI and LLM rules

- **Model access:** LiteLLM (`litellm.completion`), with `LLM_MODEL`, `LLM_API_KEY` and `LLM_BASE_URL` from the environment, the same names as `.env.example`. `LLM_MODEL` uses LiteLLM's `provider/model` format (e.g. `anthropic/claude-haiku-4-5`, an economy-tier model per ADR-0001). If `LLM_MODEL` is unset, the notebook stops with a message; it never guesses a model.
- **Cache every call** on disk, keyed by model + prompt. Reruns cost nothing and give identical outputs; that, not temperature, is the reproducibility mechanism. Do not send `temperature` or other sampling parameters: several current models reject them.
- **Cap rows:** `MAX_ROWS = 20` by default in the settings cell. Print the tokens used.
- **No personal data leaves the machine** (AGENTS.md rule 5). Never send `first_name`, `last_name`, `document_number`, `email`, `mobile_phone`, `landline_phone`, `address`, `postal_code`, `date_of_birth` or `ip_address`, nor `customer_id` or other IDs. Send only the text or attributes the question needs.
- **JSON output:** ask for a JSON object in the prompt, parse with `json.loads`, and keep the raw text when parsing fails. No provider-specific structured-output features, so the notebook stays provider-neutral.
- **Prompts** live in their own cell as a plain string, with a `PROMPT_VERSION` setting.
- **Synthetic outputs** carry provenance columns (`source = 'llm-synthetic'`, `model`, `prompt_version`, `generated_at`), and the header states that they need human review before any use in evaluation.
- **Embeddings:** `sentence-transformers` on CPU, model name from `EMBEDDING_MODEL` (default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, multilingual, ~470 MB). marimo re-runs the encoding cell only when its inputs change, so no extra caching is needed.
- **External data** (BANKING77 and others) is used only in `text-classifier`, `llm-zero-shot` and `llm-synthetic`. The header says "external, pending organizer approval".

---

## 7. Dependencies

The `lab/` project already has `duckdb`, `polars`, `pyarrow`, `altair`, `marimo` and `scikit-learn`. The AI types need extras, added once when the first notebook of that type is generated:

| Type | Add with |
|---|---|
| `text-classifier` | `cd lab && uv add datasets sentence-transformers ipython` (pulls PyTorch, CPU). `ipython` is required: once marimo is loaded, `transformers` assumes a notebook and imports it. |
| `llm-zero-shot`, `llm-synthetic` | `cd lab && uv add litellm` (plus `datasets` if the input is BANKING77) |

The agent tells the engineer which command it ran.

---

## 8. Code

The blocks below are exact enough to copy. Values in angle brackets are filled per notebook. Each `@app.cell` shows its `return`, because marimo needs it.

### 8.1 Skeleton

```python
import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # <type> · <subject>

    **Question:** <one sentence>

    **Data:** `<table>` (<year or all years>) · **Generated:** <YYYY-MM-DD> from `lab/NOTEBOOK_GUIDE.md`
    """)
    return


@app.cell
def _():
    import os

    import altair as alt
    import duckdb
    import marimo as mo
    import polars as pl
    return alt, duckdb, mo, os, pl


@app.cell
def _(mo, os):
    # Settings: change these, the rest of the notebook follows
    DATA_DIR = os.environ.get("DATA_DIR", str(mo.notebook_dir().parents[1] / "data" / "raw" / "factored"))
    YEAR = "2025"  # fact-table partitions to read; "*" for all years
    return DATA_DIR, YEAR


@app.cell
def _(DATA_DIR, YEAR, duckdb, mo, os):
    mo.stop(
        not os.path.isdir(DATA_DIR),
        mo.md(f"**Dataset not found at `{DATA_DIR}`.** Copy it to `data/raw/factored` or set `DATA_DIR`."),
    )
    con = duckdb.connect()
    con.sql(f"""
        CREATE VIEW <fact_table> AS
        SELECT * FROM read_csv('{DATA_DIR}/<fact_table>/year={YEAR}/*/*/*.csv', hive_partitioning = true)
    """)
    con.sql(f"CREATE VIEW <dimension_table> AS SELECT * FROM read_csv('{DATA_DIR}/<dimension_table>.csv')")
    return (con,)
# Several fact tables: loop over their names with a `_table` variable instead of repeating the statement.


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats** (from `lab/dataset-characterization.md`)

    - <fact> (§n)
    """)
    return


# ... type-specific cells ...


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
```

### 8.2 `eda-table`

```python
@app.cell
def _(con, mo):
    mo.sql("SELECT count(*) AS n_rows FROM <table>", engine=con)
    return


@app.cell
def _(con, mo):
    profile = mo.sql("SUMMARIZE <table>", engine=con)
    return (profile,)


@app.cell
def _(mo, profile):
    column = mo.ui.dropdown(profile["column_name"].to_list(), value="<a categorical column>", label="Column")
    column
    return (column,)


@app.cell
def _(column, con, mo):
    mo.sql(
        f"""
        SELECT {column.value} AS value, count(*) AS n, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
        FROM <table> GROUP BY 1 ORDER BY n DESC LIMIT 20
        """,
        engine=con,
    )
    return


@app.cell
def _(alt, con):
    _sample = con.sql("SELECT <numeric column> FROM <table> USING SAMPLE 5000 ROWS").pl()
    alt.Chart(_sample, title="<numeric column> (sample of 5,000 rows)").mark_bar().encode(
        alt.X("<numeric column>", bin=alt.Bin(maxbins=40)), y="count()"
    )
    return


@app.cell
def _(alt, con):
    # Fact tables only
    _daily = con.sql("SELECT process_date AS day, count(*) AS n FROM <table> GROUP BY 1 ORDER BY 1").pl()
    alt.Chart(_daily, title="Rows per day").mark_line().encode(x="day:T", y="n:Q")
    return
```

### 8.3 `ml-target`

Settings cell additions:

```python
    TARGET = "<target>"
    TIME_COLUMN = "<time column>"
    CUTOFF = "2025-07-01"  # train before, test from
    FEATURES = ["<feature>", "<feature>"]  # no leaky columns, see caveats
```

Cells:

```python
@app.cell
def _(TARGET, alt, con, mo):
    _counts = mo.sql(f"SELECT {TARGET} AS target, count(*) AS n FROM <table> GROUP BY 1 ORDER BY 1", engine=con, output=False)
    mo.hstack([_counts, alt.Chart(_counts, title=TARGET).mark_bar().encode(x="target:N", y="n:Q")])
    return


@app.cell
def _(CUTOFF, FEATURES, TARGET, TIME_COLUMN, con):
    # Booleans cast to INT here, before they reach scikit-learn
    data = con.sql(f"""
        SELECT {TARGET}::INT AS y, {TIME_COLUMN} < DATE '{CUTOFF}' AS is_train, {", ".join(FEATURES)}
        FROM <table>
    """).pl()
    train, test = data.filter(data["is_train"]), data.filter(~data["is_train"])
    {"train": train.height, "test": test.height, "test base rate": round(test["y"].mean(), 4)}
    return test, train


@app.cell
def _(FEATURES, pl, test, train):
    from sklearn.compose import make_column_transformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    categorical = [c for c in FEATURES if train.schema[c] == pl.String]
    numeric = [c for c in FEATURES if c not in categorical]
    X_train, X_test = (d.select(FEATURES).with_columns(pl.col(pl.String).fill_null("missing")).to_pandas() for d in (train, test))

    model = make_pipeline(
        make_column_transformer(
            (OneHotEncoder(handle_unknown="ignore"), categorical),
            (make_pipeline(SimpleImputer(), StandardScaler()), numeric),
        ),
        LogisticRegression(max_iter=1000),
    )
    model.fit(X_train, train["y"])
    f"ROC-AUC on test: {roc_auc_score(test['y'], model.predict_proba(X_test)[:, 1]):.3f}"
    return
```

For a numeric target, drop the `::INT` cast, use `Ridge()` instead of `LogisticRegression`, and report `r2_score(test["y"], model.predict(X_test))`.

### 8.4 `join`

Settings cell additions:

```python
    LEFT, RIGHT, KEY = "<left table>", "<right table>", "<key>"
    LEFT_COLUMN, RIGHT_COLUMN = "<column in left>", "<column in right>"  # for the crosstab
```

Cells:

```python
@app.cell
def _(KEY, LEFT, RIGHT, con, mo):
    mo.sql(
        f"""
        SELECT
            (SELECT count(*) FROM {LEFT}) AS left_rows,
            (SELECT round(100.0 * avg((r.{KEY} IS NOT NULL)::INT), 2)
               FROM {LEFT} l LEFT JOIN (SELECT DISTINCT {KEY} FROM {RIGHT}) r USING ({KEY})) AS pct_left_matched,
            (SELECT round(100.0 * avg((l.{KEY} IS NOT NULL)::INT), 2)
               FROM (SELECT DISTINCT {KEY} FROM {RIGHT}) r LEFT JOIN (SELECT DISTINCT {KEY} FROM {LEFT}) l USING ({KEY})) AS pct_right_with_left_rows
        """,
        engine=con,
    )
    return


@app.cell
def _(KEY, LEFT, con, mo):
    mo.sql(
        f"""
        SELECT rows_per_key, count(*) AS n_keys
        FROM (SELECT {KEY}, count(*) AS rows_per_key FROM {LEFT} GROUP BY 1) GROUP BY 1 ORDER BY 1
        """,
        engine=con,
    )
    return


@app.cell
def _(KEY, LEFT, RIGHT, con, mo):
    mo.ui.table(con.sql(f"SELECT * FROM {LEFT} JOIN {RIGHT} USING ({KEY}) LIMIT 100").pl())
    return


@app.cell
def _(KEY, LEFT, LEFT_COLUMN, RIGHT, RIGHT_COLUMN, con, mo):
    mo.sql(
        f"""
        SELECT l.{LEFT_COLUMN}, r.{RIGHT_COLUMN}, count(*) AS n
        FROM {LEFT} l JOIN {RIGHT} r USING ({KEY}) GROUP BY ALL ORDER BY n DESC LIMIT 30
        """,
        engine=con,
    )
    return
```

When both tables have a column with the same name (e.g. `customer_id`), the joined sample keeps one copy; select explicit columns if the difference matters.

### 8.5 `text-classifier`

Settings cell (replaces `DATA_DIR`/`YEAR` when the source is external; the connection cell is then dropped):

```python
    DATASET = "mteb/banking77"  # external, pending organizer approval
    LABELS = []  # empty keeps all labels; e.g. ["lost_or_stolen_card", "compromised_card"]
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
```

Cells:

```python
@app.cell
def _(DATASET, LABELS, pl):
    from datasets import load_dataset

    _ds = load_dataset(DATASET)
    train, test = (
        d.to_polars().filter(pl.col("label_text").is_in(LABELS) if LABELS else pl.lit(True))
        for d in (_ds["train"], _ds["test"])
    )
    {"train": train.height, "test": test.height, "labels": train["label_text"].n_unique()}
    return test, train


@app.cell
def _(test, train):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.pipeline import make_pipeline

    tfidf = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2), LogisticRegression(max_iter=1000))
    tfidf.fit(train["text"], train["label_text"])
    f"TF-IDF baseline macro-F1: {f1_score(test['label_text'], tfidf.predict(test['text']), average='macro'):.3f}"
    return LogisticRegression, f1_score


@app.cell
def _(EMBEDDING_MODEL, LogisticRegression, f1_score, test, train):
    from sentence_transformers import SentenceTransformer

    _encoder = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    emb_train = _encoder.encode(train["text"].to_list(), batch_size=64, normalize_embeddings=True)
    emb_test = _encoder.encode(test["text"].to_list(), batch_size=64, normalize_embeddings=True)
    _clf = LogisticRegression(max_iter=1000).fit(emb_train, train["label_text"])
    f"Embedding classifier macro-F1: {f1_score(test['label_text'], _clf.predict(emb_test), average='macro'):.3f}"
    return
```

For supplied text instead (e.g. `call_transcripts.customer_text` against `main_topics`), keep the skeleton's data cells, load `text` and `label` columns with SQL, and split by time as in §8.3.

### 8.6 `llm-zero-shot`

Settings cell additions:

```python
    LLM_MODEL = os.environ.get("LLM_MODEL")  # LiteLLM format, e.g. "anthropic/claude-haiku-4-5"
    MAX_ROWS = 20
    PROMPT_VERSION = "v1"
    CACHE_DIR = mo.notebook_dir().parent / ".cache" / "llm"
```

Cells:

```python
@app.cell
def _(CACHE_DIR, LLM_MODEL, mo, os):
    mo.stop(not LLM_MODEL, mo.md("**Set `LLM_MODEL`** (and `LLM_API_KEY`) in the environment to run this notebook."))

    import hashlib
    import json

    import litellm

    def ask(prompt: str) -> dict:
        """One cached LLM call. Returns the stored record: model, prompt, text, tokens."""
        key = hashlib.sha256(f"{LLM_MODEL}\n{prompt}".encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        response = litellm.completion(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL") or None,
        )
        record = {"model": LLM_MODEL, "prompt": prompt, "text": response.choices[0].message.content,
                  "tokens": response.usage.prompt_tokens + response.usage.completion_tokens}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False))
        return record

    def parse(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    return ask, parse


@app.cell
def _(MAX_ROWS, pl):
    # Input rows: only the text or attributes the question needs, never personal data (guide §6.5)
    from datasets import load_dataset

    rows = load_dataset("mteb/banking77")["test"].to_polars().sample(MAX_ROWS, seed=0).select("text", "label_text")
    rows
    return (rows,)


@app.cell
def _():
    PROMPT = """Classify this bank customer message into one of these intents: <intent list>.
Reply with only a JSON object: {{"intent": "<one of the intents>"}}

Message: {text}"""
    return (PROMPT,)


@app.cell
def _(PROMPT, ask, parse, pl, rows):
    _records = [ask(PROMPT.format(text=t)) for t in rows["text"]]
    results = rows.with_columns(
        predicted=pl.Series([parse(r["text"]).get("intent") for r in _records]),
        tokens=pl.Series([r["tokens"] for r in _records]),
    )
    results
    return (results,)


@app.cell
def _(results):
    {"agreement": round((results["predicted"] == results["label_text"]).mean(), 3),
     "unparsed": results["predicted"].null_count(), "tokens": results["tokens"].sum()}
    return
```

Double the braces in the prompt (`{{ }}`) wherever a literal `{` must survive `.format`. Cached calls report the tokens from their first run.

### 8.7 `llm-synthetic`

Settings cell additions: as in §8.6, plus

```python
    NAME = "<set name>"  # output file: data/staging/lab/<NAME>.parquet
    N_PER_CELL = 10
    LANGUAGES = ["es", "pt"]
    OUTPUT = mo.notebook_dir().parents[1] / "data" / "staging" / "lab" / f"{NAME}.parquet"
```

Cells (plus the `ask`/`parse` cell from §8.6):

```python
@app.cell
def _():
    SPEC = {
        "<label>": "<one-line description of what the customer means>",
    }
    return (SPEC,)


@app.cell
def _():
    PROMPT = """Write {n} different messages a bank customer could type in a chat, in {language},
all meaning: {description}. Vary tone, length and wording. Do not include names, IDs or numbers that identify a person.
Reply with only a JSON object: {{"messages": ["...", "..."]}}"""
    return (PROMPT,)


@app.cell
def _(LANGUAGES, LLM_MODEL, N_PER_CELL, PROMPT, PROMPT_VERSION, SPEC, ask, parse, pl):
    from datetime import datetime, timezone

    _rows = []
    for _label, _description in SPEC.items():
        for _language in LANGUAGES:
            _record = ask(PROMPT.format(n=N_PER_CELL, language=_language, description=_description))
            _rows += [{"text": m, "label": _label, "language": _language}
                      for m in parse(_record["text"]).get("messages", [])]
    synthetic = pl.DataFrame(_rows).unique(["text", "label", "language"], maintain_order=True).with_columns(
        source=pl.lit("llm-synthetic"), model=pl.lit(LLM_MODEL), prompt_version=pl.lit(PROMPT_VERSION),
        generated_at=pl.lit(datetime.now(timezone.utc).isoformat()),
    )
    synthetic
    return (synthetic,)


@app.cell
def _(OUTPUT, synthetic):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    synthetic.write_parquet(OUTPUT)
    f"Wrote {synthetic.height} rows to {OUTPUT}. Team-generated: review before using in evaluation."
    return
```

---

## 9. Checks before handing back

The agent runs these and reports the results:

1. `cd lab && uv run marimo check notebooks/<file>.py` passes. The only expected warning is `empty-cells` for the `# next:` cell.
2. `cd lab && uv run marimo export html notebooks/<file>.py -o /tmp/<file>.html` exits 0. It exits 1 if any cell raised, so read the error and fix it. With missing data or no `LLM_MODEL`, the stop message renders and the export still exits 0; check that case too.
3. Every cell in §4 for the type is present, in order, and nothing else.
4. The settings cell holds every tunable value; no literal year, target or model name appears elsewhere.
5. The caveats cell lists every characterization fact that touches the columns used.
6. LLM notebooks: no personal-data column is selected into `rows`, and every call goes through `ask`.
7. Files written only to the paths in §6.4.
