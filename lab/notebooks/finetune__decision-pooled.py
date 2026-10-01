import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # finetune · decision-pooled

    **Question:** Does one multilingual DistilBERT fine-tuned on the pooled pt-BR + es-MX + es-AR grounded datasets match or beat the three single-country fine-tunes on every country's test and real-world set?

    **Training sets:** `data/staging/decision_{pt,es_mx,es_ar}/*.{train,validation}.jsonl` (1,500 + 750 rows each; pooled 4,500 + 2,250) · **Evaluation sets:** the three provisional tests (750 rows each) and the three silver-labelled real sets (300 BR complaints, 150 MX and 150 AR app reviews) · **Generated:** 2026-09-30, following the style rules in `lab/NOTEBOOK_GUIDE.md`, modelled on the fine-tune cell of `compare__decision-es.py`. Laya and the reranker are not rerun: their scores are in `compare__decision-{pt,es}.py`.
    """)
    return


@app.cell
def _():
    import marimo as mo
    import numpy as np
    import polars as pl
    import torch
    import yaml

    return mo, np, pl, torch, yaml


@app.cell
def _(mo, torch):
    # Settings: change these, the rest of the notebook follows
    REPO = mo.notebook_dir().parents[1]
    SCHEMA_PATH = REPO / "data" / "eval" / "synthetic" / "schema.yaml"
    STAGING = REPO / "data" / "staging"
    DATASETS = {"PT": ("decision_pt", "decision.pt"), "MX": ("decision_es_mx", "decision.es_mx"), "AR": ("decision_es_ar", "decision.es_ar")}
    TRAINING = {"PT": ["PT"], "MX": ["MX"], "AR": ["AR"], "pooled": ["PT", "MX", "AR"]}  # model name → datasets it trains on
    BASE_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    TRAIN_MAX_LENGTH, FT_MAX_LENGTH = 128, 256
    EPOCHS, BATCH_SIZE, LEARNING_RATE = 4, 32, 5e-5
    SEEDS = (0, 1)  # two runs per model, to see how much of a gap is training noise
    SCORE_BATCH = 64
    DISPUTE_INTENTS = ["request_dispute", "report_unrecognized_charge"]
    TRAIN_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"  # ADR-0010 §3
    return (
        BASE_MODEL,
        BATCH_SIZE,
        DATASETS,
        DISPUTE_INTENTS,
        EPOCHS,
        FT_MAX_LENGTH,
        LEARNING_RATE,
        SCHEMA_PATH,
        SCORE_BATCH,
        SEEDS,
        STAGING,
        TRAINING,
        TRAIN_DEVICE,
        TRAIN_MAX_LENGTH,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - **No evaluation set is human-labelled** (provisional agent-written tests, silver real-world labels). See `lab/complaints-labeling-notes.md` and `docs/limitations.md`.
    - **Same epochs, more steps:** with 4 epochs the pooled model makes three times as many updates as a single-country model. That is the natural recipe (one pass over all data per epoch), not a controlled equal-compute comparison.
    - **Validation is pooled too**, so the pooled model's validation score mixes the three varieties.
    - Scoring is batched on CPU; latency is not measured here (about 10 ms p95 per message in `compare__decision-es.py`).
    - The es-MX and es-AR tests share scenarios, and the real-world sets hold few in-scope rows (85 BR, 19 MX, 23 AR): read accuracy and out-of-scope recall there.
    """)
    return


@app.cell
def _(SCHEMA_PATH, yaml):
    CRITERIA = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    label2id = {name: i for i, name in enumerate(CRITERIA)}
    return CRITERIA, label2id


@app.cell
def _(DATASETS, STAGING, mo, pl):
    _missing = [k for k, (d, s) in DATASETS.items() if not (STAGING / d / f"{s}.test.provisional.jsonl").exists()]
    mo.stop(bool(_missing), mo.md(f"**Build the datasets first** (`tools/synthdata_regional`): missing {_missing}."))
    splits = {k: {s: pl.read_ndjson(STAGING / d / f"{stem}.{s}.jsonl").select("text", "intent")
                  for s in ("train", "validation", "test.provisional")} for k, (d, stem) in DATASETS.items()}
    _complaints = STAGING / "complaints"
    eval_sets = {f"{k} test": v["test.provisional"] for k, v in splits.items()}
    eval_sets["PT real complaints"] = pl.read_parquet(_complaints / "complaints_sample_900.parquet").with_row_index("id").join(
        pl.read_parquet(_complaints / "complaints_sample_900.labels.parquet").select("id", "intent"), on="id"
    ).filter(pl.col("country") == "br").select(pl.col("ask").alias("text"), "intent")
    for _c in ("mx", "ar"):
        eval_sets[f"{_c.upper()} real reviews"] = pl.read_parquet(_complaints / f"complaints_{_c}_sample_150.parquet").join(
            pl.read_parquet(_complaints / f"complaints_{_c}_sample_150.labels.parquet").select("id", "intent"), on="id"
        ).select(pl.col("original").alias("text"), "intent")
    pl.DataFrame([{"set": k, "rows": v.height, "in-scope rows": v.filter(pl.col("intent") != "out_of_scope").height} for k, v in eval_sets.items()])
    return eval_sets, splits


@app.cell
def _(TRAINING, pl, splits):
    train_sets = {name: (pl.concat([splits[k]["train"] for k in parts]), pl.concat([splits[k]["validation"] for k in parts]))
                  for name, parts in TRAINING.items()}
    pl.DataFrame([{"model": k, "trains on": " + ".join(TRAINING[k]), "train": t.height, "validation": v.height} for k, (t, v) in train_sets.items()])
    return (train_sets,)


@app.cell
def _(
    BASE_MODEL,
    BATCH_SIZE,
    CRITERIA,
    EPOCHS,
    FT_MAX_LENGTH,
    LEARNING_RATE,
    SCORE_BATCH,
    SEEDS,
    TRAIN_DEVICE,
    TRAIN_MAX_LENGTH,
    eval_sets,
    label2id,
    pl,
    torch,
    train_sets,
):
    # Every model × seed is trained the same way and scored on every set
    from sklearn.metrics import f1_score
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    def _predict(model, texts, device, max_length):
        out = []
        with torch.no_grad():
            for k in range(0, len(texts), SCORE_BATCH):
                batch = _tokenizer(texts[k:k + SCORE_BATCH], padding=True, truncation=True, max_length=max_length, return_tensors="pt").to(device)
                out += [model.config.id2label[int(i)] for i in model(**batch).logits.argmax(-1)]
        return out

    _rows, _history = [], []
    for _name, (_train, _validation) in train_sets.items():
        for _seed in SEEDS:
            torch.manual_seed(_seed)
            _model = AutoModelForSequenceClassification.from_pretrained(
                BASE_MODEL, num_labels=len(CRITERIA), label2id=label2id, id2label={i: n for n, i in label2id.items()},
                ignore_mismatched_sizes=True,
            ).to(TRAIN_DEVICE)
            _optimizer = torch.optim.AdamW(_model.parameters(), lr=LEARNING_RATE)
            _texts, _y = _train["text"].to_list(), torch.tensor([label2id[i] for i in _train["intent"]])
            for _epoch in range(EPOCHS):
                _model.train()
                for _idx in torch.randperm(len(_texts)).split(BATCH_SIZE):  # shuffled, so pooled batches mix the three varieties
                    _batch = _tokenizer([_texts[i] for i in _idx], padding=True, truncation=True, max_length=TRAIN_MAX_LENGTH, return_tensors="pt").to(TRAIN_DEVICE)
                    _model(**_batch, labels=_y[_idx].to(TRAIN_DEVICE)).loss.backward()
                    _optimizer.step()
                    _optimizer.zero_grad()
            _model.eval()
            _pred = _predict(_model, _validation["text"].to_list(), TRAIN_DEVICE, TRAIN_MAX_LENGTH)
            _history.append({"model": _name, "seed": _seed, "own validation macro_f1": round(f1_score(_validation["intent"], _pred, average="macro"), 3)})
            _model.to("cpu")
            for _set, _d in eval_sets.items():
                _rows += [{"model": _name, "seed": _seed, "set": _set, "intent": i, "predicted": p}
                          for i, p in zip(_d["intent"], _predict(_model, _d["text"].to_list(), "cpu", FT_MAX_LENGTH))]
            del _model
    predictions = pl.DataFrame(_rows)
    pl.DataFrame(_history)
    return (predictions,)


@app.cell
def _(DISPUTE_INTENTS, np, pl, predictions):
    from sklearn.metrics import accuracy_score, f1_score as _f1, precision_recall_fscore_support

    _rows = []
    for (_model, _seed, _set), _d in predictions.group_by("model", "seed", "set", maintain_order=True):
        _y, _p = _d["intent"].to_list(), _d["predicted"].to_list()
        _, _oos, _, _ = precision_recall_fscore_support(_y, _p, labels=["out_of_scope"], zero_division=0)
        _rows.append({"model": _model, "seed": _seed, "set": _set, "accuracy": accuracy_score(_y, _p),
                      "macro_f1": _f1(_y, _p, average="macro", zero_division=0), "out_of_scope_recall": float(_oos[0]),
                      "dispute_f1": float(np.mean(_f1(_y, _p, labels=DISPUTE_INTENTS, average=None, zero_division=0)))})
    per_seed = pl.DataFrame(_rows)
    # Mean over seeds, with the spread (max − min) so a gap can be read against training noise
    summary = per_seed.group_by("model", "set", maintain_order=True).agg(
        *[pl.col(m).mean().round(3).alias(m) for m in ("accuracy", "macro_f1", "out_of_scope_recall", "dispute_f1")],
        accuracy_spread=(pl.col("accuracy").max() - pl.col("accuracy").min()).round(3),
    )
    summary
    return (summary,)


@app.cell
def _(pl, summary):
    # Accuracy: one row per model, one column per evaluation set (mean over seeds)
    summary.pivot("set", index="model", values="accuracy").with_columns(
        mean_over_sets=pl.mean_horizontal(pl.exclude("model")).round(3))
    return


@app.cell
def _(pl, summary):
    # Out-of-scope recall: the weak spot on real text
    summary.pivot("set", index="model", values="out_of_scope_recall")
    return


@app.cell
def _(CRITERIA, pl, predictions):
    # Per-intent F1 of the pooled model on each test (seed 0)
    from sklearn.metrics import f1_score as _f1_score

    _rows = []
    for (_set,), _d in predictions.filter((pl.col("model") == "pooled") & (pl.col("seed") == 0) & pl.col("set").str.ends_with("test")).group_by("set", maintain_order=True):
        _f = _f1_score(_d["intent"], _d["predicted"], labels=list(CRITERIA), average=None, zero_division=0)
        _rows += [{"set": _set, "intent": _i, "f1": round(float(_v), 3)} for _i, _v in zip(CRITERIA, _f)]
    pl.DataFrame(_rows).pivot("set", index="intent", values="f1")
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
