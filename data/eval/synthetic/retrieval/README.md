# Synthetic Retrieval Validation Dataset

Provisional synthetic validation query set for evaluating Knowledge Base (KB) policy retrieval accuracy (Hit@k per language, ADR-0006; cross-language is not measured yet, see section 5).

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

> **Pending (harness):** `calibrate` scores only rows with `split: "test"`. Every row here is `validation`, so that run currently loads the KB and queries but reports `no data` for every language. Scoring the validation split is a harness change, not a data change: the `test` split stays reserved for human-validated queries.

### BM25 Baseline Results

Computed with the harness's `BM25Adapter` and its `hit_at_k` / `mrr` functions over the 120 validation queries per language (KB: 120 snippets):

| Language | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|
| **Spanish (`es`)** | 0.325 | 0.458 | 0.550 | 0.407 |
| **Portuguese (`pt`)** | 0.342 | 0.525 | 0.567 | 0.428 |
| **English (`en`)** | 0.383 | 0.592 | 0.667 | 0.495 |

---

## 5. Cross-Language Retrieval: Not Covered by This Set

This set has **no cross-lingual subset**, on purpose. The harness counts a query as cross-language when any of its `relevant_ids` is in another language, and then uses the same `relevant_ids` for Hit@k against the full KB. Two consequences:

1. Listing all three languages as gold makes every query "cross-language", so Cross-Hit@1 equals Hit@1 and measures nothing.
2. A subset whose gold is only in the *other* languages still does not work, because every topic exists in all three languages and the same-language snippet stays in the index. Retrieving it first (the correct behavior) would be scored as a miss.

A meaningful cross-lingual measure needs a harness change: restrict the searched index to the target languages per query (or exclude the query's language). Until then, cross-language Hit@k is reported as `n/a`.
