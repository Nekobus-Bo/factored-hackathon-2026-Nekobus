# ADR-0003: What AI decides and what deterministic logic decides

**Status:** Accepted · **Date:** 2026-09-26 · **Amended:** 2026-09-29 (the risk amount comes from the database, see the last section) · **Deciders:** TODO (team)

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
| The amount compared against the risk threshold | The database row of the disputed transaction | It is a fact the bank holds, not something the customer or the model states (amendment 2026-09-29) |
| Creating a handoff the policy requires | The turn engine, deterministically | A required escalation cannot depend on the model remembering to ask for it (amendment 2026-09-29) |
| Assigning a case to an agent | Queue with deterministic priority | Ticket assignment is not a language problem |
| Writing the customer-facing reply | LLM | It is a language problem |
| Handoff summary | LLM, over already-verified facts | It generates text, not facts: the data comes from the system |
| Confirming the action happened | Re-read from the database | What the model says is not evidence |
| Choosing an enum argument or releasing a write on the customer's confirmation | Calibrated decision model, applied by the engine through a closed set of restrict-only effects | Evidence-backed and recorded; banking-core still authorizes (amendment 2026-09-29 (2), [ADR-0012](0012-decision-points.md)) |

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
| `otp.send` | state-changing: requires idempotency key, returns a receipt | `IDENTIFIED`, `OTP_PENDING` | Dispatches an OTP challenge. Delivery channel (the customer's registered email or SMS; delivery is simulated through an in-app inbox, [ADR-0007](0007-no-llm-biometrics.md)) and destination are resolved strictly server-side from registered customer profile and deployment configuration; the model never chooses or provides the channel or destination. Transitions state to `OTP_PENDING`. Allowed in `OTP_PENDING` to permit code resend within rate limits. |
| `otp.verify` | state-changing: requires idempotency key, returns a receipt | `OTP_PENDING` | Verifies the customer-supplied OTP code against the active challenge. Valid code transitions session to `VERIFIED`. Exceeding maximum allowed attempts transitions session to `LOCKED`. |
| `identity.verify_document` | Verification | `IDENTIFIED` | Interacts with a simulated document verification provider (ADR-0007). Returns score, decision, and reasons. Never sufficient alone to grant `VERIFIED` status without registered channel authentication. |
| `card.list` | Read | `VERIFIED` | Lists payment cards belonging to the pinned session customer. PANs are always masked (e.g. `**** **** **** 1234`). Returns opaque card references (`card_ref`) used for subsequent operations. |
| `transaction.list_recent` | Read | `VERIFIED` | Retrieves recent transaction history for the pinned customer or a specific card referenced by `card_ref`. Contains amounts, timestamps, merchants, and dispute eligibility indicators. |
| `account.get_summary` | Read | `VERIFIED` | Returns balance and status summaries for accounts belonging to the pinned customer. Read-only; enables the secondary workflow (inquiries) via configuration alone without code changes (ADR-0002). |
| `card.block` | state-changing: requires idempotency key, returns a receipt | `VERIFIED` | Blocks a payment card identified by its opaque `card_ref`. Requires an idempotency key and policy engine authorization. Permitted strictly in `VERIFIED` only (owner confirmed). Takes an optional opaque `transaction_id` (from `transaction.list_recent`): the charge the customer disputes, which must belong to the pinned holder and to that card. The risk threshold reads that charge's amount and currency from the database, never from the customer's words or the model's arguments. Returns a verified `Receipt` re-read from the database and the `handoff_requirement` (`NONE`, `RECOMMENDED` or `REQUIRED`, with priority, department and reason) the policy decided. |
| `handoff.create` | state-changing: requires idempotency key, returns a receipt | All states (`ANONYMOUS`, `IDENTIFIED`, `OTP_PENDING`, `VERIFIED`, `LOCKED`, `HANDED_OFF`) | Escalates the session to a human representative in the back-office queue with reason, priority, and department routing. Available in every state, including `LOCKED`. Takes the same optional `transaction_id` with the same ownership check, honored only in a `VERIFIED` session (dropped otherwise); the charge's amount, currency, merchant, date and masked card go into the server-built `verified_facts` from the database. A session that remembers a `handoff_requirement` gets at least that priority and always that department: banking-core raises, the model cannot lower. |
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
4. **`IDENTIFIED` → `OTP_PENDING`**: `otp.send` generates an OTP and dispatches it. The delivery channel (the customer's registered email or SMS; delivery is simulated through an in-app inbox, [ADR-0007](0007-no-llm-biometrics.md)) is resolved server-side from registered customer data and deployment configuration—the model never selects or provides the channel or destination.
5. **`OTP_PENDING` → `VERIFIED`**: `otp.verify` confirms the customer submitted the correct OTP within expiry.
6. **`OTP_PENDING` → `LOCKED`**: Repeated failed OTP verification attempts exceed the configured threshold.
7. **`IDENTIFIED` → `LOCKED`**: Repeated failed match attempts or rate limit violations trigger lock to prevent enumeration.
8. **Any state → `HANDED_OFF`**: `handoff.create` is invoked (either requested by customer, recommended by policy, or automatically following `LOCKED` state).

---

## Amendment 2026-09-29 — The risk amount comes from the database

This amendment adds to the decisions above; it does not replace them. It closes a gap found while reviewing the amount guardrail against the code.

### Context

The amount guardrail never fired. `card.block` took only a `card_ref` and a `reason`, so no amount ever reached the policy engine, which looked for amount keys in the tool arguments or the call context. The policy also produced advisory flags (`POLICY_FLAGGED`, `HANDOFF_RECOMMENDED`, `HANDOFF_REQUIRED`, `PRIORITY`) that were written to the audit log only: `ToolResult` carries no flags, so the orchestrator never saw them and nothing acted on them.

### Options considered

**Option 1: let the model pass the amount.** The number that drives a control would come from the component this ADR says must never be the authority. It is also derived from customer text, which the customer controls: an inflated or understated figure changes the outcome.

**Option 2: take the amount from the customer's message** (for instance the encoder's amount slot). Same flaw: the customer's words are not evidence of what the bank charged.

**Option 3 (chosen): read the amount from the disputed transaction in the database.** The bank already holds the fact; the model only points at it.

### Decision

1. `card.block` and `handoff.create` accept an optional opaque `transaction_id`: the id `transaction.list_recent` returned for the charge the customer disputes. It follows the same constraints as `TransactionItem.transaction_id`.
2. banking-core loads that transaction. It must belong to the pinned holder, and for `card.block` also to the card being blocked. Otherwise the call is `REFUSED` with `INVALID_ARGUMENTS`, and the response is identical whether the transaction does not exist or belongs to someone else (ADR-0004, IDOR). The lookup runs after the state check, so a call the FSM refuses is answered as it always was and never resolves a transaction. `handoff.create` works in every state, so it attaches the charge only in a `VERIFIED` session: in any other state the id is dropped (no lookup, no facts), which keeps the tool from being a way to read a charge before OTP and never holds up an escalation.
3. The amount and currency of that row are the only amount input of the policy. The customer's stated amount and any number the model produces never feed it: the tools have no amount argument, and the policy ignores amount keys in arguments.
4. The policy outcome is returned to the caller and enforced, not just audited:
   - `CardBlockOutput.handoff_requirement` carries the level (`NONE`, `RECOMMENDED`, `REQUIRED`) and, unless `NONE`, a priority, department and reason. It is also returned when an idempotent replay answers the call.
   - banking-core remembers the requirement in the session. A later `handoff.create` in that session gets at least that priority and that department: banking-core may raise a priority, never lower it, and the model's lower request is overridden.
   - For `REQUIRED`, the orchestrator's turn engine creates the handoff itself, in the same turn, when the model has not: same reason, department and priority, the same `transaction_id`, and a fixed summary string built by the engine, with no model text. Its result enters the history and produces the normal handoff block, so the model's final reply can tell the customer. The engine uses the same idempotency-key scheme as any other write, so a retried turn cannot create a second handoff.
   - `RECOMMENDED` stays advisory: the model sees it in the tool result and may offer the customer a human.

### Outcome table

The threshold is the one configured for the transaction's currency (ADR-0002); the mode is the stored `amount_mode`. The card block itself is never refused because of an amount.

| Situation | Level | Priority | Notes |
|---|---|---|---|
| Transaction amount at or below its currency threshold | `NONE` | none | Automated resolution: the card is blocked, no handoff |
| Above the threshold, mode `flag` | `RECOMMENDED` | `NORMAL` | The handoff is advisory |
| Above the threshold, mode `block` | `REQUIRED` | `URGENT` | The engine creates it if the model did not |
| Transaction currency without a threshold, or a malformed amount | `REQUIRED` | `URGENT` | Unknown amount: fail safe |
| Reason `UNRECOGNIZED_CHARGE` or `SUSPICIOUS_ACTIVITY` and no `transaction_id` | `REQUIRED` | `URGENT` | Unknown amount: fail safe |
| Reason `LOST`, `STOLEN` or `CUSTOMER_REQUEST` and no `transaction_id` | `NONE` | none | There is no charge to compare |

With a `transaction_id` the amount rule applies whatever the block reason is (unsafe outcome U8). `URGENT` for `REQUIRED` is what `handoff.create` already maps the `PRIORITY` flag to; `NORMAL` is the contract default priority.

Reason and department follow the block reason:

| Block reason | Handoff reason | Department |
|---|---|---|
| `UNRECOGNIZED_CHARGE` | `UNRECOGNIZED_TRANSACTION` | `DISPUTES` |
| `SUSPICIOUS_ACTIVITY`, `LOST`, `STOLEN` | `SUSPECTED_FRAUD` | `FRAUD_OPERATIONS` |
| `CUSTOMER_REQUEST` | `DISPUTE_CLAIM` | `DISPUTES` |

### Naming of the two amount modes

The stored values stay `flag` and `block` (database, admin API, environment seeds, evaluation scenarios). Documentation calls them by what they do:

| Stored value | Documented as | Effect above the threshold |
|---|---|---|
| `flag` | handoff recommended | `RECOMMENDED` |
| `block` | handoff required | `REQUIRED` |

`block` never blocked anything: `card.block` is not refused for amount, the mode decides whether a handoff is required. Renaming the stored values to `recommend` and `require` is pending (AGENTS.md).

### Consequences

**Becomes easier:** the guardrail can be demonstrated live (lower the threshold, repeat the operation, the outcome flips) and evaluated without depending on what the customer types.

**Becomes harder:** the model must link the disputed charge (list the transactions, pass the id). A model that omits the link for `UNRECOGNIZED_CHARGE` or `SUSPICIOUS_ACTIVITY` fails safe into a required handoff. One that picks `LOST`, `STOLEN` or `CUSTOMER_REQUEST` and omits the link gets no amount check; that gap is declared in `docs/limitations.md`.

**To revisit:** if the residual gap matters, banking-core can evaluate the card's recent disputable charges itself instead of relying on the model's link.

## Amendment 2026-09-29 (2): decision points may choose an argument or hold a write

**Context.** The rule above kept every choice between "the model proposes" and "banking-core disposes" out of the encoder's hands: it was advisory. [ADR-0012](0012-decision-points.md) lets a calibrated local decision (a *decision point*) do two narrow things the LLM did unaided: pick the enum argument of a call the LLM proposed (the block reason, a handoff's department), and hold a write until the customer has consented (the gate on `card.block`).

**Decision.** This adds a row to the split above and changes none of the others. The engine applies a decision point only through a closed set of effects that can record, choose among values banking-core already accepts, or withhold a write. None can authorize, create a call, or make one succeed that the state machine and the policy engine refuse; and when a decision point abstains or is unavailable the outcome is the LLM's own argument or a withheld write, never an action. The gate is a control in the untrusted zone and not an authorization: banking-core still requires `VERIFIED`, ownership and an idempotency key for every block. "The engine never alters model arguments" becomes "except the `select` allowlist of the effects file, which cannot touch `priority`, `card_ref`, an identity or a secret".

**Consequences.** Every decision point ships in `shadow` (computed and recorded, nothing changes) and flips to `enforce` only by its own reviewed diff. A fail-closed gate adds a turn when the model abstains on a colloquial "yes": the same trade this ADR already accepts for unnecessary escalation, measured instead of assumed. What is not built and why is in [limitations.md](../limitations.md).
