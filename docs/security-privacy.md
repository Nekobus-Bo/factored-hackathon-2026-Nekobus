# Security and privacy

Operational summary of the decisions taken in [ADR-0004](adr/0004-trust-boundary.md), [ADR-0005](adr/0005-application-level-encryption.md) and [ADR-0007](adr/0007-no-llm-biometrics.md).

## 1. What data we handle

| Category | Examples | Treatment |
|---|---|---|
| Identifiers | Document number, phone, email | Encrypted; lookup via blind index |
| Financial | Accounts, cards, transactions | Sensitive fields encrypted; card numbers always masked on display |
| Conversational | Customer messages | Encrypted per conversation |
| Operational | Decisions, tool calls, timings, costs | No PII; the basis for analytics |

## 2. Principles

**Minimization.** Every tool returns only the fields its verification state allows. Before identity is verified, data is used to **match**, never to display: the system asks and compares, it does not read information out loud.

**Mask before leaving.** All text headed for the LLM provider passes through local PII detection and is replaced with markers. Rehydration happens on our side, after the response.

**Evaluation hook.** `EVAL_EXPOSE_TURN` is disabled by default and rejected when
`APP_ENV=production`. When enabled, chat responses expose only masked outbound
messages, replay keys, token totals and USD cost. The hook never exposes a
banking session ID or the placeholder map.

**Encryption at rest** at the application level, with envelope encryption. The master key lives in the environment and never in the database. **Known limitation:** in production it belongs in a KMS or HSM.

**Verifiable audit.** Every decision and every action lands in an append-only log with hash chaining. `make verify-audit` (⚠️ pending) walks the chain and detects any later alteration.

**Least privilege.** Only `banking-core` holds database credentials. The back office acts under the agent's identity, and every takeover is recorded with user and timestamp.

## 3. Untrusted content

The customer's message and the model's output are data, never instructions. The concrete consequences:

- The model **proposes** tool calls; `banking-core` **authorizes** ([ADR-0003](adr/0003-deterministic-vs-ai.md)).
- The session's account holder is pinned server-side and never passed as a parameter from the model.
- The model may only emit message blocks from a schema-validated allowlist.
- Handoff blocks are engine-built only from a successful, receipt-backed
  `handoff.create`. Summary, effective priority, handoff ID and queue position
  come from its `ToolResult`; model text appears only in stored `open_questions`.
- Editable configuration cannot modify policy ([ADR-0002](adr/0002-config-code-boundary.md)).

## 4. Customer authentication

| Step | Mechanism |
|---|---|
| Identification | The customer provides data; the system matches, it does not disclose |
| Verification | OTP for a **previously registered** channel (email or SMS on the customer record), delivered to a simulated in-app inbox instead of a real channel ([ADR-0007](adr/0007-no-llm-biometrics.md)); the model never sees the code or chooses the channel. In the demo whoever sees the browser sees the code, so the OTP does not prove possession of the channel |
| Document verification | Interface defined, simulated provider ([ADR-0007](adr/0007-no-llm-biometrics.md)) |
| Attempt limits | Per session, per customer and per document across sessions, and per IP on conversation creation, with indistinguishable responses for non-existent data (below) |

### Attempt limits

Opening a new session resets the per-session counters, so brute force is limited on what is being guessed, not only on who is guessing:

| Limit | What is counted | Effect | Configuration (seed) |
|---|---|---|---|
| Per session | Total attempts, failed matches, failed OTP verifications and resends of one session | Session `LOCKED`; only `handoff.create` and `kb.search` remain | `RATE_LIMIT_ATTEMPTS_PER_SESSION`, `OTP_MAX_ATTEMPTS`, `OTP_MAX_RESENDS` |
| Per customer | Failed `otp.verify` of the pinned customer, in any session, in a fixed window | Customer locked for a duration: no new code, no code compared, the session goes to a human | `RATE_LIMIT_CUSTOMER_OTP_MAX_FAILURES` (5), `_WINDOW_SECONDS` (3600), `_LOCK_SECONDS` (1800) |
| Per document | Failed `customer.match` on the claimed document (its blind index), in any session, whether or not a customer has it | Past the maximum, `matched=false` without a lookup | `RATE_LIMIT_DOCUMENT_MATCH_MAX_FAILURES` (10), `_WINDOW_SECONDS` (3600) |
| Per IP | `POST /v1/conversations` per client address, one-hour fixed window, at the orchestrator | HTTP 429 with `Retry-After`; no banking session opened | `RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR` (30; 1000 in the development compose), `TRUSTED_PROXY_HOPS` (0) |

The customer and document thresholds are policy configuration in `config.policy_config` (seeded from the environment, [ADR-0002](adr/0002-config-code-boundary.md)); the per-IP settings are read by the orchestrator, which has no database.

- **Nothing personal is stored to count.** Redis keys hold an internal customer UUID, a blind index (HMAC, not reversible without `BLIND_INDEX_SALT`) or an HMAC of the client address keyed from `SESSION_SECRET`; never a document number, a contact or a raw address. Lock events are audited with the same identifiers and the thresholds only.
- **Responses stay indistinguishable.** A document that does not exist is counted, limited and answered exactly like one that does; the only outcome that differs is a correct match, which is the intended one.
- **Behind a reverse proxy**, set `TRUSTED_PROXY_HOPS` to the number of proxies. Left at 0 every customer shares the proxy's address; set too high, the client can choose its own. `X-Forwarded-For` is otherwise ignored.
- **Gaps** (distributed attackers, per-IP limit on messages, `otp.send` volume across sessions, fixed-window boundary, lock as denial of service) are declared in [limitations](limitations.md).

## 5. Retention

| Data | Retention in this submission | In production |
|---|---|---|
| Transcripts | For the duration of the demo | Per bank policy, with scheduled deletion |
| Audit log | Complete | Long retention; it is regulatory evidence |
| Operational metrics | Complete | Indefinite; contains no PII |

## 6. What we deliberately do not do

- LLM-based biometric verification ([ADR-0007](adr/0007-no-llm-biometrics.md)).
- Send personal data in cleartext to an external provider.
- Let the model compose database queries.
- Authorize irreversible actions without identity verification, however convincing the message.
