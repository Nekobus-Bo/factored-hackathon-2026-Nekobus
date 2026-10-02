import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # compare · kb-embeddings

    **Question:** On our knowledge base and synthetic queries, does any of four retrieval-trained models beat the current MiniLM on same- and cross-language Hit@1 and MRR, and at what CPU latency and memory?

    **Data:** `packages/retrieval/kb/snippets.jsonl` (120 snippets: 40 topics × es/pt/en) and the `validation` split of `data/eval/synthetic/retrieval/queries.jsonl` (360 queries, 120 per language) · **Generated:** 2026-10-01, following the style rules in `lab/NOTEBOOK_GUIDE.md`, modelled on `compare__decision-es.py`. Plan, pros and cons: `lab/notebooks/embedding-comparison-plan.md`. Candidates: `docs/embedding-model-candidates.md`.
    """)
    return


@app.cell
def _():
    import gc
    import time

    import altair as alt
    import marimo as mo
    import numpy as np
    import polars as pl
    import torch
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer, alt, gc, mo, np, pl, time, torch


@app.cell
def _(mo):
    # Settings: change these, the rest of the notebook follows
    REPO = mo.notebook_dir().parents[1]
    KB_PATH = REPO / "packages" / "retrieval" / "kb" / "snippets.jsonl"
    QUERIES_PATH = REPO / "data" / "eval" / "synthetic" / "retrieval" / "queries.jsonl"
    SPLIT = "validation"
    LANGUAGES = ["es", "pt", "en"]
    K_LIST = [1, 3, 5]  # the ranking is cut at max(K_LIST) before MRR, as the harness does
    TORCH_THREADS = 4  # same as the committed calibration report
    BOOTSTRAP, SEED = 2000, 0
    BASELINE = "minilm"
    HARRIER_INSTRUCTION = "Instruct: Given a bank customer's question, retrieve the policy passage that answers it\nQuery: "
    # Revisions pinned on 2026-10-01. Variants: (row name, query prefix, passage prefix).
    # MiniLM twice: e8f8c211 is the transformers-v5 tokenizer fix (same weights); 86741b4e is the pin in .env.example,
    # whose tokenizer_config loads a BertTokenizer under transformers 5.x that maps most words to <unk>
    MODELS = [
        {"model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
         "variants": [("minilm", "", "")]},
        {"model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "revision": "86741b4e3f5cb7765a600d3a3d55a0f6a6cb443d",
         "variants": [("minilm@env-pin", "", "")]},
        {"model_id": "intfloat/multilingual-e5-small", "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
         "variants": [("e5-small", "", ""), ("e5-small+prefix", "query: ", "passage: ")]},
        {"model_id": "ibm-granite/granite-embedding-97m-multilingual-r2", "revision": "835ad14087e140460703cf0fae09f97d469d65c2",
         "variants": [("granite-97m", "", "")]},
        {"model_id": "ibm-granite/granite-embedding-311m-multilingual-r2", "revision": "44399559930365213510b1ee2eb15ded83374f0e",
         "variants": [("granite-311m", "", "")]},
        {"model_id": "microsoft/harrier-oss-v1-270m", "revision": "31de22b673913c7d658c0f03f792d77c2dcf8ebd",
         "variants": [("harrier", "", ""), ("harrier+instruction", HARRIER_INSTRUCTION, "")]},
    ]
    # reports/calibration-embedding-2026-09-27.md: MiniLM (Hit@1, MRR) per language, and BM25 means over es/pt/en
    REPORT_MINILM = {"es": (0.492, 0.591), "pt": (0.458, 0.578), "en": (0.533, 0.646)}
    MATCH_TOLERANCE = 0.01  # one query out of 120 moves a score by 0.008
    BM25_REFERENCE = {"model": "bm25 (report)", "hit@1": 0.366, "hit@3": 0.525, "hit@5": 0.603, "mrr": 0.456,
                      "cross_hit@1": 0.144, "cross_mrr": 0.197, "p95_ms": 0.2}
    return (
        BASELINE,
        BM25_REFERENCE,
        BOOTSTRAP,
        KB_PATH,
        K_LIST,
        LANGUAGES,
        MATCH_TOLERANCE,
        MODELS,
        QUERIES_PATH,
        REPORT_MINILM,
        SEED,
        SPLIT,
        TORCH_THREADS,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - **The queries are synthetic and provisional** (`split: validation`); no human-written test set exists. With 120 queries per language, Hit@1 differences under ~0.09 are within sampling noise (`docs/embeddings.md`). The pooled 360-query bootstrap below is the fairer test.
    - **The queries avoid the KB's wording on purpose**, which favours meaning over keyword overlap. The BM25 row is copied from the report, not re-run.
    - **Gold is in-language only.** Same-language search ranks only the query's language; cross-language ranks only the other two, with the query's topic in those languages as gold (as `KnowledgeBase.cross_language_gold`).
    - **MTEB is not our task.** Public scores earned these models a place here, nothing more.
    - **Memory is the size of the weights as loaded** (parameters × bytes per parameter), not process RSS: models load in sequence in one process, where RSS deltas are unreliable. Runtime RAM on the Linux encoder is higher and still has to be measured there.
    - **MiniLM appears twice.** `minilm` is revision `e8f8c211`, the transformers-v5 tokenizer fix with the same weights, and is what the report measured. `minilm@env-pin` is `86741b4e`, the pin in `.env.example`: under transformers 5.x its tokenizer config loads a `BertTokenizer` that maps most words to `<unk>`.
    - **Weights load with the library default dtype**, as `SentenceTransformersAdapter` does. Granite and Harrier ship bf16; the `dtype` column shows what was actually loaded.
    - **The Harrier instruction is ours**, written for this domain as its card recommends; its built-in `web_search_query` prompt is not tested. Latency is one query at a time on this machine's CPU, encode plus ranking.
    """)
    return


@app.cell
def _(KB_PATH, QUERIES_PATH, SPLIT, mo, pl):
    mo.stop(
        not (KB_PATH.exists() and QUERIES_PATH.exists()),
        mo.md(f"**KB or queries not found:** `{KB_PATH}`, `{QUERIES_PATH}`."),
    )
    kb = pl.read_ndjson(KB_PATH)
    _queries = pl.read_ndjson(QUERIES_PATH).filter(pl.col("split") == SPLIT)
    # Cross-language gold: the topics of relevant_ids, in every language except the query's
    _topic_of = dict(zip(kb["id"], kb["topic_id"]))
    _snippets_of = {t: g["id"].to_list() for (t,), g in kb.group_by("topic_id")}
    _lang_of = dict(zip(kb["id"], kb["lang"]))
    queries = _queries.with_columns(
        cross_ids=pl.Series([
            sorted({s for r in rel for s in _snippets_of[_topic_of[r]] if _lang_of[s] != lang})
            for rel, lang in zip(_queries["relevant_ids"], _queries["lang"])
        ])
    )
    mo.hstack([kb.group_by("lang").len().sort("lang"), queries.group_by("lang").len().sort("lang")])
    return kb, queries


@app.cell
def _(np):
    def first_hit_rank(scores, doc_ids, gold, max_k):
        """Per query: 1-based rank of the first gold snippet in the top max_k (0 if missed), and the top-ranked id."""
        ranks, firsts = [], []
        for row, relevant in zip(np.argsort(-scores, axis=1)[:, :max_k], gold):
            ids = [doc_ids[i] for i in row]
            ranks.append(next((r for r, d in enumerate(ids, start=1) if d in relevant), 0))
            firsts.append(ids[0])
        return ranks, firsts

    return (first_hit_rank,)


@app.cell
def _(
    K_LIST,
    MODELS,
    SentenceTransformer,
    TORCH_THREADS,
    first_hit_rank,
    gc,
    kb,
    np,
    pl,
    queries,
    time,
    torch,
):
    torch.set_num_threads(TORCH_THREADS)
    _doc_ids, _passages = kb["id"].to_list(), [f"{t} {x}" for t, x in zip(kb["title"], kb["text"])]
    _same = queries["lang"].to_numpy()[:, None] == kb["lang"].to_numpy()[None, :]
    _rows, _costs = [], []
    for _spec in MODELS:
        gc.collect()
        _start = time.perf_counter()
        _model = SentenceTransformer(_spec["model_id"], revision=_spec["revision"], device="cpu")
        _load_s = time.perf_counter() - _start
        for _name, _query_prefix, _passage_prefix in _spec["variants"]:
            _docs = _model.encode([_passage_prefix + p for p in _passages], batch_size=32, normalize_embeddings=True)
            _model.encode([_query_prefix + queries["text"][0]], normalize_embeddings=True)  # warm-up
            _vectors, _latency = [], []
            for _text in queries["text"]:  # one query at a time, as kb.search does
                _t = time.perf_counter()
                _vectors.append(_model.encode([_query_prefix + _text], normalize_embeddings=True)[0])
                _docs @ _vectors[-1]
                _latency.append((time.perf_counter() - _t) * 1000)
            _scores = np.stack(_vectors) @ _docs.T
            _same_rank, _top1 = first_hit_rank(np.where(_same, _scores, -np.inf), _doc_ids, queries["relevant_ids"], max(K_LIST))
            _cross_rank, _ = first_hit_rank(np.where(~_same, _scores, -np.inf), _doc_ids, queries["cross_ids"], max(K_LIST))
            _rows.append(queries.select("id", "lang", "text", "relevant_ids").with_columns(
                model=pl.lit(_name), same_rank=pl.Series(_same_rank), top1=pl.Series(_top1), cross_rank=pl.Series(_cross_rank)))
            _costs.append({"model": _name, "dims": _docs.shape[1], "dtype": str(next(_model.parameters()).dtype),
                           "max_tokens": _model.max_seq_length, "load_s": round(_load_s, 1),
                           "p50_ms": round(float(np.percentile(_latency, 50)), 1), "p95_ms": round(float(np.percentile(_latency, 95)), 1),
                           "weights_mb": round(sum(p.numel() * p.element_size() for p in _model.parameters()) / 2**20),
                           "revision": _spec["revision"][:12]})
        del _model
    per_query = pl.concat(_rows)
    costs = pl.DataFrame(_costs)
    costs
    return costs, per_query


@app.cell
def _(K_LIST, pl):
    # Hit@k and MRR from a rank column (0 = not in the top max(K_LIST))
    def rank_metrics(column, prefix=""):
        _rank = pl.col(column)
        return [((_rank > 0) & (_rank <= k)).mean().round(3).alias(f"{prefix}hit@{k}") for k in K_LIST] + [
            pl.when(_rank > 0).then(1 / _rank).otherwise(0).mean().round(3).alias(f"{prefix}mrr")
        ]

    METRICS = rank_metrics("same_rank") + rank_metrics("cross_rank", "cross_")
    return (METRICS,)


@app.cell
def _(BASELINE, MATCH_TOLERANCE, METRICS, REPORT_MINILM, mo, per_query, pl):
    # Sanity check: the notebook must reproduce the harness's MiniLM numbers before anything else is trusted
    _check = per_query.filter(pl.col("model") == BASELINE).group_by("lang").agg(METRICS).select("lang", "hit@1", "mrr").with_columns(
        report_hit1=pl.col("lang").replace_strict({k: v[0] for k, v in REPORT_MINILM.items()}),
        report_mrr=pl.col("lang").replace_strict({k: v[1] for k, v in REPORT_MINILM.items()}),
    ).sort("lang")
    _ok = ((_check["hit@1"] - _check["report_hit1"]).abs().max() <= MATCH_TOLERANCE) and (
        (_check["mrr"] - _check["report_mrr"]).abs().max() <= MATCH_TOLERANCE)
    mo.vstack([
        mo.callout(mo.md("MiniLM matches the committed report." if _ok else "**MiniLM does not match the report:** the notebook and the harness disagree; fix that before reading the rest."),
                   kind="success" if _ok else "danger"),
        _check,
    ])
    return


@app.cell
def _(BM25_REFERENCE, METRICS, costs, per_query, pl):
    # Pooled over the 360 queries (equal to the mean of the three languages, 120 each)
    summary = per_query.group_by("model", maintain_order=True).agg(METRICS).join(
        costs.select("model", "dims", "dtype", "p95_ms", "weights_mb", "load_s"), on="model")
    pl.concat([summary, pl.DataFrame([BM25_REFERENCE])], how="diagonal_relaxed")
    return (summary,)


@app.cell
def _(LANGUAGES, per_query, pl):
    # Hit@1 by language: same-language and cross-language
    per_query.group_by("model", "lang", maintain_order=True).agg(
        hit1=(pl.col("same_rank") == 1).mean().round(3), cross_hit1=(pl.col("cross_rank") == 1).mean().round(3),
    ).pivot(on="lang", index="model", values=["hit1", "cross_hit1"]).select(
        "model", *[f"hit1_{lang}" for lang in LANGUAGES], *[f"cross_hit1_{lang}" for lang in LANGUAGES])
    return


@app.cell
def _(BASELINE, BOOTSTRAP, SEED, np, per_query, pl):
    # Paired bootstrap over queries: 95% CI of the Hit@1 difference against the baseline
    _rng = np.random.default_rng(SEED)
    _hits = per_query.sort("model", "id").with_columns(same=(pl.col("same_rank") == 1).cast(int), cross=(pl.col("cross_rank") == 1).cast(int))
    _base = _hits.filter(pl.col("model") == BASELINE)
    _samples = _rng.integers(0, _base.height, size=(BOOTSTRAP, _base.height))
    _rows = []
    for _model in [m for m in per_query["model"].unique(maintain_order=True) if m != BASELINE]:
        _cand = _hits.filter(pl.col("model") == _model)
        for _kind in ("same", "cross"):
            _diff = (_cand[_kind] - _base[_kind]).to_numpy()
            _low, _high = np.percentile(_diff[_samples].mean(axis=1), [2.5, 97.5])
            _rows.append({"model": _model, "search": _kind, "hit@1 diff": round(_diff.mean(), 3),
                          "ci_low": round(_low, 3), "ci_high": round(_high, 3), "excludes 0": bool(_low > 0 or _high < 0)})
    pl.DataFrame(_rows)
    return


@app.cell
def _(alt, summary):
    alt.Chart(summary, title="Same-language Hit@1 against p95 latency (size = weights in memory)").mark_circle(opacity=0.7).encode(
        x=alt.X("p95_ms:Q", title="p95 latency per query (ms, CPU)"),
        y=alt.Y("hit@1:Q", scale=alt.Scale(zero=False)),
        size=alt.Size("weights_mb:Q", title="Weights (MB)"),
        color="model:N",
        tooltip=["model", "hit@1", "mrr", "cross_hit@1", "p95_ms", "weights_mb", "dims", "dtype"],
    )
    return


@app.cell
def _(pl, summary):
    # Prefix effect: what the adapter's prefix option would be worth
    summary.filter(pl.col("model").str.starts_with("e5") | pl.col("model").str.starts_with("harrier")).select(
        "model", "hit@1", "mrr", "cross_hit@1", "cross_mrr")
    return


@app.cell
def _(mo, per_query):
    picked = mo.ui.dropdown(per_query["model"].unique(maintain_order=True).to_list(), value=per_query["model"][0], label="Misses for")
    picked
    return (picked,)


@app.cell
def _(kb, mo, per_query, picked, pl):
    # Same-language queries the picked model does not rank first, with the snippet it put first
    mo.ui.table(
        per_query.filter((pl.col("model") == picked.value) & (pl.col("same_rank") != 1))
        .join(kb.select(pl.col("id").alias("top1"), pl.col("title").alias("top1_title")), on="top1")
        .select("lang", "text", "relevant_ids", "same_rank", "top1", "top1_title")
    )
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
