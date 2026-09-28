# Data

## 1. Sources

| Source | Use | Notes |
|---|---|---|
| Dataset provided by Factored | Bulk realistic volume for the banking core, through `make ingest SOURCE=factored` | Profile, volumes and date range in [datasets/factored.md](datasets/factored.md); not usable as an evaluation set (Spanish only, template transcripts) |
| Provided data dictionary | Contract for interpreting fields | TODO: field-by-field mapping against our model |
| Knowledge base | Policies and responses of the simulated bank | Written by the team from the dataset's domain |
| Synthetic eval data | Labeled sets for decision calibration and scenario tests | Written by the team and versioned under `data/eval/synthetic/` |

**Principle — hybrid seed ([ADR-0011](adr/0011-hybrid-seed-dataset-ingest.md)):** the banking core holds the **synthetic demo identities** (`demo_es`, `demo_pt`, `demo_en` and the rest of the generated sample the scenarios depend on) **plus the delivered dataset**, mapped through a source-pluggable ingest. Demo identities are loaded first and always win a collision. The organization's dataset stays unversioned in `data/raw/`. Only synthetic data and human-written test sets live in `data/eval/synthetic/` (versioned). Anything derived from the organization's dataset stays in `data/eval/` (ignored). The reproducible `make calibrate` (⚠️ pending) run uses only the synthetic splits.

## 2. Pipeline

```
data/raw/         immutable copy of what was delivered, untransformed (unversioned)
  └── staging/    typing, normalization, deduplication, contract validation (unversioned)
        └── curated/  operational model consumed by banking-core (unversioned),
                      plus pseudonymized views for analytics
        └── eval/     splits derived from the dataset (ignored)
              └── synthetic/  versioned synthetic labeled data & human-written test sets
```

Every stage is idempotent and re-runnable from `data/raw/`. `make seed` rebuilds the whole database from scratch.

### 2.1 Seeding: synthetic + ingested datasets

```bash
make ingest SOURCE=factored   # data/raw/factored → data/staging/factored + reports/data-quality-factored.md
make seed                     # synthetic demo data + every source in data/staging/, one transaction
```

- `make ingest` rebuilds `data/staging/<source>/` (`customers`, `accounts`, `cards`, `transactions` JSONL plus `manifest.json`) from `data/raw/<source>/` only. The directory is written aside, validated with the dataset staging rules and swapped in, so a failed run leaves the previous staging untouched.
- `make seed` validates the synthetic data and every staged source, then loads them in one transaction (`data_origin` `synthetic` / `dataset`). A dataset customer whose document, email or phone blind index collides with one already loaded is skipped with everything hanging from it, and the count is printed. If `data/raw/<source>` exists but was never ingested, the seed loads synthetic data only and says so.
- Variables (seed service, `.env`): `INGEST_MAX_CUSTOMERS` (default 5,000; `0` = full volume) and `INGEST_ANCHOR_DATE` (default: run date). Dataset timestamps at or after the cutoff are clamped to just before it, then shifted by `anchor − cutoff`; the report prints the shift.
- Dataset rules that differ from synthetic data: no PAN (cards keep `pan_last4`, brand, `card_type`, expiry); each account keeps its own currency (no locale→currency rule); emails are replaced by a keyed hash `@example.com`.

### 2.2 Adding a dataset: the mapping contract

A new source is a mapping file plus, if its layout is new, a small adapter:

1. `apps/banking-core/src/banking_core/seed/ingest/sources/<source>.json`, validated by `SourceMapping` (`seed/ingest/mapping.py`; unknown keys are rejected). It holds every table: `document_types` → `DocumentType`, `countries` (code, phone code), `customer_status_dropped`, `products` (account type or card type; types not listed are dropped), `product_status` (`null` = drop), `transaction_status` (`null` = drop), `mcc_by_category` / `mcc_by_type` / `default_mcc`, `merchant_fallback_by_channel`, `dataset_cutoff`, `history_days` (≤ 120, inside the staging window), `dispute_window_days`, `locale`, `otp_channel`, and optional `policy_threshold_equivalents` (the report converts a base threshold with the dataset's exchange rates).
2. `"adapter"` names a function registered in `seed/ingest/pipeline.py` (`ADAPTERS`) that reads `data/raw/<source>/` and returns staging records plus a counter per rule. A value missing from a mapping table is dropped and counted, never guessed.
3. Tests with a small fictitious fixture shaped like the source (see `apps/banking-core/tests/test_ingest.py`); never real rows.

Once the mapping exists, `data/raw/<source>/` is accepted by `make seed`; without one it fails naming the directory.

## 3. Contracts and quality

Validation at the entrance to `staging`, failing loudly:

| Check | Example |
|---|---|
| Schema and types | Every transaction has a numeric amount and a valid currency |
| Keys and uniqueness | No duplicate card identifiers |
| Referential integrity | Every card belongs to an existing account |
| Ranges and domains | Dates within the declared range; statuses within the enumeration |
| Completeness | Null percentage per critical field, against a threshold |
| Distribution | Sharp deviations from the previous run |

The quality report is produced by `make data-quality` (⚠️ pending) and versioned in `reports/`. **TODO: issues found and how they were handled** — including what we decided *not* to clean, and why.

## 4. Splits

- **By conversation:** all messages from one conversation land in the same split. Splitting by message would leak information between sets.
- **By time:** validation and test come after training. Avoids learning from a future that would not exist in production (applies only to data derived from the organization's dataset; synthetic data has no real timestamps).
- **Stratified by language and intent**, so the test split is not dominated by the majority class or by a single language.
- **Synthetic vs dataset:** Only synthetic data and human-written test sets live in `data/eval/synthetic/` (versioned). Anything derived from the organization's dataset stays in `data/eval/` (ignored). The reproducible `make calibrate` run uses only the synthetic splits.

| Split | Criterion | Size |
|---|---|---|
| Training | Synthetic domain data | TODO |
| Validation | Synthetic domain data | TODO |
| Test | Written by humans (never generated by training generator). Until then, a provisional free-form set stands in: see [data/eval/synthetic/README.md](../data/eval/synthetic/README.md) | 450 provisional; human set TODO |

## 5. Labeling

If the dataset does not ship usable intent labels:

1. **Rubric written first**, with a definition and a positive and negative example per class (see [labeling-rubric.md](labeling-rubric.md)).
2. **Stratified sample** by language and intent: TODO conversations.
3. **Double labeling of 20%** by two different people; agreement reported (Cohen's κ = TODO).
4. Disagreements resolved in review, and **the rubric is updated**; if the update changes criteria, affected items are relabeled.
5. Labels are versioned alongside the rubric that produced them.

**Anti-leakage:** labelers do not see model predictions. The test split is labeled before any system is run against it.

## 6. Personal data

Dataset records are treated as if they were real. See [security-privacy.md](security-privacy.md): encryption at rest, blind index for lookup, masking before any external provider call, and analytics only over pseudonymized views.

## 7. Lineage

Every derived table records: source, transformation applied, code version and run date. It answers "where did this number come from" without re-reading the pipeline.
