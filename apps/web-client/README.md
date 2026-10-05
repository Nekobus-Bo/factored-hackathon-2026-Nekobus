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

`src/app/landing/` is the home page of Pattern Blue, a fictional bank, built from the design system's Landing composition: Navbar (the section links, three tools of radios: Idioma (ES, PT) and País (MX, AR, CO, for Spanish only: the market), each with a visible label, and the theme (a sun and a moon, "Claro" and "Oscuro", with no visible label and named "Tema" for assistive technology); the bar folds into its menu up to 1140px; the chat opens from the hero and from the launcher, not from the bar), Hero (with an active `CardVisual`), FeatureGrid (the bank's products: the checking account, the debit card, help in the chat), HowItWorks (what to do if you lose your card), S2PromoCard, FaqAccordion (Ark UI), Footer, and the chat dock last. The hero button ("Hablar con el asistente") and the launcher at the bottom right open the chat; the navigation bar has no button for it. It offers es and pt (`LANGS`): the system was built and measured on es-CO, es-MX, es-AR and pt-BR, and the intent model was never trained on English. There is one dictionary per language (`src/i18n/`), English included, because the chat contract still takes `en`; a test holds the landing rules in every dictionary (every number is a product fact, no claims about users or speed, no vocabulary of the system behind the bank, no colon joining two clauses, the demo note and the S² small print always present).

### Machines (`src/machines/`)

**Global** (`app.machine.ts`): the theme (`system`, `light`, `dark`; `data-theme` on `<html>`, remembered in `localStorage` behind `try/catch`, applied from the head before the first paint) the language (from `navigator.language`, `es` when it is neither es nor pt, an English browser included; not remembered) and the market (`locale`, [ADR-0014](../../docs/adr/0014-distilbert-intent-backend.md): `es-CO`, `es-MX`, `es-AR` or `pt-BR` when `navigator.language` names one exactly, else the language's default, `es-CO` for Spanish, the locale with the best intent test score; not remembered). A market always belongs to the language: picking one sets its language, switching to another language moves to that language's default market. The Navbar's language, market and theme tools drive it (the theme is two radios that pin a theme; until one is pinned, the checked one is the system's); the market switch shows only for Spanish, the one language served in more than one market. The text is one neutral Spanish for every Spanish market: the market changes what the chat sends, not what the page says.

**Chat** (`chat.machine.ts`), six regions:

- *conversation*: `idle`, `creating`, `sending`, `ready`, and the failures. **No request is made until the first message**: creating a conversation is rate limited per address. The language goes out on creation and on every message; the market goes out only on creation (the chat API takes none on a turn), and only when it belongs to the message's language.
  - `unavailable` (503, 409, 502, a body outside the contract, a network failure): the message stays in the log with one line under it, "No pudimos enviar tu mensaje. El asistente no está disponible." and Reintentar, which resends the same `client_message_id`, so the orchestrator answers a turn it already ran from its store.
  - `rateLimited` (429): the wait is in minutes, from `Retry-After`; the composer is off until then, and then the message can be retried.
  - `gone` (404, the conversation expired): "Empezar de nuevo" opens a new conversation and sends the message that was not sent.
- *followup*: after every completed turn, the transcript is read once (to detect a takeover) and so is the inbox.
- *takeover*: from the handoff block on, the transcript is polled every 2 s **while the tab is visible**, so the agent's first message arrives without the customer writing again. Once the transcript says an agent holds the conversation, the status "Un agente está atendiendo tu caso" appears and the agent's messages join the log in the agent style. Starting over stops the polling. A send during a takeover returns `blocks: []` by design; that is a normal answer.
- *inbox*: see below.
- *capabilities*: whether detective mode is on ([ADR-0019](../../docs/adr/0019-detective-mode.md)), asked with `GET /api/capabilities` when the chat opens (the chat is open on entering, so that is on page load: the dock's open effect sends it, without moving the focus; the hero's button, with the chat open, only asks for the composer: `Landing` raises a counter, `focusRequest`, and the dock focuses the visible composer through `focusesOnRequest` and its `focusComposer`) and after every turn, since the back office can turn it off and on.
- *script* (not a region: `context.script`): where the customer stands in one of the demo scripts, or null. It moves in `startSend`, with the raw text of the send (`nextClientState` of `@pattern-blue/contracts`), and when a turn brings the verification receipt for the first time (`scriptVerified`). `SCRIPT.START` opens a **new** conversation with the script's first line, with the script's own language and market (not the page's), and starts clean: the log, the takeover, the inbox, the `verifiedAt` and the *feedback* and *followup* regions. It is accepted when a conversation can be started (`idle`, `ready`, `unavailable`, `retryable`, and `gone`: choosing a script opens a new conversation by itself, so an expired one does not need "Empezar de nuevo" first and one creation is spent, not two) and ignored while a message is in flight or a rate limit runs. A retry resends `pending` and does not go through `startSend`, so a message counts once; "Empezar de nuevo" after a 404 stops the script, because the new conversation holds only the message that was not sent. `SCRIPT.RESET` ("Cambiar de guion") forgets the script and touches nothing else.
- *feedback*: after a handoff block the log asks "¿Te ayudó el asistente?" with two equal buttons. The answer goes to `POST /api/conversations/:id/feedback`; banking-core keeps one per handoff and refuses it when there is none (ADR-0017). A failed answer can be sent again.

### The OTP notice

The code is delivered synchronously during the turn that calls `otp.send`, so nothing polls for it. The inbox is read once after each turn; if it holds a message that has not expired and was received after the last successful `otp.verify`, the `otp.send` receipt in the log gains a countdown to `expires_at` and "Abrir bandeja". That opens the simulated inbox as a sheet over the messages (the words "simulada" and "demo" stay visible; Escape, the close button or sending a message closes it); the code is drawn only after "Mostrar código". The notice hides itself at expiry (and the log says so once), and when the code is used. The code lives in the machine's `inbox` context and nowhere else: it is not in any transcript entry, and what the customer types is masked before it is stored (`Código: ••••••` for the code, `•••• 4821` for a card number).

### Detective mode

Where the orchestrator says detective mode is on, each assistant reply with a trace (`trace` on the send answer, kept on the reply's entry) gets an action of the system, `pb-action`: the icon, "Ver detective", the turn's time and an arrow. The view is `TracePanel.tsx` (styles `pb-trace-*` in `@pattern-blue/design-tokens`' `local.css`) and lives in the **demo panel** at the left of the chat (`SidePanel.tsx`, below), as its "Detective" tab, where there is room (920px wide and 500px tall or more): the chat and its composer stay in sight and usable. The panel opens from the one header button, "Menú demo" (text and the `menu` icon; `aria-pressed` while the panel shows; on the tab last used in the visit, the guide the first time; pressing it again closes the panel), or from the action under a reply, which opens it on the Detective tab with that turn. With no room (under 920px wide or under 500px tall) the chat takes the whole screen and the same button, which exists always, opens the panel (the same `SidePanel`, with both tabs) in place of the log and the composer inside the chat's panel, and turns into an icon button back to the chat; on a window of 340px or less it keeps its icon alone. Whether there is room is `useSidePanelRoom` (`matchMedia` on `SIDE_PANEL_QUERY`, `(min-width: 920px) and (min-height: 500px)`, the exact complement of the stylesheet's full-screen query); the panel is drawn in one place only, and where it is is derived from that, never stored. Whether the panel is open, its tab and the turn picked are state of `ChatDock`, a pure reducer in `detective-view.ts`, not of a machine, and are not remembered: every visit starts with the panel closed (the `pb-detective` key an earlier version wrote is ignored). In place of the chat the log and the composer stay mounted and hidden, so the scroll and the draft survive (the log is `display:none` meanwhile, so a reply that arrives while the panel is in place is not announced by its live region; it is there when the chat is back) (and a resize between the two layouts keeps the open tab, the turn and the script); leaving it puts the log back where it was (or at the bottom, if it was there and has grown), and Escape goes back to the chat instead of closing it. The focus after a use of the guide is chosen by one pure function (`focusAfterGuide` in `detective-view.ts`, applied by `ChatDock`): the log for a pick or a send, so the phone's keyboard does not cover the reply. It is not the only code that moves the focus: Escape and the way back fall to the layout effect on leaving the in-place panel (the composer), and a copy is focused by `Composer` itself in the click, through its `fill`. The log is a tab stop (`tabindex="0"`) so the keyboard can scroll it, and it shows the system's ring on `:focus-visible`. With no room and the chat open the landing under it is `inert` (`Landing.tsx`: the bar, the main and the footer), so Tab and screen readers stay in the chat. The view follows the newest turn until another is picked with the stepper, "Turno n de total" counted among every reply, which skips the replies without a trace; switching tabs keeps the turn picked. It shows the turn as a list of steps that open in place or as a timeline of bars, with totals for the turn and the conversation (`USD 0.00034`). When the back office turns the mode off, the next check (and opening the panel on the tab asks again) takes the panel to the guide, beside the chat or in place of it. The trace holds masked values only; the quote above it is the customer's bubble, already masked for display ([ADR-0019](../../docs/adr/0019-detective-mode.md)).

### The demo guide

The "Guion" tab of the demo panel at the left of the chat. The panel is `SidePanel.tsx` (props only): an `aside` as tall as the chat, `min(520px, calc(100% - 580px))` wide (340px at 920px), with a tab list (the guide and, where detective mode is offered, "Detective"; with the mode off it is the guide alone, with no tabs) and the "Solo demo" tag, which belongs to the guide's tab. It is closed by default and opened from the "Menú demo" header button (the same one that opens the Detective tab), which exists at every size; with no room beside the chat the guide is drawn in place of the chat (see Detective mode above). The guide's content is `GuidePanel.tsx` (props only; `ChatDock` connects it, `guide-actions.ts` is what a click does to the machines). With no script it lists the six, each with its label, its first line, its market and, for the two unrecognized-charge scripts, a note naming the guardrail. Choosing one switches the page to the script's market (`LOCALE.SET`, which brings the language) and starts the script in the chat (`SCRIPT.START`); beside the chat nothing closes and only the composer takes the focus if it is free, in place of the chat the panel closes and the log takes it. With a script it shows the lines sent, the next one as a text card with two icon buttons beside it, send and copy (both disabled while a message is in flight or waits for its retry), and what comes after; at the code step there is no option, only a pointer to the inbox. The card is text, not a button; beside it are two icon buttons of the same kind (`pb-btn pb-btn--secondary pb-btn--icon`, 44px: one primary per view, and it is the composer's send): send (the `send` glyph, named "Enviar este mensaje" so it is not mistaken for the composer's "Enviar mensaje") and copy (the `copy` glyph, `pb-ico--copy`, named "Copiar al chat"); the names are their `aria-label` and `title`. Copy puts the line in the composer through the `Composer`'s imperative handle (`fill`: it replaces the draft, focuses the text area and puts the caret at the end, after the value is painted, inside the click; the draft stays the composer's own state), and sends nothing. It is disabled like the card and while the code field is the composer in sight, and absent on the six, at the code step, when complete and when stopped. A line sent unchanged moves the script (`nextClientState`: exact match after trim); a changed one stops it, and the stopped hint says the visitor left the script and the guide no longer suggests the following steps: it lives in the panel only (never as a message of the conversation). The card and its copy button are one component, `NextLine.tsx`, which `NextBand` (same file) also draws over the composer, between the log and the composer and outside the `role="log"` element, whenever a script is running on a message step and neither the panel beside the chat nor the code field is showing; it is compact (the line clamped to three lines, full text in `title`) and has no panel of its own: a send keeps the visitor in the chat (the log takes the focus when there is no room, so the phone's keyboard stays closed), a copy fills the composer as the guide does. "Cambiar de guion" brings the six back. Switching to the detective tab and back keeps the script in progress: it lives in the chat machine, not in the panel. The lines come from `@pattern-blue/contracts` and are never in a dictionary; the labels, the notes and the hints are, in es, pt and en. Nothing of the guide is inside the conversation.

### The code field

While a one-time code is pending the composer is `CodeComposer.tsx` instead of the text area: one field for the six digits drawn as six boxes (the design system's digit cell `pb-code__d` in its `mono-code` type, the box to type in marked in the focus colour, only while the field has the focus) under a visible label, "Código de 6 dígitos", with one real transparent `<input>` over them (`inputmode="numeric"`, `autocomplete="one-time-code"`; no `maxLength`, so a pasted "588 820" reaches the digit filter), "Cancelar" beside it and no send button. The text area stays mounted, hidden, so a draft survives. Whether the composer is the field, and in which state, is a pure function of the machine's context and the clock (`codeModeOf` in `chat-model.ts`, read through `selectCodeMode`): `entry` (a live code: an unexpired inbox message received after the last verification, the receipts say it was sent and not verified, and the session is not locked, handed off or gone), `expired`, `dismissed` and `off`. `context.codeDismissed` holds the challenge the customer cancelled (the id of the entry with the newest `otp.send` receipt), so a new code enters the field again. The field keeps only digits and six at most, so pasting "588 820" keeps "588820"; the sixth digit sends the code once through the chat's own send (`SEND`: the demo script and the `Código: ••••••` mask work as for any message) and empties the field, which is off while the turn is in flight. A failed code keeps the mode, with the field empty and focused; the line under it shows only when the newest turn carries an `otp.verify` receipt that did not end verified, and a `LOCKED` receipt ends the mode, and so does a handoff (a code sent after one does not bring the field back). The cursor of the transparent input stays at the end whatever a click or an arrow tries. The decision of the field (what stays, whether it sends) is the pure `codeFieldChange`. A new code is a new field (`key` is the challenge) and the field or "Pedir otro código" takes the focus when the chat reopens or the view that replaced the chat goes. When the code expires the field gives way to "El código venció." and "Pedir otro código" (it takes the focus, and the digits typed are dropped), which sends a fixed message in the conversation's language (the client cannot call tools; the assistant decides to resend, up to `OTP_MAX_RESENDS`); inside a demo script that message is the chat's own and does not stop it: it is sent with `codeRequest`, and at the script's code step the script stays there (anywhere else, or the same words typed by hand, it is free text and stops the script as any other). "Cancelar" sends nothing: the normal composer comes back and, while the code is live, the notice offers "Escribir el código". No attempts counter is shown: the contract does not carry one to the client.

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
| `tests/code-mode.test.tsx`, `tests/chat-model.test.ts` | The code field: its markup in each state, the machine around it (cancel, resume, a new code, expiry, a failed code, a lock), and the pure decision `codeModeOf` with the digit filter |
| `tests/detective-view.test.ts` | The demo panel's state as a pure function: open, tab, turn picked, and where it sits (beside the chat or in place of it) |
| `tests/guide.test.tsx` | The demo guide and its panel: the guide in each state (the six, in progress, code step, complete, stopped), its dictionaries, the dock around it, and what a click does to the page and the chat machines. The script transitions themselves are in `tests/chat.machine.test.ts` |
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
- **The guide does not follow the model.** It offers the script's lines in order; the assistant may not ask for the code, or may ask for something else, where the script expects. Each script chosen creates a conversation (30 per hour per address in production), and two scripts that share a customer need "Reset demo" between them ([limitations](../../docs/limitations.md)).
- **No "assistant online" dot** on the launcher: nothing tells the client that the assistant is up.
- **No trusted-proxy handling.** `X-Forwarded-For` is the address of the connection to this server. Behind a TLS-terminating proxy every customer would share one rate-limit bucket until this server is taught to trust that proxy.
- **No CSP and no self-hosted fonts.** The fonts load from Google Fonts; offline, the fallback stacks apply.
- **The login in the Navbar and the legal links are decorative**, as the design system says: there is no account, session or legal page behind them.
