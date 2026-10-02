# kb.search on regional test questions: GPT Sol set vs Claude Opus 5.5 set

- **Date:** 2026-10-02
- **Purpose:** the same recipe with a second author. This tests whether the results in [embedding-regional-2026-10-02.md](embedding-regional-2026-10-02.md) belong to the model or to the generator that wrote the questions.
- **Sets** (both provisional, `split: test`, 600 rows, 150 per locale: 120 answerable, 15 out-of-scope banking, 15 off-topic):
  - **GPT Sol:** `data/eval/synthetic/retrieval/queries_regional.jsonl`, written by `openai/gpt-6.1-sol` through the API.
  - **Claude:** `data/eval/synthetic/retrieval/queries_regional_claude.jsonl`. Claude Opus 5.5 wrote it **by hand in a coding session**, from the same per-call briefs GPT Sol received (`tools/synthdata_regional/retrieval.py --brief`: half-B style card, regional terms, the same sampled real phrases, the same persona per topic). The raw messages are versioned in `regional_claude/written/<locale>.jsonl`. They then go through the same filters, the same `gpt-6-luna` rewrite and the same checks (`make synth-retrieval-regional LOCALE=<locale> GENERATOR=claude`).
- **Harness reports:**
  - `calibration-embedding-regional-claude-message-2026-10-02.md`;
  - `calibration-embedding-regional-claude-rewrite-2026-10-02.md`.

## How the two sets differ

From each set's `checks.md`:

| | GPT Sol | Claude |
|---|---:|---:|
| Possible label drift (both models agree on another topic) | 68 / 540 | 48 / 540 |
| BM25 Hit@1 on messages, es / pt (keyword overlap; lower = harder) | 0.11 / 0.15 | 0.26 / 0.31 |
| Typing distance to real customers, L1 (es-MX / es-AR / es-CO) | 0.52 / 0.52 / 0.38 | 0.75 / 0.55 / 0.31 |
| Median words | 17–18 | 13–15 |
| Spanish rows with a near-duplicate in another locale (char TF-IDF ≥ 0.75) | 8 / 450 | 12 / 450 |

**About the last row.** The first Claude draft adapted the same situations across the three Spanish locales: 192 of 450 rows had a near-duplicate, and 61 rows were exact copies. es-AR and es-CO were then rewritten with different situations for every topic. Only the rewritten set is evaluated here.

The Claude questions carry cleaner labels, but they are shorter and closer to the KB's vocabulary, so they are easier.

## Results

Same-language Hit@1 / MRR on the 540 answerable questions (BM25 / MiniLM `e8f8c211` / Granite-311m fp32).

**Searched: the customer message**

| Model | es-MX | es-AR | es-CO | pt-BR | All |
|---|---|---|---|---|---|
| BM25, GPT Sol set | 0.104 / 0.168 | 0.111 / 0.193 | 0.119 / 0.183 | 0.148 / 0.228 | 0.120 / 0.193 |
| BM25, Claude set | 0.244 / 0.317 | 0.267 / 0.350 | 0.267 / 0.353 | 0.311 / 0.397 | 0.272 / 0.355 |
| MiniLM, GPT Sol set | 0.274 / 0.355 | 0.267 / 0.367 | 0.230 / 0.315 | 0.259 / 0.372 | 0.257 / 0.352 |
| MiniLM, Claude set | 0.333 / 0.441 | 0.311 / 0.426 | 0.363 / 0.453 | 0.311 / 0.421 | 0.330 / 0.436 |
| **Granite, GPT Sol set** | 0.326 / 0.447 | 0.393 / 0.515 | 0.326 / 0.451 | 0.400 / 0.536 | **0.361 / 0.487** |
| **Granite, Claude set** | 0.578 / 0.659 | 0.481 / 0.610 | 0.570 / 0.658 | 0.533 / 0.651 | **0.541 / 0.645** |

**Searched: the LLM's `kb_query` (production path)**

| Model | es-MX | es-AR | es-CO | pt-BR | All |
|---|---|---|---|---|---|
| BM25, GPT Sol set | 0.474 / 0.574 | 0.444 / 0.549 | 0.430 / 0.539 | 0.444 / 0.535 | 0.448 / 0.549 |
| BM25, Claude set | 0.452 / 0.583 | 0.430 / 0.555 | 0.489 / 0.579 | 0.511 / 0.615 | 0.470 / 0.583 |
| MiniLM, GPT Sol set | 0.459 / 0.545 | 0.422 / 0.526 | 0.430 / 0.524 | 0.526 / 0.581 | 0.459 / 0.544 |
| MiniLM, Claude set | 0.489 / 0.600 | 0.444 / 0.552 | 0.511 / 0.607 | 0.504 / 0.595 | 0.487 / 0.588 |
| **Granite, GPT Sol set** | 0.533 / 0.653 | 0.541 / 0.656 | 0.548 / 0.656 | 0.585 / 0.671 | **0.552 / 0.659** |
| **Granite, Claude set** | 0.615 / 0.707 | 0.607 / 0.709 | 0.607 / 0.717 | 0.578 / 0.688 | **0.602 / 0.705** |

**Reading:**
- **The ranking holds across authors.** Granite is first on both sets, in every locale and on both inputs. On the production path its lead over MiniLM is +0.09 (GPT Sol) and +0.12 (Claude), so the ADR-0006 decision of 2026-10-01 is not an artifact of one generator.
- **Absolute levels depend on the author.** Granite on messages scores 0.36 on GPT Sol's questions and 0.54 on Claude's. Most of that gap is how lexical the questions are (BM25 0.12 vs 0.27). Any single number on synthetic questions describes that set, not production.
- **The production path converges.** After the LLM rewrites the messages, the sets differ much less (Granite 0.55 vs 0.60, BM25 0.45 vs 0.47). The rewrite removes most of each author's style, so the production-path numbers are the more stable ones.
- **No locale is consistently weaker.** With 135 questions per locale, differences under about 0.12 are noise. es-AR is lowest for Granite on Claude messages and highest on GPT Sol messages.

## Score floor (0.81)

Granite. Lost = answerable questions left with no result; answered = off-topic questions that still get snippets.

| Set, searched field | In-scope lost | Out-of-scope banking lost | Off-topic answered |
|---|---:|---:|---:|
| GPT Sol, message | 2 / 480 | 0.017 | 0.100 (6/60) |
| Claude, message | 2 / 480 | 0.117 | 0.100 (6/60) |
| GPT Sol, LLM query | 0 / 480 | 0.067 | 0.083 (5/60) |
| Claude, LLM query | 1 / 480 | 0.067 | **0.200 (12/60)** |

The two sets agree on messages (10% off-topic answered). On the LLM-query path the Claude set lets twice as many through. These are the twelve:

| Off-topic message | Query the forced rewrite wrote | Score |
|---|---|---:|
| "hola probando" | "saludo y prueba de atención al cliente" | 0.88 |
| "jaja sorry, era para mi hermana" | "ayuda para hermana consulta bancaria privacidad verificación de identidad" | 0.91 |
| "uy qué pena, era para mi mamá" | "ayuda para un familiar mamá atención bancaria" | 0.87 |

The other nine follow the same pattern. The Claude set has more greetings, "testing" and wrong-chat messages, and the rewrite step forces a `kb_search` call. So the LLM has to invent a query and turns small talk into bank-flavoured searches. In a real conversation the LLM can answer a greeting without searching. This inflates off-topic leakage on the production path in both sets, and more in this one.

**Decision: keep 0.81.** Raising the floor to stop these would lose answerable questions first: at 0.84, 5 of 480 in-scope and 42% of out-of-scope banking are lost, while 13% of off-topic still pass. The floor cannot separate small talk the LLM rewrites into banking terms. Keeping kb.search away from small talk is the LLM's job, not the floor's.

## Caveats

- **The Claude set was written by the same agent, in the same session, that built the pipeline.** That agent had already read the KB, a dozen GPT Sol questions and the GPT Sol label-drift list. It is a second author, not an independent one.
- **es-AR and es-CO were rewritten** after the first draft paraphrased es-MX. es-MX keeps its first draft and is the furthest from real typing (L1 0.75).
- **Both sets are LLM-written and not reviewed by a human.** The gold label is the topic the author targeted.
- **The rewrite forces a `kb_search` call**, which inflates off-topic leakage (see above).
