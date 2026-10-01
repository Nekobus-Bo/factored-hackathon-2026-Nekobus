# ADR-0008: CPU inference, offline training and private-environment deployment

**Status:** Accepted · amended 2026-09-29, 2026-09-30 ([ADR-0014](0014-distilbert-intent-backend.md): decision weights are baked into the encoder image from a digest-pinned seed image) · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

We use our own specialized encoder, with the option of fine-tuning it on domain data. That raises the infrastructure question: is a GPU required, and is it required while the jury is evaluating?

The common confusion is treating training and inference as the same resource problem. They are not.

## Decision

- **Training (build-time):** the encoder is fine-tuned offline on an Apple Silicon Mac with Metal Performance Shaders (MPS). It happens once, the resulting weights are versioned, and the procedure is documented and reproducible.
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

Separating training from inference removes the apparent dilemma between "our own model" and "no GPU". Fine-tuning a small encoder is a matter of minutes on local Apple Silicon (MPS); serving it is a matter of a couple of cores on CPU. What the private environment buys is not power, it is **predictability** during evaluation.

## Consequences

**Becomes easier:** guaranteeing availability in the review window; measuring real latency without cold-start noise; reproducing the full system with one command.

**Becomes harder:** the environment has to be administered; model weights must be versioned and reachable at image build time, or reproducibility breaks.

**To revisit:** if the fine-tune does not beat zero-shot on validation, it is not deployed and the base model stands. That decision is made with the results table in hand.

## Action items

1. [ ] Measure encoder memory and p95 latency on CPU, and record it
2. [ ] Quantize if latency requires it
3. [ ] Version weights and document the training procedure
4. [ ] Full `docker compose up`, verified on a clean machine
5. [ ] ~~Confirm environment availability during the evaluation window~~ superseded by the amendment of 2026-09-29

## Amendment 2026-09-29: judges run it locally; the private environment is the team's

**Context.** The decision and Option B assumed judges would use an instance the team runs, available during an evaluation window. The team decided otherwise: judges clone the repository and run `make demo` on their own machine, with at most an LLM API key in `.env`. A hosted instance would make the evaluation depend on our server being up, and the first criterion is that a third party can run the system.

**Decision.** The runtime decisions stand: offline training, CPU inference, the LLM API as the only external dependency. What changes is who uses the private environment. There is no environment for judges, no link is published and no availability window is promised. The team keeps its own presentation environment for its live presentation, an ordinary deployment with production-hardened defaults and the demo features switched on explicitly ([deployment.md](../deployment.md), section 7). The hosting platform is still to be decided.

**Consequences.** The "availability during the evaluation window" advantage of Option B no longer applies to judges, and action item 5 is dropped. Sizing the runtime for CPU now protects the judge's machine rather than our server: the requirements in the [runbook](../runbook.md) are the contract, and a clean-machine run of `make demo` is the check that matters.

## Amendment 2026-09-29 (2): the model server, and the local sidecar after the freeze

**Context.** [ADR-0012](0012-decision-points.md) makes the decision model and the embedding model two of three models (the third is the external LLM) and asks where they run.

**Decision.** The runtime decision stands (both run on CPU, the LLM API is the only external dependency), and the two local models run on a separate **model server**: the existing `apps/encoder` service, deployable on its own host in the team's private network. The model server receives raw customer text, so it runs only inside that network and never as a third-party service. Both models are pinned by revision and hash and calibrated by the teammate who owns calibration.

ADR-0012 also adds this option, which this ADR did not consider: *an optional local sidecar of up to ~4B parameters, 4-bit quantized, is allowed for individual decision points when calibration evidence shows a gain that smaller models cannot deliver. It runs on CPU in its own container with its own memory limit and is never on by default.* At the freeze only the interface, a conformance test and a stub that fails as `pending: llm_sidecar is not implemented (ADR-0012)` ship. The container, prompt and calibration belong to the teammate and come after the freeze.

**Consequences.** The environment sized for CPU includes the model server. With `tfidf_lr` and the embedding model it should fit the default 3 GB container limit (an estimate: the ~1.3 GB measured earlier in `banking-core` included the KB index, and the model server holds the model only; the Linux measurement is pending); with `gliner` (~3.5 GB peak) plus the embedding model it needs a larger limit (estimate). A ~4B sidecar would add a 4 GB container, so the host would need 12 GB or more; the host size is an open question in ADR-0012, Appendix C.3.

## Amendment 2026-09-29 (3): the platform is Cloud Run

**Decision.** The presentation environment runs on Google Cloud Run ([ADR-0015](0015-gcp-cloud-run-terraform.md)). The runtime decisions stand: CPU inference, the LLM API as the only external dependency.

**Consequences.** Option B's "no cold starts" becomes a setting rather than a property of the host: the model server, `banking-core` and the orchestrator keep one instance running, the model server with CPU always allocated, and a `warm` switch turns that off between presentations. "Model weights must be reachable at image build time" becomes literal: the embedding model is baked into the model server's image, pinned by revision and hash. The model server has no path to the internet, which the Docker host never enforced.
