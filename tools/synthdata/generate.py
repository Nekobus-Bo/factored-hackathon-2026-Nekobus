"""Deterministic synthetic dataset generator for intent and slot models.

Produces:
- data/eval/synthetic/decision.train.jsonl (1800 rows: 40 per intent x 3 langs)
- data/eval/synthetic/decision.validation.jsonl (450 rows: 10 per intent x 3 langs)

Conforms strictly to ADR-0010:
- Test split is NEVER generated synthetically (human-written only).
- Frozen harness format:
  {"id", "text", "lang", "intent", "slots": [...], "split", "source": "synthetic"}
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any

from tools.synthdata.fillers import get_fillers
from tools.synthdata.templates_en import (
    TRAIN_TEMPLATES as TRAIN_EN,
)
from tools.synthdata.templates_en import (
    VAL_TEMPLATES as VAL_EN,
)
from tools.synthdata.templates_es import (
    TRAIN_TEMPLATES as TRAIN_ES,
)
from tools.synthdata.templates_es import (
    VAL_TEMPLATES as VAL_ES,
)
from tools.synthdata.templates_pt import (
    TRAIN_TEMPLATES as TRAIN_PT,
)
from tools.synthdata.templates_pt import (
    VAL_TEMPLATES as VAL_PT,
)

DEFAULT_SEED = 42
SUPPORTED_LANGUAGES = ["es", "pt", "en"]

LANG_TEMPLATES = {
    "es": {"train": TRAIN_ES, "validation": VAL_ES},
    "pt": {"train": TRAIN_PT, "validation": VAL_PT},
    "en": {"train": TRAIN_EN, "validation": VAL_EN},
}


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load and validate the intent and slot schema."""
    import yaml

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    return schema


def render_template(
    template: list[str | tuple[str, str]], fillers: dict[str, str]
) -> tuple[str, list[dict[str, Any]]]:
    """Assemble utterance and compute exact slot character offsets."""
    text = ""
    slots = []
    for part in template:
        if isinstance(part, str):
            text += part
        elif isinstance(part, tuple):
            slot_type, filler_key = part
            val = fillers[filler_key]
            start = len(text)
            text += val
            end = len(text)
            slot_dict: dict[str, Any] = {
                "type": slot_type,
                "value": val,
                "start": start,
                "end": end,
            }
            if slot_type == "document_type" and "document_type_normalized" in fillers:
                slot_dict["normalized"] = fillers["document_type_normalized"]
            slots.append(slot_dict)
        else:
            raise TypeError(f"Invalid template part: {part!r}")

    # Verify offset integrity immediately
    for slot in slots:
        extracted = text[slot["start"] : slot["end"]]
        assert extracted == slot["value"], (
            f"Offset mismatch for {slot['type']}: "
            f"text[{slot['start']}:{slot['end']}]='{extracted}' != '{slot['value']}'"
        )

    return text, slots


def generate_split(
    split: str,
    seed: int = DEFAULT_SEED,
    seen_train_texts: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate rows for a single split ('train' or 'validation').

    Strictly forbids 'test' split generation per ADR-0010.
    """
    # Strict ADR-0010 test split prohibition assertion
    if split == "test":
        raise ValueError(
            "Test split must never be generated synthetically. "
            "Test sets are human-written per ADR-0010."
        )

    if split not in ("train", "validation"):
        raise ValueError(
            f"Invalid split '{split}'. Only 'train' and 'validation' are permitted."
        )

    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    is_train = split == "train"
    target_count = 40 if is_train else 10

    # Ensure consistent order across languages and intents
    for lang in SUPPORTED_LANGUAGES:
        templates_dict = LANG_TEMPLATES[lang][split]
        for intent, templates in sorted(templates_dict.items()):
            generated_for_intent = 0
            t_idx = 0
            retries = 0

            while generated_for_intent < target_count:
                template = templates[t_idx % len(templates)]
                t_idx += 1

                fillers = get_fillers(lang, rng)
                text, slots = render_template(template, fillers)

                # Collision check within current split and against train split
                if text in seen_texts or (
                    seen_train_texts and text in seen_train_texts
                ):
                    retries += 1
                    if retries > 100:
                        raise RuntimeError(
                            f"Too many collisions in {split} for {lang} {intent}"
                        )
                    continue

                seen_texts.add(text)
                row_id = f"synth_{split}_{lang}_{intent}_{generated_for_intent + 1:03d}"
                rows.append(
                    {
                        "id": row_id,
                        "text": text,
                        "lang": lang,
                        "intent": intent,
                        "slots": slots,
                        "split": split,
                        "source": "synthetic",
                    }
                )
                generated_for_intent += 1

    return rows


def generate_datasets(
    out_dir: Path,
    seed: int = DEFAULT_SEED,
) -> tuple[Path, Path]:
    """Generate both train and validation datasets deterministically."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate train split
    train_rows = generate_split("train", seed=seed)
    train_texts = {r["text"] for r in train_rows}

    # 2. Generate validation split, ensuring disjointness from train
    val_rows = generate_split(
        "validation", seed=seed + 1000, seen_train_texts=train_texts
    )
    val_texts = {r["text"] for r in val_rows}

    # Verify no text overlap between train and validation
    overlap = train_texts.intersection(val_texts)
    assert len(overlap) == 0, (
        f"Found {len(overlap)} overlapping texts between train and validation!"
    )

    # Verify frozen harness schema and slot offsets for all records
    for r in train_rows + val_rows:
        for s in r["slots"]:
            assert r["text"][s["start"] : s["end"]] == s["value"]

    # Write files deterministically
    train_path = out_dir / "decision.train.jsonl"
    val_path = out_dir / "decision.validation.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for row in train_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for row in val_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return train_path, val_path


def main() -> None:
    """CLI entry point for synthetic dataset generation."""
    parser = argparse.ArgumentParser(
        description="Deterministic synthetic dataset generator for intent/slot models."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/eval/synthetic"),
        help="Target output directory (default: data/eval/synthetic)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED})",
    )
    args = parser.parse_args()

    train_path, val_path = generate_datasets(args.out_dir, seed=args.seed)

    print(f"Generated synthetic training dataset: {train_path}")
    print(f"Generated synthetic validation dataset: {val_path}")

    # Print summary counts
    with open(train_path, encoding="utf-8") as f:
        train_lines = [json.loads(line) for line in f]
    with open(val_path, encoding="utf-8") as f:
        val_lines = [json.loads(line) for line in f]

    print("\nDataset Summary:")
    print(
        f"  Train rows: {len(train_lines)} (40 per intent x 15 intents x 3 languages)"
    )
    for lang in SUPPORTED_LANGUAGES:
        c = sum(1 for r in train_lines if r["lang"] == lang)
        print(f"    - {lang}: {c} rows")

    print(
        f"  Validation rows: {len(val_lines)} "
        "(10 per intent x 15 intents x 3 languages)"
    )
    for lang in SUPPORTED_LANGUAGES:
        c = sum(1 for r in val_lines if r["lang"] == lang)
        print(f"    - {lang}: {c} rows")

    print(f"  Total: {len(train_lines) + len(val_lines)} rows")


if __name__ == "__main__":
    main()
