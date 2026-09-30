"""Pool the regional decision datasets into the DistilBERT's training splits.

Reads each locale's decision.<stem>.{train,validation,test.provisional}.jsonl (pt-BR,
es-MX, es-AR) and writes
data/staging/decision_pooled/decision.pooled.{train,validation,test}.jsonl:

- every row keeps its fields; pt-BR rows, which predate the `locale` field, get "pt-BR";
- the English rows of the versioned template splits (data/eval/synthetic, lang "en") are
  appended to validation and test only: the model is not trained on English, but its
  English threshold is calibrated on them (ADR-0014). They carry no locale, so they
  calibrate the `en` key;
- rows keep their order, locale by locale, so a rerun writes identical bytes.

A missing input split fails with the command that builds it.

Usage: python -m tools.synthdata_regional.pool
"""

import argparse
import json
import sys
from pathlib import Path

from tools.synthdata_regional.locales import LOCALES, REPO

OUT_DIR = REPO / "data" / "staging" / "decision_pooled"
STEM = "decision.pooled"
TEMPLATE_DIR = REPO / "data" / "eval" / "synthetic"
TEMPLATE_SPLITS = {
    "validation": "decision.validation.jsonl",
    "test": "decision.test.provisional.jsonl",
}
EXTRA_LANG = "en"


def read_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pooled_split(
    split: str, locales=LOCALES, template_dir: Path = TEMPLATE_DIR
) -> list[dict]:
    rows: list[dict] = []
    for code, loc in locales.items():
        path = loc.out_dir / loc.splits[split]
        if not path.is_file():
            hint = "build-test-regional" if split == "test" else "synth-data-regional"
            raise FileNotFoundError(
                f"{path} is missing: run `make {hint} LOCALE={code}` first"
            )
        for row in read_rows(path):
            rows.append({**row, "locale": row.get("locale") or code})
    if split in TEMPLATE_SPLITS:
        extra = [
            r
            for r in read_rows(template_dir / TEMPLATE_SPLITS[split])
            if r["lang"] == EXTRA_LANG
        ]
        rows.extend({k: v for k, v in r.items() if k != "locale"} for r in extra)
    return rows


def write_split(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    try:
        splits = {
            split: pooled_split(split) for split in ("train", "validation", "test")
        }
    except FileNotFoundError as exc:
        print(f"pool: {exc}", file=sys.stderr)
        return 1
    for split, rows in splits.items():
        path = args.out_dir / f"{STEM}.{split}.jsonl"
        write_split(rows, path)
        by_locale: dict[str, int] = {}
        for r in rows:
            key = r.get("locale") or r["lang"]
            by_locale[key] = by_locale.get(key, 0) + 1
        shown = path.relative_to(REPO) if path.is_relative_to(REPO) else path
        print(f"{shown}: {len(rows)} rows {by_locale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
