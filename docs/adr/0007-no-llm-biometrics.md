# ADR-0007: No LLM-based biometric verification

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

We considered using a vision model to verify identity: the customer sends a photo holding their ID document and the model compares that face against the ID photo on file. It is technically feasible with available multimodal models and would fit the flow.

We rejected it on purpose, and we document it because the challenge explicitly asks teams to state **when the system should not act**.

## Decision

We do not use an LLM as a biometric verification mechanism. Instead:

- We define the interface `identity.verify_document(...)`, returning score, decision and reasons.
- We implement it with a **simulated provider** that responds according to test scenarios.
- The real verification available in this submission is **an OTP to a previously registered channel** (delivery channel is an open decision: email, Telegram, WhatsApp or SMS; currently simulated, and the model never chooses it), plus matching of ownership data.
- No path in the system authorizes an action on a biometric result alone.

## Options considered

### Option A: verification with a vision model

**Pros:** visually impressive in a demo; no provider cost; we already have the model.
**Cons:**
- A vision LLM does not return a **calibrated** face-match score; it returns a natural-language opinion that cannot be defensibly thresholded.
- There is no **liveness detection**: a printed photo or a screen passes the check.
- It is **biometric data**, the most sensitive category under any data protection regime. Sending it to an external LLM provider for a demo is exactly the decision a risk reviewer would flag.
- A false positive here is not a conversation error: it is an account takeover.

### Option B (chosen): defined interface, simulated provider, OTP as the real verification

**Pros:** the flow is complete and tested without pretending to a capability we do not have; plugging in a certified provider means swapping an implementation behind the interface; avoids handling biometric data.
**Cons:** less spectacular in the demo; requires explaining the decision, which is exactly what this document does.

### Option C: ignore document verification entirely

Rejected: it would leave a design gap for cases where OTP is not enough.

## Trade-off analysis

We lose visual impact and gain credibility. A jury with banking experience knows that production face matching runs through certified providers with liveness detection, and that a team solving it with a vision model in 10 days **did not understand the risk**. We would rather the absence be an argued decision than an oversight.

## Consequences

**Becomes easier:** integrating a real provider later; sustaining the privacy argument; avoiding biometric storage.

**Becomes harder:** cases where the customer has lost access to every registered channel cannot be resolved online — they escalate to an agent. That is the correct behavior.

**To revisit:** when integrating a real provider, define thresholds, retry policy and image retention.

## Action items

1. [ ] `identity.verify_document` interface with contract and simulated provider
2. [ ] Test scenario: failed document verification with escalation
3. [ ] Explicit note in the slides and in `limitations.md`
