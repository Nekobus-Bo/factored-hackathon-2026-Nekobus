# web-backoffice

The agent back office of Pattern Blue: login, the handoff queue, the case with its verified summary and the masked conversation, "Tomar caso" (claim and take over) with a reply composer, the guardrails (thresholds, amount mode, tool by state matrix, demo reset), the metrics, and the flows (the verification state machine, the tools the policy allows in each state and the main flows, read only). One Bun process serves the page and its same-origin BFF. Spec: [docs/front-ends.md](../../docs/front-ends.md) (decisions 4 to 7, the HTTP contract and "Back office scope").

The browser talks only to this origin. The BFF calls banking-core (`/v1/admin`, queue, claim, guardrails, metrics) and the orchestrator (`/v1/agent`, transcript, takeover, reply) with tokens that never leave the server.

## Stack

Bun fullstack (`Bun.serve` with an HTML import, no Vite), React 19, TypeScript, Zod through `@pattern-blue/contracts` (every payload that crosses a boundary), XState v5 with `@xstate/react` (one global machine for theme, language and the agent session, and one per screen), Ark UI for the dialog and the switch. Styles are `@pattern-blue/design-tokens` (the `pb-*` classes) plus `src/app/app.css`, which only places things.

```
src/
  server.ts       Bun.serve: /healthz, /api/* (the BFF) and the page
  bff/            config, session cookie, upstream calls, the closed list of routes
  index.html      the page (the fonts link and the theme boot script)
  app/            React: shell, screens, design-system pieces, styles.css and app.css
  machines/       app (global), queue, handoff, guardrails, metrics, flows, and the pure draft rules
  i18n/           es (default), pt, en: same keys, checked by a test
  api/            the browser's typed client of /api, and the error categories
tests/            bun test (see below)
Dockerfile        multi-stage, non-root; Dockerfile.dockerignore is its build context
```

## Commands

From the repository root (`make` is the single entry point; Bun 1.3 or later):

```bash
make web-check                          # typecheck and bun test for the contracts and every apps/web-*
make web-backoffice                     # the dev server against the stack from `make up` (stop the compose container first)
bun run --cwd apps/web-backoffice dev   # bun --hot src/server.ts, on :5174
bun run --cwd apps/web-backoffice build # bun build --target=bun: dist/server.js, the page and its assets
bun run --cwd apps/web-backoffice start # serves dist/ (run `build` first)
bun run --cwd apps/web-backoffice typecheck
bun run --cwd apps/web-backoffice test
```

To try it without the backend, `tests/support/fake-upstreams.ts` starts a fake banking-core and a fake orchestrator that follow the contract, with fixtures; the tests and the visual check use them.

The image, from the repository root (`Dockerfile.dockerignore` next to the Dockerfile is its build context):

```bash
docker build -f apps/web-backoffice/Dockerfile -t pattern-blue/web-backoffice .
```

Compose builds it as the `web-backoffice` service (`make up` and `make demo` start it on `127.0.0.1:5174`, with the same development tokens as the two backends, so no `.env` is needed). The production overlay does not publish it and requires its four secrets ([docs/deployment.md](../../docs/deployment.md), section 3).

## Configuration

Read once at start. The defaults are the development values of `.env.example`; the server logs every problem it finds and exits with 1.

| Variable | Default | |
|---|---|---|
| `PORT` | `5174` | |
| `APP_ENV` | `development` | `production` turns on the refusals below and the `Secure` cookie |
| `ORCHESTRATOR_URL` | `http://localhost:8080` | agent API |
| `BANKING_CORE_URL` | `http://localhost:8081` | admin API |
| `ADMIN_API_TOKEN` | `dev-only-admin-token` | bearer for banking-core |
| `AGENT_API_TOKEN` | `dev-only-agent-token` | bearer for the orchestrator |
| `DEMO_AGENT_EMAIL` | `agent@demo.local` | the agent's login, and the `agent_ref` of every claim, takeover and audit row |
| `DEMO_AGENT_PASSWORD` | `demo-only-change-me` | |
| `BACKOFFICE_SESSION_SECRET` | a development default | HMAC key of the session cookie |
| `UPSTREAM_TIMEOUT_MS` | `10000` | how long an upstream may take before the BFF answers 503 |

Under `APP_ENV=production` the server refuses to start with the default password, the default secret, or either development token (unset and empty count as the default).

## Security notes

- **Tokens stay on the server.** `ADMIN_API_TOKEN` and `AGENT_API_TOKEN` are read by `src/bff/` and used in `Authorization` headers to the upstreams. Nothing in the bundle or in a response carries them (a test checks the headers of a real response).
- **The session is a signed cookie**, `pb_session`: `base64url({agent_ref, exp})` plus an HMAC-SHA256 over it, `HttpOnly`, `SameSite=Strict`, `Path=/`, 8 hours, and `Secure` when `APP_ENV=production`. There is no server-side store: the signature and the expiry are the proof, and a tampered, foreign or expired cookie is simply no session.
- **Credentials and signatures are compared in constant time** (`timingSafeEqual` over SHA-256 digests, so lengths do not leak). A login always compares both fields.
- **The gate**, in this order, for every `/api` request: the route must exist (else 404, exactly the routes of `backofficeBffRoutes`), the cookie must verify (else 401, except `POST /api/session`), a mutating route needs `Content-Type: application/json` (else 415, with or without a body), and params, query and body are validated with the contract's strict schemas (422, or 400 for bad JSON). Then the upstream is called and its answer validated again; an unknown field is dropped.
- **The browser's headers are never forwarded.** `X-Agent-Ref` is built from the session, and a value sent by the browser is ignored. Ids are checked as opaque tokens before they become part of an upstream path.
- **Errors do not leak upstream text.** An upstream 5xx is 502 `upstream_error`; a refused BFF token (upstream 401) is 502 `upstream_unauthorized`, never a 401 that would send the agent to the login for a deployment mistake. An unreachable upstream is 503 `unavailable`.
- **The customer's messages are masked at the source; the agent's own are shown as written.** The orchestrator stores customer messages masked. An agent's message is stored masked in clear and, encrypted, as written, and both transcripts return the text as written: what the composer sends is read back unchanged, by the agent and by the customer. The composer says so, that the assistant never sees it, and to write only what the customer needs. The customer app still renders a full card number as `•••• 1234`, whoever wrote it.
- Every `/api` response says `Cache-Control: no-store`. Requests are limited to 64 KiB.

## How the takeover works

`POST /api/handoffs/:ref/claim` claims in banking-core (audited there with the agent as actor), looks up the conversation of the handoff's session in the orchestrator and takes it over. Both steps are idempotent for the same agent, so a retry is safe:

| Outcome | Answer |
|---|---|
| Both steps done | 200 `{handoff, takeover}` |
| Another agent holds the handoff, or the conversation | 409 `claimed_by_another_agent` / `taken_over_by_another_agent`, shown as "Otro agente ya tomó este caso" |
| The claim is done and the second step failed (unreachable, 5xx, no conversation, `turn_in_progress`, a bad answer) | 502 `claimed_but_takeover_failed`; the screen says so and offers the same action again |
| banking-core unreachable | 503 `unavailable`, nothing was claimed |

A reply carries its own `client_message_id`. If it fails (a customer turn in flight is 503 `turn_in_progress` with `Retry-After`), the message stays on screen and "Reintentar" sends the same id, so it cannot be posted twice.

## Screens

- **Queue.** The design system's QueueRow. Polls every 3 s while the tab is visible and refreshes at once when it comes back. Filter: open (both), `QUEUED`, `ASSIGNED`. Priority and department in words and as the raw enum, the status with its queue position, the wait as `mm:ss`, the agent.
- **Case.** HandoffCard with the stored summary as it is (verified facts, actions taken with their decision and audit id, the verification method, the open questions marked with their source). The masked transcript is loaded once before the takeover and polled every 2 s after it (paused while the tab is hidden). The composer is enabled only while this agent holds the conversation.
- **Guardrails.** PolicyControl: a threshold per currency (shown in major units, stored in minor units), the mode as "handoff recomendado (`flag`)" or "handoff requerido (`block`)", and the tool by state matrix. A cell outside the code floor is `aria-disabled` and, when clicked, answered with the hazard-striped refusal the API would give (422); the master switch turns a tool off, or back on within its floor. Saving asks for confirmation, sends only what changed (`PUT policy-config`, then `PUT tool-policy`) and shows the new versions. The demo reset asks first.
- **Flows.** `#/flows`, read only: the path to VERIFIED with the tool of each step and the ways out, the tool by state matrix as the policy in force has it (a disabled tool reads as disabled), and four flows (unrecognized charge, fraud with an example conversation, lost or stolen card, balance) with their outcomes and what is still pending. It reads the same two admin routes as Guardrails and changes nothing.
- **Metrics.** Tool calls by action, decision and reason, handoffs by status, priority and department, cards blocked, OTP counts; 24 h or 7 d. Only what `GET /v1/admin/metrics` returns.

Theme (system, light or dark, `data-theme` on `<html>`, remembered in `localStorage` with try/catch) and language (es by default, pt, en) are in the header.

## Tests

`bun test`: the BFF (cookie signature, tampering, expiry, constant-time use, production refusal of the defaults, every route against fake upstream servers on ephemeral ports with the token and header forwarding checked, the claim-then-takeover sequence with its 502 path and retry), the machines against a fake `fetch`, server-rendered markup of the queue row, the handoff card and the policy matrix (floor cells not toggleable), the dictionaries (same keys and placeholders), and the client API.

## What it does not do

- **No hand-back to the assistant, no reassignment, no resolving.** After a takeover the LLM never sees the conversation again. "Reasignar" of the HandoffCard is not shown: nothing behind it exists. Disputes are resolved by people, outside this screen.
- **No SLA marker in the queue.** The design's late marker needs an SLA from configuration and no service provides one. The design's language and masked-customer columns are replaced by status and agent: `HandoffItem` carries neither language nor customer.
- **No seed values in the thresholds.** The admin API does not return the `.env` seed, so a row shows the value in force ("Vigente") and marks an edited one. The API needs a threshold above zero; the design's README says "non-negative".
- **The masked transcript before the takeover is a snapshot**, not live. A queued case is not polled either: a claim by someone else shows up as the 409.
- **One demo agent.** There is one login (`DEMO_AGENT_*`), no user store, no roles, no login rate limiting, no CSRF token beyond `SameSite=Strict` and the JSON content type. It is meant to run inside the private network, or behind its own login in the presentation environment.
- **No decision-point numbers** in the metrics and no derived rates: nothing feeds them yet.
- **Fonts load from Google Fonts**; offline the fallback stacks apply.
- **Not published in production.** The production compose overlay gives it no host port: it is reached through a proxy with its own login, or a loopback port the operator publishes and tunnels to ([docs/deployment.md](../../docs/deployment.md)).
