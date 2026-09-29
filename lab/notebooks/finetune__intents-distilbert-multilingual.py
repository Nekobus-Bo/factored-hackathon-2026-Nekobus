import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # finetune · intents · distilbert multilingual

    **Question:** How well does a small multilingual encoder classify customer messages into the 15-intent taxonomy after fine-tuning on the synthetic train split?

    **Data:** `data/eval/synthetic/decision.{train,validation,test.provisional}.jsonl` (es/pt/en) · **Taxonomy:** `data/eval/synthetic/schema.yaml` · **Base model:** [`lxyuan/distilbert-base-multilingual-cased-sentiments-student`](https://huggingface.co/lxyuan/distilbert-base-multilingual-cased-sentiments-student), its 3-label sentiment head replaced by a 15-intent head · **Generated:** 2026-09-28, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type is not in its menu yet)
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
def _(mo, torch):
    # Settings: change these, the rest of the notebook follows
    BASE_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
    SPLITS_DIR = mo.notebook_dir().parents[1] / "data" / "eval" / "synthetic"
    SCHEMA_PATH = SPLITS_DIR / "schema.yaml"
    EPOCHS = 4
    BATCH_SIZE = 32
    LEARNING_RATE = 5e-5
    MAX_LENGTH = 64  # tokens; the longest message is ~115 characters
    SEED = 0
    # Training may use Apple Silicon (ADR-0010 §3); test latency is always measured on CPU
    TRAIN_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
    return (
        BASE_MODEL,
        BATCH_SIZE,
        EPOCHS,
        LEARNING_RATE,
        MAX_LENGTH,
        SCHEMA_PATH,
        SEED,
        SPLITS_DIR,
        TRAIN_DEVICE,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - Train and validation are **template-generated**; the provisional test is free-form, **AI-written** text. The gap between validation and test F1 is the template-to-free-form shift, not overfitting alone. The human-written `decision.test.jsonl` is pending (`data/eval/synthetic/README.md`).
    - One validation row is a suspected mislabel ("I completely dispute an unknown charge…" labelled `report_unrecognized_charge`, `lab/dispute-intent-classification-plan.md`).
    - The base model was distilled for **sentiment**, not intents: only its encoder is reused, and the new head starts from random weights. The intent descriptions in the taxonomy are not seen by the model; only the 15 label names are.
    - Reference points on the same test file: TF-IDF + LR at macro-F1 0.79–0.84, GLiNER2.5 zero-shot at 0.43–0.52 (`reports/calibration-decision-2026-09-28.md`), Laya zero-shot at 0.495, bge-reranker-v2-m3 zero-shot at 0.655 (sibling notebooks).
    - `confidence` is the raw softmax, uncalibrated; a threshold τ needs temperature fitting on validation (ADR-0010). Test latency is one message at a time on this machine's CPU, not the Linux container.
    """)
    return


@app.cell
def _(SCHEMA_PATH, mo, pl, yaml):
    # The taxonomy fixes the head: one output per intent, in schema order
    CRITERIA = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    label2id = {name: i for i, name in enumerate(CRITERIA)}
    mo.ui.table(pl.DataFrame({"id": list(label2id.values()), "intent": list(CRITERIA), "description": list(CRITERIA.values())}))
    return CRITERIA, label2id


@app.cell
def _(SPLITS_DIR, pl):
    train, validation, test = (
        pl.read_ndjson(SPLITS_DIR / f"decision.{s}.jsonl").select("id", "lang", "text", "intent")
        for s in ("train", "validation", "test.provisional")
    )
    pl.concat([train.with_columns(split=pl.lit("train")), validation.with_columns(split=pl.lit("validation")),
               test.with_columns(split=pl.lit("test"))]).pivot("lang", index="split", values="id", aggregate_function="len")
    return test, train, validation


@app.cell
def _(BASE_MODEL):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    return (tokenizer,)


@app.cell
def _(
    BASE_MODEL,
    BATCH_SIZE,
    CRITERIA,
    EPOCHS,
    LEARNING_RATE,
    MAX_LENGTH,
    SEED,
    TRAIN_DEVICE,
    label2id,
    pl,
    tokenizer,
    torch,
    train,
    validation,
):
    from sklearn.metrics import f1_score
    from transformers import AutoModelForSequenceClassification

    torch.manual_seed(SEED)
    # ignore_mismatched_sizes swaps the 3-label sentiment head for a fresh 15-label one
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(CRITERIA), label2id=label2id, id2label={i: n for n, i in label2id.items()},
        ignore_mismatched_sizes=True,
    ).to(TRAIN_DEVICE)
    _optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    _texts, _y = train["text"].to_list(), torch.tensor([label2id[i] for i in train["intent"]])
    _history = []
    for _epoch in range(1, EPOCHS + 1):
        model.train()
        _losses = []
        for _idx in torch.randperm(len(_texts)).split(BATCH_SIZE):
            _batch = tokenizer([_texts[i] for i in _idx], padding=True, truncation=True, max_length=MAX_LENGTH,
                               return_tensors="pt").to(TRAIN_DEVICE)
            _loss = model(**_batch, labels=_y[_idx].to(TRAIN_DEVICE)).loss
            _loss.backward()
            _optimizer.step()
            _optimizer.zero_grad()
            _losses.append(_loss.item())
        model.eval()
        with torch.no_grad():
            _batch = tokenizer(validation["text"].to_list(), padding=True, truncation=True, max_length=MAX_LENGTH,
                               return_tensors="pt").to(TRAIN_DEVICE)
            _pred = [model.config.id2label[int(i)] for i in model(**_batch).logits.argmax(-1)]
        _history.append({"epoch": _epoch, "train_loss": round(sum(_losses) / len(_losses), 4),
                         "validation_macro_f1": round(f1_score(validation["intent"], _pred, average="macro"), 3)})
    model.to("cpu")
    pl.DataFrame(_history)
    return (model,)


@app.cell
def _(MAX_LENGTH, model, pl, test, time, tokenizer, torch):
    # Test on CPU, one message at a time, as the runtime would see it
    _predicted, _confidence, _latency_ms = [], [], []
    for _text in test["text"]:
        _start = time.perf_counter()
        with torch.no_grad():
            _probs = torch.softmax(model(**tokenizer(_text, truncation=True, max_length=MAX_LENGTH,
                                                     return_tensors="pt")).logits[0], dim=0)
        _latency_ms.append(1000 * (time.perf_counter() - _start))
        _predicted.append(model.config.id2label[int(_probs.argmax())])
        _confidence.append(round(float(_probs.max()), 4))
    results = test.with_columns(
        predicted=pl.Series(_predicted), confidence=pl.Series(_confidence), latency_ms=pl.Series(_latency_ms)
    )
    results
    return (results,)


@app.cell
def _(np, pl, results):
    from sklearn.metrics import f1_score as _f1_score

    _groups = [("all", results)] + [(g, d) for (g,), d in results.group_by("lang", maintain_order=True)]
    pl.DataFrame([
        {"lang": _name, "rows": _d.height,
         "macro_f1": round(_f1_score(_d["intent"], _d["predicted"], average="macro"), 3),
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
