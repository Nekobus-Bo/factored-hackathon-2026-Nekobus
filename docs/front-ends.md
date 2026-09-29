# Front ends: specification and HTTP contract

> **Status: in progress** (2026-09-29). The Zod mirror of every shape below is `@pattern-blue/contracts` (`packages/contracts/ts/`, conventions in `packages/contracts/README.md`): requests are strict, responses strip unknown keys, and `blocks` stay raw until `parseBlocks`. Progress and next steps: [status-and-plan.md](status-and-plan.md). The decisions are recorded in ADR-0013 (`docs/adr/0013-front-ends-bff-takeover.md`, landing with the back-office API work).

Everyone working on the front ends reads this file. The API shapes below are the contract between work packages: implement them exactly. Anything this file does not fix is yours to decide; record what you decided. If something here is impossible or contradicts the code, raise it and change this file first; do not improvise around it.

Read `AGENTS.md` first. Design system: the Claude Artifact "Pattern Blue" (type Design System), https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV, version 1790655197-4dbb. It is private to its owner until shared from its Share menu, so a verbatim copy of its documentation lives in `packages/design-tokens/reference/`:
- `README.md`: voice, type, color, layout and motion rules;
- `components/<Name>/README.md` and `preview.html`: the markup and rules of each component;
- the stylesheet itself is `packages/design-tokens/src/components.css` (the artifact's `components/bundle.css`).

## Decisions (ADR-0013, "Front ends, their BFFs and the human takeover")

1. **Each front end is a Bun fullstack app.** `Bun.serve` with HTML imports serves the bundle; no Vite. React + TypeScript, Zod on every payload that crosses a boundary, XState v5 (one global app machine for theme, language and, in the back office, the agent session; local machines per feature), Zag.js / Ark UI for accessible headless parts. Styles come only from `@pattern-blue/design-tokens` (`index.css` + `dist/fonts.html`); no CSS framework, no inline colors, no new tokens.
2. **Same-origin BFF.** Each app's server exposes the bundle and a closed list of `/api/*` routes. The browser never talks to the orchestrator or banking-core directly, so there is no CORS. The BFF forwards only the routes listed here, with typed request and response validation. It never forwards an arbitrary path or body; a generic pass-through would void ADR-0004.
3. **web-client BFF** (`apps/web-client`, port 5173) forwards the four chat routes of the orchestrator. It holds no tokens. It sets `X-Forwarded-For` to the client address, and compose sets `TRUSTED_PROXY_HOPS=1` on the orchestrator. It also serves `GET /healthz`.
4. **web-backoffice BFF** (`apps/web-backoffice`, port 5174):
   - The agent logs in with `DEMO_AGENT_EMAIL` / `DEMO_AGENT_PASSWORD`. Compare in constant time.
   - The session is an HttpOnly, `SameSite=Strict` cookie signed with HMAC-SHA256 using `BACKOFFICE_SESSION_SECRET`, with an 8 h expiry.
   - Under `APP_ENV=production` the server refuses to start with the default password or the default secret.
   - It holds `ADMIN_API_TOKEN` (banking-core) and `AGENT_API_TOKEN` (orchestrator) server-side. Neither reaches the browser.
   - Every mutating route requires the session and `Content-Type: application/json`.
   - It also serves `GET /healthz`.
5. **Back-office data path** (amends ADR-0004, whose text says the orchestrator "exposes the back office"):
   - Queue, handoff detail, claim, guardrails and metrics come from the **banking-core admin API**, over the internal network.
   - The conversation (masked transcript, takeover, agent reply) comes from a new **orchestrator agent API**.
   - The web-backoffice server runs in the internal network. In the presentation environment it is either not published or published only behind its login.
6. **Takeover:**
   - The agent claims the handoff in banking-core first. That write is audited with `actor_type='agent'` and the agent's email as `actor_ref`, which is the "every takeover is recorded" of ADR-0004.
   - Then the BFF takes over the conversation in the orchestrator.
   - From then on the LLM never sees that conversation again. Customer messages are stored masked and reach the agent. Agent messages are masked with the same masker before storage (fail closed to `[REDACTED]`), so the transcript never holds raw PII.
   - There is no hand-back to the assistant; that is out of scope and declared in limitations.
7. **Live updates by polling, no WebSocket:**
   - back-office queue: every 3 s;
   - back-office open conversation: every 2 s;
   - customer chat while a takeover is active: every 2 s;
   - OTP inbox, after the assistant asks for a code: every 2 s until a message arrives or it expires.
   - Polling stops when the tab is hidden and resumes when it is visible.
8. **Shared TypeScript contracts:**
   - `packages/contracts` gains a TS entry: `package.json` named `@pattern-blue/contracts`, Zod schemas in `packages/contracts/ts/`. It joins the Bun workspace through the existing `packages/*` glob; the Python package is untouched.
   - It holds the message block schemas (text, receipt, handoff, mirroring `packages/contracts/src/contracts/blocks.py`), and a drift test compares them against the committed JSON Schemas that `export_schemas.py` writes (field names, required fields, enums).
   - It also holds the HTTP shapes below.
9. **Languages:**
   - Both apps are served in es, pt and en with one dictionary per language, following the global machine's `lang`.
   - The customer app starts from `navigator.language`, falling back to `es`.
   - The back office starts in `es`.
   - The back office shows raw enums (`OTP_PENDING`, `URGENT`) beside the words, per the StatusChip rule.
10. **Wiring:**
    - Each app has `src/`, `tests/` and a `Dockerfile`, with an `oven/bun:1.3` base and a non-root user. The image contains only the production bundle and server.
    - Compose services `web-client` and `web-backoffice`, with healthchecks on `/healthz`, depend on a healthy orchestrator (and banking-core for the back office). `make smoke` checks them.
    - `make web-check` runs typecheck and `bun test` for the contracts TS entry and both apps. CI runs it in the existing Bun job. The `images` matrix gains both apps.
    - `docs/runbook.md` loses its "⚠️ pending UI" marks only for what really works.

## HTTP contract

All JSON. Times are ISO 8601 UTC. Errors keep FastAPI's `{"detail": ...}`.

### Orchestrator chat API (exists; do not change its shapes except as marked NEW)

- `POST /v1/conversations` `{lang?}` → 201 `{conversation_id, language}`; 429 with `Retry-After`.
- `POST /v1/conversations/{id}/messages` `{text, lang?, client_message_id?}` → `{conversation_id, blocks[]}`; 503 `{detail:"replay_miss"}` or unavailable; 429.
- `GET /v1/conversations/{id}` → `{conversation_id, language, messages[{role, content, blocks[], created_at}], takeover}`.
  - NEW: `role` may also be `"agent"`.
  - NEW: `takeover` is `{active: bool, since: time|null}`, with no agent identity.
- `GET /v1/conversations/{id}/inbox` → `{messages[{channel, destination_masked, code, received_at, expires_at}]}`.
- NEW behavior: while a takeover is active, `POST .../messages` stores the customer message (masked), does not call the LLM or banking-core tools, and returns `{conversation_id, blocks: []}`.

### Orchestrator agent API (NEW)

- Router `/v1/agent`, mounted only when `AGENT_API_ENABLED=true`.
- Auth is `Authorization: Bearer <AGENT_API_TOKEN>`, compared in constant time.
- The development token is `dev-only-agent-token`. Startup fails under `APP_ENV=production` with an empty or development token (mirror `require_admin` in banking-core `routes_admin.py`).

Routes:
- `GET /v1/agent/sessions/{session_ref}/conversation` → `{conversation_id}` or 404. It is backed by a reverse index in redis-edge, written when the conversation is created, with the conversation's TTL. `session_ref` is the banking-core session id, which is what `ops.handoff.session_ref` stores; verify that.
- `GET /v1/agent/conversations/{id}` → the transcript shape above, with `takeover: {active, since, agent_ref|null}`.
- `POST /v1/agent/conversations/{id}/takeover` `{agent_ref, handoff_ref}` → `{conversation_id, takeover:{active:true, since, agent_ref}}`.
  - Idempotent for the same agent.
  - 409 `{detail:"taken_over_by_another_agent"}` when another agent holds it.
  - 404 for an unknown conversation.
- `POST /v1/agent/conversations/{id}/messages` `{text (1..2000), client_message_id}` → `{message:{role:"agent", content, blocks:[], created_at}}`.
  - The text is masked before storage.
  - 409 `{detail:"no_active_takeover"}` if not taken over by this agent (the agent is identified by an `X-Agent-Ref` header the BFF sets from the session).
  - A repeated `client_message_id` returns the stored message.

### banking-core admin API (NEW routes on the existing `/v1/admin` router, same `require_admin`)

- `GET /v1/admin/handoffs?status=QUEUED&status=ASSIGNED` (default both) → `{items:[HandoffItem]}`, ordered by priority (URGENT, HIGH, NORMAL, LOW) and then `created_at`.
  - `HandoffItem`: `{handoff_ref, status, priority, department, reason, created_at, queue_position|null (only when QUEUED, same rule the handoff block uses), assigned_agent|null, assigned_at|null, session_ref}`.
- `GET /v1/admin/handoffs/{handoff_ref}` → `HandoffItem` + `summary`, exactly as stored: `verified_facts`, `actions_taken`, `verification_method`, `open_questions`, and any other stored keys. 404 when unknown.
- `POST /v1/admin/handoffs/{handoff_ref}/claim` `{agent_ref}` (an email, 3..254) → the detail above.
  - The status becomes `ASSIGNED`, with `assigned_agent` and `assigned_at` set.
  - Idempotent for the same agent. 409 `{detail:"claimed_by_another_agent"}` otherwise.
  - Writes audit action `admin.handoff.claimed` with `actor_type='agent'`, `actor_ref=agent_ref` and payload `{handoff_ref, before_status, after_status}`, with no PII.
  - Needs migration `0008` adding the nullable columns `assigned_agent` and `assigned_at` to `ops.handoff`.
- `GET /v1/admin/metrics?hours=24` (1..720) → `{generated_at, window_hours, tool_calls:[{action, decision, reason_code|null, count}], handoffs:{total, by_status{}, by_priority{}, by_department{}}, cards_blocked, otp:{sent, verified, failed}}`.
  - It aggregates from `ops.audit_log` over the window and from `ops.handoff`, with no PII.
  - Use the real audit action names. List them in your report.
- Existing routes the back office uses as they are: `GET`/`PUT /v1/admin/policy-config`, `GET`/`PUT /v1/admin/tool-policy`, `POST /v1/admin/demo/reset-fixtures`.

### web-client BFF (`/api`, same origin)

These map 1:1 to the four orchestrator chat routes:
- `POST /api/conversations`
- `POST /api/conversations/:id/messages`
- `GET /api/conversations/:id`
- `GET /api/conversations/:id/inbox`

Rules:
- `:id` is an opaque path-safe token, `^[A-Za-z0-9_-]{1,64}$` (`ConversationIdSchema`). The orchestrator's ids are `conv_<hex>`, not UUIDs. Validate the request, forward, then validate the response with Zod.
- Status codes and `Retry-After` pass through.
- Upstream unreachable → 503 `{detail:"unavailable"}`.

### web-backoffice BFF (`/api`, same origin, cookie session)

- **Session:**
  - `POST /api/session` `{email, password}` → 204 plus the cookie; 401 otherwise.
  - `DELETE /api/session`.
  - `GET /api/session` → `{agent_ref}` or 401.
- **Queue and handoffs:**
  - `GET /api/handoffs` → the admin list.
  - `GET /api/handoffs/:ref` → the admin detail, plus `conversation_id|null` resolved through the agent API.
  - `POST /api/handoffs/:ref/claim` → claims in banking-core with the session's agent, then takes over in the orchestrator. It returns `{handoff, takeover}`: `handoff` is the claim's handoff detail, and `takeover` is the agent API's takeover response verbatim, `{conversation_id, takeover:{active, since, agent_ref}}`. If the takeover fails after the claim succeeded, it returns 502 `{detail:"claimed_but_takeover_failed"}`, and a retry of the same call is safe because both steps are idempotent.
- **Conversations:**
  - `GET /api/conversations/:id` → the agent transcript.
  - `POST /api/conversations/:id/messages` `{text, client_message_id}` → the agent API, with `X-Agent-Ref` from the session.
- **Guardrails and metrics:**
  - `GET`/`PUT /api/policy-config`, `GET`/`PUT /api/tool-policy` and `POST /api/demo/reset` → the admin routes.
  - `GET /api/metrics?hours=` → the admin metrics.

## Customer app (web-client) scope

- **Landing:** the Landing composition (Navbar, Hero, FeatureGrid, HowItWorks, S2PromoCard, FaqAccordion, Footer), with the copy of the previews in es, pt and en. The previews have only es copy for FeatureGrid, HowItWorks, FAQ and Footer; translate them faithfully, keeping every rule: no invented numbers, and a demo note in every language.
- **Chat dock:** ChatBubble launcher and panel. Every content type in `components/ChatMessage/README.md` that says "Exists", with the backend source it names:
  - text;
  - receipts;
  - handoff (customer view);
  - the OTP notice (OtpInboxNotice, fed by the inbox route, never echoing the code into the transcript);
  - service unavailable with a retry that resends the same `client_message_id`;
  - rate limited with the `Retry-After` time;
  - agent messages after a takeover, with a "Un agente está atendiendo tu caso" status.
  - Items marked "In design" or "Pending" in that README are not built.
- **State chip in the chat header:** derived only from what the blocks prove. When nothing proves a state, show none; never guess.
- **Global machine:** theme (system, light or dark; persisted in localStorage with try/catch; `data-theme` on `<html>`) and lang.
- **Chat machine:** create lazily on the first message, send, retry, rate limit, unavailable, takeover polling, inbox polling.
- **Tests:** machines (every transition that matters), BFF routes against a fake upstream `Bun.serve` on an ephemeral port, and block rendering against fixtures.

## Back office (web-backoffice) scope

- **Login.**
- **Queue:** QueueRow list, polling, filters by status.
- **Handoff detail:** HandoffCard with the stored summary, the masked transcript, "Tomar caso" (claim plus takeover), and the reply composer once taken over.
- **Guardrails:**
  - PolicyControl for the per-currency thresholds and the amount mode, labelled "handoff recomendado (`flag`)" / "handoff requerido (`block`)" per AGENTS.md.
  - The tool × state matrix, where only what the code floor allows is toggleable and the floor is shown.
  - Demo reset with a confirmation.
- **Metrics:** tool calls by decision and reason, handoffs by status, priority and department, cards blocked, OTP counts. No invented metrics, and no decision-point numbers (there is no source for them here).
- **Tests:** machines, BFF auth (cookie signature, expiry, constant-time compare, production refusal), BFF routes against fake upstreams, and the claim-then-takeover sequence including the 502 path.
