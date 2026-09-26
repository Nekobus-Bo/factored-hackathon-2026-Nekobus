# Data

## 1. Sources

| Source | Use | Notes |
|---|---|---|
| Dataset provided by Factored | Seed for the banking core and input for evaluation scenarios | TODO: entities, volume, date range after exploration |
| Provided data dictionary | Contract for interpreting fields | TODO: field-by-field mapping against our model |
| Knowledge base | Policies and responses of the simulated bank | Written by the team from the dataset's domain |

**Principle:** the banking core is seeded **from the delivered dataset**, not from invented data. Synthetic data is used only where the dataset does not cover a required entity, and is marked as such in the lineage.

## 2. Pipeline

```
data/raw/         immutable copy of what was delivered, untransformed
  └── staging/    typing, normalization, deduplication, contract validation
        └── curated/  operational model consumed by banking-core,
                      plus pseudonymized views for analytics
        └── eval/     training, validation and held-out splits
```

Every stage is idempotent and re-runnable from `data/raw/`. `make seed` rebuilds the whole database from scratch.

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

The quality report is produced by `make data-quality` and versioned in `reports/`. **TODO: issues found and how they were handled** — including what we decided *not* to clean, and why.

## 4. Splits

- **By conversation:** all messages from one conversation land in the same split. Splitting by message would leak information between sets.
- **By time:** validation and held-out come after training. Avoids learning from a future that would not exist in production.
- **Stratified by language and intent**, so the held-out set is not dominated by the majority class or by a single language.

| Split | Criterion | Size |
|---|---|---|
| Training | TODO | TODO |
| Validation | TODO | TODO |
| Held-out | TODO | TODO |

## 5. Labeling

If the dataset does not ship usable intent labels:

1. **Rubric written first**, with a definition and a positive and negative example per class.
2. **Stratified sample** by language and intent: TODO conversations.
3. **Double labeling of 20%** by two different people; agreement reported (Cohen's κ = TODO).
4. Disagreements resolved in review, and **the rubric is updated**; if the update changes criteria, affected items are relabeled.
5. Labels are versioned alongside the rubric that produced them.

**Anti-leakage:** labelers do not see model predictions. The held-out set is labeled before any system is run against it.

## 6. Personal data

Dataset records are treated as if they were real. See [security-privacy.md](security-privacy.md): encryption at rest, blind index for lookup, masking before any external provider call, and analytics only over pseudonymized views.

## 7. Lineage

Every derived table records: source, transformation applied, code version and run date. It answers "where did this number come from" without re-reading the pipeline.
