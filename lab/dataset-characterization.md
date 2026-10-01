# LATAM Bank dataset — characterization

**Date:** 2026-09-27 · **Snapshot:** organizer S3 `data/` prefix (identical to the local copy) plus `data_backup_20260831/` for comparison · **Scripts:** `lab/profiling/` (**pending**, not in the repository yet)

What the supplied dataset contains, how it was generated as far as can be inferred, and where it carries learnable signal. This document records findings only. What they mean for the system design goes in a separate document.

> **Pending: the numbers cannot be reproduced yet.** The profiling scripts that produced them (`lab/profiling/`) are not committed, and marimo notebooks store no outputs. Until they land, treat every figure here as a recorded observation, not a checkable result. See [Reproduce](#reproduce).

Every number below came from the profiling scripts, run on the full tables (no sampling unless stated). Signal is measured with a gradient-boosted model trained before 2025-06-01 and tested after, reported as ROC-AUC (0.5 = no signal) or R², plus group-rate spreads (`max/min` of the target rate across groups with ≥ 200 rows).

---

## 1. Summary

| # | Finding | Evidence |
|---|---|---|
| 1 | **Most columns are drawn independently at random.** Relationships between tables exist only as keys; behaviour in one table does not affect another. | §6: 9 of 14 targets show no signal (AUC 0.49–0.51) |
| 2 | **The few real relationships are simple generator rules**, concentrated in the contact centre (resolution, handle time, CSAT) and marketing (conversion by channel). | §6.2, §6.5 |
| 3 | **`is_fraud` is unlearnable from behaviour; `fraud_score` is a leaked label.** Legitimate transactions score U(0, 30); every score ≥ 40 is fraud. | §6.1 |
| 4 | **Text fields are templates with no information.** 42 distinct customer utterances, each appearing under all 6 contact reasons. | §7 |
| 5 | **The data-quality challenges the dictionary announces are absent**: 0 duplicates, 1 schema per table, no late arrivals. Other defects not announced are present. | §2, §3 |
| 6 | **There is no Portuguese content and no MXN currency.** Mexico is recorded in USD. | §3, §7 |
| 7 | **The backup snapshot is a separate generation run**, not an earlier version: 97% of customer IDs differ. It cannot demonstrate incremental updates. | §2.3 |

---

## 2. Provenance and completeness

### 2.1 Layout

| Location | Content |
|---|---|
| S3 `data/` | 13 tables, 12,505 CSV files in total across both prefixes. Local copy matches file for file. |
| S3 `data_backup_20260831/` | 11 tables. No `call_transcripts` or `satisfaction_surveys`; `transactions` only 453 daily files. |
| S3 root | A stray `marketing_campaigns.csv` |

Fact tables are partitioned `year=/month=/day=`, one file per day, 1,097 days from 2023-06-17 to 2026-06-17 (`campaign_sends`: 1,083 days from 2023-07-01). Every day is present.

### 2.2 Row counts against the dictionary

| Table | Rows | Dictionary | % |
|---|---:|---:|---:|
| customers | 150,000 | 150,000 | 100 |
| products | 400,000 | 400,000 | 100 |
| branches | 350 | 350 | 100 |
| service_agents | 1,200 | 1,200 | 100 |
| marketing_campaigns | 200 | 200 | 100 |
| daily_exchange_rates | 13,164 | 3,000 | 439 |
| transactions | 4,425,008 | 5,000,000 | 88.5 |
| call_center_interactions | 686,296 | 800,000 | 85.8 |
| call_transcripts | 171,321 | 200,000 | 85.7 |
| satisfaction_surveys | 212,759 | 250,000 | 85.1 |
| digital_events | 15,620,994 | 10,000,000 | 156.2 |
| complaints | 67,095 | 80,000 | 83.9 |
| campaign_sends | 1,746,801 | 2,000,000 | 87.3 |

Exchange rates hold 12 currency pairs × 1,097 days. The gaps in fact tables are not missing days; the daily volume is simply lower than the dictionary states.

### 2.3 Backup snapshot against current

| Table | Backup rows | Current rows | Keys only in current | Notes |
|---|---:|---:|---:|---|
| customers | 150,000 | 150,000 | 145,975 | 97% of IDs regenerated |
| products | 400,000 | 400,000 | 271,401 | Shared IDs changed owner in 128,599 rows |
| complaints | 67,095 | 67,095 | 0 | Same IDs, **every row re-linked to a different customer** |
| transactions | 1,839,229 | 4,425,008 | 4,363,647 | Backup covers 2023-07-01 → 2024-09-25 only |
| call_center_interactions | 684,107 | 686,296 | 650,324 | — |
| campaign_sends | 1,735,997 | 1,746,801 | 1,697,372 | — |
| service_agents | 1,200 | 1,200 | 596 | — |
| branches, marketing_campaigns | identical | | 0 | — |

The two snapshots share almost no entities, so a diff between them is not a realistic late-arrival or correction scenario.

### 2.4 Announced data-quality challenges

| Dictionary claim | Measured |
|---|---|
| ~2% duplicates | **0** duplicate primary keys and 0 rows with identical content under another key, in every table |
| ~5% nulls in nullable fields | Nulls are injected at **fixed round rates per column**: 2, 3, 5, 10, 14, 15, 20, 30, 50%. `fraud_score` 20%, `landline_phone` 50% |
| Late arrivals | None: in every fact table, every row sits in the file of its `process_date`, and no event is older than its `process_date` |
| Schema evolution | None: every file of a table has the same header |

Event timestamps run up to 6–8 hours past the end of the partition day, consistent with UTC timestamps partitioned by a local date (UTC−6 to UTC−8). Surveys run up to 2 days past, consistent with being filed under their interaction's date.

---

## 3. Data-quality findings

| Area | Finding | Measurement |
|---|---|---|
| Currency | No MXN anywhere in `transactions` or `products`; Mexican accounts are USD | `products`: México 100% USD; AR/CO ~10% USD |
| Currency | `amount_usd` is null whenever `currency = 'USD'` | 57.3% of transactions have no USD amount |
| Currency | `complaints.currency` is uniform over ARS/COP/MXN/USD regardless of customer country | ~25% each in every country |
| Currency | `estimated_monthly_income` is in local currency (MXN for Mexico) while Mexican products are in USD | Median income: MX 39,220 · CO 9.19M · AR 802k |
| Geography | Two spellings of Mexico | `transaction_country` and `ip_country`: "México" and "Mexico"; agents use "Mexico", customers "México" |
| Geography | Coordinates are meaningless | 80.6% null; Mexican rows fall in [−1, 1]² (near 0,0); every other country shares the same box (lat −35.6…5.7, lon −75.1…1.0) |
| Geography | Transactions outside the three countries | 2.75% in Spain, USA or Brazil |
| Transactions | `transaction_type` and `channel` are independent | e.g. 338k withdrawals at POS, 214k deposits at POS, 326k purchases at ATM |
| Transactions | Response codes are random among non-approved | Declined, Pending and Reversed draw uniformly from 05/14/51/54 |
| Transactions | Transactions before the product was opened | 18.7% |
| Transactions | Only active products transact | 0% on Closed, Blocked or Suspended products |
| Customers | Mexican customers all hold a "DNI" (an Argentine document); Colombia splits evenly CC/CE/Pasaporte | — |
| Customers | Uniform categoricals | gender F/O/M ≈ 33% each; marital status 4 × ~23%; `accepts_marketing` 50/50 |
| Customers | `last_updated` in the future | 6.2% (max 2027-06-15) |
| Customers | Registered before age 18 | 2.1% |
| Customers | Customers with no transactions | 15,485 (10.3%) |
| Surveys | CSAT and CES only take 1–4; NPS only 2–7 | No 5-star CSAT and no Promoters exist |
| Complaints | `origin_interaction_id` is always null | 100% |

---

## 4. Referential integrity

All 23 foreign keys checked (18 from the dictionary, 5 implied by column names) resolve with 0% orphans, except:

| Foreign key | Orphans |
|---|---:|
| `customers.registration_branch_id → branches` | **100%** |
| `service_agents.assigned_branch_id → branches` | **99.8%** |

Keys resolve, but some relationships have no meaning:

| Check | Result |
|---|---:|
| Transaction's customer owns the transaction's product | 100% |
| Transcript's customer matches its interaction's customer | 100% |
| Transcript `main_topics` equals interaction `contact_reason` | 100% (a copy) |
| Survey's customer matches its interaction; survey after interaction | 100% · 100% |
| **Complaint's `affected_product_id` owned by the complaining customer** | **0%** |
| Transaction currency equals product currency | 100% |

---

## 5. Table notes

**Customers (150k).** México 49.9%, Colombia 30.2%, Argentina 19.9%. Segments Basic 60% / Plus 25% / Premium 10% / Student 5%. Income is ordered by segment (Premium ≈ 10× Basic in every country). `credit_score` 422–850, 15% null.

**Products (400k).** Savings 30%, credit card 25%, checking 25%, debit card 10%, personal loan 5%, mortgage 3%, investment and insurance the rest. Status Active 85%, Closed 8%, Blocked 5%, Suspended 2%. `days_past_due` exists only for credit cards and loans, with values {0, 15, 30, 60, 90, 180}.

**Transactions (4.43M).** Purchase 24%, withdrawal 22%, transfer 20%, payment 17%, deposit 14%, adjustment 3%. POS 35%, ATM 30%, web 15%, app 15%. Approved 92%, declined 5%, pending 2%, reversed 1%. 24 merchants, 6 categories. Median amount ≈ US$465 in every country. About 10 transactions per customer per year.

**Call-centre interactions (686k).** 6 contact reasons: transactional 35%, product 22%, complaint 17%, technical 15%, commercial 8%, retention 3%. `reason_category` duplicates `contact_reason`. Inbound calls 70%. First-contact resolution 76.7%, escalation 10.0%, follow-up 34.8%. `detected_sentiment` is a fixed binning of `sentiment_score`. Contacts per customer: mean 4.62, SD 2.1, max 18 (Poisson-like).

**Transcripts (171k).** Linked 1:1 to interactions flagged `has_transcript`. See §7.

**Surveys (213k).** CSAT 60%, NPS 30%, CES 10%. `nps_category` is a function of the score (Detractor 2–6, Passive 7).

**Digital events (15.6M).** Page views 38%, clicks 23%, logins 16%, logouts 16%. `customer_id` null in 24%. Sessions: mean 8.5 events, max 15; 100% start with a login; one customer and one channel per session. Channel and platform are coherent. `ip_country` always equals the customer's country. Errors are 2.3% of events, only in the Transaction (6.0%) and Navigation (4.5%) categories.

**Complaints (67k).** 5 categories at ~20% each, one subcategory per category (+10% null): Transactions → *Cargo no reconocido*, Fees → *Cobro indebido*, Technical → *Problema con app*, Branch → *Atención en sucursal*, Service → *Calidad de servicio*. Status dates are internally coherent (only Resolved and Closed have a resolution date; `resolution_days` equals the date difference exactly). Regulator channel 1.07%.

**Campaign sends (1.75M).** Delivered 94%, opened 38.6%, clicked 5.6%, converted 0.56%. No conversion without a click. 99.5% of sends fall within campaign dates. Half the recipients have `accepts_marketing = false`.

**Service agents (1.2k).** Mexico 50%, Colombia 30%, Argentina 20%. 129 agents (10.75%) list Portuguese. Specialties include *Fraudes* (8.75%) and *Quejas y Reclamos*.

---

## 6. Signal tests

### 6.1 Fraud (`transactions.is_fraud`)

Base rate 0.098% (4,316 frauds), stable across years (0.102% → 0.088%).

| Model (test: 1.55M rows, 1,442 frauds) | ROC-AUC | PR-AUC |
|---|---:|---:|
| 22 behavioural features (amount, type, channel, merchant, status, hour, day, abroad, other city, product, segment, age, velocity 1h/24h, amount vs. own average, …) | **0.507** | 0.0009 |
| `fraud_score` alone | 0.835 | 0.555 |
| Both | 0.822 | 0.557 |

- **Univariate:** the fraud rate varies by at most 1.5× across any group (merchant 1.97×, on small groups).
- **How `fraud_score` is built:** legitimate transactions score uniformly in [0, 30] (maximum exactly 30.0). Scored frauds: 31% fall in [0, 30]; the rest are spread over 30–100. Every score ≥ 40 is fraud (2,013 rows). The score is null for 20% of rows, independently of the label.
- **No downstream effect:** within 30 days of a fraud, the customer files a complaint in 0.93% of cases (legitimate: 1.21%) and an *unrecognised charge* complaint in 0.19% (0.22%). Within 7 days they call in 3.17% of cases (2.88%).
- **No digital precursor:** logins in the 24 hours before the transaction are 0.013 for both fraud and legitimate transactions.

### 6.2 Contact centre

| Target | Base | Model | Main drivers (group spread) |
|---|---:|---|---|
| `was_escalated` | 10.0% | AUC **0.498** | None (every spread ≤ 1.07×, except small duration buckets) |
| `was_resolved` (first-contact resolution) | 76.7% | AUC **0.772** | Contact reason 2.1× (transactional 91.5%, product 89.6%, technical 69.9%, commercial 65.2%, retention 60.2%, complaint 43.6%); sentiment (neutral 82.6% vs. ~64%); duration |
| `requires_followup` | 34.8% | AUC **0.682** | Contact reason 2.8× (complaint 63%); duration; sentiment extremes |
| `duration_seconds` | — | R² **0.475** | Reason: average 221 s transactional, 266 product, 360 technical, 435 complaint, 479 retention, 540 commercial |
| `wait_time_seconds` | — | — | About 120 s for every reason |

No effect from agent experience, agent type, specialty, accent match, segment, country, channel or hour.

### 6.3 Satisfaction (CSAT)

| Driver | Effect on mean CSAT (1–4) |
|---|---|
| `was_resolved` | 3.00 vs. 2.00 (+1.0) |
| Contact reason | 0.48 spread |
| Sentiment | 0.20 spread |
| Wait time, escalation, accent match, agent experience, survey channel | ≤ 0.02 |

Model R² 0.37. An agent's `avg_csat` in `service_agents` does not correlate with the CSAT observed in their surveys (r = −0.015, 1,090 agents).

### 6.4 Demand

| Pattern | Measured |
|---|---|
| Hour of day | **Flat**: 28.3k–29.1k interactions in every hour, 24/7. Digital events are flat too. |
| Day of week | Sunday 57.7k, Monday 96.4k, Tuesday–Friday ~114k, Saturday 76.2k |
| Month / trend | ~18–20k per month, no trend or seasonality |
| Daily volume | CV 0.24 (175–894 per day), mostly from the day-of-week pattern |
| Reason mix | Identical across countries and years (±0.2 pp) |

### 6.5 Other targets

| Target | Model | Notes |
|---|---|---|
| `complaints.sla_breached` (20%) | AUC **0.504** | Flat across priority, category, channel, segment |
| `complaints.resolution_days` | — | Uniform 1–30 (mean 15.6), identical for every priority |
| Complaint ↔ transaction | — | A transaction within 1% of the claimed amount in the prior 60 days exists for 0.2–0.4% of complaints in every subcategory (chance level). *Unrecognised charge* complaints are preceded by a fraud in 0.12% of cases (other subcategories 0.10%). |
| `is_repeat_complainer` | — | Flagged customers had a complaint in the prior 90 days in 3.3% of cases; unflagged in 3.5%. The flag is random. |
| `days_past_due ≥ 30` (12.4%) | AUC **0.495** | Identical by product type, score, income, segment. Only real correlation in the table: `credit_score`–income 0.36. |
| Digital errors → technical calls | — | Technical calls per customer are ~0.68 regardless of the customer's digital error count |
| `had_conversion` (0.56%) | AUC **0.654** | Channel: SMS 0.94%, push 0.77%, email 0.56%. Promoted product 2.2× spread. Segment targeting has no effect. |

---

## 7. Text and language

| Field | Distinct values | Behaviour |
|---|---:|---|
| `call_transcripts.customer_text` | 42 | Two openers ("saldo de mi tarjeta de crédito" / "saldo actual en mi cuenta de ahorros") plus a follow-up phrase. **Every text appears under all 6 contact reasons**: predicting the reason from the text is 34.9% accurate, the same as always guessing the majority class. |
| `call_transcripts.full_text` | 546 | 100% contain unfilled placeholders (`{monto}`, `{moneda}`, `{limite}`) |
| `detected_intents` | 1 | `consulta_general` (95%) or null |
| `detected_keywords` | 12 | Permutations of {banco, cuenta, servicio}, identical across reasons |
| `detected_language` | 1 | `es` |
| `survey.open_comments` | 15 | 5 negative, 3 neutral, 5 positive templates; each group tied to a score (positive → exactly 4.0) |
| `complaints.description` | 5 | "Queja relacionada con {category}" |
| `complaints.resolution` | 5 | Fixed sentences |
| `campaign_sends.subject` | 9 | "¡Oferta especial en {product}!" |

**Accents.** A customer's `detected_accent` is either null (30%) or the accent of their country (100%). Transcript accent equals the customer's accent in 100% of rows. Agent native accent equals country of origin 1:1. `agent_used_accent` matches the customer's accent in 81% of interactions. Accent has no effect on any outcome (§6.2, §6.3).

**Portuguese.** No Portuguese text in any table. Brazil appears only as a transaction country (0.91%). 129 agents list Portuguese as a language.

---

## 8. What the dataset can and cannot support

| Use | Supported? | Evidence |
|---|---|---|
| Seeding a realistic banking core (customers, products, cards, transactions) | ✅ | Keys resolve; distributions are plausible at table level |
| Account and card lookups, statuses, balances | ✅ | `products`, `transactions` |
| Contact-centre baseline: volumes, resolution, handle time, CSAT by reason | ✅ | §6.2–6.4 |
| Day-of-week staffing patterns | ◐ | Weekly pattern only; no intraday pattern |
| Behavioural fraud detection | ❌ | §6.1 |
| Fraud as a given upstream signal | ◐ | `fraud_score` separates two-thirds of frauds, by construction |
| Linking an event to a later contact (fraud → call, error → call, charge → complaint) | ❌ | §6.1, §6.5 |
| Intent classification or any NLP on supplied text | ❌ | §7 |
| Escalation, SLA or credit-risk prediction | ❌ | AUC ≈ 0.50 |
| Accent- or dialect-aware analysis | ❌ | §7 |
| Portuguese | ❌ | §7 |
| Update and freshness correctness | ❌ | §2.3, §2.4 |
| Per-segment and per-country comparisons | ✅ | Columns present; outcomes do not differ, which is itself a result |

---

## 9. ML starting points

A starting point for discussion, not a recommendation.

**Targets with measurable signal in the supplied data**

| Target | Signal | Nature of the signal |
|---|---|---|
| First-contact resolution | AUC 0.77 | Mostly contact reason, plus sentiment and duration |
| Follow-up needed | AUC 0.68 | Contact reason, duration |
| Handle time | R² 0.47 | Contact reason |
| CSAT | R² 0.37 | Resolution, reason |
| Campaign conversion | AUC 0.65 | Channel, product |
| Fraud given `fraud_score` | AUC 0.84 | The score itself; a threshold rule captures the same information |

These relationships are few and simple, so a well-specified rule or a linear model is likely to match a complex model on them. That is a useful baseline to report.

**Where the supplied data has no signal**, learned components would need external or team-generated data: language understanding (intent, slots, Portuguese), and any behavioural anomaly detection. Candidate external sources, not yet validated or approved by the organizers: BANKING77 (English banking intents, CC BY 4.0), Consumidor.gov.br open data (Brazilian complaint taxonomy, CC-BY), MASSIVE (European Portuguese intents, CC BY 4.0).

**Leakage and evaluation notes**

- Label-derived columns: `fraud_score` (for `is_fraud`), `sentiment_score` ↔ `detected_sentiment`, `main_score` ↔ `nps_category`, `open_comments` ↔ `main_score`, `main_topics` = `contact_reason`, `resolution_days` = the date difference.
- The generator has no temporal drift, so a time split behaves like a random split. It is still the right protocol, but it will not reveal drift problems.
- With signals this uniform, per-language and per-segment comparisons on supplied data will show no disparities by construction.

---

## 10. Limitations of this analysis

- **Near-duplicates** were checked only as identical content under a different key. Fuzzy matches (same customer, amount and minute) were not tested.
- **Nonlinear interactions** beyond what gradient boosting captures, and sequence models over digital sessions, were not tested.
- `digital_events` of the backup snapshot were not downloaded.
- The fraud feature set did not include merchant history or cross-customer features.

## Reproduce

**Pending.** The scripts below are not in the repository yet, so these commands fail today. They are kept as the intended procedure. Once the scripts land they get a `make` target.

```bash
cd lab && uv sync
cd profiling
uv run --project .. python stage.py            # raw CSV → data/staging Parquet (~45 s)
uv run --project .. python profile.py
uv run --project .. python integrity.py
uv run --project .. python snapshot_diff.py    # needs data/raw/latam_bank_backup (~15 min)
uv run --project .. python signal_fraud.py
uv run --project .. python signal_contact_center.py
uv run --project .. python signal_other.py
```

Raw JSON outputs go to `lab/profiling/out/`. They are not versioned, because they contain sample values from the dataset.
