# tools/synthdata

Deterministic synthetic dataset generator for intent classification and slot extraction models.

## Overview

Produces reproducible synthetic training and validation datasets in the frozen calibration harness format:
- `data/eval/synthetic/decision.train.jsonl` (1800 rows: 40 examples per intent × 15 intents × 3 languages)
- `data/eval/synthetic/decision.validation.jsonl` (450 rows: 10 examples per intent × 15 intents × 3 languages)

Authoritative schema defined in [`data/eval/synthetic/schema.yaml`](../../data/eval/synthetic/schema.yaml).

## Commands

### Generate Data

Run the generator using `make`:
```bash
make synth-data
```

Or invoke directly via `uv`:
```bash
uv run --with pyyaml python -m tools.synthdata
```

Options:
- `--out-dir`: Destination directory (default: `data/eval/synthetic`)
- `--seed`: Deterministic PRNG seed (default: `42`)

### Run Tests

Execute unit tests verifying schema integrity, exact slot offsets, split disjointness, and ADR-0010 compliance:
```bash
uv run --with pyyaml pytest tools/synthdata
```

## Contract & Constraints (ADR-0010)

1. **Test Split Prohibition:** Test sets must be written and double-labeled by humans ([docs/labeling-rubric.md](../../docs/labeling-rubric.md)). The synthetic generator explicitly forbids generating any `"test"` split.
2. **Zero Overlap:** Train and validation splits are strictly disjoint; no text appears in both splits.
3. **Exact Slot Offsets:** Every slot annotation satisfies `text[start:end] == value` with character-exact offsets.
4. **Fictitious Data Only:** Generated PII values use reserved ranges (RFC 2606 `@example.com` domains, NANPA 555-01xx and national test phone ranges, never starting with `+00`, and standard test card numbers).
5. **Document Identification & Normalization:** Natural surface forms (e.g. `cédula`, `CPF`, `passport`, `RUT`) appear in text, while the slot annotation includes an optional `normalized` field mapping to the canonical `DocumentType` enum (`NATIONAL_ID`, `PASSPORT`, `FOREIGN_ID`, `TAX_ID`). Document types and numbers are generated as consistent, realistic pairs without artificial prefixes.
