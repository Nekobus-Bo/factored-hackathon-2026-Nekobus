# ADR-0011: Hybrid seed — synthetic demo identities plus the delivered dataset through a pluggable ingest

**Status:** Accepted · **Date:** 2026-09-27 · **Deciders:** owner (hybrid seed), team

## Context

The banking core was seeded only from synthetic data. The delivered Factored dataset ([datasets/factored.md](../datasets/factored.md)) has realistic volume (150,000 customers, 4.4M transactions), but it does not fit the staging contract as written:

- Cards carry a 16-digit number in clear text. `core_bank.card.pan_enc` was `NOT NULL`, so the only way to load a card was to store that number.
- Staging required each account's currency to follow the customer's locale (`es`→COP, `pt`→BRL, `en`→USD). Mexican customers hold USD, Argentine ones ARS: every row in those two countries failed.
- Staging rejects transactions older than 125 days from *now*. The dataset ends on 2026-06-18, so almost all of it fell outside the window, and the loaded part depended on the day the seed ran.
- Staging requires `@example.` emails (fake PII); the dataset has real-looking addresses.
- Statuses `Suspended` and `Closed` have no counterpart in the card `CHECK` (`ACTIVE`, `BLOCKED`).
- `make seed` failed whenever `data/raw/` held the dataset ("mapping pending").

The eval scenarios depend on the synthetic demo identities (`demo_es`, `demo_pt`, `demo_en`), so they cannot be replaced.

## Options considered

| Option | Why not |
|---|---|
| Seed from the dataset only | Loses the demo identities that the scenarios and the replay recordings depend on |
| Keep synthetic only | Ignores the delivered data; no realistic volume |
| Load the dataset straight into curated, skipping staging | Breaks the `raw → staging → curated` contract and its checks ([data.md](../data.md)) |
| **Hybrid: synthetic first, then ingested datasets, one transaction** | Chosen |

## Decision

1. **`make ingest SOURCE=<name>`** maps `data/raw/<name>/` to `data/staging/<name>/` (the same four JSONL files the synthetic path writes). A source is a mapping file `apps/banking-core/src/banking_core/seed/ingest/sources/<name>.json` plus an adapter; everything that is a table (document types, product types, statuses, MCCs, merchant fallbacks, cutoff, window) lives in the mapping, never in code. The pipeline lives in banking-core because it reuses the staging models and the blind-index key, and runs in the `seed` container that already mounts `data/` and `reports/`. JSON instead of YAML: banking-core has no YAML dependency and the standard library covers it.
2. **`make seed`** loads the synthetic demo data first, then every source that has a complete `data/staging/<name>/` (with its `manifest.json`), in **one transaction**, with `data_origin='dataset'` and `source_ref=<name>/…`. A dataset customer whose document, email or phone blind index collides with one already loaded is skipped along with their accounts, cards and transactions; **demo wins**, and the skips are printed. `check_raw_directory` accepts any `data/raw/<name>` that has a mapping.
3. **No PAN for dataset cards.** Migration `0005_dataset_cards` (on `0004_ops_handoff`): `pan_enc` becomes nullable with `CHECK (data_origin = 'synthetic' OR pan_enc IS NULL)`. The ingest reads the number only to take its last four digits and brand. New nullable columns `card_type` (`DEBIT`|`CREDIT`), `expiry_month`, `expiry_year`, filled only from the dataset.
4. **Origin-specific staging rules.** The locale→currency rule applies to synthetic data only; dataset staging must *not* carry a PAN, synthetic staging must.
5. **Status mapping.** `Suspended` → `BLOCKED` (`SUSPICIOUS_ACTIVITY`), `Blocked` → `BLOCKED` (`CUSTOMER_REQUEST`), `Closed` products and customers are dropped and counted.
6. **Dates.** Timestamps at or after the dataset cutoff are clamped to just before it; then every event timestamp is shifted by `INGEST_ANCHOR_DATE − cutoff` (anchor default: the run date), so the last 90 days of history end at the anchor. Deterministic given the anchor. Birth dates are not shifted; card expiry is shifted but not clamped.
7. **Emails** are replaced by `HMAC(BLIND_INDEX_SALT-derived key, email)@example.com`; the raw address never reaches staging. Names, documents and phones do reach staging in clear text, exactly as synthetic staging does, and are encrypted at the curated step.
8. **Deduplication before the cap.** Customers repeating a document, email or phone within the dataset are dropped (first by `customer_id` wins), so every loaded customer is unambiguous for `customer.match`. `INGEST_MAX_CUSTOMERS` (default 5,000; 0 = all) keeps the local seed fast.
9. **ARS threshold.** USD 500 converted with the last USD→ARS rate before the cutoff in `daily_exchange_rates`: 50,000 × 355.912847 (2026-06-17) = **17,795,642** minor units, added to `POLICY_SEED_THRESHOLDS_MINOR` (`.env.example`, compose). The ingest report prints the computation.

## Consequences

**Easier:** the demo keeps working while the core holds realistic volume in three currencies; a new dataset is a mapping file plus, at most, a small adapter; every drop and repair is counted in `reports/data-quality-<source>.md`.

**Harder:** `pan_enc` is no longer guaranteed; code that decrypts it must handle `NULL` (dataset cards never had a PAN to show). The seed now depends on the ingest having run; if `data/raw/<source>` exists but was not ingested, `make seed` loads synthetic data only and says so.

**Accepted losses:** in the full dataset about a third of the customers share an email with another (54,507 of 150,000 are dropped by the dedup rule), 3% have no mobile phone, debit cards without an account in their currency are dropped, and transaction coordinates are not loaded (no column in the model). The report gives the numbers of each run.

**To revisit:** the ARS threshold is a seed value derived once from the dataset; if the rate or the policy changes, it is edited in the back office, not recomputed.
