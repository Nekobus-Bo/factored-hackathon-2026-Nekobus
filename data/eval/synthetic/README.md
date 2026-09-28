# Synthetic decision data

Labeled data for the decision model (intent + slots), in the format defined by
[schema.yaml](schema.yaml) and [docs/labeling-rubric.md](../../../docs/labeling-rubric.md) §4.

| File | Split | `source` | Rows | Produced by |
|---|---|---|---|---|
| `decision.train.jsonl` | train | `synthetic` | 1800 (40 per intent × language) | `make synth-data` (templates in `tools/synthdata/`) |
| `decision.validation.jsonl` | validation | `synthetic` | 450 (10 per intent × language) | `make synth-data` |
| `decision.test.provisional.jsonl` | test | `synthetic-provisional` | 450 (10 per intent × language) | Written free-form, see below |
| `decision.test.jsonl` | test | `human` | — | ⚠️ Pending: human-written per the labeling rubric |

## Provisional test set

`decision.test.provisional.jsonl` is a stand-in held-out split so the decision
candidates can be calibrated before the human-written set exists. It is
**provisional synthetic, not human**:

- Written free-form by an AI coding agent, not by `tools/synthdata`: varied
  phrasing, colloquial Spanish/Portuguese/English, typos and some code-switching.
  It follows a different generating process than train/validation, but it has
  not been double-labeled and has no inter-annotator agreement.
- All PII is fictitious and disjoint from train/validation, the seed fixtures
  and the eval scenarios. No text appears in train or validation.
- `tools/calibrate/tests/test_decision_test_provisional.py` enforces the format,
  exact offsets, the 10 per intent × language counts and both disjointness rules.

Use it with `tools/calibrate/configs/decision_synthetic.yaml`. Any report built
on it carries a "Test split: provisional synthetic (not human)" banner.

When `decision.test.jsonl` (human) lands, it **replaces** the provisional file
in that config; the provisional file is then deleted, not merged with it.
