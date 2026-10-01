# Intent classification on real Latin American banking text: datasets and model comparison

**Date:** 2026-09-30 · **Branch:** `feat/es-intent-dataset` · **Status:** lab evidence. No evaluation set here is
human-labelled, so read every number as a comparison between models, not as a production estimate.

**Question:** which model should classify customer messages into the 15 runtime intents
(`data/eval/synthetic/schema.yaml`) for Brazil, Mexico and Argentina, and what data does it need?

**Answer:**
- One multilingual DistilBERT, fine-tuned on the pooled pt-BR, es-MX and es-AR grounded datasets.
  - Mean accuracy 0.76 over six evaluation sets, at about 10 ms per message on CPU.
  - The zero-shot models (Laya, bge reranker) are not viable on real text.
- The main open problem is **out-of-scope recall on real text** (0.47–0.75).
- **es-CO (2026-10-01, §10):** a grounded Colombian dataset lifts CO real accuracy from 0.50 to 0.57, but the four-locale model drops MX real by 0.023, just past the pre-set tolerance, so the shipped three-locale weights stay.

---

## 1. Sequence of work

| Step | What | Why |
|---|---|---|
| 1 | Baseline: 3 models on a 900-row real complaint sample | See how existing candidates behave on real text |
| 2 | pt-BR grounded dataset (mined from 59.5k Reclame Aqui complaints) | Real complaints don't map to the 15 intents; turn their language into a labelled dataset |
| 3 | pt-BR model comparison | Does grounded training data help? |
| 4 | es-MX and es-AR grounded datasets (from 63k Google Play reviews) | Same method for two Spanish varieties, avoiding the flaws of earlier LLM rows |
| 5 | es model comparison, including cross-country transfer | Does a model need its own country's Spanish? |
| 6 | Pooled model (pt + MX + AR), 2 seeds | One model for all markets, with noise control |
| 7 | Out-of-scope error analysis | The weakest point on real text |
| 8 | es-CO dataset (tuquejasuma.com complaint threads) and a four-locale pooled model | Add Colombia; replace the weights only if no market loses |

---

## 2. Models compared

| Model | Type | Size | How it classifies |
|---|---|---|---|
| **Laya** (`convaiinnovations/laya-multilingual`) | Zero-shot | — | Reads the 15 intent descriptions and chooses one |
| **Reranker** (`BAAI/bge-reranker-v2-m3`) | Zero-shot cross-encoder, XLM-RoBERTa-large | ~568M | Scores each (message, intent description) pair, so 15 passes per message |
| **Fine-tuned DistilBERT** (`lxyuan/distilbert-base-multilingual-cased-sentiments-student`) | Supervised | ~135M | 6-layer multilingual encoder with a new 15-way output layer, trained on labelled rows |

**Fine-tuning settings** (the same everywhere):
- 4 epochs, AdamW, learning rate 5e-5, batch 32;
- 128 tokens for training and 256 for scoring;
- training on Apple MPS; scoring and latency measured on CPU (ADR-0010).

## 3. Metrics

| Metric | Meaning | Why it matters here |
|---|---|---|
| Accuracy | Share of messages with the correct intent | Headline number; dominated by out-of-scope on real text |
| Macro-F1 | Mean F1 over intents, each weighted equally | Fair on the balanced synthetic tests |
| Weighted-F1 | F1 weighted by class frequency | Fairer on the unbalanced real sets |
| **Out-of-scope recall** | Share of truly out-of-scope messages predicted out-of-scope | Real text is 72–87% out-of-scope; a miss sends a non-banking message into a banking flow |
| Dispute F1 | Mean F1 of `request_dispute` and `report_unrecognized_charge` | Core of the compromised-card workflow |
| p95 latency | 95th-percentile time per message, CPU, single message | Encoder budget |
| Seed spread | Gap between two training runs with different seeds | Differences smaller than this are noise |

The dataset quality metrics (gates in `tools/synthdata_regional/checks.py`) are listed in §5.3.

---

## 4. Step 1: baseline on real complaints

**Data:** `complaints_sample_900` (300 BR, 300 MX, 300 AR real complaints), with silver labels from the coding agent.
- 79% of rows are `out_of_scope`, and only 8 of the 15 intents occur at all.
- The fine-tuned model here was trained on the old **template** dataset (`data/eval/synthetic`).

**Notebooks** (one per model, with the same metric cells):
- `lab/notebooks/laya-zero-shot__complaints.py`
- `lab/notebooks/reranker-zero-shot__complaints.py`
- `lab/notebooks/finetune__complaints-distilbert-multilingual.py`

| Model | Accuracy, 15 intents offered | Accuracy, only the 8 present intents offered | BR rows only (8 intents) |
|---|---|---|---|
| Laya | 0.049 | 0.138 | 0.150 |
| Reranker | **0.236** | **0.333** | **0.377** |
| Fine-tuned on templates | 0.093 | 0.123 | 0.073 |

**Takeaway:**
- All three models fail on real text. Laya over-predicts `deny`.
- The fine-tuned model is worst on Brazilian text: template phrases don't transfer to real customer language.

---

## 5. Steps 2 and 4: grounded datasets

### 5.1 Method (the same for the three locales, `tools/synthdata_regional/`)

1. **Mine locally** (`mine.py`):
   - mask personal data, split into sentences, and keep only sentences that pass a safety filter;
   - tag each sentence with a theme per intent;
   - rank distinctive terms per theme (log-odds);
   - measure register (openers, informal spelling, money and date formats);
   - for es, also extract the words that set Mexico apart from Argentina and vice versa.

   Companies are split into two halves: A feeds train and validation, B feeds the test.
2. **Generate train and validation** (`generate.py`, gpt-6.1-sol):
   - 1 intent × 1 length per call, with `{slot}` placeholders filled locally with fictitious values;
   - for es, the prompt includes rejected earlier rows as anti-examples;
   - near-duplicates, source leaks, stray PII and foreign-variety markers are dropped;
   - top-up rounds refill intents the filters leave short.
3. **Hand-write the test** (the coding agent, from half-B material; `build_test.py`): a different model,
   process and set of companies from train.
4. **Gate** (`checks.py`, §5.3).

**Size per locale:** 100 train, 50 validation and 50 test rows per intent, so 1,500 + 750 + 750. About 25% of
rows are long, complaint-style messages.

**Privacy (AGENTS.md rule 5):** only aggregated style cards, at most 5 masked sentences per call, and
rejected synthetic rows reach the provider.

**Notebooks and tools:**
- `lab/notebooks/eda-text__complaints-br-banking.py` (pt mining);
- `lab/notebooks/llm-synthetic__decision-pt.py` (pt generation prototype);
- es mining and generation run directly through `make synth-data-regional LOCALE=…`.

### 5.2 Why the es datasets were built differently

The review files shipped 459 earlier LLM rows, which were judged not good enough. Measured against the real
reviews, they failed in a consistent way. The pilot (10 rows per intent) fixed it before the full run:

| Typing feature (MX / AR) | Real reviews | Rejected LLM rows | Pilot |
|---|---|---|---|
| Word-count CV (length spread) | 0.64 / 0.67 | 0.19 / 0.17 | 0.99 / 0.98 |
| Ends in a request | 19% / 17% | 62% / 67% | 32% / 25% |
| Contains regional slang | 0.5% / 1.0% | 13% / 16% | 0% / 0.7% |
| No final punctuation | 58% / 53% | 15% / 12% | 74% / 63% |
| Register distance to real / to rejected (L1 over 8 features) | — | — | 0.49 / 1.05 · 0.45 / 1.01 |

Three fixes after the pilot:
- long rows cycle through 30–50, 50–80 and 80–130 word bands;
- relative dates are never placed after an article ("el hoy");
- personas no longer name cities.

### 5.3 Final dataset quality (all hard gates pass for all three locales)

| Check | pt-BR | es-MX | es-AR |
|---|---|---|---|
| Format and exact slot offsets, counts, short/long mix | PASS | PASS | PASS |
| Near-duplicates within a split / across splits | 0 / 0 | 0 / 0 | 0 / 0 |
| 8-word run shared with a source text | 0 | 0 | 0 |
| PII outside filled slots | 0 | 0 | 0 |
| Rows with foreign-variety markers | 0 | 0 | 0 |
| Register distance to real / to rejected rows | — | 0.41 / 1.06 | 0.38 / 1.08 |
| Most frequent slang term | — | 0.3% | 0.3% |
| Out-of-fold label consistency (TF-IDF+LR, worst intent: out_of_scope) | 0.947 | 0.920 | 0.907 |
| TF-IDF train → test accuracy (how easy the test is) | 0.941 | 0.915 | 0.905 |
| Real-review country classifier assigns rows to own country | — | 0.54–0.58 | 0.76–0.82 |

### 5.4 Real-world check sets (silver labels, `lab/complaints-labeling-notes.md`)

| Set | Rows | `out_of_scope` | In-scope |
|---|---|---|---|
| BR complaints (from the 900 sample) | 300 | 215 (72%) | 85 |
| MX app reviews (stratified sample) | 150 | 131 (87%) | 19 |
| AR app reviews (stratified sample) | 150 | 127 (85%) | 23 |

---

## 6. Step 3: pt-BR comparison (`lab/notebooks/compare__decision-pt.py`)

| Model | pt test accuracy / macro-F1 | BR real accuracy / weighted-F1 | Out-of-scope recall (BR) | Dispute F1 (BR) | p95 |
|---|---|---|---|---|---|
| **FT grounded pt** | **0.900 / 0.902** | **0.497 / 0.563** | **0.52** | **0.48** | 16 ms |
| Reranker | 0.669 / 0.648 | 0.277 / 0.363 | 0.31 | 0.20 | 954 ms |
| FT templates | 0.540 / 0.542 | 0.080 / 0.077 | 0.05 | 0.00 | 16 ms |
| Laya | 0.489 / 0.468 | 0.047 / 0.051 | 0.01 | 0.19 | 105 ms |

**Takeaway:** it's the same architecture, and only the data changed. On real BR text the grounded model scores
0.50 against 0.08 for the template-trained one.

## 7. Step 5: es comparison (`lab/notebooks/compare__decision-es.py`)

Single seed. Each fine-tune is scored on both countries.

| Model | MX test | AR test | MX real | AR real | Out-of-scope recall, real MX / AR | p95 |
|---|---|---|---|---|---|---|
| FT on AR | **0.885** | **0.885** | **0.687** | **0.720** | 0.74 / 0.72 | ~10 ms |
| FT on MX | 0.865 | 0.804 | 0.493 | 0.540 | 0.51 / 0.58 | ~10 ms |
| Reranker | 0.647 | 0.665 | 0.167 | 0.267 | 0.15 / 0.23 | ~450 ms |
| Laya | 0.503 | 0.496 | 0.027 | 0.047 | 0.02 / 0.04 | ~70 ms |

**Takeaway:**
- Zero-shot models collapse on real reviews because they almost never predict out-of-scope.
- The apparent "AR beats MX" gap turned out to be mostly seed noise (step 6).

## 8. Step 6: pooled model (`lab/notebooks/finetune__decision-pooled.py`)

Four DistilBERTs with identical settings, 2 seeds each, scored on six sets. The table gives accuracy as the mean
over the seeds; the ± value is the gap between the two runs.

| Trained on | PT test | MX test | AR test | BR real | MX real | AR real | **Mean** |
|---|---|---|---|---|---|---|---|
| PT only (1,500 rows) | 0.893 | 0.617 | 0.618 | **0.545** ±0.10 | 0.603 ±0.10 | 0.647 | 0.654 |
| MX only (1,500) | 0.639 | 0.876 | 0.819 | 0.423 | 0.523 | 0.570 | 0.642 |
| AR only (1,500) | 0.698 | 0.874 | 0.879 | 0.433 ±0.26 | 0.607 ±0.16 | 0.660 ±0.12 | 0.692 |
| **Pooled (4,500)** | **0.904** | **0.924** | **0.917** | 0.472 ±0.02 | **0.667** | **0.683** | **0.761** |

| Out-of-scope recall | PT test | MX test | AR test | BR real | MX real | AR real |
|---|---|---|---|---|---|---|
| PT only | 0.74 | 0.72 | 0.77 | **0.60** | 0.67 | **0.72** |
| MX only | 0.81 | 0.77 | 0.75 | 0.52 | 0.54 | 0.60 |
| AR only | 0.72 | 0.74 | 0.71 | 0.46 | 0.65 | 0.65 |
| **Pooled** | **0.81** | **0.86** | **0.84** | 0.51 | **0.70** | 0.70 |

**Takeaways:**
- **Pooling wins overall.** It is best on all three tests (+4–5 points on MX and AR, beyond the seed noise) and
  most stable on real text.
- **Language matters more than regional variety.** A Portuguese-only model drops to about 0.62 on Spanish, but
  Mexican and Argentine data transfer well to each other (0.82–0.87).
- **One exception:** on BR real complaints the PT-only model leads (0.545 vs 0.472), but its seed spread is ±0.10.

---

## 9. Step 7: out-of-scope analysis

| | Synthetic training | Synthetic tests (pooled recall) | Real text (pooled recall) |
|---|---|---|---|
| Out-of-scope share | 6.7% (100 of 1,500 per locale) | 6.7% | **72–87%** |
| Rows containing intent keywords (tarjeta, saldo, bloqueo, token…) | 4–16 per 100 | few | most |
| Recall | — | 0.82 / 0.88 / 0.88 (PT/MX/AR) | **0.47 / 0.74 / 0.75** (BR/MX/AR) |

**Failure pattern: keyword traps.** A real complaint about the app or a bank policy uses intent words, so the
model maps it to that intent. Most frequent wrong outputs: card block (41), unrecognized charge (30),
suspicious activity (30), dispute (23). Examples (real, masked):

| Message | Predicted | Actually |
|---|---|---|
| "No me permite ver los saldos. La semana pasada funcionaba perfectamente." | `check_balance` | App bug |
| "Arreglen el token de seguridad de una vez…" | `report_suspicious_activity` | App bug |
| "…cortou meu cartão de crédito… meu nome tá limpo" | `report_lost_card` | Credit cancelled by the bank |

---

## 10. Step 8 (2026-10-01): es-CO dataset and a four-locale model (`lab/notebooks/compare__decision-pooled-co.py`)

**Question:** does an es-CO grounded dataset, added to the pooled training data, help Colombia without costing the other three markets, so that it should replace the shipped weights? (ADR-0014 amendment.)

### 10.1 The es-CO dataset

Same method as §5.1, with three differences:

- **Source:** 618 consumer texts (openings and comments) from tuquejasuma.com complaint threads about five Colombian banks (Bancolombia, Davivienda, Banco Popular in half A; DaviPlata, Banco Agrario in half B), staged by `make stage-data-co`. It is a complaint forum, not app reviews, and it is small: only 105 half-A sentences pass the safety filter and match a theme, with almost none for the card intents.
- **Regional terms** are contrasted with Mexican bank threads from the same site, so they reflect dialect rather than genre: *transacción*, *plata*, *valor*, *rechazada*, *movicuenta*, *entidad*.
- **No rejected rows:** the prompt states the MX/AR lessons in words and shows no anti-examples (like pt-BR). The register check gates only the slang cap.

Generation took 166 calls (about 262k tokens, gpt-6.1-sol). The test split was hand-written from half-B material.

| Check | es-CO |
|---|---|
| Format and exact slot offsets, counts, short/long mix | PASS |
| Near-duplicates within a split / across splits | 0 / 0 (after rewriting 44 short test rows) |
| 8-word run shared with a source text | 0 |
| PII outside filled slots (now including cédulas and NITs) | 0 |
| Rows with foreign-variety markers | 0 |
| Register distance to real text (no rejects to compare with) | 0.29 |
| Most frequent slang term | *qué pena* 0.5% |
| Out-of-fold label consistency (worst intent: out_of_scope) | 0.873 |
| TF-IDF train → test accuracy | 0.948 |
| Real-text country classifier (CO vs MX threads) assigns rows to Colombia | 0.53–0.57 |

**CO real set:** 150 half-B texts with silver labels: 115 `out_of_scope`, 27 `request_dispute`, 6 `report_suspicious_activity` and 2 `report_unrecognized_charge`. Nearly every in-scope row is a PSE or Transfiya transfer that was rejected but debited (labelling rule in `lab/complaints-labeling-notes.md`, Colombia).

### 10.2 Comparison

Two seeds each; the shipped weights (the pinned model, seed 0 of the same recipe) are scored as a reference. Accuracy, mean over seeds:

| Model | PT test | MX test | AR test | CO test | BR real | MX real | AR real | CO real | Mean |
|---|---|---|---|---|---|---|---|---|---|
| Pooled-3 (pt+MX+AR, retrained) | 0.897 | 0.919 | 0.916 | 0.910 | **0.520** | **0.713** | **0.753** | 0.497 | 0.766 |
| **Pooled-4 (+ CO)** | **0.925** | **0.933** | **0.931** | **0.932** | 0.483 | 0.690 | 0.743 | **0.573** | **0.776** |
| Shipped weights | 0.903 | 0.931 | 0.928 | 0.920 | 0.460 | 0.713 | 0.727 | 0.480 | 0.758 |

| Out-of-scope recall / dispute F1 | BR real | MX real | AR real | CO real | Mean of 8 sets |
|---|---|---|---|---|---|
| Pooled-3 | 0.60 / 0.28 | 0.76 / 0.36 | 0.79 / 0.52 | 0.60 / 0.11 | 0.76 / 0.60 |
| Pooled-4 | 0.53 / 0.31 | 0.74 / 0.40 | 0.76 / 0.60 | 0.65 / 0.23 | 0.77 / 0.66 |

Seed spreads on the real sets reach 0.11 (BR), so most real-text gaps are noise.

### 10.3 Decision: the shipped weights stay

The replacement rule was fixed before running:

| Rule | Result |
|---|---|
| 1. Beats Pooled-3 on CO test and CO real by more than the seed spread | **pass**: +0.022 (spread 0.020) and +0.076 (spread 0.033) |
| 2. No non-CO set drops by more than max(seed spread, 0.02) | **fail**: MX real −0.023 against an allowed 0.020 (spread 0.007), about 3.5 of 150 rows. BR real −0.037 is inside its 0.113 spread |
| 3. Mean real-text out-of-scope recall not lower beyond the spread | **pass**: −0.017 (spread 0.115) |

**Takeaways:**
- **CO data helps Colombia** (+7.6 points on CO real) and every synthetic test (+1.4 to +2.8), and raises dispute F1 on all eight sets.
- **The cost is small but measured on real text:** MX real drops just past the tolerance, and BR real drops within noise. With 150 silver-labelled rows per country, the rule cannot tell a 3-row change from noise any better than this.
- **Retrained Pooled-3 already beats the shipped weights** on five of eight sets (mean 0.766 against 0.758): MPS training is not deterministic, so a retrain alone moves the numbers.
- es-CO keeps falling back to the `es` thresholds at runtime (ADR-0014 decision 3).

---

## 11. Limitations

- **No human labels anywhere.**
  - The tests are provisional (written by the coding agent).
  - The real-world labels are silver (one LLM pass).
  - The MX and AR tests share scenarios.
- **The synthetic tests are easy** (TF-IDF reaches 0.90–0.94 on them), so rankings on real text matter more.
- **Too few in-scope real rows** (19 MX, 23 AR) for per-intent real-world scores.
- **Card intents have very little real evidence** in the Spanish sources (lost card: 7 MX and 2 AR sentences).
- **Single seed** in steps 3 and 5.
- **Unequal training compute:** the pooled model makes 3× more updates than a single-country model.
- **Data stays local:** `data/staging/` is not versioned, so rerunning needs the LLM cache
  (`lab/.cache/llm/`) or new paid calls.

## 12. Future improvements

| Priority | Improvement | Expected effect | Cost |
|---|---|---|---|
| 1 | Add real masked out-of-scope sentences from the phrase banks to training, excluding evaluation reviews | Out-of-scope recall on real text | Low, no LLM |
| 2 | Calibrate an abstention threshold τ (confidence below τ → out-of-scope), run through `make calibrate` (ADR-0010) | Fewer confident wrong intents on rants | Low |
| 3 | Contrastive hard negatives: out-of-scope rows that contain intent keywords, paired with the in-scope version | Removes keyword traps | 1 LLM run per locale |
| 4 | Rebalance training (out-of-scope share about 20%, or class weights) | Closer to the real class prior | Retraining only |
| 5 | Human review of the silver labels and the provisional tests (rubric §1) | Numbers that can be quoted outside the lab | People time |
| 6 | More seeds (5) and an equal-compute comparison | Reliable gaps between models | Compute |
| 7 | Harmonize labelling rules (fees: pt counted improper fees as unrecognized charges, es counts them as out-of-scope) | Consistent labels across markets | Low |
| 8 | Close pending plan items: push the branch, a Spanish mining notebook, pt generation notebook importing `fill.py`, `make calibrate` for pt and MX | Reproducibility | Low |

## Appendix: how to reproduce

```bash
make stage-data-co                        # es-CO only: stage the tuquejasuma.com bank threads
make synth-data-regional LOCALE=es-MX     # mine (skipped if cards exist) → generate → check
make build-test-regional LOCALE=es-MX     # hand-written templates → provisional test split
make check-data-regional LOCALE=es-MX     # quality gate, writes data/staging/decision_es_mx/checks.md
make calibrate TASK=decision CONFIG=tools/calibrate/configs/decision_es_mx.yaml
uv run --with pyyaml --with polars --with scikit-learn --with pytest pytest tools/synthdata_regional
```

Model comparisons run from `lab/`: `uv run marimo edit notebooks/compare__decision-es.py`. The comparison
notebooks show progress bars; the es run takes about 11 minutes on an Apple M-series laptop, most of it in the
reranker.
