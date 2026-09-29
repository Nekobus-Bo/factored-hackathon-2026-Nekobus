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
| Account enumeration by trial and error | Attempt limits per session, per customer (failed OTP) and per claimed document (failed matches) across sessions, and per client IP on conversation creation, with indistinguishable responses for non-existent data. Exactly what is counted, and what is not covered: amendment of 2026-09-29 |
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
5. [x] Attempt limits and indistinguishable responses (see the amendment of 2026-09-29 for scope and gaps)

## Amendment 2026-09-29: attempt limits across sessions and per IP

**Context.** The decision promised "attempt limits per session and IP", but only the per-session counters existed. They start over with every banking-core session, and `POST /v1/conversations` opened one for anyone who asked, unauthenticated and unlimited. An attacker could brute-force OTP codes or identity data against one customer by opening new conversations, and nothing limited by address.

**Decision.** The decision above stands; four layers now enforce it, all as configuration seeded from the environment (ADR-0002) except the last, which the orchestrator reads from its own environment because it has no database:

| Layer | Counted | Where | Effect |
|---|---|---|---|
| Per session | Attempts, failed matches, failed verifies, resends | `banking-core`, session state | Session goes to `LOCKED` |
| Per customer | Failed `otp.verify` evaluations of the pinned customer, in any session, in a fixed window (`RATE_LIMIT_CUSTOMER_OTP_*`) | `banking-core`, redis-core `limit:` | Customer locked for a duration: `otp.send` and `otp.verify` refused with `RATE_LIMITED` before anything is delivered or compared, and the session goes to `LOCKED` (a human) |
| Per document | Failed `customer.match` attempts on the claimed document's blind index, in any session, whether or not a customer has that document (`RATE_LIMIT_DOCUMENT_MATCH_*`) | `banking-core`, redis-core `limit:` | Past the maximum, `customer.match` answers `matched=false` without looking anything up; it still counts as a session attempt |
| Per IP | `POST /v1/conversations` per client address, one-hour fixed window (`RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR`) | `orchestrator`, redis-edge `orch:ratelimit:` | HTTP 429 with `Retry-After`; no banking-core session is opened |

Rules that make the layers hold:

- **Decide before acting.** The customer lock is checked before a code is generated, stored or delivered, and before a submitted code is compared, the same structure as the resend limit. A refused call delivers nothing.
- **Count before evaluating.** A match is reserved on its document counter before the lookup (atomic `INCR`), so parallel sessions cannot all slip past a check-then-act gap; a successful match gives its count back, so only failures stay counted. Failed OTP verifications are counted right after the code is compared.
- **A session locked by OTP failures needs no extra rule**: each of its failures already counted toward the customer. The counter is not reset by the lock or by a successful verify; it ages out with its window.
- **Indistinguishable, still.** The document counter, the response and the audit fields of a call are the same for a document that exists and one that does not; a limited call skips the lookups for both alike.
- **No PII in keys or audit.** Keys hold an internal customer UUID, a blind index, or an HMAC of the client address keyed from `SESSION_SECRET`. The lock events (`security.customer_otp_locked`, `security.document_match_limited`) are audited with the UUID or a 32-character blind-index reference and the thresholds, nothing else.
- **The client address** is the connection peer. `X-Forwarded-For` is ignored unless `TRUSTED_PROXY_HOPS` says how many reverse proxies stand in front; then only the entry a trusted proxy wrote counts. IPv6 clients are grouped by /64. If redis-edge cannot be read, conversation creation answers 503: the limit fails closed.

**Consequences.**

- *Easier:* an attacker gets a bounded number of guesses per customer, per document and per address, however many sessions or conversations they open.
- *Harder:* the limits are a denial-of-service lever. Someone who knows a customer's document can lock that document's matches for a window, and someone who fails five OTPs for a customer locks that customer for a while. The way to a human (`handoff.create`) is never limited (ADR-0003 Appendix A), which is the mitigation, not a cure.
- *Out of scope, declared in [limitations](../limitations.md):* distributed attackers across many addresses; per-IP limits on messages; a limit on `otp.send` volume across sessions (SMS bombing); proxy trust configuration beyond the hop count; the fixed-window boundary (up to twice a maximum can fall around a window change); Redis counters moving before the database commit.
- *Operations:* Redis ACLs need `~limit:*` for `core-svc` and `+incr +incrby +expire` for `edge-svc` ([deployment](../deployment.md)). Verified against a real Redis 7: the previously documented `core-svc` line lacked `+incrby` (redis-py sends `INCR` as `INCRBY`), which the OTP evaluation counter already needed.
