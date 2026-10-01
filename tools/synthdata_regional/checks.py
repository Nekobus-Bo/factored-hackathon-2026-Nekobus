"""Automated quality gate for a regional decision dataset (pt-BR, es-MX, es-AR).

Reads the locale's decision.<stem>.{train,validation,test.provisional}.jsonl, writes checks.md
next to them and exits 1 if a hard check fails. There is no human review of these datasets, so
these checks are the only quality evidence (docs/limitations.md).

Hard checks: format and exact offsets, counts per intent, no duplicate or near-duplicate text
across splits, no 8-word run shared with a real source text, no PII outside filled slots, and
foreign-variety markers in at most 1% of rows. Where the source ships rejected LLM rows (es-MX,
es-AR), also: a length spread and register closer to the real reviews than to the rejects, and
no slang term in more than 2% of rows.
Reported only: near-duplicates within a split, out-of-fold label consistency, a TF-IDF
train→test score, authenticity markers and a real-review country classifier.

Usage: python -m tools.synthdata_regional.checks --locale es-MX
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import polars as pl
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import make_pipeline

from tools.synthdata_regional import register
from tools.synthdata_regional.locales import LOCALES, REPO, Locale, get_locale

SCHEMA_PATH = REPO / "data" / "eval" / "synthetic" / "schema.yaml"
EXPECTED_PER_INTENT = {"train": 100, "validation": 50, "test": 50}
LONG_SHARE, LONG_TOLERANCE = 0.25, 0.05
NEAR_DUP = 0.9
MAX_WITHIN_NEAR_DUP_RATE = 0.01
LEAK_NGRAM = 8
REQUIRED = ("id", "text", "lang", "intent", "slots", "split", "source")
MAX_FOREIGN_RATE = 0.01
MIN_CV_RATIO = 2.0  # the dataset's word-count spread must be at least this multiple of the rejects'
MAX_SLANG_TERM_RATE = 0.02


def normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load(loc: Locale, data_dir: Path) -> pl.DataFrame:
    frames = []
    for split, name in loc.splits.items():
        path = data_dir / name
        if not path.exists():
            raise SystemExit(f"Missing {path}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        frames.append(pl.DataFrame(rows).with_columns(file_split=pl.lit(split)))
    return pl.concat(frames, how="diagonal_relaxed")


def check_format(df: pl.DataFrame, schema: dict, loc: Locale) -> list[str]:
    intents = {i["name"] for i in schema["intents"]}
    slot_types = {s["name"] for s in schema["slots"]}
    errors = []
    for row in df.iter_rows(named=True):
        missing = [k for k in REQUIRED if row.get(k) is None]
        if missing:
            errors.append(f"{row.get('id')}: missing {missing}")
            continue
        if row["intent"] not in intents:
            errors.append(f"{row['id']}: unknown intent {row['intent']}")
        if row["lang"] != loc.lang:
            errors.append(f"{row['id']}: lang {row['lang']}")
        if loc.record_locale and row.get("locale") != loc.code:
            errors.append(f"{row['id']}: locale {row.get('locale')}")
        if row["split"] != row["file_split"]:
            errors.append(f"{row['id']}: split {row['split']} in {row['file_split']} file")
        for slot in row["slots"]:
            if slot["type"] not in slot_types:
                errors.append(f"{row['id']}: unknown slot {slot['type']}")
            if row["text"][slot["start"]:slot["end"]] != slot["value"] or slot["value"] != slot["value"].strip():
                errors.append(f"{row['id']}: bad offsets for {slot['type']}")
    if df["id"].n_unique() != df.height:
        errors.append("duplicate ids")
    return errors


def check_counts(df: pl.DataFrame, schema: dict) -> tuple[list[str], pl.DataFrame]:
    intents = [i["name"] for i in schema["intents"]]
    counts = df.group_by("file_split", "intent").len()
    errors = []
    for split, expected in EXPECTED_PER_INTENT.items():
        got = dict(counts.filter(pl.col("file_split") == split).select("intent", "len").iter_rows())
        errors += [f"{split}/{i}: {got.get(i, 0)} rows, expected {expected}" for i in intents if got.get(i, 0) != expected]
    mix = df.group_by("file_split").agg(rows=pl.len(), long_share=(pl.col("length") == "long").mean().round(3)).sort("file_split")
    errors += [f"{s}: long share {share}" for s, share in mix.select("file_split", "long_share").iter_rows()
               if abs(share - LONG_SHARE) > LONG_TOLERANCE]
    return errors, mix


def check_duplicates(df: pl.DataFrame) -> tuple[list[str], dict]:
    norm = [normalise(t) for t in df["text"]]
    splits = df["file_split"].to_list()
    errors, report = [], {}
    seen: dict[str, str] = {}
    for text, split in zip(norm, splits, strict=True):
        if text in seen and seen[text] != split:
            errors.append(f"exact duplicate across {seen[text]} and {split}: {text!r}")
        seen.setdefault(text, split)
    vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(norm)
    for split in EXPECTED_PER_INTENT:
        idx = [i for i, s in enumerate(splits) if s == split]
        sims = (vectors[idx] @ vectors[idx].T).toarray()
        for k in range(len(idx)):
            sims[k, k] = 0
        near_rows = int((sims.max(axis=1) >= NEAR_DUP).sum())
        report[f"near-duplicate rows within {split}"] = f"{near_rows} ({near_rows / len(idx):.1%})"
        if near_rows / len(idx) > MAX_WITHIN_NEAR_DUP_RATE:
            errors.append(f"{split}: near-duplicate rate {near_rows / len(idx):.1%} above {MAX_WITHIN_NEAR_DUP_RATE:.0%}")
    for newer, older in (("validation", ["train"]), ("test", ["train", "validation"])):
        a = [i for i, s in enumerate(splits) if s == newer]
        b = [i for i, s in enumerate(splits) if s in older]
        crossing = int(((vectors[a] @ vectors[b].T).max(axis=1).toarray().ravel() >= NEAR_DUP).sum())
        report[f"{newer} rows near a {'/'.join(older)} row"] = crossing
        if crossing:
            errors.append(f"{crossing} {newer} rows are near-duplicates of {'/'.join(older)} rows")
    return errors, report


def source_texts(loc: Locale, raw_file: Path, *, all_sources: bool) -> pl.Series:
    raw = pl.read_parquet(raw_file, columns=["source", "ask"])
    return (raw if all_sources else raw.filter(pl.col("source") == loc.raw_source))["ask"]


def check_leakage(df: pl.DataFrame, loc: Locale, raw_file: Path) -> list[str]:
    words = lambda t: re.findall(r"\w+", t.lower())  # noqa: E731
    grams: dict[tuple, set[str]] = {}
    for row_id, text in df.select("id", "text").iter_rows():
        w = words(text)
        for k in range(len(w) - LEAK_NGRAM + 1):
            grams.setdefault(tuple(w[k:k + LEAK_NGRAM]), set()).add(row_id)
    leaks: set[str] = set()
    for text in source_texts(loc, raw_file, all_sources=loc.leak_all_sources):
        w = words(text)
        for k in range(len(w) - LEAK_NGRAM + 1):
            leaks |= grams.get(tuple(w[k:k + LEAK_NGRAM]), set())
    return [f"{row_id}: shares an {LEAK_NGRAM}-word run with a source text" for row_id in sorted(leaks)]


def check_pii(df: pl.DataFrame, loc: Locale) -> list[str]:
    pii = re.compile(loc.pii_rx)
    errors = []
    for row_id, text, slots in df.select("id", "text", "slots").iter_rows():
        chars = list(text)
        for slot in slots:
            chars[slot["start"]:slot["end"]] = ["_"] * (slot["end"] - slot["start"])
        if pii.search("".join(chars)):
            errors.append(f"{row_id}: PII-like text outside slots")
    return errors


def check_purity(df: pl.DataFrame, loc: Locale) -> tuple[list[str], pl.DataFrame]:
    """Markers of another variety (another country, Portugal/Spain, the other language) must stay rare."""
    marked = df.with_columns(foreign=pl.col("text").str.extract_all(loc.foreign_markers))
    per_split = marked.group_by("file_split").agg(rows=pl.len(), foreign_rows=(pl.col("foreign").list.len() > 0).sum()).sort("file_split")
    errors = [f"{s}: {n} of {rows} rows ({n / rows:.1%}) carry foreign-variety markers"
              for s, rows, n in per_split.iter_rows() if n / rows > MAX_FOREIGN_RATE]
    top = Counter(w.lower() for ws in marked["foreign"] for w in ws).most_common(10)
    if errors and top:
        errors.append("most frequent: " + ", ".join(f"{w} ({n})" for w, n in top))
    return errors, per_split


def check_register(df: pl.DataFrame, loc: Locale, raw_file: Path) -> tuple[dict[str, list[str]], pl.DataFrame, dict]:
    """Compare the dataset with the real reviews and, where the source has them, with its rejected LLM rows.

    Without rejected rows (es-CO) only the slang cap gates; the profiles are still reported."""
    raw = pl.read_parquet(raw_file, columns=["source", "ask"])
    real = raw.filter(pl.col("source") == loc.raw_source)["ask"].unique().to_list()
    bad = raw.filter(pl.col("source") == loc.bad_source)["ask"].unique().to_list() if loc.bad_source else []
    texts = df["text"].to_list()
    long_texts = df.filter(pl.col("length") == "long")["text"].to_list()
    profiles = {"real reviews": register.profile(real, loc), **({"rejected LLM rows": register.profile(bad, loc)} if bad else {}),
                "dataset": register.profile(texts, loc), "dataset, long rows": register.profile(long_texts, loc)}
    ours, r = profiles["dataset"], profiles["real reviews"]
    d_real = register.distance(ours, r)
    errors: dict[str, list[str]] = {"slang cap": []} if not bad else {"length spread": [], "register": [], "slang cap": []}
    shares = register.slang_shares(texts, loc)
    errors["slang cap"] = [f"'{w}' in {s:.1%} of rows" for w, s in shares.items() if s > MAX_SLANG_TERM_RATE]
    slang_summary = ", ".join(f"{w} {s:.1%}" for w, s in list(shares.items())[:5] if s > 0) or "none"
    table_rows = [{"set": name, **{k: v for k, v in p.items() if k != "messages"}, "rows": int(p["messages"])} for name, p in profiles.items()]
    if not bad:
        summary = {"register distance to real reviews": d_real, "most frequent slang terms": slang_summary}
        return errors, pl.DataFrame(table_rows), summary
    b = profiles["rejected LLM rows"]
    d_bad = register.distance(ours, b)
    if ours["words_cv"] < MIN_CV_RATIO * b["words_cv"]:
        errors["length spread"].append(f"word-count CV {ours['words_cv']} below {MIN_CV_RATIO}× the rejects' {b['words_cv']}")
    if profiles["dataset, long rows"]["ends_request"] >= b["ends_request"]:
        errors["length spread"].append(f"long rows end in a request as often as the rejects ({profiles['dataset, long rows']['ends_request']} ≥ {b['ends_request']})")
    if d_real >= d_bad:
        errors["register"].append(f"register distance to real reviews {d_real} is not below the distance to the rejects {d_bad}")
    summary = {"register distance to real reviews": d_real, "register distance to rejected rows": d_bad,
               "most frequent slang terms": slang_summary}
    return errors, pl.DataFrame(table_rows), summary


def country_report(df: pl.DataFrame, loc: Locale) -> pl.DataFrame:
    """A TF-IDF classifier trained on real reviews of both countries: share of our rows it assigns to ours."""
    own = pl.read_parquet(loc.raw_file, columns=["source", "ask"]).filter(pl.col("source") == loc.raw_source)["ask"]
    other = pl.read_parquet(loc.contrast_raw_file, columns=["source", "ask"]).filter(pl.col("source") == loc.raw_source)["ask"]
    n = min(own.len(), other.len())
    texts = own.sample(n, seed=0).to_list() + other.sample(n, seed=0).to_list()
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=3, sublinear_tf=True), LogisticRegression(max_iter=2000))
    model.fit(texts, [1] * n + [0] * n)
    return df.with_columns(own_country=pl.Series(model.predict_proba(df["text"].to_list())[:, 1] >= 0.5)).group_by("file_split").agg(
        rows=pl.len(), assigned_to_own_country=pl.col("own_country").mean().round(3)).sort("file_split")


def label_report(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    model = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True),
                          LogisticRegression(max_iter=2000))
    fit = df.filter(pl.col("file_split") != "test")
    proba = cross_val_predict(model, fit["text"].to_list(), fit["intent"].to_list(), cv=5, method="predict_proba")
    classes = sorted(fit["intent"].unique().to_list())
    own = [proba[i, classes.index(label)] for i, label in enumerate(fit["intent"])]
    per_intent = fit.with_columns(own_prob=pl.Series(own), oof=pl.Series([classes[j] for j in proba.argmax(1)])).group_by("intent").agg(
        oof_accuracy=(pl.col("oof") == pl.col("intent")).mean().round(3), flagged=(pl.col("own_prob") < 0.1).sum()).sort("oof_accuracy", "intent")
    test = df.filter(pl.col("file_split") == "test")
    predicted = model.fit(fit["text"].to_list(), fit["intent"].to_list()).predict(test["text"].to_list())
    summary = {"TF-IDF train+validation → test accuracy": round(accuracy_score(test["intent"], predicted), 3),
               "TF-IDF train+validation → test macro-F1": round(f1_score(test["intent"], predicted, average="macro"), 3)}
    return per_intent, summary


def authenticity(df: pl.DataFrame, loc: Locale) -> pl.DataFrame:
    return df.with_columns(local=pl.col("text").str.contains(loc.local_markers), foreign=pl.col("text").str.contains(loc.foreign_markers),
                           words=pl.col("text").str.count_matches(r"\S+")).group_by("file_split").agg(
        local_marker_share=pl.col("local").mean().round(3), foreign_marker_rows=pl.col("foreign").sum(),
        median_words=pl.col("words").median(), p90_words=pl.col("words").quantile(0.9)).sort("file_split")


def table(frame: pl.DataFrame) -> str:
    head = "| " + " | ".join(frame.columns) + " |\n|" + "---|" * len(frame.columns) + "\n"
    return head + "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in frame.iter_rows())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locale", required=True, choices=list(LOCALES))
    parser.add_argument("--data-dir", type=Path, help="defaults to the locale's staging directory")
    parser.add_argument("--raw-file", type=Path, help="defaults to the locale's source file")
    args = parser.parse_args()
    loc = get_locale(args.locale)
    data_dir, raw_file = args.data_dir or loc.out_dir, args.raw_file or loc.raw_file

    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    df = load(loc, data_dir)
    hard: dict[str, list[str]] = {"format and offsets": check_format(df, schema, loc)}
    hard["counts"], mix = check_counts(df, schema)
    hard["duplicates"], dup_report = check_duplicates(df)
    hard["source leakage"] = check_leakage(df, loc, raw_file) if raw_file.exists() else [f"raw file {raw_file} not found"]
    hard["PII outside slots"] = check_pii(df, loc)
    hard["regional purity"], purity = check_purity(df, loc)
    register_table = None
    if loc.lang == "es" and raw_file.exists():
        register_errors, register_table, register_summary = check_register(df, loc, raw_file)
        hard.update(register_errors)
    per_intent, summary = label_report(df)

    lines = [f"# {loc.code} decision dataset: automated checks\n",
             f"Generated by `make check-data LOCALE={loc.code}` (`tools/synthdata_regional/checks.py`). No human has reviewed this dataset.\n",
             "## Hard checks\n", "| Check | Result |\n|---|---|\n"]
    lines += [f"| {name} | {'PASS' if not errs else f'FAIL ({len(errs)})'} |\n" for name, errs in hard.items()]
    for name, errs in hard.items():
        if errs:
            lines += [f"\n### {name}\n\n"] + [f"- {e}\n" for e in errs[:50]]
    lines += ["\n## Mix per split\n\n", table(mix), "\n## Duplicates\n\n"]
    lines += [f"- {k}: {v}\n" for k, v in dup_report.items()]
    lines += ["\n## Regional purity\n\n", table(purity)]
    if register_table is not None:
        title = "dataset vs real reviews vs rejected LLM rows" if loc.bad_source else "dataset vs real source text"
        lines += [f"\n## Register: {title}\n\n", table(register_table), "\n"]
        lines += [f"- {k}: {v}\n" for k, v in register_summary.items()]
    lines += ["\n## Label consistency (5-fold out-of-fold TF-IDF + LR on train + validation)\n\n", table(per_intent), "\n"]
    lines += [f"- {k}: {v}\n" for k, v in summary.items()]
    lines += ["\n## Authenticity\n\n", table(authenticity(df, loc))]
    if loc.contrast_raw_file is not None and loc.contrast_raw_file.exists():
        lines += ["\n## Country classifier trained on real reviews (report only)\n\n", table(country_report(df, loc))]
    out = data_dir / "checks.md"
    out.write_text("".join(lines), encoding="utf-8")

    failed = [name for name, errs in hard.items() if errs]
    print(f"Wrote {out}. Rows: {dict(Counter(df['file_split']))}.", "FAILED: " + ", ".join(failed) if failed else "All hard checks passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
