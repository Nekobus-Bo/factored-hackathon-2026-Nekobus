"""Quality report for the regional kb.search test questions: data/eval/synthetic/retrieval/regional/checks.md.

Counts, duplicates, source leaks, PII, foreign-variety markers, how close the typing is to the
real texts (half-B style card) compared with the older synthetic set, the rewrite step, BM25
Hit@1 as a measure of how lexical the questions are, and possible label drift (questions where
two embedding models agree on another topic). It reports; it does not drop rows.
"""

import re
from pathlib import Path

import polars as pl
import yaml

from tools.synthdata_regional.checks import check_leakage, check_pii, table
from tools.synthdata_regional.locales import LOCALES, get_locale
from tools.synthdata_regional.register import SHARE_FEATURES, distance, profile
from tools.synthdata_regional.retrieval import KB_PATH, OLD_QUERIES, OUT_DIR

DRIFT_MODELS = {
    "minilm": ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"),
    "granite": ("ibm-granite/granite-embedding-311m-multilingual-r2", "44399559930365213510b1ee2eb15ded83374f0e"),
}


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def counts(df: pl.DataFrame) -> pl.DataFrame:
    return df.group_by("locale", "kind").agg(
        rows=pl.len(), long=(pl.col("length") == "long").sum(), topics=pl.col("topic_id").n_unique(),
    ).sort("locale", "kind")


def integrity(df: pl.DataFrame) -> tuple[list[str], pl.DataFrame]:
    """Duplicates, leaks, PII and foreign markers per locale; any error is a failed check."""
    errors, rows = [], []
    dup = df.with_columns(n=pl.col("text").map_elements(_norm, return_dtype=pl.String)).filter(pl.col("n").is_duplicated())
    errors += [f"{i}: duplicate text" for i in dup["id"]]
    for code in LOCALES:
        part = df.filter(pl.col("locale") == code)
        if not part.height:
            continue
        loc = get_locale(code)
        leaks = check_leakage(part, loc, loc.raw_file)
        pii = check_pii(part.with_columns(slots=pl.Series([[] for _ in range(part.height)],
                                                          dtype=pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64})))), loc)
        foreign = part.filter(pl.col("text").str.contains(loc.foreign_markers)).height if loc.foreign_markers else 0
        errors += leaks + pii + ([f"{code}: {foreign} rows with foreign-variety markers"] if foreign else [])
        rows.append({"locale": code, "rows": part.height, "source leaks": len(leaks), "PII outside slots": len(pii),
                     "foreign markers": foreign})
    return errors, pl.DataFrame(rows)


def register_table(df: pl.DataFrame) -> pl.DataFrame:
    """Typing profile of the real texts (half-B card), this set and the older synthetic set."""
    old = pl.read_ndjson(OLD_QUERIES)
    rows = []
    for code in LOCALES:
        part = df.filter(pl.col("locale") == code)
        if not part.height:
            continue
        loc = get_locale(code)
        real = yaml.safe_load((loc.out_dir / "style_cards.B.yaml").read_text())["register"].get("typing")
        ours = profile(part["text"].to_list(), loc)
        before = profile(old.filter(pl.col("lang") == loc.lang)["text"].to_list(), loc)
        for name, prof in (("real texts (half B)", real), ("regional set", ours), ("older synthetic set", before)):
            if prof is None:
                continue
            rows.append({"locale": code, "texts": name, "median words": prof["median_words"],
                         **{f: round(prof[f], 3) for f in SHARE_FEATURES},
                         "L1 to real": distance(prof, real) if real else None})
    return pl.DataFrame(rows)


def rewrite_table(df: pl.DataFrame) -> pl.DataFrame:
    return df.group_by("locale").agg(
        empty=(pl.col("kb_query").str.len_chars() == 0).sum(),
        same_as_message=(pl.col("kb_query").map_elements(_norm, return_dtype=pl.String)
                         == pl.col("text").map_elements(_norm, return_dtype=pl.String)).sum(),
        median_message_words=pl.col("text").str.count_matches(r"\S+").median(),
        median_query_words=pl.col("kb_query").str.count_matches(r"\S+").median(),
    ).sort("locale")


def bm25_table(df: pl.DataFrame) -> pl.DataFrame:
    """Same-language BM25 Hit@1 on answerable questions: how much keyword overlap they carry."""
    from retrieval import BM25Adapter, KBSnippet

    kb = [KBSnippet(**r) for r in pl.read_ndjson(KB_PATH).to_dicts()]
    old = pl.read_ndjson(OLD_QUERIES).with_columns(locale=pl.lit("older set"))
    rows = []
    for name, frame in (("regional set", df.filter(pl.col("relevant_ids").list.len() > 0)), ("older set", old)):
        for (lang,), part in frame.group_by("lang", maintain_order=True):
            bm25 = BM25Adapter()
            bm25.index([s for s in kb if s.lang == lang])
            hits = [bm25.search(t, top_k=1)[0][0] in gold for t, gold in zip(part["text"], part["relevant_ids"], strict=True)]
            rows.append({"set": name, "lang": lang, "questions": part.height, "BM25 Hit@1": round(sum(hits) / len(hits), 3)})
    return pl.DataFrame(rows).sort("set", "lang")


def drift_table(df: pl.DataFrame) -> pl.DataFrame | str:
    """Answerable questions where both models put the same other topic first: the gold may be wrong."""
    try:
        from retrieval.adapters.sentence_transformers import SentenceTransformersAdapter
    except ImportError:
        return "skipped: needs sentence-transformers (the `vector` extra of packages/retrieval)"
    import numpy as np

    kb = pl.read_ndjson(KB_PATH)
    answerable = df.filter(pl.col("relevant_ids").list.len() > 0)
    firsts = {}
    for name, (model_id, revision) in DRIFT_MODELS.items():
        from sentence_transformers import SentenceTransformer

        SentenceTransformer(model_id, revision=revision, device="cpu")  # pin the revision in the HF cache
        adapter = SentenceTransformersAdapter(model_id=model_id)
        docs = adapter.embed([f"{t} {x}" for t, x in zip(kb["title"], kb["text"], strict=True)])
        queries = adapter.embed(answerable["text"].to_list())
        scores = np.where(answerable["lang"].to_numpy()[:, None] == kb["lang"].to_numpy()[None, :], queries @ docs.T, -np.inf)
        firsts[name] = [kb["id"][int(i)] for i in scores.argmax(axis=1)]
    flagged = answerable.with_columns(**{f"{n}_first": pl.Series(v) for n, v in firsts.items()}).filter(
        (pl.col("minilm_first") == pl.col("granite_first"))
        & ~pl.col("relevant_ids").list.contains(pl.col("granite_first"))
    )
    return flagged.select("id", "locale", "text", "relevant_ids", pl.col("granite_first").alias("both models chose"))


def write_checks(df: pl.DataFrame, out_dir: Path = OUT_DIR) -> list[str]:
    errors, integrity_rows = integrity(df)
    drift = drift_table(df)
    drift_md = drift if isinstance(drift, str) else (
        f"{drift.height} of {df.filter(pl.col('relevant_ids').list.len() > 0).height} answerable questions. "
        "Listed, not removed: dropping them would bias the set toward the two models.\n\n"
        + (table(drift.with_columns(pl.col("relevant_ids").list.join(", "))) if drift.height else ""))
    text = "\n".join([
        "# Regional kb.search test questions: checks",
        "",
        f"Generated by `make synth-retrieval-regional` (`tools/synthdata_regional/retrieval.py`), generator `{df['model'][0]}`. Provisional: LLM-written, not reviewed by a human.",
        "",
        f"**Gate:** {'PASS' if not errors else 'FAIL'} ({len(errors)} problems)",
        *(f"- {e}" for e in errors[:50]),
        "",
        "## Counts",
        "",
        table(counts(df)),
        "## Integrity",
        "",
        table(integrity_rows),
        "## Typing compared with real customers",
        "",
        "Shares of messages with each trait. `L1 to real` sums the absolute differences from the real texts; lower is closer.",
        "",
        table(register_table(df)),
        "## Rewrite step (the query the orchestrator's LLM sends to kb_search)",
        "",
        table(rewrite_table(df)),
        "## Keyword overlap",
        "",
        "Same-language BM25 Hit@1 on answerable questions. Lower means the questions share fewer words with their gold snippet.",
        "",
        table(bm25_table(df)),
        "## Possible label drift",
        "",
        drift_md,
    ])
    (out_dir / "checks.md").write_text(text + "\n")
    print(f"checks: {'PASS' if not errors else 'FAIL'} ({len(errors)} problems) → {out_dir / 'checks.md'}")
    return errors
