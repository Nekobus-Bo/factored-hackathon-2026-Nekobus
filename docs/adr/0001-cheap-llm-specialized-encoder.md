# ADR-0001: Cheap generic LLM for language, small specialized encoder for decisions

**Status:** Accepted · amended 2026-09-26, 2026-09-29, 2026-09-30 ([ADR-0014](0014-distilbert-intent-backend.md): the pooled DistilBERT is the decision model; the `hint` effect is the structured context) · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

The system has to do two things of a different nature. One is **conversing**: understanding free text, holding context, writing replies in the customer's language and emitting tool calls. The other is **deciding**: classifying intent, extracting entities (card, transaction, amount, document) and detecting PII, consistently, cheaply, with a calibrated score and an audit trail.

A single model can do both, but optimizing for one degrades the other. The binding constraints: 10 days, no API credits provided, and an explicit requirement to justify where AI is appropriate and where it is not.

## Decision

A two-model architecture:

- **Language and tool-calling:** an economy-tier commercial LLM with solid agentic performance, behind an OpenAI-compatible layer (LiteLLM). Candidates were DeepSeek V4 Flash 0731 (default), DeepSeek V4.1 Flash and GPT 6 Luna; the amendment of 2026-09-29 closes the list to one. Candidates are evaluated using the scenario evaluation runner ([evaluation.md](../evaluation.md)), not the encoder calibration harness. The model name is configuration, not code.
- **Decision and extraction:** a small multilingual encoder served locally on CPU. GLiNER2.5 multilingual (~0.3B, Apache 2.0, declarative schema for NER, classification and structured extraction) is the leading candidate, evaluated and calibrated alongside deterministic baselines via a dedicated calibration harness ([ADR-0010](0010-model-selection-calibration-harness.md)).

The encoder produces intent + slots + score. The LLM never decides intent on its own: it receives the classification as structured context.

## Options considered

### Option A: a single large LLM for everything

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | High and proportional to traffic |
| Scalability | Bounded by budget and latency |
| Team familiarity | High |

**Pros:** one component, immediate start, no data pipeline.
**Cons:** no calibrated probability, so no defensible abstention threshold; high per-turn cost and latency; behavior shifts with every provider update; all PII travels to the provider.

### Option B: fully local, self-hosted open-weights LLM

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Cost | High in infrastructure |
| Scalability | Poor within 10 days |
| Team familiarity | Medium |

**Pros:** full control, no data to third parties.
**Cons:** the models with good tool-use right now are MoE models with hundreds of billions of parameters; serving them exceeds both budget and time. It would consume the entire schedule.

### Option C (chosen): hybrid, cheap LLM + specialized encoder

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Low: the component that runs on every turn is local |
| Scalability | Good; the encoder scales horizontally on CPU |
| Team familiarity | Medium-high |

**Pros:** calibrated score and abstention threshold; the encoder can be fine-tuned on domain data; makes it possible to mask PII **before** leaving for the external provider; per-conversation cost is measurable and low.
**Cons:** two model pipelines to maintain; requires labels; one more dependency at startup.

### Option D: fine-tune the LLM

Rejected: providers at the tier we use do not offer it over the API, and it does not solve the actual problem (calibration and per-turn cost).

## Trade-off analysis

The deciding axis is not language quality, where any of the options is good enough: it is **calibration**. Without a comparable score there is no way to set a threshold below which the system asks for clarification instead of guessing, and that behavior is a requirement of the challenge. An LLM can say "I am unsure", but not consistently and not tunably against a validation set.

The second axis is **privacy**: with a local encoder in place, detecting and masking PII before calling the external provider costs milliseconds, not a new integration.

## Consequences

**Becomes easier:** tuning abstention behavior with a number instead of a prompt; measuring cost per conversation; defending the decision to a jury or a risk committee.

**Becomes harder:** startup has to download weights; a validation set must be kept alive; a change to the intent schema touches two places (configuration and model).

**To revisit:** if the zero-shot classifier meets the per-language macro-F1 target, the fine-tune is not run and is documented as future work.

## Action items

1. [ ] Provider layer with model from configuration and per-turn token/cost logging
2. [ ] Serve the encoder on CPU, with p95 latency measured
3. [ ] Define the workflow's intent and slot schema
4. [ ] Calibrate the abstention threshold on validation using the calibration harness ([ADR-0010](0010-model-selection-calibration-harness.md)) and record it in `evaluation.md`
5. [ ] Mask PII before every outbound call

## Amendment 2026-09-29: one model for the submission, GPT 6 Luna

**Context.** The decision left three candidates to be compared with `make eval`: DeepSeek V4 Flash 0731 (the default), DeepSeek V4.1 Flash and GPT 6 Luna. The runner is not wired yet (⚠️ pending), the code freeze is 2026-10-04 at noon, and the team has one API key, provided by a teammate, for one of them. Comparing three models in three languages in the time left would leave every model with thin evidence.

**Decision.** The submission uses one conversational model, **GPT 6 Luna (OpenAI)**, for the demo, the replay recordings and the evaluation; baseline and proposed system share it. The other candidates are future work. The model stays configuration, not code: the exact model id, base URL and key are set in `.env` by the teammate who provides the key. For reference, the LiteLLM registry bundled with litellm 1.102.1 lists it as `gpt-6-luna` (provider `openai`).

Why this one, and how far the reasons go:

- **Cost.** The registry lists $0.10 per million input tokens, $0.50 per million output tokens and $0.01 per million cached input tokens (list prices; DeepSeek V4 Flash through its own API: $0.30 and $1.20). These are registry prices, not our measurement: the cost per conversation in [evaluation.md](../evaluation.md) is still TODO.
- **Tool calling.** The registry flags function calling, parallel function calling, tool choice, response schemas and system messages for it, the features the turn engine relies on. A registry flag is a claim about the model, not our measurement of tool-call correctness.
- **Time and access.** One model gets the whole scenario suite, per language, once `make eval` exists; the key we have is for this one.

It was **not** chosen on comparative evidence, and no document should say it beats the alternatives.

**Temperature.** The orchestrator calls at temperature 0. Per the teammate who owns the model configuration, Luna accepts that only with reasoning effort `none` (the registry lists `none` as a supported effort for it; we have not made a live call). The setting that sends it, `LLM_REASONING_EFFORT`, is pending in PR #1 (branch `feat/llm-reasoning-effort`), owned by the teammate who configures the model. Until it is merged and set, live calls at temperature 0 are expected to be refused by the provider; replay mode is unaffected.

**Data residency.** Masked conversations leave our perimeter for OpenAI, a US provider. That is a cross-border transfer of personal data; a bank would cover it with a data-processing agreement and a legal basis, and neither exists for this submission. A jury will ask, so the answer is on the record:

- *What leaves.* The system prompt, the tool schemas, the masked customer turns, the model's replies and the masked tool results. Raw values stay in the trusted zone and in the session mapping, which is never sent.
- *What is masked, fail-closed* (the engine checks every string, and the provider layer masks and verifies every outbound message again; a failure sends nothing): emails, card numbers, document numbers, phone numbers, one-time codes, dates (numeric and written out, es/pt/en) and names given with an intro phrase or a salutation, by regular expressions; plus every PII span the local encoder returns for the customer's text (names, phones and documents only when the `gliner` backend runs; the demo default `tfidf_lr` returns email, card number, one-time code and birth date). The encoder is not the provider: it receives the raw text but runs locally on the edge network.
- *Residual risk.* (1) What neither detector recognizes goes out in clear: names without an intro phrase under `tfidf_lr`, digit groups split by spaces, addresses, merchant names, amounts, the last four card digits ([limitations](../limitations.md)). (2) Unmasked details can identify in combination, such as a merchant, an amount and the day of a fraud narrative. (3) Placeholders keep structure: the provider sees that a customer gave an email, a document and a birth date. (4) The provider account's retention and training-use terms were not reviewed contractually.
- *Levers that exist but are not used here.* Regional processing (the registry lists a 10% price uplift for EU or US processing on the OpenAI API, and Azure EU deployments of the same model as `azure/eu/gpt-6-luna`), a zero-retention agreement, and Option B (a self-hosted model) if a risk committee rejects any transfer. Switching is a configuration change plus a contract, not a code change.

**Consequences.**

- *Easier:* one set of numbers per language to defend; the model id is one variable.
- *Harder:* replay recordings are keyed by model id, prompt version and tool schema, so they must be recorded with this model (`LLM_MODE=live`, `RECORD=1`) by whoever holds the key, and again after any change to those. Per AGENTS.md a prompt change needs `make eval` before and after; until it exists, prompt changes are unmeasured.
- *Future work:* run DeepSeek V4 Flash 0731 and DeepSeek V4.1 Flash through the same suite and compare per language on tool-call correctness, unsafe outcomes, cost and p95 latency; review the provider's contractual terms; evaluate regional processing.
