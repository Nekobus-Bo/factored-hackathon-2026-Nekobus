# ADR-0007: No LLM-based biometric verification

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

We considered using a vision model to verify identity: the customer sends a photo holding their ID document and the model compares that face against the ID photo on file. It is technically feasible with available multimodal models and would fit the flow.

We rejected it on purpose, and we document it because the challenge explicitly asks teams to state **when the system should not act**.

## Decision

We do not use an LLM as a biometric verification mechanism. Instead:

- We define the interface `identity.verify_document(...)`, returning score, decision and reasons.
- We implement it with a **simulated provider** that responds according to test scenarios.
- The real verification available in this submission is **an OTP to a previously registered channel** (delivered to a simulated in-app inbox, see the 2026-09-29 amendment; the model never chooses the channel), plus matching of ownership data.
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

## Amendment (2026-09-29): OTP delivery is simulated through an in-app inbox

**Context:** the decision above left the OTP delivery channel open (email, Telegram, WhatsApp or SMS, chosen by feasibility and free tier). The product owner closed it: the OTP is **not** sent by email, SMS or any other external channel in this submission. The web client simulates a "you got an email with the code" notice. A real service can be plugged in later, but not for the hackathon.

**Options:** (A) integrate one real channel (SMTP, Telegram, WhatsApp or an SMS gateway): credentials, quotas and a verified sender for a demo nobody can inspect from outside. (B, chosen) simulate delivery in the trusted zone behind the delivery port a real provider would implement. (C) keep an in-memory dev sink: a per-process dict that never expires and breaks with more than one worker or a restart.

**Decision:**

- `banking-core` delivers through `OtpDeliveryPort`. `OTP_CHANNEL_MODE` selects the implementation; the only one implemented is `simulated`, and any other value stops the service at startup with an explicit message (there is no real provider to fall back to).
- The simulated port writes an inbox entry on `redis-core` for each challenge, keyed by the banking session and the challenge and expiring with the challenge. It holds the channel, the masked destination, the code and the timestamps.
- The customer's registered channel (email or SMS) is still resolved server-side from the customer record, and the model never sees the code or chooses the channel or destination. The inbox entry is what the notice is built from: the web client localizes the text from structured data.
- The web client reads the inbox through the orchestrator (`GET /v1/conversations/{id}/inbox`), which relays `banking-core` (`GET /v1/sessions/{id}/simulated-inbox`) using the conversation's own banking session. The code never enters the LLM history, the transcript, the logs or the turn metadata.

**Consequences:**

- The browser that shows the notice is the browser that types the code, so in the demo **the OTP does not prove possession of the registered channel**. This is declared and acceptable for a hackathon, and it is the property a real provider restores by plugging into the port. Since the code now travels through the orchestrator to the browser, the OTP also no longer protects against a compromised orchestrator; that is part of the same declared limit.
- The challenge store keeps only an HMAC of the code as before. The clear code lives in the inbox entry for the challenge TTL and nowhere else.
- Choosing a real channel later is a new decision and gets its own ADR.

## Action items

1. [ ] `identity.verify_document` interface with contract and simulated provider
2. [ ] Test scenario: failed document verification with escalation
3. [ ] Explicit note in the slides and in `limitations.md`
