import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # compare · decision-pt

    **Question:** On pt-BR, how do Laya (zero-shot), the bge reranker (zero-shot) and the fine-tuned multilingual DistilBERT compare, and does fine-tuning on the new grounded pt dataset beat fine-tuning on the old template pt rows?

    **Evaluation sets:** `data/staging/decision_pt/decision.pt.test.provisional.jsonl` (750 rows, 15 intents) and the 300 Brazilian rows of `data/staging/complaints/complaints_sample_900.parquet`, scored against `complaints_sample_900.labels.parquet` · **Training sets for the fine-tuned model:** the pt rows of `data/eval/synthetic/decision.{train,validation}.jsonl` (templates) or `decision.pt.{train,validation}.jsonl` (grounded) · **Generated:** 2026-09-29, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type is not in its menu yet). Step 6 of the plan for the pt intent dataset.
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
    PT_DIR = REPO / "data" / "staging" / "decision_pt"
    TEMPLATE_DIR = REPO / "data" / "eval" / "synthetic"
    COMPLAINTS_PATH = REPO / "data" / "staging" / "complaints" / "complaints_sample_900.parquet"
    LABELS_PATH = COMPLAINTS_PATH.with_name("complaints_sample_900.labels.parquet")
    LAYA_MODEL = "convaiinnovations/laya-multilingual"
    RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
    BASE_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    LAYA_MAX_LENGTH, RERANKER_MAX_LENGTH, FT_MAX_LENGTH = 512, 256, 256  # tokens when scoring; long texts are cut
    TRAIN_MAX_LENGTH = 128  # tokens when fine-tuning; grounded long messages reach ~110 words
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
        COMPLAINTS_PATH,
        DISPUTE_INTENTS,
        EPOCHS,
        FT_MAX_LENGTH,
        INSTRUCTIONS,
        LABELS_PATH,
        LAYA_MAX_LENGTH,
        LAYA_MODEL,
        LEARNING_RATE,
        PT_DIR,
        RERANKER_MAX_LENGTH,
        RERANKER_MODEL,
        SCHEMA_PATH,
        SEED,
        TEMPLATE_DIR,
        TRAIN_DEVICE,
        TRAIN_MAX_LENGTH,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - **Neither evaluation set is human-labelled.** The new test was written by the coding agent (Claude) from half-B style cards: a different model and different companies from the gpt-6.1-sol train split, but still synthetic. The 300 complaints carry Claude's silver labels (`lab/complaints-labeling-notes.md`). Treat every number as a lab comparison.
    - **The new test is easy for lexical models:** TF-IDF + LR trained on the grounded train split scores 0.94 on it (`data/staging/decision_pt/checks.md`). Its messages are shorter than training (median 8 words against 15), so it is partly a style-shift test too.
    - **The real complaints are mostly `out_of_scope`** (215 of 300) and only 7 intents occur. Macro averages include every intent that appears in the labels or the predictions.
    - All 15 intents are offered to every model, as at runtime. The zero-shot models see the schema descriptions; the fine-tuned model sees only labelled examples.
    - Template baseline: the 600 pt train rows (40 per intent) and 150 pt validation rows of the template splits. Grounded: 1,500 train and 750 validation rows. Same base model, epochs and seed.
    - Confidence is uncalibrated for all models, so no threshold τ is applied (ADR-0010). Latency is one message at a time on this machine's CPU.
    """)
    return


@app.cell
def _(SCHEMA_PATH, yaml):
    CRITERIA = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    label2id = {name: i for i, name in enumerate(CRITERIA)}
    return CRITERIA, label2id


@app.cell
def _(COMPLAINTS_PATH, LABELS_PATH, PT_DIR, mo, pl):
    mo.stop(not (PT_DIR / "decision.pt.test.provisional.jsonl").exists(), mo.md("**Build the pt dataset first** (`llm-synthetic__decision-pt.py`, `tools/synthdata_pt`)."))
    eval_sets = {
        "new pt test": pl.read_ndjson(PT_DIR / "decision.pt.test.provisional.jsonl").select("text", "intent"),
        "real BR complaints": pl.read_parquet(COMPLAINTS_PATH).with_row_index("id").join(
            pl.read_parquet(LABELS_PATH).select("id", "intent"), on="id"
        ).filter(pl.col("country") == "br").select(pl.col("ask").alias("text"), "intent"),
    }
    pl.DataFrame([{"set": k, "rows": v.height, "intents": v["intent"].n_unique()} for k, v in eval_sets.items()])
    return (eval_sets,)


@app.cell
def _(PT_DIR, TEMPLATE_DIR, pl):
    train_sets = {
        "template": tuple(pl.read_ndjson(TEMPLATE_DIR / f"decision.{s}.jsonl").filter(pl.col("lang") == "pt").select("text", "intent")
                          for s in ("train", "validation")),
        "grounded": tuple(pl.read_ndjson(PT_DIR / f"decision.pt.{s}.jsonl").select("text", "intent") for s in ("train", "validation")),
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
            _answer = _agent.predict(_text, _questions, lang="pt", max_len=LAYA_MAX_LENGTH)["answers"]["intent"]
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
    # Same base model, epochs and seed; only the training rows differ
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
def _(CRITERIA, pl, predictions):
    # Per-intent F1 on the new pt test, one column per model
    from sklearn.metrics import f1_score as _f1_score

    _rows = []
    for (_model,), _d in predictions.filter(pl.col("set") == "new pt test").group_by("model", maintain_order=True):
        _f = _f1_score(_d["intent"], _d["predicted"], labels=list(CRITERIA), average=None, zero_division=0)
        _rows += [{"model": _model, "intent": _i, "f1": round(float(_v), 3)} for _i, _v in zip(CRITERIA, _f)]
    pl.DataFrame(_rows).pivot("model", index="intent", values="f1")
    return


@app.cell
def _(mo, pl, predictions):
    # Errors on the real complaints, for the model that matters most at runtime
    mo.ui.table(
        predictions.filter(pl.col("set") == "real BR complaints", pl.col("intent") != pl.col("predicted"))
        .select("model", "intent", "predicted", "text")
    )
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
