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
