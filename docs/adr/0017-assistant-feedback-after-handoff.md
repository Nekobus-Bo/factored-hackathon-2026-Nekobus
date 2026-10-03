# ADR-0017: the customer rates the assistant after a handoff

**Status:** Accepted · **Date:** 2026-10-02 · **Deciders:** TODO (team)

## Context

The declutter review of the customer chat (2026-10-02) asked for a small, optional question at the end of a conversation: did the assistant help, yes or no. A conversation ends in one of two ways. Either the case goes to a person, or the customer needs nothing else.

Only the first has a signal the client can trust. A handoff reaches the browser as an engine-built `handoff` block, which only a successful `handoff.create` produces. "Nothing else" exists only in the model's text, and the model's text cannot make the interface do anything ([ADR-0003](0003-deterministic-vs-ai.md); the design system's ChatMessage rules: "Never show a receipt, a handoff or a 'verified' line because the model said so").

The answer has to be stored, and the orchestrator has no database ([ADR-0004](0004-trust-boundary.md)).

## Decision

**After a handoff block, the chat shows one line: "¿Te ayudó el asistente?" with two equal buttons. The answer goes to banking-core, which stores one answer per handoff.**

- **Route.** Browser `POST /api/conversations/{id}/feedback` with `{"helpful": true|false}` → web-client BFF → orchestrator `POST /v1/conversations/{id}/feedback` → banking-core `POST /v1/sessions/{session_id}/feedback`. The orchestrator takes the banking session id from its stored conversation, never from the client, as it does for the simulated inbox.
- **banking-core decides.** It accepts the answer only when the session has a handoff (`ops.handoff.session_ref`), and ties it to the newest one. With no handoff it answers 409 `no_handoff`. The client shows the line only after a handoff block, but the rule is enforced where the data is.
- **One answer per handoff, idempotent by meaning.** A new table, `ops.assistant_feedback` (`handoff_id` unique, `helpful`, `created_at`). The same answer again returns the stored row with no second write, so a retried request is safe. A different answer gets 409 `already_answered`: the first answer stands. This is the back-office claim's pattern ([ADR-0013](0013-front-ends-bff-takeover.md)), not an idempotency key, because the handoff itself is the natural key.
- **Audited, re-read.** The insert and an audit row (`feedback.recorded`, actor `customer_session`, payload `handoff_ref` and `helpful`) commit together, with the audit chain lock taken before the handoff row, in the same order as the claim. The response is the row re-read after the commit: `handoff_ref`, `helpful`, `recorded_at`. The orchestrator passes on `helpful` and `recorded_at` only.
- **Nothing reaches the model.** The answer is not part of the transcript or the LLM history.

## Options considered

| Option | Why not |
|---|---|
| Also ask when the model says the conversation is over | Needs a signal the engine confirms (a new block or FSM state the model proposes and banking-core accepts), with eval scenarios for when it must not fire and a prompt change. Left for later: see Consequences |
| Store the answer in the orchestrator's Redis | Lost when the conversation expires, and outside the audited store |
| Write it into `ops.handoff.summary` | The summary is the handoff's evidence for the agent; a customer rating there mixes the two, and the column is not meant to change after creation |
| An idempotency key from the client | The handoff is already a natural key; a second key adds a table lookup and nothing the uniqueness constraint does not give |

## Consequences

- One table and one migration (`0009_assistant_feedback`), one route on each of banking-core, the orchestrator and the web-client BFF, and a fifth route in the client's closed route list ([docs/front-ends.md](../front-ends.md)).
- The question only appears after a handoff. A conversation the assistant solves end to end never asks. Covering it needs the engine-confirmed end signal above, and is listed in [limitations](../limitations.md).
- The back office does not report the answers yet. The counts are in `ops.assistant_feedback` and in the audit log, and listed in limitations.
- Eval scenarios cannot express a button press (their `turns` are customer messages only), so the feedback path is covered by API tests in banking-core, the orchestrator and the web client, not by `make eval`.
