# ADR-0013: Front ends, their BFFs and the human takeover

**Status:** Accepted · **Date:** 2026-09-29 · **Deciders:** TODO (team)

## Context

Two front ends start now: a simulated fintech with the customer chat (`web-client`) and the agent back office (`web-backoffice`). [ADR-0004](0004-trust-boundary.md) says the orchestrator "exposes the chat and the back office", which was written before either existed. Three facts make that sentence hard to keep:

- The back office's data is not in the orchestrator. The queue (`ops.handoff`), the guardrails (`config.*`) and the metrics (`ops.audit_log`) live in `banking-core`, and the orchestrator holds no database credentials ([AGENTS.md](../../AGENTS.md) rule 1). Serving them through the orchestrator means new pass-through tools, that is, a way for the untrusted zone to read and write the trusted zone's administration.
- A browser is untrusted. Whatever credentials reach it are public, and calling two services from it needs CORS and tokens in JavaScript.
- A human takeover needs two things done in two places: the claim of the case (banking-core, audited) and the conversation switching to the agent (orchestrator, where the session lives). "Every takeover is recorded" ([ADR-0004](0004-trust-boundary.md), threat table) has to be true for the first, not only the second.

## Decision

**Each front end is a Bun fullstack app with a same-origin BFF.** The server that ships the bundle also exposes a closed list of `/api/*` routes; the browser talks only to it. Stack, tokens and workspace: [ADR-0009](0009-monorepo-structure.md), amendment of 2026-09-29.

- **Closed list, typed both ways.** A BFF forwards only the routes named for it, validating the request and the response with Zod. It never forwards an arbitrary path or body: a generic pass-through would void [ADR-0004](0004-trust-boundary.md).
- **`web-client` BFF** forwards the four chat routes of the orchestrator and holds no tokens. It sets `X-Forwarded-For` to the client address, and compose sets `TRUSTED_PROXY_HOPS=1` on the orchestrator so the per-IP limit keeps seeing the customer.
- **`web-backoffice` BFF** authenticates one demo agent (`DEMO_AGENT_EMAIL` / `DEMO_AGENT_PASSWORD`, constant-time compare) and issues an HttpOnly, `SameSite=Strict` cookie signed with HMAC-SHA256 (`BACKOFFICE_SESSION_SECRET`), 8 h. It holds `ADMIN_API_TOKEN` and `AGENT_API_TOKEN` server-side; neither reaches the browser. Under `APP_ENV=production` it refuses to start with the default password or secret. Mutating routes need the session and `Content-Type: application/json`.
- **Split data path for the back office.** Queue, handoff detail, claim, guardrails and metrics come from the **banking-core admin API** (`/v1/admin`, same bearer auth as today). The conversation (masked transcript, takeover, agent reply) comes from a new **orchestrator agent API** (`/v1/agent`, own bearer token, mounted only when enabled). The back-office server runs on the internal network; in the presentation environment it is either not published or published only behind its login.
- **Takeover in two idempotent steps, in this order.** The BFF claims the handoff in banking-core first: the write changes the status to `ASSIGNED` and is audited with `actor_type='agent'` and the agent's email as `actor_ref`, in one transaction. Only then does it take over the conversation in the orchestrator. From then on the LLM never sees that conversation again: customer messages are stored masked and reach the agent, agent messages are masked with the same masker before storage (failing closed to `[REDACTED]`). If the second step fails after the first, the BFF answers 502 and the same call can be repeated. **There is no hand-back to the assistant.**
- **Live updates by polling**, no WebSocket: 3 s for the queue, 2 s for an open conversation and for the customer chat while a takeover is active. Polling stops when the tab is hidden. The OTP inbox needs no polling: the code is delivered during the turn that calls `otp.send`, so the customer app reads the inbox once after each turn.
- **Shared contracts.** `packages/contracts` gains a TypeScript entry (`@pattern-blue/contracts`, Zod) with the message block schemas and the HTTP shapes, checked by a drift test against the JSON Schemas Python exports.

## Options considered

### Option A: everything through the orchestrator

The browser (or a thin static server) talks only to the orchestrator, which relays queue, claim and configuration to `banking-core`.

**Pros:** one API for the front end; no BFF; the ADR-0004 sentence stays as written.
**Cons:** the orchestrator would need tools to list, claim and reconfigure, so the untrusted zone gains a route to the trusted zone's administration, the pass-through ADR-0004 forbids. Agent identity would have to be trusted from a service that is exposed to the internet. The audit of a takeover would depend on a relay.

### Option B (chosen): a BFF per front end; admin API for queue and configuration, agent API for the conversation

**Pros:** each write lands in the service that owns the data, with its own bearer token and audit; the untrusted zone gains no new access to `banking-core`; secrets stay on a server; no CORS; a closed route list is reviewable.
**Cons:** two new servers (in the compose stack), a new API on the orchestrator, and a takeover that spans two services.

### Option C: the browser calls the APIs directly, with CORS

**Pros:** no BFF code; fewest moving parts.
**Cons:** the admin and agent tokens would live in the browser, so the back office would be public to anyone who opens the page; the admin API would have to be published and open to browser origins; there would be nowhere to hold a session or validate a payload before it crosses the boundary. Rejected.

## Trade-off analysis

The cost is two more processes and a takeover that cannot be one transaction. Ordering the steps (the audited claim first) and making both idempotent turns the failure into "claimed, conversation not yet taken over", which shows in the queue and is repaired by repeating the call, and never into a takeover without a record. The benefit is that the trust boundary keeps its shape: the browser reaches a BFF, the BFF reaches each service with the credential that service issues, and no path leads from the orchestrator to the bank's administration.

Polling costs up to 3 s of latency and steady small requests against a push channel's instant updates; it needs no connection state, survives restarts of any service and is enough for a demo with a handful of agents.

## Consequences

**Becomes easier:** reasoning about who can do what (a route list per BFF); testing the back office against fake upstreams; reproducing the takeover audit trail.

**Becomes harder:** each new back-office capability crosses a BFF route, an admin or agent route, and their Zod shapes; the two token-holding servers are new things to protect.

**Declared in [limitations](../limitations.md):**
- The BFF trusts its own session for `agent_ref`. `banking-core` authenticates the BFF with one shared token and records the email the BFF sends; it cannot tell agents apart by itself.
- A claim cannot be released or closed, and a conversation cannot be handed back to the assistant.
- One demo agent credential, not a user directory or SSO.
- Polling, not push.

**To revisit:** a per-agent identity that `banking-core` can verify, a release/close/hand-back flow, and push updates, in that order.

## Action items

1. [x] banking-core admin API: `GET /v1/admin/handoffs`, `GET /v1/admin/handoffs/{ref}`, `POST /v1/admin/handoffs/{ref}/claim`, `GET /v1/admin/metrics`; migration `0008`
2. [ ] Orchestrator agent API and the takeover in the conversation flow
3. [ ] `web-client` and `web-backoffice` BFFs with their closed route lists and tests against fake upstreams
4. [x] `packages/contracts` TypeScript entry and drift test
5. [ ] Compose services, healthchecks, `make smoke` and `make web-check`
6. [ ] `docs/runbook.md`: drop the "pending UI" marks only for what works
