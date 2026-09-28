# Synthetic Retrieval Validation Dataset

Provisional synthetic validation query set for evaluating Knowledge Base (KB)
policy retrieval accuracy (Hit@k per language, ADR-0006). See the [committed
embedding calibration report](../../../../reports/calibration-embedding-2026-09-27.md)
for same-language and cross-language metrics.

> **Important Note:** This dataset is designated with `split: "validation"` and marked as a **provisional synthetic validation set**. Following [ADR-0010](../../../../docs/adr/0010-model-selection-calibration-harness.md) and [docs/data.md](../../../../docs/data.md), the `test` split is strictly reserved for human-authored and human-validated benchmarks.

---

## 1. Overview

- **Location:** `data/eval/synthetic/retrieval/queries.jsonl`
- **Total Queries:** 360 (120 Spanish `es`, 120 Portuguese `pt`, 120 English `en`).
- **KB Snippets:** 40 topics × 3 languages = 120 snippets (`packages/retrieval/kb/snippets.jsonl`).
- **Format:** Each line matches `retrieval.models.QueryExample`:
  ```json
  {
    "id": "q-es-001",
    "text": "hola quiero apagar mi tarjeta temporalmente por fa",
    "lang": "es",
    "relevant_ids": ["card_security.01.es"],
    "split": "validation",
    "source": "synthetic"
  }
  ```

---

## 2. Construction Principles

1. **Realistic Customer Phrasing:** Queries are written from the perspective of real customers contacting banking chat support (casual expressions, typos, hesitation, stress, slang).
2. **De-lexicalization (Anti-Keyword Leaks):** Overly technical or formal bank jargon present in snippets was avoided:
   - "freeze my plastic" / "hit pause on my debit card" instead of "precautionary blocking".
   - "someone bought stuff on my card" instead of "unauthorized transaction".
   - "fight this charge" instead of "dispute / chargeback".
   - "courtesy money while checking" instead of "provisional credit".
3. **Privacy by Design:** No real customer PII (no real card numbers, no real names, no real credentials).

---

## 3. Ambiguous Gold Label Resolution

A critical challenge in retrieval evaluation is topic overlap across closely related policy articles. To ensure fair evaluation without artificial penalties, ambiguous queries are handled as follows:

| Topic Pair | Status | Resolution | Scope |
|---|---|---|---|
| `support_handoff.01` (Structured handoff) vs `support_handoff.05` (Context transfer & receipts) | Multi-labeled | **Both topic snippet IDs (in the query's language) included in `relevant_ids`.** Both articles describe the transfer of case notes, verified facts, and receipts to human agents so customers do not repeat themselves. | 18 queries (3 `es` + 3 `pt` + 3 `en` per topic) |
| `fraud_reporting.01` (First steps on unknown charge) vs `fraud_reporting.04` (Detecting & reporting suspicious activity) | Multi-labeled | **Both topic snippet IDs (in the query's language) included in `relevant_ids`.** Both articles address identifying unauthorized purchases, initiating immediate card blocks, and transitioning to dispute specialists. | 18 queries (3 `es` + 3 `pt` + 3 `en` per topic) |
| `fraud_reporting.02` (Pending vs posted) vs `account_inquiry.03` (Temporary merchant holds) | Cleanly separated | **Single topic gold per query.** Queries under `fraud_reporting.02` strictly focus on pending transaction status and dispute eligibility, while queries under `account_inquiry.03` focus on merchant incidental holds (hotels, gas pumps, car rental security deposits). | 18 queries (9 for 02, 9 for 03) |

**Total multi-labeled ambiguous queries:** 36 of 360 queries (10.0%).

---

## 4. Evaluation and Baseline Performance

Gold labels are **in-language only**: `relevant_ids` lists the snippet(s) in the query's own language (`q-es-*` → `*.es`). A query is never credited for retrieving the same topic in another language.

The calibration harness loads this set end to end through its own config (the default `embedding.yaml` points at the test fixtures):
```bash
make calibrate TASK=embedding CONFIG=tools/calibrate/configs/embedding_kb_v1.yaml OUT=/tmp/calib
```

The committed calibration run scores this dataset's `validation` split. The
`test` split remains reserved for human-authored and human-validated benchmarks.

### Committed Calibration Results

The [committed embedding calibration report](../../../../reports/calibration-embedding-2026-09-27.md)
contains measured BM25, SentenceTransformers, and hybrid results by language,
including same-language and cross-language Hit@k/MRR, latency, and RAM.

---

## 5. Cross-Language Retrieval Results

The harness evaluates a query against snippets in other languages and maps its
topic IDs to those translations. Cross-language metrics are `n/a` when the KB
snippets lack `topic_id`. See the [committed report](../../../../reports/calibration-embedding-2026-09-27.md)
for the measured scores.
