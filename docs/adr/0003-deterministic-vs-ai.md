# ADR-0003: What AI decides and what deterministic logic decides

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

The challenge asks for an explicit justification of where AI is appropriate and where it is not. Our position: **AI is good at interpreting language and bad at being the authority**. A model that decides whether an action is authorized turns every generation error into a security incident.

## Decision

A rule that runs through the whole system:

> **The model proposes. The deterministic engine disposes.**

The LLM emits intents and tool calls; `banking-core` decides whether the call proceeds, against the state machine and the policy table. The model cannot skip a step because the state simply does not enable the tool.

### Split by component

| Component | Who decides | Why |
|---|---|---|
| Understanding free-text messages | LLM | It is a language problem |
| Intent classification and slot extraction | Specialized encoder | Needs a calibrated score and consistency |
| Identity verification sequence | State machine | A protocol, not a conversation; must be identical every time |
| Authorizing an action | Policy engine | An auditable business rule, not an inference |
| Risk thresholds (amount, attempts, ownership) | Configuration + engine | They change for business reasons, not model reasons |
| Assigning a case to an agent | Queue with deterministic priority | Ticket assignment is not a language problem |
| Writing the customer-facing reply | LLM | It is a language problem |
| Handoff summary | LLM, over already-verified facts | It generates text, not facts: the data comes from the system |
| Confirming the action happened | Re-read from the database | What the model says is not evidence |

### Derived behaviors

- **Abstention:** below the calibrated threshold the system asks for clarification instead of guessing. The threshold is a number tuned on validation, not a prompt instruction.
- **Verification:** every write returns a receipt re-read from the database. The system states it blocked a card only if the card state actually changed.
- **Idempotency:** every write tool accepts an idempotency key; a model retry does not produce two blocks.

## Options considered

### Option A: autonomous agent with instructions in the prompt

**Pros:** far less code, flashier demo, handles unforeseen cases gracefully.
**Cons:** prompt instructions are not controls: they degrade with long context and give way under prompt injection. There is no way to audit why something was authorized.

### Option B (chosen): the model proposes, the engine authorizes

**Pros:** the unsafe-action surface is bounded by construction rather than by model good behavior; auditable; the same control applies to any workflow.
**Cons:** more code; legitimate but unforeseen cases escalate to a human instead of resolving.

### Option C: fully deterministic, AI only as a writer

**Pros:** maximum predictability.
**Cons:** returns to the rigid decision tree the challenge asks us to move past; tolerates neither free text nor ambiguity.

## Trade-off analysis

Option B loses some coverage against A: cases an autonomous agent would resolve get escalated. We accept that cost knowingly, because the inverse cost — an action executed without authorization — is not symmetric. And we measure it: unnecessary escalation rate is one of the reported metrics, not a side effect we hide.

## Consequences

**Becomes easier:** explaining any system decision; adding workflows without reopening the security discussion; testing the controls without depending on the model.

**Becomes harder:** every new tool needs its policy entry; states and permissions must stay in sync.

**To revisit:** if unnecessary escalation turns out high, we loosen it through configurable policy — never by giving the model authority.

## Action items

1. [ ] Verification state machine with a state × tool matrix
2. [ ] Policy engine evaluating rules from the database
3. [ ] Verified receipt on every write
4. [ ] Idempotency keys
5. [ ] Unnecessary-escalation metric in the suite

---

## Appendix A — Tool catalog and state × tool matrix (Approved 2026-09-26)

This appendix defines the formal tool catalog and the authorization matrix mapping customer verification states to permitted banking tools. In accordance with the core principle that **the model proposes and deterministic logic disposes**, tool execution is authorized solely by the state machine and policy engine within `banking-core`.

### Non-Configurable Code Floor

While ADR-0002 allows operators to edit which tools each state enables through configuration in the database edited from the back office (where .env is only the initial seed), the application code enforces a strict **code floor** that no configuration can lower or bypass:
- **Sensitive customer data reads** (`card.list`, `transaction.list_recent`, `account.get_summary`) and card mutation (`card.block`) are permitted **only in `VERIFIED`** state.
- In **`LOCKED`** and **`HANDED_OFF`** states, **only `handoff.create` and `kb.search`** are permitted.
- Configuration can only **restrict** the seed matrix (e.g. disable a tool entirely), **never widen** it beyond the code floor.
- This architectural floor is why `POLICY_SEED_REQUIRE_OTP_FOR_WRITES` is removed: a false configuration value would allow `card.block` without OTP authentication, violating safe outcome invariants (unsafe outcome U1).

### Verification States

| State | Description |
|---|---|
| `ANONYMOUS` | Initial state. The customer session is unauthenticated and unverified. |
| `IDENTIFIED` | Claimed customer identification attributes (e.g. document type and number) have been matched against bank records. Identity is not yet authenticated. |
| `OTP_PENDING` | A one-time passcode has been dispatched to the customer's registered channel (never specified by the model). Awaiting verification. |
| `VERIFIED` | Full identity verification established (e.g. successful OTP verification). Access to sensitive customer data and card management actions is enabled. |
| `LOCKED` | Security threshold exceeded (e.g. maximum failed OTP or match attempts). Sensitive operations are blocked. Escalation to human agent or knowledge search remains available. |
| `HANDED_OFF` | Control of the session has transitioned to a human agent queue. Autonomous banking actions are disabled. |

### Tool Catalog

| Tool | Type | Permitted States | Description & Constraints |
|---|---|---|---|
| `customer.match` | Read / Match | `ANONYMOUS`, `IDENTIFIED` | Matches claimed holder data against records. Returns only a boolean match status (`matched: true/false`). Responses are strictly indistinguishable for non-existent records to prevent customer enumeration (ADR-0004). Calling in `IDENTIFIED` matching a different holder replaces the pinned holder, discards any issued OTP challenge, and counts as an attempt. |
| `otp.send` | state-changing: requires idempotency key, returns a receipt | `IDENTIFIED`, `OTP_PENDING` | Dispatches an OTP challenge. Delivery channel (email, Telegram, WhatsApp, SMS; delivery simulated pending feasibility decision) and destination are resolved strictly server-side from registered customer profile and deployment configuration; the model never chooses or provides the channel or destination. Transitions state to `OTP_PENDING`. Allowed in `OTP_PENDING` to permit code resend within rate limits. |
| `otp.verify` | state-changing: requires idempotency key, returns a receipt | `OTP_PENDING` | Verifies the customer-supplied OTP code against the active challenge. Valid code transitions session to `VERIFIED`. Exceeding maximum allowed attempts transitions session to `LOCKED`. |
| `identity.verify_document` | Verification | `IDENTIFIED` | Interacts with a simulated document verification provider (ADR-0007). Returns score, decision, and reasons. Never sufficient alone to grant `VERIFIED` status without registered channel authentication. |
| `card.list` | Read | `VERIFIED` | Lists payment cards belonging to the pinned session customer. PANs are always masked (e.g. `**** **** **** 1234`). Returns opaque card references (`card_ref`) used for subsequent operations. |
| `transaction.list_recent` | Read | `VERIFIED` | Retrieves recent transaction history for the pinned customer or a specific card referenced by `card_ref`. Contains amounts, timestamps, merchants, and dispute eligibility indicators. |
| `account.get_summary` | Read | `VERIFIED` | Returns balance and status summaries for accounts belonging to the pinned customer. Read-only; enables the secondary workflow (inquiries) via configuration alone without code changes (ADR-0002). |
| `card.block` | state-changing: requires idempotency key, returns a receipt | `VERIFIED` | Blocks a payment card identified by its opaque `card_ref`. Requires an idempotency key and policy engine authorization. Permitted strictly in `VERIFIED` only (owner confirmed). Returns a verified `Receipt` re-read from the database. |
| `handoff.create` | state-changing: requires idempotency key, returns a receipt | All states (`ANONYMOUS`, `IDENTIFIED`, `OTP_PENDING`, `VERIFIED`, `LOCKED`, `HANDED_OFF`) | Escalates the session to a human representative in the back-office queue with reason, priority, and department routing. Available in every state, including `LOCKED`. |
| `kb.search` | Read / Public | All states (`ANONYMOUS`, `IDENTIFIED`, `OTP_PENDING`, `VERIFIED`, `LOCKED`, `HANDED_OFF`) | Vector search over the public knowledge base; BM25 or hybrid only when configured (ADR-0006). Never handles or returns customer PII. Available in all states. |

### State × Tool Authorization Matrix

| Tool | `ANONYMOUS` | `IDENTIFIED` | `OTP_PENDING` | `VERIFIED` | `LOCKED` | `HANDED_OFF` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `customer.match` | Allowed | Allowed | Refused | Refused | Refused | Refused |
| `otp.send` | Refused | Allowed | Allowed | Refused | Refused | Refused |
| `otp.verify` | Refused | Refused | Allowed | Refused | Refused | Refused |
| `identity.verify_document` | Refused | Allowed | Refused | Refused | Refused | Refused |
| `card.list` | Refused | Refused | Refused | Allowed | Refused | Refused |
| `transaction.list_recent` | Refused | Refused | Refused | Allowed | Refused | Refused |
| `account.get_summary` | Refused | Refused | Refused | Allowed | Refused | Refused |
| `card.block` | Refused | Refused | Refused | Allowed | Refused | Refused |
| `handoff.create` | Allowed | Allowed | Allowed | Allowed | Allowed | Allowed |
| `kb.search` | Allowed | Allowed | Allowed | Allowed | Allowed | Allowed |

*Note: In `OTP_PENDING`, `otp.send` is allowed to support legitimate "resend code" requests within rate limits.*

### State Transitions

```
[ ANONYMOUS ] ─── repeated failed match ───► [ LOCKED ]
      │
      │  customer.match (success)
      ▼
[ IDENTIFIED ] ─── otp.send ───► [ OTP_PENDING ]
      │                                │    │
      │ (enumeration / rate limit)     │    │ otp.verify (valid code)
      │                                │    ▼
      ▼                                │ [ VERIFIED ]
[  LOCKED   ] ◄── max attempts exceeded ┘
      │
      │ (any state) ─── handoff.create ───► [ HANDED_OFF ]
```

1. **`ANONYMOUS` → `IDENTIFIED`**: Customer provides claimed identification data; `customer.match` returns `matched: true`. Holder identity is pinned in server session.
2. **`ANONYMOUS` → `LOCKED`**: Repeated failed `customer.match` attempts trigger session lock to mitigate customer enumeration attacks starting anonymously.
3. **`IDENTIFIED` (re-match)**: `customer.match` called in `IDENTIFIED` matching a different holder replaces the pinned holder, discards any previously issued OTP challenge, and counts as one verification attempt.
4. **`IDENTIFIED` → `OTP_PENDING`**: `otp.send` generates an OTP and dispatches it. The delivery channel (email, Telegram, WhatsApp, SMS; delivery simulated pending feasibility decision) is resolved server-side from registered customer data and deployment configuration—the model never selects or provides the channel or destination.
5. **`OTP_PENDING` → `VERIFIED`**: `otp.verify` confirms the customer submitted the correct OTP within expiry.
6. **`OTP_PENDING` → `LOCKED`**: Repeated failed OTP verification attempts exceed the configured threshold.
7. **`IDENTIFIED` → `LOCKED`**: Repeated failed match attempts or rate limit violations trigger lock to prevent enumeration.
8. **Any state → `HANDED_OFF`**: `handoff.create` is invoked (either requested by customer, recommended by policy, or automatically following `LOCKED` state).


