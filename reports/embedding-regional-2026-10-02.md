# kb.search on regional test questions: per locale and score floor

- **Date:** 2026-10-02
- **Questions:** `data/eval/synthetic/retrieval/queries_regional.jsonl`, 600 rows, `split: test`, **provisional synthetic**. 150 per locale (es-MX, es-AR, es-CO, pt-BR):
  - 120 answerable, 3 per KB topic;
  - 15 out-of-scope banking products, whose gold is `security_privacy.03`, the scope snippet;
  - 15 off-topic, with no gold.
- **How they were made:** `make synth-retrieval-regional` (`tools/synthdata_regional/retrieval.py`). `openai/gpt-6.1-sol` wrote the customer messages from the half-B style cards and masked phrases mined from real reviews and complaints (Google Play MX/AR, tuquejasuma CO, Reclame Aqui BR). `openai/gpt-6-luna` then wrote, for each message, the query it sends to `kb_search`, using the orchestrator's system prompt and tool schemas. Not reviewed by a human. Quality gate: `data/eval/synthetic/retrieval/regional/checks.md`.
- **Harness reports:**
  - `calibration-embedding-regional-message-2026-10-02.md`: the customer message is searched;
  - `calibration-embedding-regional-rewrite-2026-10-02.md`: the LLM's `kb_query` is searched, which is what kb.search receives in production.
- **Models:** BM25; MiniLM `e8f8c211` (fixed tokenizer); Granite-311m `44399559`, fp32.

## How these questions differ from the older set

From `checks.md`:

| | Older set (`queries.jsonl`) | Regional set |
|---|---|---|
| Median words | 12 | 17–18 |
| Typing distance to real customers (L1 over share features; es) | 1.83 | 0.38–0.52 |
| BM25 Hit@1, a measure of keyword overlap with the gold snippet | 0.37 | 0.11 (es), 0.15 (pt) |
| Questions the KB does not cover | none | 60 off-topic + 60 out-of-scope banking |

They share far fewer words with the KB, so they test meaning, not keyword overlap. Absolute scores drop for every model.

## Results per locale

Same-language Hit@1 / MRR (ranking cut at 5) on the 135 answerable questions per locale, including the out-of-scope banking ones.

| Model | Searched | es-MX | es-AR | es-CO | pt-BR | All |
|---|---|---|---|---|---|---|
| BM25 | message | 0.104 / 0.168 | 0.111 / 0.193 | 0.119 / 0.183 | 0.148 / 0.228 | 0.120 / 0.193 |
| MiniLM | message | 0.274 / 0.355 | 0.267 / 0.367 | 0.230 / 0.315 | 0.259 / 0.372 | 0.257 / 0.352 |
| **Granite** | message | 0.326 / 0.447 | 0.393 / 0.515 | 0.326 / 0.451 | 0.400 / 0.536 | **0.361 / 0.487** |
| BM25 | LLM query | 0.474 / 0.574 | 0.444 / 0.549 | 0.430 / 0.539 | 0.444 / 0.535 | 0.448 / 0.549 |
| MiniLM | LLM query | 0.459 / 0.545 | 0.422 / 0.526 | 0.430 / 0.524 | 0.526 / 0.581 | 0.459 / 0.544 |
| **Granite** | **LLM query** | 0.533 / 0.653 | 0.541 / 0.656 | 0.548 / 0.656 | 0.585 / 0.671 | **0.552 / 0.659** |

**Reading:**
- **Granite is first in every locale and on both inputs.** That confirms the switch (ADR-0006, amendment 2026-10-01) on harder questions grounded in real regional language.
- **The LLM's rewrite helps every model.** Granite gains +0.19 Hit@1. The rewrite is keyword-dense, so BM25 gains most (+0.33) and almost catches MiniLM. The production path is therefore better than the raw-message numbers suggest. It also depends on how the LLM phrases the query, a dependency the older set never measured.
- **Spanish is still the weaker language**, as on the older set. No Spanish locale is clearly worse than another: with 135 questions per locale, differences under about 0.12 are noise.
- **Absolute levels are much lower than on the older set** (Granite 0.72 → 0.55 on the production path). Part of the drop is a harder set. Part is label ambiguity between neighbouring topics: `checks.md` lists 68 of 540 answerable questions where MiniLM and Granite agree on another topic, mostly "unrecognized charge" vs "dispute" and "block" vs "block receipt". No human has resolved them.

## Score floor

A question gets an answer when its best same- or cross-language score reaches the floor, as kb.search does (cosine clipped to [0, 1]). Granite, the 480 answerable in-scope, 60 out-of-scope banking and 60 off-topic questions:

**Searched: the LLM's query (production)**

| Floor | In-scope lost | Out-of-scope banking lost | Off-topic answered |
|---:|---:|---:|---:|
| 0.78 | 0 / 480 | 0.000 | 0.333 (20/60) |
| 0.80 (previous seed) | 0 / 480 | 0.033 | 0.167 (10/60) |
| **0.81 (new seed)** | **0 / 480** | **0.067** | **0.083 (5/60)** |
| 0.82 | 5 / 480 | 0.167 | 0.033 (2/60) |
| 0.83 | 7 / 480 | 0.233 | 0.033 |
| 0.84 | 11 / 480 | 0.317 | 0.033 |
| 0.85 | 12 / 480 | 0.617 | 0.033 |

**Searched: the customer message**

| Floor | In-scope lost | Out-of-scope banking lost | Off-topic answered |
|---:|---:|---:|---:|
| 0.80 | 1 / 480 | 0.000 | 0.183 (11/60) |
| 0.81 | 2 / 480 | 0.017 | 0.100 (6/60) |
| 0.82 | 5 / 480 | 0.100 | 0.017 (1/60) |
| 0.83 | 10 / 480 | 0.183 | 0.000 |

**Decision: `RETRIEVAL_SCORE_FLOOR` 0.80 → 0.81.** On the production path it:
- keeps every answerable in-scope question;
- halves the off-topic questions that still get bank snippets (17% → 8%);
- costs 7% of the out-of-scope banking questions their scope snippet. The LLM can still decline those itself.

Above 0.81, answerable questions start to go unanswered faster than off-topic ones are removed. The earlier floor report (`embedding-score-floor-2026-10-02.md`, 30 team-written off-topic queries) found 3% off-topic answered at 0.80. These regional off-topic messages are closer to banking chat in tone, so they are the harder test.

## Caveats

- **The questions are LLM-written and not reviewed by a human**, so this is a provisional test split. The gold label is the topic the generator was asked to target; the label-drift list in `checks.md` shows where it may be wrong.
- **The generator is the same LLM family that wrote the DistilBERT intent data** (GPT Sol). Nothing for kb.search is trained on its output, so the overlap limits stylistic diversity; it does not leak answers.
- **The rewrite forces a `kb_search` call.** In production the LLM may answer without searching, or search with different context from earlier turns.
- **English has no real-data grounding** and stays on the older set.
- **Each locale is 15 + 15 not-covered questions.** The off-topic rates per locale (0–27%) are too small to compare, so read the pooled rate.
