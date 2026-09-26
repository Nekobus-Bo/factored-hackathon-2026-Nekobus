# ADR-0008: CPU inference, offline training and private-environment deployment

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

We use our own specialized encoder, with the option of fine-tuning it on domain data. That raises the infrastructure question: is a GPU required, and is it required while the jury is evaluating?

The common confusion is treating training and inference as the same resource problem. They are not.

## Decision

- **Training (build-time):** the encoder is fine-tuned offline, in a temporary GPU environment. It happens once, the resulting weights are versioned, and the procedure is documented and reproducible.
- **Inference (runtime):** the encoder and the embedding model run **on CPU**. These are models in the hundreds of millions of parameters, not billions; quantized, they occupy hundreds of megabytes and respond in tens of milliseconds.
- **Deployment:** the whole system runs in a **private environment** managed by the team, sized comfortably above what the runtime demands. It does not depend on an online GPU.
- **Only external runtime dependency:** the LLM API. Everything else is local, so that reproducing the system requires as few third-party credentials as possible.

## Options considered

### Option A: everything on platform free tiers

| Dimension | Assessment |
|---|---|
| Cost | Zero |
| Risk | High: memory limits, idle suspension, cold starts |
| Control | Low |

**Pros:** no spend.
**Cons:** typical memory limits are not enough to load the models; idle suspension would have the jury find the system down or extremely slow on first try. The number-one evaluation criterion is that the system runs: this is not where to save money.

### Option B (chosen): private environment sized for CPU

**Pros:** full control, no cold starts, availability during the evaluation window, marginal cost over the challenge period.
**Cons:** the team administers the environment; deployment must be documented so third parties can reproduce it.

### Option C: online GPU inference

**Pros:** would enable larger models.
**Cons:** disproportionate cost with no need: no runtime component requires it. It would be optimizing what does not hurt.

## Trade-off analysis

Separating training from inference removes the apparent dilemma between "our own model" and "no GPU". Fine-tuning a small encoder is a matter of minutes on borrowed hardware; serving it is a matter of a couple of cores. What the private environment buys is not power, it is **predictability** during evaluation.

## Consequences

**Becomes easier:** guaranteeing availability in the review window; measuring real latency without cold-start noise; reproducing the full system with one command.

**Becomes harder:** the environment has to be administered; model weights must be versioned and reachable at image build time, or reproducibility breaks.

**To revisit:** if the fine-tune does not beat zero-shot on validation, it is not deployed and the base model stands. That decision is made with the results table in hand.

## Action items

1. [ ] Measure encoder memory and p95 latency on CPU, and record it
2. [ ] Quantize if latency requires it
3. [ ] Version weights and document the training procedure
4. [ ] Full `docker compose up`, verified on a clean machine
5. [ ] Confirm environment availability during the evaluation window
