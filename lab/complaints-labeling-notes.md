# Complaint sample labels: how they were made

Intent labels for `data/staging/complaints/complaints_sample_900.parquet`, stored next to it as
`complaints_sample_900.labels.parquet` (not versioned, like the rest of `data/staging/`). The
`*__complaints*.py` notebooks in `lab/notebooks/` score the three intent models against them.

## Provenance

- **Labelled by an LLM (Claude Opus 5.5), one pass, no second annotator.** These are silver labels.
  `docs/labeling-rubric.md` §1 says test labels must come from humans, so these labels are **not** a test
  set and must never be copied into `data/eval/synthetic/decision.test.jsonl`. Use them for lab
  comparisons only, until a person has reviewed them.
- The labeller read each text's first 900 characters. A few Brazilian complaints are longer.
- Row key: `id` is the row's position in the source parquet (0–899). Columns: `id`, `intent`,
  `label_source`, `labeled_at`.

## Rules added for complaints

The rubric was written for short chat turns. These texts are long, mixed complaints, so these rules
were applied on top of rubric §2. The dominant, most specific actionable intent still wins.

| Situation | Label |
|---|---|
| A charge the customer calls improper, unknown or unauthorized (fees, insurance, debts, purchases), with no request to reverse it | `report_unrecognized_charge` |
| The same, plus an explicit request to refund, reverse, remove or correct it; also *contestação*, *aclaración* or *desconocer el cargo* | `request_dispute` |
| A refund owed for a cancelled or returned purchase that has not arrived | `request_dispute` |
| A scam or hacked account with no specific charge, or an account opened in the customer's name | `report_suspicious_activity` |
| An explicit request to block, cancel or deactivate the customer's own card, including when charges are also disputed | `request_card_block` |
| The main point is not being able to reach a person or agent | `request_human_agent` |
| Asking to see statements, invoices or brokerage notes | `check_recent_transactions` |
| App bugs, login, token or biometrics problems; blocks placed by the bank; transfers or deposits that did not arrive; loans, limits, debt collection, account closure, card machines, promotions, cashback, general bad service | `out_of_scope` |

## Result

900 rows, 8 of the 15 intents present:

| Intent | Rows |
|---|---:|
| `out_of_scope` | 710 |
| `request_dispute` | 91 |
| `report_unrecognized_charge` | 72 |
| `report_suspicious_activity` | 11 |
| `request_card_block` | 6 |
| `request_human_agent` | 6 |
| `check_recent_transactions` | 3 |
| `check_balance` | 1 |

Share of in-scope rows by source: LLM-written 41%, Reclame Aqui 28%, app reviews 2%.

## Known weak spots

- The line between `report_unrecognized_charge` and `request_dispute` is the least stable, because
  many complaints hint at wanting their money back without asking outright.
- `request_human_agent` versus `out_of_scope` for "nobody answers me" complaints is a judgement call.
- A human review of at least the 190 in-scope rows, plus a sample of `out_of_scope`, should come
  before these numbers are quoted outside the lab.

# App-review samples, Mexico and Argentina

Real-world check sets for the es-MX and es-AR datasets: `complaints_{mx,ar}_sample_150.parquet`, with
labels in `complaints_{mx,ar}_sample_150.labels.parquet` (same columns as above). Both files are in
`data/staging/complaints/` and are not versioned.

## Provenance

- **Source:** real Google Play reviews only (`source = 'app_review'`) from `complaints_{mx,ar}.parquet`,
  deduplicated. Reviews over 120 words are excluded. Both company halves are used.
- **Stratified sample of 150 per country:** about 60 reviews hit one of the intent themes of
  `tools/synthdata_regional/locales.py`, at most 6 per theme (out-of-scope themes excluded), and the rest are
  random. Seed 11. The `stratum` and `theme` columns record the draw.
- **Masking:** the same regex masks as mining were applied first. The labeller (Claude Opus 5.5, one pass,
  no second annotator) saw only the masked text. The masks missed one name after "que se llama" (MX row 79).
  They were left unchanged, because changing them would re-mine the style cards and invalidate the
  generation cache.
- **Status:** silver labels, not a test set (rubric §1).

## Rules added for app reviews

The complaint rules above still apply, plus these:

| Situation | Label |
|---|---|
| The review is about the app itself (login, token, biometrics, updates, crashes), even when it says "I can't see my balance" or "I can't see my transactions" | `out_of_scope` |
| Money missing or debited without a matching transaction ("me robaron plata de la cuenta") | `report_unrecognized_charge` |
| A claim or *aclaración* already filed, or a refund still owed | `request_dispute` |
| Cancelling a card out of dissatisfaction, with no security reason ("voy a dar de baja la tarjeta") | `out_of_scope` |
| A known fee the customer only finds abusive (ATM fee, renewal fee) | `out_of_scope` |
| A lost card mentioned as the reason for an app problem | `report_lost_card` |

The last two rules are stricter than the complaint rules above, which counted fees called improper as
`report_unrecognized_charge`.

## Result

| Intent | MX | AR |
|---|---:|---:|
| `out_of_scope` | 131 | 127 |
| `report_unrecognized_charge` | 8 | 8 |
| `request_dispute` | 4 | 8 |
| `request_human_agent` | 1 | 3 |
| `report_lost_card` | 2 | 2 |
| `request_card_block` | 2 | 0 |
| `report_stolen_card` | 1 | 0 |
| `report_suspicious_activity` | 1 | 1 |
| `check_recent_transactions` | 0 | 1 |

Of about 90 random reviews per country, only 1 is in scope, so the theme stratum carries nearly all the
in-scope rows. With 19 (MX) and 23 (AR) in-scope rows, per-intent scores on these sets are anecdotal. Read
the out-of-scope recall and the overall accuracy.

# Complaint threads, Colombia

Real-world check set for the es-CO dataset: `complaints_co_sample_150.parquet`, with labels in
`complaints_co_sample_150.labels.parquet` (same columns as above), both in `data/staging/complaints/` and not
versioned. Built by `make stage-data-co` (`tools/synthdata_regional/stage_tqs.py`).

## Provenance

- **Source:** consumer turns of tuquejasuma.com complaint threads about Colombian banks
  (`data/raw/apple_store_reviews/snapshot_co_1000`, despite the folder name). Only company **half B**
  (DaviPlata, Banco Agrario) is sampled, so no row overlaps the half-A text that mining shows the LLM. Texts
  over 120 words are excluded.
- **Draw:** up to 6 texts per in-scope theme (23 drawn), the rest random. Seed 11. Half B has few texts, so
  the 150 rows are most of it.
- **Masking:** the site's own masks (`[números]`, `[nombre]`, email), the staging name scrub and the mining
  masks were applied first. The labeller (Claude Opus 5.5, one pass, no second annotator) saw only the masked
  text. Two misses remain: a lowercase name after a phone mask (row 61) and a partial email with a masked
  number (row 136). Neither pattern occurs in the half-A phrases sent to the generator.
- **Status:** silver labels, not a test set (rubric §1).

## Rule added for transfers

Most Colombian texts are PSE or Transfiya transfers that were rejected but debited. The complaint rules
above make a transfer that did not arrive `out_of_scope`, and a refund owed `request_dispute`. To keep the
line mechanical:

| Situation | Label |
|---|---|
| A transfer rejected, pending or not credited, with no refund wording | `out_of_scope` |
| The same, when the text asks for or says a refund is still owed (*reembolso*, *devolución*, *devuelto*, *reintegro*, *regresar* or *rebotar la plata*), or a claim was already filed | `request_dispute` |
| Someone else opened or took over a DaviPlata in the customer's name | `report_suspicious_activity` |
| Money missing from the balance with no matching transaction | `report_unrecognized_charge` |
| Registration problems (the RappiPay email loop), blocked wallets, follow-ups ("ya me solucionaron") | `out_of_scope` |

## Result

| Intent | CO |
|---|---:|
| `out_of_scope` | 115 |
| `request_dispute` | 27 |
| `report_suspicious_activity` | 6 |
| `report_unrecognized_charge` | 2 |

35 in-scope rows, more than MX (19) or AR (23), but nearly all of them are disputes about transfers, a
pattern the synthetic test splits barely contain. Per-intent scores beyond `request_dispute` are anecdotal.
