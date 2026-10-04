# web-client

The simulated Pattern Blue fintech: a landing page with the customer chat dock, and the same-origin BFF that connects the dock to the orchestrator. It is the only thing a customer's browser talks to ([front-ends.md](../../docs/front-ends.md), decisions 1 to 3, 7 and 9).

Bun fullstack (`Bun.serve` with an HTML import, no Vite), React 19, XState v5, Ark UI for the FAQ accordion, Zod through `@pattern-blue/contracts`. Styles come only from `@pattern-blue/design-tokens`; the one stylesheet of this app, `src/app/app.css`, is layout glue with no colors and no tokens.

## Commands

From the repository root, `make web-check` runs `typecheck` and `bun test` for this app (and the contracts), and `make web-client` runs the dev server against the stack from `make up` (stop the compose container first, it holds :5173). Inside the app:

```bash
bun run dev         # bun --hot src/server.ts, on :5173
bun run build       # production bundle into dist/ (the server and the page, dependencies included)
bun run start       # serve dist/ (needs the build)
bun run typecheck   # tsc --noEmit
bun test
```

`start` runs from `dist/` on purpose: Bun looks the bundled assets up relative to the working directory.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5173` | Port to listen on |
| `ORCHESTRATOR_URL` | `http://localhost:8080` | Where the five chat routes are forwarded. Compose sets `http://orchestrator:8080` |

A bad value stops the server at startup with the variable's name. The server holds no token and no other secret.

## The server

| Path | What |
|---|---|
| `GET /` | The page (`src/index.html`) |
| `GET /healthz` | `{"status":"ok"}`. Liveness only: it does not call the orchestrator |
| `/api/*` | The BFF (`src/api/bff.ts`) |
| anything else | 404 |

### The BFF

It registers exactly the five routes of `clientBffRoutes` in `@pattern-blue/contracts` and maps each 1:1 to the orchestrator route of the same name:

- `POST /api/conversations`
- `POST /api/conversations/:id/messages`
- `GET /api/conversations/:id`
- `GET /api/conversations/:id/inbox`
- `POST /api/conversations/:id/feedback` (ADR-0017)

For each request it validates the path id (`ConversationIdSchema`, not a UUID) and the body (strict: an unknown key is a 422), forwards to a path it builds itself, validates the answer with the route's response schema and sends the parsed value on. It forwards none of the browser's headers or query string; it sets `Accept`, the content type, and `X-Forwarded-For` to the connection's address (`server.requestIP`), which the orchestrator reads with `TRUSTED_PROXY_HOPS=1`.

| Situation | Answer |
|---|---|
| Path or body outside the contract | 422 with FastAPI's `{"detail": [{loc, msg, type}]}`, nothing forwarded |
| Upstream error status (404, 409, 429, 502, 503 `replay_miss`...) with a `{"detail"}` body | The same status and `detail`; `Retry-After` passes through |
| Upstream unreachable, timed out (150 s for a turn, 15 s for a read), a 2xx that is not the route's success status, a body outside the contract, a redirect, or an error with no `detail` | 503 `{"detail": "unavailable"}` |
| Any other `/api` path | 404 `{"detail": "not_found"}` |
| A known `/api` path with another method | 405 with `Allow` |

Blocks stay raw on the wire (`RawBlock[]`); the page runs `parseBlocks`. Every `/api` answer is `Cache-Control: no-store`: the inbox carries a live code. The BFF never logs a body.

## The page

`src/app/landing/` is the home page of Pattern Blue, a fictional bank, built from the design system's Landing composition: Navbar (with "Abrir chat" and one theme toggle), Hero (with an active `CardVisual`), FeatureGrid (the bank's products: the checking account, the debit card, help in the chat), HowItWorks (what to do if you lose your card), S2PromoCard, FaqAccordion (Ark UI), Footer, and the chat dock last. The navbar, the hero and the dock open the chat. It is served in es, pt and en from one dictionary per language (`src/i18n/`); a test holds the landing rules in every language (every number is a product fact, no claims about users or speed, no vocabulary of the system behind the bank, no colon joining two clauses, the demo note and the S² small print always present).

### Machines (`src/machines/`)

**Global** (`app.machine.ts`): the theme (`system`, `light`, `dark`; `data-theme` on `<html>`, remembered in `localStorage` behind `try/catch`, applied from the head before the first paint) the language (from `navigator.language`, `es` when it is none of the three; not remembered) and the market (`locale`, [ADR-0014](../../docs/adr/0014-distilbert-intent-backend.md): `es-CO`, `es-MX`, `es-AR`, `pt-BR` or `en-US` when `navigator.language` names one exactly, else none; not remembered). A market always belongs to the language: picking one sets its language, switching to another language drops it. The Navbar's language switch, market switch and theme toggle drive it; the market switch shows only for Spanish, the one language served in more than one market. The text is one neutral Spanish for every Spanish market: the market changes what the chat sends, not what the page says.

**Chat** (`chat.machine.ts`), six regions:

- *conversation*: `idle`, `creating`, `sending`, `ready`, and the failures. **No request is made until the first message**: creating a conversation is rate limited per address. The language goes out on creation and on every message; the market goes out only on creation (the chat API takes none on a turn), and only when it belongs to the message's language.
  - `unavailable` (503, 409, 502, a body outside the contract, a network failure): the message stays in the log with one line under it, "No pudimos enviar tu mensaje. El asistente no está disponible." and Reintentar, which resends the same `client_message_id`, so the orchestrator answers a turn it already ran from its store.
  - `rateLimited` (429): the wait is in minutes, from `Retry-After`; the composer is off until then, and then the message can be retried.
  - `gone` (404, the conversation expired): "Empezar de nuevo" opens a new conversation and sends the message that was not sent.
- *followup*: after every completed turn, the transcript is read once (to detect a takeover) and so is the inbox.
- *takeover*: from the handoff block on, the transcript is polled every 2 s **while the tab is visible**, so the agent's first message arrives without the customer writing again. Once the transcript says an agent holds the conversation, the status "Un agente está atendiendo tu caso" appears and the agent's messages join the log in the agent style. Starting over stops the polling. A send during a takeover returns `blocks: []` by design; that is a normal answer.
- *inbox*: see below.
- *capabilities*: whether detective mode is on ([ADR-0019](../../docs/adr/0019-detective-mode.md)), asked with `GET /api/capabilities` when the chat opens (never on page load) and after every turn, since the back office can turn it off and on.
- *feedback*: after a handoff block the log asks "¿Te ayudó el asistente?" with two equal buttons. The answer goes to `POST /api/conversations/:id/feedback`; banking-core keeps one per handoff and refuses it when there is none (ADR-0017). A failed answer can be sent again.

### The OTP notice

The code is delivered synchronously during the turn that calls `otp.send`, so nothing polls for it. The inbox is read once after each turn; if it holds a message that has not expired and was received after the last successful `otp.verify`, the `otp.send` receipt in the log gains a countdown to `expires_at` and "Abrir bandeja". That opens the simulated inbox as a sheet over the messages (the words "simulada" and "demo" stay visible; Escape, the close button or sending a message closes it); the code is drawn only after "Mostrar código". The notice hides itself at expiry (and the log says so once), and when the code is used. The code lives in the machine's `inbox` context and nowhere else: it is not in any transcript entry, and what the customer types is masked before it is stored (`Código: ••••••` for the code, `•••• 4821` for a card number).

### Detective mode

Where the orchestrator says detective mode is on, the chat header shows a switch (`aria-pressed`); the viewer's choice is remembered in `localStorage` (`pb-detective`, behind `try/catch`), off by default. With it on, each assistant reply shows its turn's trace (`trace` on the send answer, kept on the reply's entry): for now the raw JSON folded under the reply, to be replaced by the designed panel. The trace holds masked values only ([ADR-0019](../../docs/adr/0019-detective-mode.md)).

### The header chip

Derived only from what the blocks prove: a receipt for `otp.send` (code pending), `otp.verify` (verified), `card.block` showing BLOCKED, a handoff block or an active takeover (with an agent). Text never proves anything. With no proof there is no chip.

## Tests

`bun test`:

| File | What |
|---|---|
| `tests/bff.test.ts` | The BFF and the server against a fake orchestrator (`Bun.serve` on an ephemeral port): forwarding, validation rejects, status and `Retry-After` pass-through, unreachable and invalid upstreams to 503, the closed list of routes, `X-Forwarded-For` |
| `tests/chat.machine.test.ts` | Every transition that matters, with a fake `fetch` and a simulated clock |
| `tests/app.machine.test.ts` | Theme, language and market, with a storage that works, is missing or throws |
| `tests/chat-model.test.ts`, `tests/api-client.test.ts` | The pure rules (masking, chip, inbox selection) and the browser client |
| `tests/render.test.tsx` | Block rendering with `react-dom/server`: text, each receipt (result and reference, details hidden until asked), the customer view of a handoff (never the summary or the queue details), the feedback line, an unknown block ignored, the code absent from the transcript, the landing's sections |
| `tests/i18n.test.ts` | The es, pt and en dictionaries have the same keys, and the landing rules |

## Docker

```bash
docker build -f apps/web-client/Dockerfile -t pattern-blue-web-client .   # context: the repository root
docker run --rm -p 5173:5173 -e ORCHESTRATOR_URL=http://host.docker.internal:8080 pattern-blue-web-client
```

Two stages on `oven/bun:1.3`, laid out like the back office's: install and build, then a runtime that holds only `dist/` and runs as the non-root `bun` user. `Dockerfile.dockerignore` next to the Dockerfile is the build context: the workspace manifests (all of them: `--frozen-lockfile` refuses a lockfile that lists a workspace whose `package.json` is missing), the contracts and design-tokens entries, and this app's sources. The build stage runs on the builder's platform, so a `linux/arm64` image needs no emulation. Compose builds it as the `web-client` service (`make up` and `make demo` start it on `127.0.0.1:5173`, in front of the orchestrator). The image has no `curl`; the compose healthcheck is

```
bun -e "fetch('http://127.0.0.1:' + (process.env.PORT ?? 5173) + '/healthz').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"
```

## What it does not do

- **No conversation survives a reload.** The id is held in memory; a reload starts a new conversation. The language is not remembered either (the theme is).
- **A market picked after the first message does not reach that conversation.** The chat API sets the market only when the conversation is created, so the change applies from the next one. Switching to Portuguese or English and back to Spanish forgets the Spanish market. The page text is the same in every Spanish market (no voseo for es-AR).
- **No sign of a new agent message while the chat is closed.** The transcript is still polled, but the launcher does not change.
- **No hand-back from the agent to the assistant** (out of scope, [limitations](../../docs/limitations.md)), and none of the "In design" or "Pending" items of `ChatMessage`: quick replies, card and charge pickers, the account summary. The orchestrator's "could not process that message safely" arrives as a plain text block and is shown as one.
- **No "assistant online" dot** on the launcher: nothing tells the client that the assistant is up.
- **No trusted-proxy handling.** `X-Forwarded-For` is the address of the connection to this server. Behind a TLS-terminating proxy every customer would share one rate-limit bucket until this server is taught to trust that proxy.
- **No CSP and no self-hosted fonts.** The fonts load from Google Fonts; offline, the fallback stacks apply.
- **The login in the Navbar and the legal links are decorative**, as the design system says: there is no account, session or legal page behind them.
