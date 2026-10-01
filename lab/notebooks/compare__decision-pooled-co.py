import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # compare · decision-pooled-co

    **Question:** Does adding the grounded es-CO dataset to the pooled DistilBERT help Colombia without costing Brazil, Mexico or Argentina, so that it should replace the shipped weights?

    **Training sets:** `data/staging/decision_{pt,es_mx,es_ar,es_co}/*.{train,validation}.jsonl` (1,500 + 750 rows each). Pooled-3 trains on pt + MX + AR (the shipped recipe), Pooled-4 adds CO · **Evaluation sets:** the four provisional tests (750 rows each) and the four silver-labelled real sets (300 BR complaints, 150 MX and 150 AR app reviews, 150 CO complaint threads) · **Shipped weights:** `packages/encoder/weights/distilbert-intent-pooled.prev-f43063c6` (the pinned model, scored only) · **Generated:** 2026-10-01, following the style rules in `lab/NOTEBOOK_GUIDE.md`, modelled on `finetune__decision-pooled.py`. Amends ADR-0014 (es-CO).

    **Replacement rule** (fixed before running, ADR-0014 amendment). Pooled-4 replaces the shipped model only if all three hold:
    1. it beats Pooled-3 on **CO test** and **CO real** by more than the seed spread;
    2. on each of the six non-CO sets, its mean accuracy drops by no more than max(seed spread, 0.02);
    3. its mean out-of-scope recall over the four real sets is not lower than Pooled-3's by more than the seed spread.
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
    DATASETS = {"PT": ("decision_pt", "decision.pt"), "MX": ("decision_es_mx", "decision.es_mx"),
                "AR": ("decision_es_ar", "decision.es_ar"), "CO": ("decision_es_co", "decision.es_co")}
    TRAINING = {"pooled-3": ["PT", "MX", "AR"], "pooled-4": ["PT", "MX", "AR", "CO"]}  # model name → datasets it trains on
    SHIPPED = REPO / "packages" / "encoder" / "weights" / "distilbert-intent-pooled.prev-f43063c6"
    BASE_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    BASE_REVISION = "cf991100d706c13c0a080c097134c05b7f436c45"  # the commit the shipped model was trained from
    TRAIN_MAX_LENGTH, FT_MAX_LENGTH = 128, 256
    EPOCHS, BATCH_SIZE, LEARNING_RATE = 4, 32, 5e-5
    SEEDS = (0, 1)  # two runs per model, to see how much of a gap is training noise
    MIN_TOLERANCE = 0.02  # rule 2: a non-CO set may drop by up to max(seed spread, this)
    SCORE_BATCH = 64
    DISPUTE_INTENTS = ["request_dispute", "report_unrecognized_charge"]
    TRAIN_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"  # ADR-0010 §3
    return (
        BASE_MODEL,
        BASE_REVISION,
        BATCH_SIZE,
        DATASETS,
        DISPUTE_INTENTS,
        EPOCHS,
        FT_MAX_LENGTH,
        LEARNING_RATE,
        MIN_TOLERANCE,
        SCHEMA_PATH,
        SCORE_BATCH,
        SEEDS,
        SHIPPED,
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
    - **Pooled-4 trains on a third more rows**, so it also makes a third more updates in 4 epochs. That is the shipped recipe applied to more data, not an equal-compute comparison.
    - **CO real is mostly transfer disputes.** 27 of its 35 in-scope rows are `request_dispute` about rejected PSE or Transfiya transfers (`lab/complaints-labeling-notes.md`, Colombia), a pattern the synthetic data barely contains.
    - **The CO source is small** (618 texts from 5 banks, a complaint forum rather than app reviews), so the CO dataset carries register and regional words more than per-intent phrasing.
    - The shipped model was trained with the same recipe (seed 0) by `make train-encoder`; it is scored as a reference, not counted in the rule.
    - Scoring is batched on CPU; latency is not measured here (about 10 ms p95 per message in `compare__decision-es.py`).
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
    eval_sets["BR real"] = pl.read_parquet(_complaints / "complaints_sample_900.parquet").with_row_index("id").join(
        pl.read_parquet(_complaints / "complaints_sample_900.labels.parquet").select("id", "intent"), on="id"
    ).filter(pl.col("country") == "br").select(pl.col("ask").alias("text"), "intent")
    for _c in ("mx", "ar", "co"):
        eval_sets[f"{_c.upper()} real"] = pl.read_parquet(_complaints / f"complaints_{_c}_sample_150.parquet").join(
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
    BASE_REVISION,
    BATCH_SIZE,
    CRITERIA,
    EPOCHS,
    FT_MAX_LENGTH,
    LEARNING_RATE,
    SCORE_BATCH,
    SEEDS,
    SHIPPED,
    TRAIN_DEVICE,
    TRAIN_MAX_LENGTH,
    eval_sets,
    label2id,
    mo,
    pl,
    torch,
    train_sets,
):
    # Every model × seed is trained the same way and scored on every set; the shipped weights are only scored
    from sklearn.metrics import f1_score
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REVISION)

    def _predict(model, texts, device, max_length):
        out = []
        with torch.no_grad():
            for k in range(0, len(texts), SCORE_BATCH):
                batch = _tokenizer(texts[k:k + SCORE_BATCH], padding=True, truncation=True, max_length=max_length, return_tensors="pt").to(device)
                out += [model.config.id2label[int(i)] for i in model(**batch).logits.argmax(-1)]
        return out

    def _score(name, seed, model):
        return [{"model": name, "seed": seed, "set": s, "intent": i, "predicted": p}
                for s, d in eval_sets.items() for i, p in zip(d["intent"], _predict(model, d["text"].to_list(), "cpu", FT_MAX_LENGTH))]

    _rows, _history = [], []
    for _name, _seed in mo.status.progress_bar([(n, s) for n in train_sets for s in SEEDS], title="Training"):
        _train, _validation = train_sets[_name]
        torch.manual_seed(_seed)
        _model = AutoModelForSequenceClassification.from_pretrained(
            BASE_MODEL, revision=BASE_REVISION, num_labels=len(CRITERIA), label2id=label2id,
            id2label={i: n for n, i in label2id.items()}, ignore_mismatched_sizes=True,
        ).to(TRAIN_DEVICE)
        _optimizer = torch.optim.AdamW(_model.parameters(), lr=LEARNING_RATE)
        _texts, _y = _train["text"].to_list(), torch.tensor([label2id[i] for i in _train["intent"]])
        for _epoch in range(EPOCHS):
            _model.train()
            for _idx in torch.randperm(len(_texts)).split(BATCH_SIZE):  # shuffled, so pooled batches mix the varieties
                _batch = _tokenizer([_texts[i] for i in _idx], padding=True, truncation=True, max_length=TRAIN_MAX_LENGTH, return_tensors="pt").to(TRAIN_DEVICE)
                _model(**_batch, labels=_y[_idx].to(TRAIN_DEVICE)).loss.backward()
                _optimizer.step()
                _optimizer.zero_grad()
        _model.eval()
        _pred = _predict(_model, _validation["text"].to_list(), TRAIN_DEVICE, TRAIN_MAX_LENGTH)
        _history.append({"model": _name, "seed": _seed, "own validation macro_f1": round(f1_score(_validation["intent"], _pred, average="macro"), 3)})
        _rows += _score(_name, _seed, _model.to("cpu"))
        del _model
    _shipped = AutoModelForSequenceClassification.from_pretrained(SHIPPED).eval()
    _rows += _score("shipped", 0, _shipped)
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
    return per_seed, summary


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
def _(pl, summary):
    # Dispute F1 (request_dispute and report_unrecognized_charge): the compromised-card core
    summary.pivot("set", index="model", values="dispute_f1")
    return


@app.cell
def _(MIN_TOLERANCE, per_seed, pl, summary):
    # The replacement rule, decided before running. Spreads: the larger of the two models' seed spreads
    _acc = summary.filter(pl.col("model").is_in(["pooled-3", "pooled-4"])).pivot("model", index="set", values=["accuracy", "accuracy_spread"])
    _acc = _acc.with_columns(gap=(pl.col("accuracy_pooled-4") - pl.col("accuracy_pooled-3")).round(3),
                             spread=pl.max_horizontal("accuracy_spread_pooled-3", "accuracy_spread_pooled-4"))
    _co = _acc.filter(pl.col("set").str.starts_with("CO"))
    _rest = _acc.filter(~pl.col("set").str.starts_with("CO")).with_columns(allowed=pl.max_horizontal("spread", pl.lit(MIN_TOLERANCE)))
    _oos = per_seed.filter(pl.col("set").str.ends_with("real") & pl.col("model").is_in(["pooled-3", "pooled-4"])).group_by("model", "seed").agg(
        pl.col("out_of_scope_recall").mean()).group_by("model").agg(mean=pl.col("out_of_scope_recall").mean(),
                                                                  spread=pl.col("out_of_scope_recall").max() - pl.col("out_of_scope_recall").min())
    _o = {r["model"]: r for r in _oos.iter_rows(named=True)}
    _oos_gap, _oos_spread = _o["pooled-4"]["mean"] - _o["pooled-3"]["mean"], max(_o["pooled-4"]["spread"], _o["pooled-3"]["spread"])
    decision = {
        "1. beats pooled-3 on CO test and CO real beyond the spread": bool((_co["gap"] > _co["spread"]).all()),
        "2. no non-CO set drops beyond max(spread, 0.02)": bool((_rest["gap"] >= -_rest["allowed"]).all()),
        "3. real-text out-of-scope recall not lower beyond the spread": bool(_oos_gap >= -_oos_spread),
    }
    decision["replace the shipped weights"] = all(decision.values())
    rule_table = pl.concat([_co.with_columns(allowed=pl.lit(None, dtype=pl.Float64)), _rest], how="diagonal").select(
        "set", "accuracy_pooled-3", "accuracy_pooled-4", "gap", "spread", "allowed")
    oos_check = {"mean real out-of-scope recall, pooled-3": round(_o["pooled-3"]["mean"], 3),
                 "mean real out-of-scope recall, pooled-4": round(_o["pooled-4"]["mean"], 3),
                 "gap": round(_oos_gap, 3), "spread": round(_oos_spread, 3)}
    rule_table, oos_check, decision
    return decision, oos_check, rule_table


@app.cell
def _(CRITERIA, pl, predictions):
    # Per-intent F1 of Pooled-4 on each test and on CO real (seed 0)
    from sklearn.metrics import f1_score as _f1_score

    _rows = []
    _sel = (pl.col("model") == "pooled-4") & (pl.col("seed") == 0) & (pl.col("set").str.ends_with("test") | (pl.col("set") == "CO real"))
    for (_set,), _d in predictions.filter(_sel).group_by("set", maintain_order=True):
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
