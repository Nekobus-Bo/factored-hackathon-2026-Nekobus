"""Build the provisional pt-BR test split from hand-written templates.

The templates (`test_templates.*.tsv`: intent, length, topic, template) were written by the
coding agent from the half-B style cards, a different model and process from the LLM-generated
train/validation splits. They are provisional synthetic data, not human (docs/labeling-rubric.md §1).
"""

import argparse
import json
import random
from pathlib import Path

from tools.synthdata_pt.fill import fill

DEFAULT_DIR = Path("data/staging/decision_pt")
SEED = 1009  # differs from the generation seed so test and train never share filled values by construction
GENERATOR = "claude-opus-5-5"


def load_templates(data_dir: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(data_dir.glob("test_templates.*.tsv")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) != 4:
                raise ValueError(f"{path.name}:{line_no}: expected 4 tab-separated fields, got {len(fields)}")
            intent, length, topic, template = fields
            rows.append({"intent": intent, "length": length, "topic": topic, "template": template})
    return rows


def build(data_dir: Path) -> Path:
    templates = load_templates(data_dir)
    if not templates:
        raise SystemExit(f"No test_templates.*.tsv found in {data_dir}")
    counters: dict[str, int] = {}
    records = []
    for row in templates:
        rng = random.Random(f"{SEED}-{row['intent']}-{row['template']}")
        text, slots = fill(row["template"], row["intent"], rng)
        index = counters.get(row["intent"], 0)
        counters[row["intent"]] = index + 1
        records.append({
            "id": f"synthpt_test_{row['intent']}_{index:03d}",
            "text": text,
            "lang": "pt",
            "intent": row["intent"],
            "slots": slots,
            "split": "test",
            "source": "synthetic-provisional",
            "generator": GENERATOR,
            "prompt_version": "handwritten-v1",
            "length": row["length"],
            "topic": row["topic"],
        })
    out = data_dir / "decision.pt.test.provisional.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    out = build(args.data_dir)
    print(f"Wrote {sum(1 for _ in out.open(encoding='utf-8'))} rows to {out}")


if __name__ == "__main__":
    main()
