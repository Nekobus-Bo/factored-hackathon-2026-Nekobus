# contracts

Typed contracts for Pattern Blue banking tools, envelopes, and policies.

Source of truth for tool schemas, verification states, and common request/response envelopes across `banking-core` and `orchestrator`.

The package has two entries that never import each other:

| Entry | Where | Consumers |
|---|---|---|
| Python (`contracts`, Pydantic) | `src/contracts/`, `tests/`, `schemas/` | `banking-core`, `orchestrator`, `encoder`, the eval runner |
| TypeScript (`@pattern-blue/contracts`, Zod) | `ts/` | `apps/web-client`, `apps/web-backoffice` and their servers |

The Python models stay the source of truth. The TypeScript entry mirrors them and is checked against them.

## TypeScript entry: `@pattern-blue/contracts`

A private Bun workspace member (`packages/*` in the root `package.json`), imported and never deployed ([ADR-0009](../../docs/adr/0009-monorepo-structure.md)). It holds the Zod schemas of everything that crosses a boundary between a front end, its BFF and the services behind it, with the inferred types exported next to each schema (`FooSchema`, `Foo`).

```json
{ "dependencies": { "@pattern-blue/contracts": "workspace:*" } }
```

```ts
import { parseBlocks, SendMessageResponseSchema, clientBffRoutes, routePath } from "@pattern-blue/contracts";

const answer = SendMessageResponseSchema.parse(await response.json());
const { blocks, unknown } = parseBlocks(answer.blocks); // never throws; `unknown` says what was set aside
const url = routePath(clientBffRoutes.getTranscript, { id: answer.conversation_id }); // /api/conversations/conv_...
```

| File | Exports |
|---|---|
| `ts/common.ts` | `IsoDateTimeSchema`; `ConversationIdSchema`, `HandoffRefSchema`, `SessionRefSchema`, `AgentRefSchema`, `ClientMessageIdSchema`, `MessageTextSchema`, `CountSchema`; `ApiErrorSchema`, `ValidationIssueSchema`, `ERROR_DETAIL`; `AGENT_REF_HEADER` |
| `ts/enums.ts` | The enums that mirror Python: `VerificationStateSchema`, `ToolResultStatusSchema`, `ReasonCodeSchema`, `ResourceStateSchema`, `HandoffReasonSchema`, `HandoffPrioritySchema` (+ `HANDOFF_PRIORITY_ORDER`), `DepartmentSchema`, `HandoffStatusSchema`, `TraceEventKindSchema`, `TraceEventStatusSchema` |
| `ts/blocks.ts` | `TextBlockSchema`, `ReceiptBlockSchema`, `HandoffBlockSchema`, the union `MessageBlockSchema` (discriminated on `type`), `ReceiptSchema`, `HandoffSummarySchema`, `JsonValueSchema`, `RawBlocksSchema`, `BLOCK_TYPES`, `parseBlocks` |
| `ts/trace.ts` | The detective-mode turn trace (ADR-0019): `TurnTraceSchema`, `TraceEventSchema` and one detail schema per event kind (`EncoderDetailSchema`, `MaskingDetailSchema`, `DecisionsDetailSchema`, `LlmCallDetailSchema`, `ToolCallDetailSchema`, `BlocksDetailSchema`) |
| `ts/orchestrator-chat.ts` | The customer chat API, with the `agent` role and the `takeover` object: `LangSchema`, `TranscriptRoleSchema`, `CreateConversation*`, `SendMessage*` (with the optional `trace`), `TranscriptResponseSchema`, `InboxResponseSchema`, `CapabilitiesResponseSchema`, `orchestratorChatRoutes` |
| `ts/orchestrator-agent.ts` | The agent API (human takeover): `AgentTranscriptResponseSchema`, `TakeoverRequestSchema`/`TakeoverResponseSchema`, `AgentMessage*`, `SessionConversationResponseSchema`, `orchestratorAgentRoutes` |
| `ts/banking-admin.ts` | The banking-core admin API: `HandoffItemSchema`, `HandoffDetailSchema`, `HandoffListQuerySchema`, `ClaimHandoffRequestSchema`, `MetricsQuerySchema`/`MetricsResponseSchema`, `PolicyConfig*`, `ToolPolicy*`, `DemoResetResponseSchema`, `bankingAdminRoutes` |
| `ts/bff-client.ts` | `clientBffRoutes`: the six `/api` routes of `apps/web-client` |
| `ts/bff-backoffice.ts` | `backofficeBffRoutes`: the `/api` routes of `apps/web-backoffice`; `LoginRequestSchema`, `SessionResponseSchema`, `BackofficeHandoffDetailSchema`, `ClaimHandoffResponseSchema` |
| `ts/route.ts` | `defineRoute`, `routePath`, `toQueryString`, `queryFromSearchParams`, `patternParams` |
| `ts/demo-scripts.ts` | **Not a network contract** (see below): `DEMO_SCRIPTS`, `getScript`, `DRAFT_AGENT_LINE`; the customer-side matcher `startScript`, `nextClientState`, `scriptVerified`, `currentStep`, `isCodeShaped`; the back-office matcher `suggestAgentLine`, `matchesMaskedLine` |

Conventions:

- **A route is data.** Each `*Routes` table lists `method`, `pattern` (`:name` segments, the syntax `Bun.serve` uses), the schemas of the params, query, body and response, and the success status. A BFF registers exactly the routes of its table and validates with those schemas; `ts/tests/routes.test.ts` pins every table to a fixed list of routes, so adding one is a visible change.
- **Requests are strict, responses strip.** A request schema rejects a key it does not name, so a BFF never forwards an arbitrary body. A response schema drops what it does not name: parse, then send on the parsed value, and an agent identity or a debug field never reaches the browser.
- **Blocks stay raw on the wire.** `blocks` in an HTTP response is `RawBlock[]`. Pass it through `parseBlocks`: it keeps the blocks it knows, in order, and reports the others in `unknown` (`reason: "unknown_type"` or `"invalid"`, with the index and the raw value). A block type added on the server degrades one message and does not blank the chat.
- **Ids are opaque.** A conversation id is `conv_` plus 32 hex digits today, not a UUID; the schemas check only that an id is safe to put in a URL path.

### Demo scripts (`ts/demo-scripts.ts`): not a contract

The one thing in this entry that crosses no boundary and has no Python model, so the drift test does not cover it. It is here only because two apps must agree on the same lines to the character, and this package is the one both already import (Docker context, `bun.lock`, `WEB_PACKAGES`, CI). It is a demo aid, never a bank feature.

It holds the team's six walkthrough scripts: a stable `id` (`stolenCard`, `chargeBelowThreshold`, `chargeAboveThreshold`, `fakeAdmin`, `ambiguousSlang`, `mixedLanguages`), the market (`locale`, and its `lang`), the customer's `steps` in order (a `message` with its exact text, or the `code` step where the customer types the one-time code the inbox shows) and, for the two unrecognized-charge scripts only, the agent's line. That line is a **draft** (`DRAFT_AGENT_LINE`, the only place it lives): the team's scripts carry no agent lines yet. Labels and notes are not here: they are text for people and live in each app's dictionaries, keyed by the ids.

Two pure matchers, with no React, no state machine and no clock:

| Side | Reads | Rule |
|---|---|---|
| Customer app (`nextClientState`, `scriptVerified`; the guide in `apps/web-client`, which keeps the state in its chat machine) | The raw text the customer sends, and the script's state `{scriptId, step, status}` | The identical line advances once; anything else stops the script for that conversation, for good. At the code step one or more messages of 4 to 8 digits (one space or hyphen allowed inside: `123 456`, `123-456`, the shapes the orchestrator's masker also takes for a code) belong to the script and leave it there until the caller says the chat proved the verification (`scriptVerified`); other text stops it. `{ retry: true }` marks a resend of a message already counted, so a retry never advances twice |
| Back office (`suggestAgentLine`) | The **masked** transcript (`[DOC_1]`, `[OTP_1]`) | The script is recognised by the customer's first message. Each `[TYPE_n]` stands for any stretch of the line, of any type, and the rest is literal. At the code step one or more messages containing `[OTP_n]` count. It returns the agent line only when the customer sent every line of the script, no more, and no agent has written yet |

The back-office match depends on what the masker really leaves: a code typed with no challenge pending stays in clear (`docs/limitations.md`) and the suggestion does not appear. Tests: `ts/tests/demo-scripts.test.ts`.

### Drift test

`ts/tests/drift.test.ts` reads the JSON Schemas that `export_schemas.py` writes and Python's own test pins byte for byte (`schemas/`), never the Python source:

- **Blocks.** `schemas/blocks/message_block.json` against `TextBlockSchema`, `ReceiptBlockSchema` and `HandoffBlockSchema`, recursing into the receipt, the handoff summary and the open questions: the same field names, the same required fields, the same enum values, the same length, minimum and pattern limits, and the same members of the discriminated union. The one accepted difference is `type`, which Python defaults and Zod requires because it discriminates. A definition Python exports with no Zod counterpart fails.
- **Trace.** `schemas/trace/turn_trace.json` against `TurnTraceSchema` and each of its definitions, the same way. Zod writes an unconstrained nullable field as `type: ["string", "null"]` and pydantic as an `anyOf` with null: the comparison reads both as nullable.
- **Enums.** Every enum in `ts/enums.ts` against every exported schema that defines it (`VerificationState` in `tools/otp_verify.output.json`, `ReasonCode` in `envelope/tool_result.json`, `HandoffPriority` in the block schema, and so on). An enum added to `enums.ts` without a Python source in the table fails.

**Known gap.** The drift test does not cover the HTTP shapes of the orchestrator chat and agent APIs and of the banking-core admin API. Those models live in the apps (`orchestrator/chat/routes.py`, `banking_core/api/routes_admin.py`), which this package cannot import, so no JSON Schema of them is exported and the Zod side is written from the source by hand. The enums used only there (`Lang`, `AmountMode`, the audit decision) are checked by reading, not by a test.

### Regenerating

When a Python contract changes:

```bash
uv run export-contracts-schemas   # rewrites packages/contracts/schemas/, deterministically
uv run pytest -q packages/contracts   # the committed schemas must equal a fresh export
make web-check                    # the drift test names what the Zod side must follow
```

Then change the schema in `ts/`, and commit the Python change, the regenerated `schemas/` and the `ts/` change together. A new block type also needs a Zod block, an entry in `MessageBlockSchema` and a renderer in the front ends; until then `parseBlocks` sets it aside.

### Commands

From the repository root (`make` is the single entry point; Bun 1.3 or later):

```bash
make web-check    # bun install --frozen-lockfile, then typecheck and bun test for this package and each apps/web-* package
```

Inside the package: `bun run typecheck` (`tsc --noEmit`) and `bun test`. The package has no build step: `exports` points at `ts/index.ts`.

## Python entry

Unchanged: `uv run pytest -q packages/contracts`, `uv run export-contracts-schemas`, `uv run generate-contracts-labels` (or `make generate-labels`). The wheel packages `src/contracts` only; `ts/`, `package.json` and `tsconfig.json` are not part of it.
