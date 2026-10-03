# ADR-0016: banking-core states the next step

**Status:** Accepted · **Date:** 2026-10-02 · **Deciders:** TODO (team)

## Context

A live conversation stalled after identification. The model called `customer.match`, then `card.list` twice; banking-core refused both with `STATE_NOT_ALLOWED`, and `otp.send` was never called. The LLM bench ([reports/llm-bench-2026-10-02.md](../../reports/llm-bench-2026-10-02.md)) found the same stall in most conversations and for every model but one: of the episodes that should end in a block, the submission model completed 4 of 9 and the local models at most 1.

The causes are in the harness, not the model:

- **Nothing the model sees names the step it is missing.** A refusal carries a reason code only. The tool descriptions say "for verified customer", and the prompt says nothing about the order, rightly: [ADR-0002](0002-config-code-boundary.md) keeps policy out of it.
- **Hiding tools is worse.** Offering only the tools the state allows (the bench's routing ablation) dropped the two strongest models to 0 completed flows: with `card.block` out of sight they conclude blocking is impossible here and hand off.

## Decision

**Every `ToolResult` banking-core returns carries a `flow` hint: the session's state after the call and the tools the effective configuration allows from there.**

```json
"flow": {
  "state": "IDENTIFIED",
  "next": ["otp.send"],
  "allowed": ["customer.match", "otp.send", "identity.verify_document", "handoff.create", "kb.search"],
  "required_states": ["VERIFIED"]
}
```

- **`allowed`** is every tool whose effective permitted states (the code floor narrowed by the stored tool matrix, `get_effective_permitted_states`) include the state. It is what the authorizer would let through on state alone; rate limits and amount policy still apply at call time.
- **`next`** is the FSM's forward edge from the state: `customer.match` from `ANONYMOUS`, `otp.send` from `IDENTIFIED`, `otp.verify` from `OTP_PENDING`, `handoff.create` from `LOCKED`. It names only allowed tools and never the tool this result just refused (a refused `otp.send` does not invite a retry). When nothing is left and the state is not `VERIFIED` or `HANDED_OFF`, it is `handoff.create`.
- **`required_states`** appears only on a `STATE_NOT_ALLOWED` refusal: the states in which the refused tool would run.
- **One function computes it** (`banking_core/control/flow.py`), from the same configuration repository the authorizer reads. The dispatcher attaches it to every result it returns, refusals and replays included. If the configuration cannot be read, the result goes out without a hint: the hint never fails a call.
- **It is advisory.** banking-core authorizes every call as before; nothing in the orchestrator reads `flow` to decide anything. The engine only renames the tools to the names the model was offered (`otp_send`) before the result reaches it.

## Options considered

| Option | Why not |
|---|---|
| Describe the flow in the system prompt | A copy of the FSM in the prompt drifts from the stored configuration, and reads as policy in the prompt ([ADR-0002](0002-config-code-boundary.md)) |
| Offer only the tools the state allows | Measured: it hides the goal; the strongest models stop trying (above) |
| Compute the next step in the orchestrator | The untrusted zone would hold its own copy of the FSM and the tool matrix, and drift from banking-core's |
| A hint on refusals only | The stall starts after a *successful* match: the model goes for `card.list` before any refusal |

## Consequences

- The `ToolResult` contract gains an optional `flow` field (`contracts.envelope.FlowHint`); the exported JSON Schema changes with it. Old results without it stay valid.
- Each result costs one more read of the tool matrix. The configuration repository already serves it per call to the authorizer.
- The model learns the state names and the tool matrix of the current state. Neither is customer data, and both were inferable from refusals.
- The hint changes what the model sees, so it changes the replay key of recorded conversations (none are recorded yet).

## Amendment 2026-10-02: the hint at session creation

**Context.** The hint arrived only inside a tool result, so the first completion of a conversation saw none: no `next`, and every catalog tool, disabled ones included (a gap declared in [limitations.md](../limitations.md)). On a first message such as "he detectado una compra que no hice con mi tarjeta" the model had nothing pointing at `customer.match` and escalated instead ([ADR-0003](0003-deterministic-vs-ai.md), amendment 2026-10-02).

**Decision.** `POST /v1/sessions` returns the same `flow` hint for the new `ANONYMOUS` session, computed by the same function. The orchestrator keeps it with the conversation and, until the first tool result is in the history, gives the model one system line naming the state and `next` (in the tool names it offers), and offers only the tools `flow.enabled` lists. From the first tool result on, the hint travels in the results as before. A banking-core that returns no hint leaves the first completion as it was.

**Consequences.** The opening line changes what the model sees on the first completion, so it is part of the prompt version and the replay key. It states only what banking-core said; the orchestrator computes nothing from it.
