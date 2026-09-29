import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # reranker-zero-shot · intents

    **Question:** How well does a multilingual reranker classify customer messages into the 15-intent taxonomy with no training, by scoring each message against every intent description?

    **Data:** `data/eval/synthetic/decision.test.provisional.jsonl` (es/pt/en) · **Taxonomy:** `data/eval/synthetic/schema.yaml` · **Model:** [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) on CPU · **Generated:** 2026-09-28, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type is not in its menu yet)
    """)
    return


@app.cell
def _():
    import time

    import marimo as mo
    import numpy as np
    import polars as pl
    import torch
    import yaml

    return mo, np, pl, time, torch, yaml


@app.cell
def _(mo):
    # Settings: change these, the rest of the notebook follows
    RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
    SCHEMA_PATH = mo.notebook_dir().parents[1] / "data" / "eval" / "synthetic" / "schema.yaml"
    INPUT_PATH = mo.notebook_dir().parents[1] / "data" / "eval" / "synthetic" / "decision.test.provisional.jsonl"
    MAX_ROWS = None  # None scores every row; set e.g. 50 for a quick run
    MAX_LENGTH = 128  # tokens per (message, description) pair; messages are short
    return INPUT_PATH, MAX_LENGTH, MAX_ROWS, RERANKER_MODEL, SCHEMA_PATH


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - The provisional test set is free-form, **AI-written** text. The human-written `decision.test.jsonl` is pending, so these numbers are provisional (`data/eval/synthetic/README.md`).
    - Reference points on the same file: TF-IDF + LR at macro-F1 0.79–0.84 and GLiNER2.5 zero-shot at 0.43–0.52 (`reports/calibration-decision-2026-09-28.md`); Laya multilingual zero-shot at 0.495 (`laya-zero-shot__intents.py`).
    - The reranker was trained for query–passage relevance, not classification. `confidence` is a softmax over the 15 relevance scores, which the model was never trained to produce, so it is not a threshold τ (ADR-0010).
    - Every message costs 15 pair scores, one per intent. Latency is measured one message at a time on this machine's CPU, not in the Linux container ADR-0010 requires.
    """)
    return


@app.cell
def _(SCHEMA_PATH, mo, pl, yaml):
    # The 15 intents and their descriptions are the passages each message is scored against
    CRITERIA = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    mo.ui.table(pl.DataFrame({"intent": list(CRITERIA), "description": list(CRITERIA.values())}))
    return (CRITERIA,)


@app.cell
def _(INPUT_PATH, MAX_ROWS, pl):
    rows = pl.read_ndjson(INPUT_PATH).select("id", "lang", "text", "intent")
    if MAX_ROWS:
        rows = rows.sample(MAX_ROWS, seed=0)
    rows.group_by("lang").len().sort("lang")
    return (rows,)


@app.cell
def _(RERANKER_MODEL):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL).eval()
    f"{RERANKER_MODEL}: {sum(p.numel() for p in model.parameters()) / 1e6:.0f}M parameters on CPU"
    return model, tokenizer


@app.cell
def _(CRITERIA, MAX_LENGTH, model, pl, rows, time, tokenizer, torch):
    # One forward pass per message: the message is the query, each intent description a passage
    _intents, _descriptions = list(CRITERIA), list(CRITERIA.values())
    _predicted, _confidence, _latency_ms = [], [], []
    for _text in rows["text"]:
        _start = time.perf_counter()
        _inputs = tokenizer([_text] * len(_descriptions), _descriptions, padding=True, truncation=True,
                            max_length=MAX_LENGTH, return_tensors="pt")
        with torch.no_grad():
            _probs = torch.softmax(model(**_inputs).logits.view(-1), dim=0)
        _latency_ms.append(1000 * (time.perf_counter() - _start))
        _predicted.append(_intents[int(_probs.argmax())])
        _confidence.append(round(float(_probs.max()), 4))
    results = rows.with_columns(
        predicted=pl.Series(_predicted), confidence=pl.Series(_confidence), latency_ms=pl.Series(_latency_ms)
    )
    results
    return (results,)


@app.cell
def _(np, pl, results):
    from sklearn.metrics import f1_score

    _groups = [("all", results)] + [(g, d) for (g,), d in results.group_by("lang", maintain_order=True)]
    pl.DataFrame([
        {"lang": _name, "rows": _d.height,
         "macro_f1": round(f1_score(_d["intent"], _d["predicted"], average="macro"), 3),
         "accuracy": round((_d["intent"] == _d["predicted"]).mean(), 3),
         "mean_confidence": round(_d["confidence"].mean(), 3),
         "p95_latency_ms": round(float(np.percentile(_d["latency_ms"], 95)), 1)}
        for _name, _d in _groups
    ])
    return


@app.cell
def _(CRITERIA, pl, results):
    # Per-class precision is the constraint behind τ (ADR-0010)
    from sklearn.metrics import precision_recall_fscore_support

    _p, _r, _f, _n = precision_recall_fscore_support(
        results["intent"], results["predicted"], labels=list(CRITERIA), zero_division=0
    )
    pl.DataFrame({"intent": list(CRITERIA), "precision": _p, "recall": _r, "f1": _f, "support": _n}).with_columns(
        pl.col("precision", "recall", "f1").round(3)
    ).sort("precision")
    return


@app.cell
def _(mo, pl, results):
    # Errors, most confident first: where a threshold would not have saved us
    mo.ui.table(
        results.filter(pl.col("intent") != pl.col("predicted"))
        .select("lang", "text", "intent", "predicted", "confidence")
        .sort("confidence", descending=True)
    )
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
