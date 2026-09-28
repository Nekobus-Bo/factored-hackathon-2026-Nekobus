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
| Verification | OTP to a **previously registered** channel (channel is an open decision: email, Telegram, WhatsApp or SMS; currently simulated in a panel; the model never chooses the channel) |
| Document verification | Interface defined, simulated provider ([ADR-0007](adr/0007-no-llm-biometrics.md)) |
| Attempt limits | Per session and IP, with indistinguishable responses for non-existent data |

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
