# ADR-0019: detective mode, each turn's masked timeline in the customer chat

**Status:** Accepted · **Date:** 2026-10-04 · **Deciders:** TODO (team)

## Context

Judges and the team want to see what happens under the hood of a conversation: what the encoder predicted and how fast, what was masked, what each LLM call was sent and answered, what banking-core allowed or refused, and what was kept of the reply. Today that lives in logs, in the eval hook (`EVAL_EXPOSE_TURN`, eval runs only, refused in production) and in the audit log. None of it is visible from the chat, where the demo happens.

## Options

- **(a) Read the logs.** Nothing to build, nothing anyone outside the team can follow.
- **(b) Widen the eval hook.** It is refused under `APP_ENV=production` on purpose, and its shape is pinned by the eval runner and llmbench.
- **(c) A separate, typed trace per turn, returned with the turn where an environment offers it, shown by a switch in the chat (chosen).**

## Decision

**Each customer turn can return a `TurnTrace`** (`packages/contracts/src/contracts/trace.py`, mirrored in `ts/trace.ts`, drift-tested): one timed event per step, encoder, masking, each LLM call, each tool call (and the handoff the engine creates itself), the reply's blocks and the decision records, each with the detail named after its kind.

- **Masked values only.** The engine's recorder reads the values it already computed for the provider: the masked text, the masked messages, the masked tool arguments, the feedback string the model receives. It never sees the placeholder map's values, the rehydrated tool arguments or a raw tool result. Slot values are left out (types only). A test sweeps a traced turn for the raw document number.
- **Passive.** What the provider and banking-core receive, and the LLM recording keys, are identical with the trace on or off (tested). A defect in the recorder drops an event, never the turn.
- **Availability is per environment** (`DETECTIVE_MODE`, off in code): on in the local compose, off in the production overlay unless set, and the Terraform variable `detective_mode` on Cloud Run (`presentation.tfvars` sets it). Unlike the eval hook it is allowed under `APP_ENV=production`.
- **Runtime switch in the back office.** The Guardrails screen turns it off and on for every conversation at once, through the agent API (`GET/PUT /v1/agent/detective`); the state is one key on redis-edge. It cannot go beyond what `DETECTIVE_MODE` offers (409).
- **The chat asks** `GET /v1/capabilities` when it opens and after every turn, and only then shows a switch in its header. The viewer's choice is remembered in the browser, off by default. Turning it on reveals the earlier turns too.

## Consequences

- **On a public URL, anyone using the chat sees the system prompt, the tools offered, the policy outcomes and the masked conversation.** The data is synthetic and masked, but the prompt and the policy behaviour are an easier target to probe. That is the price of showing judges the inside; the back office can turn it off at once.
- Responses are larger (the first LLM call of a turn lists its messages in full, later calls only the new ones).
- Not covered: a turn that fails (LLM error, replay miss) returns no trace; traces are not stored, so a reload shows none; the back office does not show them; retrieval internals (keyword vs embedding scores) and policy internals stay inside banking-core ([limitations](../limitations.md)).
