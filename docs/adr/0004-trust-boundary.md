# ADR-0004: Trust boundary and threat model

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

The system takes free text from the internet and operates on banking data. Everything arriving through the chat — and everything a model generates from it — is **untrusted input**. The classic mistake in agent architectures is giving the model direct database access and trusting the prompt as a control.

## Decision

Two services with a real trust boundary between them:

- **`orchestrator`** — untrusted zone. Exposes the chat and the back office, holds the session, coordinates the loop with the model and the encoder, masks PII. **Holds no banking database credentials.**
- **`banking-core`** — trusted zone. Owns the bank's data, the state machine, the policy engine and the audit log. Exposes a closed set of tools with a typed contract.

The names are deliberate: they describe responsibility, not position relative to the frontend. See [ADR-0009](0009-monorepo-structure.md).

The LLM never emits SQL and never receives raw rows: it emits tool calls with validated parameters, and `banking-core` decides and returns only the fields policy allows for that verification state.

### Threats and mitigations

| Threat | Mitigation |
|---|---|
| Prompt injection from the customer's message | The model does not authorize; state enables tools. Adversarial scenarios in the suite |
| PII exfiltration to the LLM provider | Masked with the local encoder before every outbound call |
| Access to another customer's data (IDOR) | The account holder is pinned in `banking-core` session state, never passed as a parameter from the model |
| Privilege escalation via configuration | Configuration cannot alter policy; schema validation on save ([ADR-0002](0002-config-code-boundary.md)) |
| Account enumeration by trial and error | Attempt limits per session and IP, with indistinguishable responses for non-existent data |
| Replay of an irreversible action | Idempotency keys and verified receipts |
| Malicious or compromised human agent | Hash-chained audit log; every takeover is recorded |

## Options considered

### Option A: a single monolithic service

**Pros:** simpler, less internal latency, faster to build in 10 days.
**Cons:** the process talking to the internet is the same one holding database credentials; any failure in the conversational layer exposes the core. There is no boundary to show or to audit.

### Option B (chosen): `orchestrator` + `banking-core` with a tool contract

**Pros:** the blast radius of a failure in the conversational layer is bounded; controls are verifiable; it mirrors how this is deployed in a real bank.
**Cons:** two deployments, one more network hop, contracts to maintain.

### Option C: three or more services

Rejected on operational cost versus benefit within the available time. Documented as the natural evolution.

## Trade-off analysis

The cost is latency and complexity; the benefit is that the security property holds **by architecture rather than by model behavior**. With a monolith we would have to argue that the model behaves; this way we can show that even when it misbehaves, it does not reach the data.

## Consequences

**Becomes easier:** reasoning about what an attacker can do; testing controls without the model in the loop.

**Becomes harder:** every new capability crosses a contract; we must avoid the contract degenerating into a generic pass-through that voids the boundary.

**To revisit:** if an endpoint appears that forwards arbitrary parameters to the core, that is a violation of this ADR and gets fixed.

## Action items

1. [ ] Tool contract versioned in `packages/contracts/`, shared by both services
2. [ ] Database credentials only in `banking-core`
3. [ ] PII masking on the outbound path to the provider
4. [ ] Adversarial injection scenarios in the suite
5. [ ] Attempt limits and indistinguishable responses
