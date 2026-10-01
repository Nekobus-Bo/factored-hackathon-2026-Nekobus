# tools/synthdata_regional

Builds intent datasets grounded in real regional customer text for pt-BR, es-MX, es-AR and es-CO. Each covers the
15 runtime intents with full slots, at 100 train, 50 validation and 50 test rows per intent. Real text is
mined locally into style cards. An LLM writes train and validation from those cards. The test split is
written by hand from the other half of the companies, and a quality gate checks all three splits.

| Locale | Source (local, not versioned) | Rejected rows used as anti-examples |
|---|---|---|
| `pt-BR` | `data/raw/complaints_br/db_reclamacoes_clean.parquet` (Reclame Aqui) | none |
| `es-MX` | `data/staging/complaints/complaints_mx.parquet` (Google Play reviews) | `source = 'llm-synthetic'` rows |
| `es-AR` | `data/staging/complaints/complaints_ar.parquet` (Google Play reviews) | `source = 'llm-synthetic'` rows |
| `es-CO` | `data/staging/complaints/complaints_co.parquet` (tuquejasuma.com bank complaint threads, `make stage-data-co`) | none |

es-CO is small (618 consumer texts from 5 banks) and comes from a complaint forum, not app reviews. Its
regional terms are contrasted with Mexican bank threads from the same site (`complaints_mx_tqs.parquet`), so
they reflect dialect rather than genre. With no rejected rows, its prompt states the lessons of the MX/AR
rejects in words, and its register check gates only the slang cap.

## Pipeline

```bash
make stage-data-co                      # es-CO only: stage the tuquejasuma bank threads first
make synth-data-regional LOCALE=es-MX   # mine (skipped if cards exist) → generate → check
make build-test-regional LOCALE=es-MX   # fill test_templates.*.{txt,tsv} into the provisional test split
make check-data-regional LOCALE=es-MX   # quality gate only; writes checks.md, exits 1 on failure
```

- **`mine.py`** masks real text and splits it into sentences. It keeps only sentences that pass a safety
  filter and tags each one with a theme. Companies are split into two halves by size: A feeds train and
  validation, B feeds the test. It writes `phrase_bank.parquet` and `style_cards.{A,B}.yaml`. The cards hold
  log-odds terms per theme, the register, and for es the words that set this country apart from the other
  one, plus how its customers type (`register.py`).
- **`generate.py`** makes cached LiteLLM calls (`SYNTH_LLM_MODEL`, default `openai/gpt-6.1-sol`; cache in
  `lab/.cache/llm/`). The LLM writes `{slot}` placeholders, which are filled locally with fictitious values
  (`fill.py`). The script then drops near-duplicates, 8-word overlaps with any source text, stray PII and,
  for es, foreign-variety markers. When the filters leave an intent short, top-up rounds refill it.
- **`build_test.py`** reads the hand-written templates (`@intent length [topic]` blocks in `.txt`, or
  four-column `.tsv`) and fills them with a different seed.
- **`checks.py`** is the gate:
  - format and offsets, counts and the short/long mix;
  - duplicates within and across splits;
  - source leakage and PII outside slots;
  - foreign-variety markers in at most 1% of rows;
  - for es, a length spread and typing style closer to the real reviews than to the rejected LLM rows,
    and no slang term in more than 2% of rows.

  It also reports label consistency, a TF-IDF train→test score and a real-review country classifier.
- **`locales.py`** holds everything locale-specific: sources, masks, themes, prompt wording, boundaries,
  personas, document profiles, phones, amounts, merchants and marker lists.

## Privacy (AGENTS.md rule 5)

Only three kinds of text reach the provider:
- half-A style cards (aggregated terms and shares);
- at most 5 masked, safety-filtered real sentences per call;
- for es, a few rejected synthetic rows.

Whole reviews and complaints are never sent. Every PII value in the output is fictitious and sits inside a
slot.

## Caveats

No human has reviewed these datasets, and the test splits are provisional. See `docs/limitations.md`
(regional decision datasets) and `lab/complaints-labeling-notes.md` for the silver real-world labels.

pt-BR's original style cards were mined with an unstable sort. `--if-missing` keeps them, so pt prompts stay
byte-identical and keep hitting the cache.

Tests: `uv run --with pyyaml --with polars --with scikit-learn --with pytest pytest tools/synthdata_regional`.
