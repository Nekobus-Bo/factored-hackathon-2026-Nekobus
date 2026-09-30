import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # compare · decision-es

    **Question:** On Mexican and Argentine Spanish, how do Laya (zero-shot), the bge reranker (zero-shot) and the multilingual DistilBERT fine-tuned on one country's grounded dataset compare, and how much does a fine-tune lose on the other country's Spanish?

    **Evaluation sets:** `data/staging/decision_es_{mx,ar}/decision.es_{mx,ar}.test.provisional.jsonl` (750 rows each, 15 intents) and 150 real app reviews per country, `data/staging/complaints/complaints_{mx,ar}_sample_150.parquet`, scored against their `.labels.parquet` · **Training sets:** `decision.es_{mx,ar}.{train,validation}.jsonl` (1,500 and 750 rows each) · **Generated:** 2026-09-30, following the style rules in `lab/NOTEBOOK_GUIDE.md`, modelled on `compare__decision-pt.py`. Step 7 of the plan for the regional Spanish datasets.
    """)
    return


@app.cell
def _():
    import time

    import laya
    import marimo as mo
    import numpy as np
    import polars as pl
    import torch
    import yaml

    return laya, mo, np, pl, time, torch, yaml


@app.cell
def _(mo, torch):
    # Settings: change these, the rest of the notebook follows
    REPO = mo.notebook_dir().parents[1]
    SCHEMA_PATH = REPO / "data" / "eval" / "synthetic" / "schema.yaml"
    STAGING = REPO / "data" / "staging"
    COUNTRIES = {"MX": "es_mx", "AR": "es_ar"}
    LAYA_MODEL = "convaiinnovations/laya-multilingual"
    RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
    BASE_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    LAYA_MAX_LENGTH, RERANKER_MAX_LENGTH, FT_MAX_LENGTH = 512, 256, 256  # tokens when scoring; long texts are cut
    TRAIN_MAX_LENGTH = 128  # tokens when fine-tuning; the longest generated messages reach ~130 words
    EPOCHS, BATCH_SIZE, LEARNING_RATE, SEED = 4, 32, 5e-5, 0
    DISPUTE_INTENTS = ["request_dispute", "report_unrecognized_charge"]
    INSTRUCTIONS = (
        "Which intent does this bank customer message express? "
        "If it mixes several, pick the dominant, most specific actionable one."
    )
    # Training may use Apple Silicon (ADR-0010 §3); every latency below is measured on CPU
    TRAIN_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
    return (
        BASE_MODEL,
        BATCH_SIZE,
        COUNTRIES,
        DISPUTE_INTENTS,
        EPOCHS,
        FT_MAX_LENGTH,
        INSTRUCTIONS,
        LAYA_MAX_LENGTH,
        LAYA_MODEL,
        LEARNING_RATE,
        RERANKER_MAX_LENGTH,
        RERANKER_MODEL,
        SCHEMA_PATH,
        SEED,
        STAGING,
        TRAIN_DEVICE,
        TRAIN_MAX_LENGTH,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - **No evaluation set is human-labelled.** Each test was written by the coding agent (Claude) from half-B style cards: a different model and different companies from the gpt-6.1-sol train split, but still synthetic. The real reviews carry Claude's silver labels (`lab/complaints-labeling-notes.md`). Treat every number as a lab comparison.
    - **The tests are easy for lexical models:** TF-IDF + LR trained on the grounded train split scores 0.92 (MX) and 0.91 (AR) on them (`checks.md`). Test messages are shorter than training (median 9 words against 12).
    - **The two tests share scenarios.** Many test templates were written as regional versions of the same situation, so the cross-country cells compare mostly wording, not content.
    - **The real reviews are about 85% `out_of_scope`** and hold only 19 (MX) and 23 (AR) in-scope rows. Per-intent scores there are anecdotal; read accuracy and out-of-scope recall.
    - All 15 intents are offered to every model, as at runtime. The zero-shot models see the schema descriptions; the fine-tuned models see only labelled examples. Same base model, epochs and seed for both fine-tunes.
    - Confidence is uncalibrated for all models, so no threshold τ is applied (ADR-0010). Latency is one message at a time on this machine's CPU.
    """)
    return


@app.cell
def _(SCHEMA_PATH, yaml):
    CRITERIA = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    label2id = {name: i for i, name in enumerate(CRITERIA)}
    return CRITERIA, label2id


@app.cell
def _(COUNTRIES, STAGING, mo, pl):
    _missing = [c for c, s in COUNTRIES.items() if not (STAGING / f"decision_{s}" / f"decision.{s}.test.provisional.jsonl").exists()]
    mo.stop(bool(_missing), mo.md(f"**Build the datasets first** (`tools/synthdata_regional`): missing {_missing}."))
    eval_sets = {}
    for _country, _stem in COUNTRIES.items():
        eval_sets[f"{_country} test"] = pl.read_ndjson(STAGING / f"decision_{_stem}" / f"decision.{_stem}.test.provisional.jsonl").select("text", "intent")
        _c = _stem.split("_")[1]
        eval_sets[f"{_country} real reviews"] = pl.read_parquet(STAGING / "complaints" / f"complaints_{_c}_sample_150.parquet").join(
            pl.read_parquet(STAGING / "complaints" / f"complaints_{_c}_sample_150.labels.parquet").select("id", "intent"), on="id"
        ).select(pl.col("original").alias("text"), "intent")
    pl.DataFrame([{"set": k, "rows": v.height, "intents": v["intent"].n_unique()} for k, v in eval_sets.items()])
    return (eval_sets,)


@app.cell
def _(COUNTRIES, STAGING, pl):
    train_sets = {
        _country: tuple(pl.read_ndjson(STAGING / f"decision_{_stem}" / f"decision.{_stem}.{s}.jsonl").select("text", "intent") for s in ("train", "validation"))
        for _country, _stem in COUNTRIES.items()
    }
    pl.DataFrame([{"training set": k, "train": t.height, "validation": v.height} for k, (t, v) in train_sets.items()])
    return (train_sets,)


@app.cell
def _(CRITERIA, INSTRUCTIONS, LAYA_MAX_LENGTH, LAYA_MODEL, eval_sets, laya, pl, time):
    _agent = laya.load(LAYA_MODEL, device="cpu")
    _questions = {"intent": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}}
    _rows = []
    for _set, _d in eval_sets.items():
        for _text, _intent in _d.iter_rows():
            _start = time.perf_counter()
            _answer = _agent.predict(_text, _questions, lang="es", max_len=LAYA_MAX_LENGTH)["answers"]["intent"]
            _rows.append({"model": "Laya (zero-shot)", "set": _set, "text": _text, "intent": _intent, "predicted": _answer["choice"],
                          "latency_ms": 1000 * (time.perf_counter() - _start)})
    laya_predictions = pl.DataFrame(_rows)
    laya_predictions.group_by("set").agg(accuracy=(pl.col("predicted") == pl.col("intent")).mean().round(3))
    return (laya_predictions,)


@app.cell
def _(CRITERIA, RERANKER_MAX_LENGTH, RERANKER_MODEL, eval_sets, pl, time, torch):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(RERANKER_MODEL)
    _model = AutoModelForSequenceClassification.from_pretrained(RERANKER_MODEL).eval()
    _intents, _descriptions = list(CRITERIA), list(CRITERIA.values())
    _rows = []
    for _set, _d in eval_sets.items():
        for _text, _intent in _d.iter_rows():
            _start = time.perf_counter()
            _inputs = _tokenizer([_text] * len(_descriptions), _descriptions, padding=True, truncation="only_first",
                                 max_length=RERANKER_MAX_LENGTH, return_tensors="pt")
            with torch.no_grad():
                _best = int(_model(**_inputs).logits.view(-1).argmax())
            _rows.append({"model": "Reranker (zero-shot)", "set": _set, "text": _text, "intent": _intent,
                          "predicted": _intents[_best], "latency_ms": 1000 * (time.perf_counter() - _start)})
    reranker_predictions = pl.DataFrame(_rows)
    reranker_predictions.group_by("set").agg(accuracy=(pl.col("predicted") == pl.col("intent")).mean().round(3))
    return AutoModelForSequenceClassification, AutoTokenizer, reranker_predictions


@app.cell
def _(
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BASE_MODEL,
    BATCH_SIZE,
    CRITERIA,
    EPOCHS,
    FT_MAX_LENGTH,
    LEARNING_RATE,
    SEED,
    TRAIN_DEVICE,
    TRAIN_MAX_LENGTH,
    eval_sets,
    label2id,
    pl,
    time,
    torch,
    train_sets,
):
    # One fine-tune per country; same base model, epochs and seed; each is scored on every set
    from sklearn.metrics import f1_score

    _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    _rows, _history = [], []
    for _name, (_train, _validation) in train_sets.items():
        torch.manual_seed(SEED)
        _model = AutoModelForSequenceClassification.from_pretrained(
            BASE_MODEL, num_labels=len(CRITERIA), label2id=label2id, id2label={i: n for n, i in label2id.items()},
            ignore_mismatched_sizes=True,
        ).to(TRAIN_DEVICE)
        _optimizer = torch.optim.AdamW(_model.parameters(), lr=LEARNING_RATE)
        _texts, _y = _train["text"].to_list(), torch.tensor([label2id[i] for i in _train["intent"]])
        for _epoch in range(1, EPOCHS + 1):
            _model.train()
            for _idx in torch.randperm(len(_texts)).split(BATCH_SIZE):
                _batch = _tokenizer([_texts[i] for i in _idx], padding=True, truncation=True, max_length=TRAIN_MAX_LENGTH, return_tensors="pt").to(TRAIN_DEVICE)
                _model(**_batch, labels=_y[_idx].to(TRAIN_DEVICE)).loss.backward()
                _optimizer.step()
                _optimizer.zero_grad()
        _model.eval()
        with torch.no_grad():
            _batch = _tokenizer(_validation["text"].to_list(), padding=True, truncation=True, max_length=TRAIN_MAX_LENGTH, return_tensors="pt").to(TRAIN_DEVICE)
            _pred = [_model.config.id2label[int(i)] for i in _model(**_batch).logits.argmax(-1)]
        _history.append({"training set": _name, "own validation macro_f1": round(f1_score(_validation["intent"], _pred, average="macro"), 3)})
        _model.to("cpu")
        for _set, _d in eval_sets.items():
            for _text, _intent in _d.iter_rows():
                _start = time.perf_counter()
                with torch.no_grad():
                    _logits = _model(**_tokenizer(_text, truncation=True, max_length=FT_MAX_LENGTH, return_tensors="pt")).logits[0]
                _rows.append({"model": f"Fine-tuned ({_name})", "set": _set, "text": _text, "intent": _intent,
                              "predicted": _model.config.id2label[int(_logits.argmax())], "latency_ms": 1000 * (time.perf_counter() - _start)})
    finetune_predictions = pl.DataFrame(_rows)
    pl.DataFrame(_history)
    return (finetune_predictions,)


@app.cell
def _(DISPUTE_INTENTS, finetune_predictions, laya_predictions, np, pl, reranker_predictions):
    from sklearn.metrics import accuracy_score, f1_score as _f1, precision_recall_fscore_support

    predictions = pl.concat([laya_predictions, reranker_predictions, finetune_predictions])
    _rows = []
    for (_model, _set), _d in predictions.group_by("model", "set", maintain_order=True):
        _y, _p = _d["intent"].to_list(), _d["predicted"].to_list()
        _, _oos_recall, _, _ = precision_recall_fscore_support(_y, _p, labels=["out_of_scope"], zero_division=0)
        _rows.append({"set": _set, "model": _model, "rows": _d.height, "accuracy": accuracy_score(_y, _p),
                      "macro_f1": _f1(_y, _p, average="macro", zero_division=0),
                      "weighted_f1": _f1(_y, _p, average="weighted", zero_division=0),
                      "out_of_scope_recall": float(_oos_recall[0]),
                      "dispute_f1": float(np.mean(_f1(_y, _p, labels=DISPUTE_INTENTS, average=None, zero_division=0))),
                      "p95_latency_ms": float(np.percentile(_d["latency_ms"], 95))})
    summary = pl.DataFrame(_rows).with_columns(pl.col(pl.Float64).round(3)).sort("set", "accuracy", descending=[False, True])
    summary
    return predictions, summary


@app.cell
def _(pl, summary):
    # Regional transfer: each fine-tune's accuracy on its own country's test and on the other's
    summary.filter(pl.col("model").str.starts_with("Fine-tuned")).pivot("set", index="model", values="accuracy")
    return


@app.cell
def _(CRITERIA, pl, predictions):
    # Per-intent F1 on both tests, one column per model and test
    from sklearn.metrics import f1_score as _f1_score

    _rows = []
    for (_model, _set), _d in predictions.filter(pl.col("set").str.ends_with("test")).group_by("model", "set", maintain_order=True):
        _f = _f1_score(_d["intent"], _d["predicted"], labels=list(CRITERIA), average=None, zero_division=0)
        _rows += [{"column": f"{_model} · {_set}", "intent": _i, "f1": round(float(_v), 3)} for _i, _v in zip(CRITERIA, _f)]
    pl.DataFrame(_rows).pivot("column", index="intent", values="f1")
    return


@app.cell
def _(mo, pl, predictions):
    # Errors on the real reviews
    mo.ui.table(
        predictions.filter(pl.col("set").str.ends_with("real reviews"), pl.col("intent") != pl.col("predicted"))
        .select("model", "set", "intent", "predicted", "text")
    )
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
