"""Automated quality gate for the pt-BR decision dataset (plan step 4).

Reads data/staging/decision_pt/decision.pt.{train,validation,test.provisional}.jsonl, writes
checks.md next to them and exits 1 if a hard check fails. There is no human review of this
dataset, so these checks are the only quality evidence (docs/limitations.md).

Hard checks: format and exact offsets, counts per intent, no duplicate or near-duplicate text
across splits, no 8-word run shared with a real complaint, no PII outside filled slots.
Reported only: near-duplicates within a split, out-of-fold label consistency, a TF-IDF
train→test score, and authenticity markers.
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

DEFAULT_DIR = Path("data/staging/decision_pt")
SCHEMA_PATH = Path("data/eval/synthetic/schema.yaml")
RAW_FILE = Path("data/raw/complaints_br/db_reclamacoes_clean.parquet")
SPLITS = {"train": "decision.pt.train.jsonl", "validation": "decision.pt.validation.jsonl",
          "test": "decision.pt.test.provisional.jsonl"}
EXPECTED_PER_INTENT = {"train": 100, "validation": 50, "test": 50}
LONG_SHARE, LONG_TOLERANCE = 0.25, 0.05
NEAR_DUP = 0.9
MAX_WITHIN_NEAR_DUP_RATE = 0.01
LEAK_NGRAM = 8
REQUIRED = ("id", "text", "lang", "intent", "slots", "split", "source")
PII = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\+?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}|[\w.+-]+@[\w-]+\.\w+"
                 r"|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|\d{6,}")
BR_MARKERS = r"(?i)\b(você|vc|vcs|a gente|pra|tá|tô|cadê|fatura|pix|boleto|estorno|r\$|reais|beleza|valeu|obrigad[oa]|oxe|uai|bah)\b"
FOREIGN_MARKERS = r"(?i)\b(telemóvel|multibanco|estás|tens|vós|usted|tarjeta|cuenta|necesito|quiero|gracias|ahorita)\b"


def normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def load(data_dir: Path) -> pl.DataFrame:
    frames = []
    for split, name in SPLITS.items():
        path = data_dir / name
        if not path.exists():
            raise SystemExit(f"Missing {path}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        frames.append(pl.DataFrame(rows).with_columns(file_split=pl.lit(split)))
    return pl.concat(frames, how="diagonal_relaxed")


def check_format(df: pl.DataFrame, schema: dict) -> list[str]:
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
        if row["lang"] != "pt":
            errors.append(f"{row['id']}: lang {row['lang']}")
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
    for text, split in zip(norm, splits):
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


def check_leakage(df: pl.DataFrame, raw_file: Path) -> list[str]:
    words = lambda t: re.findall(r"\w+", t.lower())  # noqa: E731
    grams: dict[tuple, set[str]] = {}
    for row_id, text in df.select("id", "text").iter_rows():
        w = words(text)
        for k in range(len(w) - LEAK_NGRAM + 1):
            grams.setdefault(tuple(w[k:k + LEAK_NGRAM]), set()).add(row_id)
    leaks: set[str] = set()
    complaints = pl.read_parquet(raw_file, columns=["source", "ask"]).filter(pl.col("source") == "reclame_aqui")["ask"]
    for text in complaints:
        w = words(text)
        for k in range(len(w) - LEAK_NGRAM + 1):
            leaks |= grams.get(tuple(w[k:k + LEAK_NGRAM]), set())
    return [f"{row_id}: shares an {LEAK_NGRAM}-word run with a real complaint" for row_id in sorted(leaks)]


def check_pii(df: pl.DataFrame) -> list[str]:
    errors = []
    for row_id, text, slots in df.select("id", "text", "slots").iter_rows():
        chars = list(text)
        for slot in slots:
            chars[slot["start"]:slot["end"]] = ["_"] * (slot["end"] - slot["start"])
        if PII.search("".join(chars)):
            errors.append(f"{row_id}: PII-like text outside slots")
    return errors


def label_report(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    model = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True),
                          LogisticRegression(max_iter=2000))
    fit = df.filter(pl.col("file_split") != "test")
    proba = cross_val_predict(model, fit["text"].to_list(), fit["intent"].to_list(), cv=5, method="predict_proba")
    classes = sorted(fit["intent"].unique().to_list())
    own = [proba[i, classes.index(label)] for i, label in enumerate(fit["intent"])]
    per_intent = fit.with_columns(own_prob=pl.Series(own), oof=pl.Series([classes[j] for j in proba.argmax(1)])).group_by("intent").agg(
        oof_accuracy=(pl.col("oof") == pl.col("intent")).mean().round(3), flagged=(pl.col("own_prob") < 0.1).sum()).sort("oof_accuracy")
    test = df.filter(pl.col("file_split") == "test")
    predicted = model.fit(fit["text"].to_list(), fit["intent"].to_list()).predict(test["text"].to_list())
    summary = {"TF-IDF train+validation → test accuracy": round(accuracy_score(test["intent"], predicted), 3),
               "TF-IDF train+validation → test macro-F1": round(f1_score(test["intent"], predicted, average="macro"), 3)}
    return per_intent, summary


def authenticity(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(br=pl.col("text").str.contains(BR_MARKERS), foreign=pl.col("text").str.contains(FOREIGN_MARKERS),
                           words=pl.col("text").str.count_matches(r"\S+")).group_by("file_split").agg(
        br_marker_share=pl.col("br").mean().round(3), foreign_marker_rows=pl.col("foreign").sum(),
        median_words=pl.col("words").median(), p90_words=pl.col("words").quantile(0.9)).sort("file_split")


def table(frame: pl.DataFrame) -> str:
    head = "| " + " | ".join(frame.columns) + " |\n|" + "---|" * len(frame.columns) + "\n"
    return head + "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in frame.iter_rows())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--raw-file", type=Path, default=RAW_FILE)
    args = parser.parse_args()

    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    df = load(args.data_dir)
    hard: dict[str, list[str]] = {"format and offsets": check_format(df, schema)}
    hard["counts"], mix = check_counts(df, schema)
    hard["duplicates"], dup_report = check_duplicates(df)
    hard["source leakage"] = check_leakage(df, args.raw_file) if args.raw_file.exists() else [f"raw file {args.raw_file} not found"]
    hard["PII outside slots"] = check_pii(df)
    per_intent, summary = label_report(df)

    lines = ["# pt-BR decision dataset: automated checks\n",
             "Generated by `make check-data-pt` (`tools/synthdata_pt/checks.py`). No human has reviewed this dataset.\n",
             "## Hard checks\n", "| Check | Result |\n|---|---|\n"]
    lines += [f"| {name} | {'PASS' if not errs else f'FAIL ({len(errs)})'} |\n" for name, errs in hard.items()]
    for name, errs in hard.items():
        if errs:
            lines += [f"\n### {name}\n\n"] + [f"- {e}\n" for e in errs[:50]]
    lines += ["\n## Mix per split\n\n", table(mix), "\n## Duplicates\n\n"]
    lines += [f"- {k}: {v}\n" for k, v in dup_report.items()]
    lines += ["\n## Label consistency (5-fold out-of-fold TF-IDF + LR on train + validation)\n\n", table(per_intent), "\n"]
    lines += [f"- {k}: {v}\n" for k, v in summary.items()]
    lines += ["\n## Authenticity\n\n", table(authenticity(df))]
    out = args.data_dir / "checks.md"
    out.write_text("".join(lines), encoding="utf-8")

    failed = [name for name, errs in hard.items() if errs]
    print(f"Wrote {out}. Rows: {dict(Counter(df['file_split']))}.", "FAILED: " + ", ".join(failed) if failed else "All hard checks passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
