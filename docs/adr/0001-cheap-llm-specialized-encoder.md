# ADR-0001: Cheap generic LLM for language, small specialized encoder for decisions

**Status:** Accepted · amended 2026-09-26 · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

The system has to do two things of a different nature. One is **conversing**: understanding free text, holding context, writing replies in the customer's language and emitting tool calls. The other is **deciding**: classifying intent, extracting entities (card, transaction, amount, document) and detecting PII, consistently, cheaply, with a calibrated score and an audit trail.

A single model can do both, but optimizing for one degrades the other. The binding constraints: 10 days, no API credits provided, and an explicit requirement to justify where AI is appropriate and where it is not.

## Decision

A two-model architecture:

- **Language and tool-calling:** an economy-tier commercial LLM with solid agentic performance, behind an OpenAI-compatible layer (LiteLLM). Default candidate: DeepSeek V4 Flash 0731; alternative candidates: DeepSeek V4.1 Flash and GPT 6 Luna. Candidates are evaluated using the scenario evaluation runner ([evaluation.md](../evaluation.md)), not the encoder calibration harness. The model name is configuration, not code.
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
