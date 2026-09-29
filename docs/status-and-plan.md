# Status and plan (internal)

> Internal working document: where the work stands and how to continue it, from a local machine or by another teammate. It is updated at every milestone. Delete it, or fold what is still true into [limitations.md](limitations.md), before submitting (see the cross-check checklist at the end of [runbook.md](runbook.md)).

**Last update:** 2026-09-29, 11:40 UTC (after #4 merged).

> **History rewritten on 2026-09-29.** The commits made from the cloud session were authored as "Claude"; `main` and `claude/optimistic-feynman-tj7ew9` were rewritten so that they carry Marcelo Mendez as author and no `Co-Authored-By: Claude` line (contents unchanged; Daniela's commit `fea5e9b` and the #1 merge keep their hashes). **If you cloned before that, re-sync:** `git fetch origin && git checkout main && git reset --hard origin/main` (and the same for any branch taken from the rewritten commits). Branches cut from `main` before 2026-09-29, such as `feat/disputes-table-fit`, are not affected.

## 1. Done and merged to `main`

- **#1:** `LLM_REASONING_EFFORT`.
- **#3:**
  - The bug sweep.
  - The design decisions:
    - amount guardrail read from the database;
    - hardened masking, with GPT 6 Luna as the single LLM;
    - one-command `make demo`;
    - second workflow through the versioned tool policy;
    - simulated OTP inbox.
  - ADR-0012 decision points (all in `shadow`), with their calibration harness and seed artifact.
  - The model server for the decision and embedding models.
  - `packages/design-tokens`.
  - The PR description lists every change and the new settings.
- **Design system:** the Claude Artifact "Pattern Blue", https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV, version `1790655197-4dbb`.
  - It is private to its owner until shared from its Share menu.
  - Its tokens and CSS are in `packages/design-tokens/src/`, and its documentation (the rules and every component's markup) is in `packages/design-tokens/reference/`.
  - Components:
    - customer app: ChatBubble, ChatMessage, ReceiptCard, OtpInboxNotice, S2PromoCard;
    - landing: Navbar, Hero, CardVisual, FeatureGrid, HowItWorks, FaqAccordion, Footer, Landing;
    - back office: QueueRow, HandoffCard, PolicyControl, SyncGauge;
    - shared: Button, StatusChip, AlertBanner, Cover.

Tests at the last merge of #3 (the branch now has 1906 passed, 5 skipped in Python, and 112 + 179 + 371 TypeScript tests in `make web-check`):
- `uv run pytest -q`: 1668 passed, 5 skipped.
- evalrunner: 141 passed.
- `make design-tokens-check`: 38 passed.

## 2. The front ends: merged to `main` (#4)

The specification and the HTTP contract between the pieces are in [front-ends.md](front-ends.md). The decisions are in [ADR-0013](adr/0013-front-ends-bff-takeover.md). Each work package below is one branch off `main` and ships with tests.

| WP | What | State | Depends on |
|---|---|---|---|
| F0 | `@pattern-blue/contracts`: Zod schemas for the message blocks and every HTTP surface, a drift test against the exported JSON Schemas, and `make web-check` in CI | **Done** (on this branch, 112 tests) | — |
| F1 | ADR-0013 and the ADR-0004 amendment. banking-core admin routes: handoff queue, detail, claim (audited as the agent), metrics; migration `0008` | **Done** (on this branch, 66 new tests) | — |
| F2 | Orchestrator agent API: reverse index from session to conversation, takeover, agent messages. After a takeover the LLM never sees the conversation again | **Done** (on this branch, 130 new tests) | — |
| F3 | `apps/web-client`: landing plus the chat dock (every content type that exists, the OTP inbox notice, retry, rate limit, the agent after takeover), and its BFF | **Done** (on this branch; tests against a fake orchestrator; the takeover part needs F2's orchestrator to run for real; Dockerfile built and run once by hand) | F0 (F2 for the takeover part) |
| F4 | `apps/web-backoffice`: login, queue, handoff detail with "take the case" and reply, guardrails (thresholds, amount mode, tool matrix, demo reset), metrics, and its BFF | **Done** (on this branch; 371 tests against fake upstreams; Dockerfile built once in the sandbox with an extra CA mount, not as committed) | F0, F1, F2 |
| F5 | Integration: compose services and healthchecks, `make smoke`, both apps in the CI `images` matrix, `TRUSTED_PROXY_HOPS` for the web-client BFF, the runbook's "⚠️ pending UI" marks, `limitations.md` | **Done** (on this branch; run on a live compose stack in the sandbox, with the caveats below) | F3, F4 |

**What F5 verified, and what it could not.** Run in the sandbox, where the model server cannot download PyTorch and the TLS interception needs a CA mounted into image builds:
- Verified: both front-end images build through `docker compose build` exactly as committed (the install step served from the BuildKit cache; a cold-cache install fails with `SELF_SIGNED_CERT_IN_CHAIN` unless the CA is mounted, so it was checked once with a temporary Dockerfile copy that does, nothing committed); the whole stack came up healthy with no `.env`; `make smoke` printed all eight services and the migration; the two `make` dev-server targets served `/healthz` and the page; the demo summary ran against the live stack. A takeover ran end to end through both BFFs with the compose defaults (claim, agent reply masked, which was the behavior then and is not any more, the customer reading it, the queue showing `ASSIGNED`), and a Guardrails save went through the BFF to the admin API. The production images start under the overlay's constraints (read-only root, no capabilities) and the back office refuses the development values.
- Not verified: `make up` itself (its `--build` needs the Python images to build from the committed Dockerfiles, which the sandbox blocks; they were built from temporary copies and the stack was started without `--build`, with the embedding model off); `make demo` from start to finish (it downloads the embedding model); the CI and deploy workflows (only YAML-parsed, never run on GitHub); the images pulled from a registry, and the `linux/arm64` builds; the UI in a browser (no browser here). Do these on the clean-machine check.

**Nothing is in progress in the cloud session.** Everything is merged to `main` (#4, 2026-09-29); no work lives only in a local worktree.

**What is left for the front ends:**
1. Done: merged as #4 on 2026-09-29, with CI green on its last head (Python, TypeScript and the five images, amd64 and arm64).
2. On a real machine, with an LLM key in `.env`: `make demo`, then walk through [runbook.md](runbook.md) section 7 in a browser, in es, pt and en, in light and dark. No browser run against the real stack exists yet; the screens were checked against fake upstreams and the BFFs against the live stack.
3. The clean-machine check of the runbook's cross-check checklist, including the arm64 images (built in CI, never run).
4. Decided and done (2026-09-29): agent text is shown as written. `content` stays masked, in clear, in redis-edge; the text as written is stored encrypted next to it and both transcripts return it; the assistant never sees it. Recorded in [ADR-0013](adr/0013-front-ends-bff-takeover.md) (amendment 2026-09-29, "agent text shown as written") and declared in [limitations.md](limitations.md). It is covered by the orchestrator and back-office tests; the stack was not brought up again with it, so the live takeover walk-through of item 2 should include an agent writing a name.
5. Nice to have, not started: an unread signal on the chat launcher, keeping the conversation across a reload, the "In design" chat content types (quick replies for the ADR-0012 confirm gate, pickers), and the other items in [limitations.md](limitations.md) "Customer app" and "Back-office UI".

**How to continue a work package**, locally or by hand:
1. Read `AGENTS.md`, then [front-ends.md](front-ends.md) ("Decisions", "HTTP contract" and the package's scope section).
2. Branch off `main` as `feat/<short-thing>`.
3. Implement the contract exactly. If the contract is wrong, change [front-ends.md](front-ends.md) first, in the same PR.
4. Validate:
   - Python: `uv run pytest -q` and `uv run ruff check .`.
   - TypeScript: `make web-check` and `make design-tokens-check`.
   - Stack: `make demo`, then walk through [runbook.md](runbook.md) section 7.
5. Update this file's table and [limitations.md](limitations.md).

## 3. Pending, outside the front ends

**Decision 2, hybrid replay/live run modes: paused on 2026-09-29.** What is left:
- **The baseline system for `make eval`.** It does not exist. It needs a decision first: the baseline is "the LLM with the same tools and no policy engine or FSM", but banking-core enforces both server-side. The options are an evaluation-only bypass, refused in production, or another comparison.
- **The `make eval` / `eval-baseline` / `eval-adversarial` targets** (they fail as pending today).
- **An eval compose overlay** with `EVAL_EXPOSE_TURN`, `ALLOW_DEV_OTP_HOOK`, the admin token, the rate limit and a read-only DSN.
- **Replay recordings.** They need the Luna key.
- **Pinning `INGEST_ANCHOR_DATE`.**

**Owned by the teammate:**
- The GPT 6 Luna configuration: `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_REASONING_EFFORT=none`.
- Confirming the `EMBEDDING_REVISION` pin: `make warmup-retrieval` prints the hash.
- Running `uv lock` on a networked machine. The lockfile was edited by hand; `uv lock --check` passes.
- The calibration of the decision points, and the sign-off of ADR-0012 appendix F before any of them moves to `enforce`.
- The six review points on her `lab/` pull request.

**Small and known:**
- The `.env.example` comment above `LLM_MODEL` still names DeepSeek as the default candidate.
- The rename of the amount modes `flag` / `block` to `recommend` / `require` is still to do (AGENTS.md, "Pending").
- In the runbook, the first-run time and download size are TODO, and the clean-machine check is still to do.
- The "TODO at close" list in section 1 of [limitations.md](limitations.md).

**Project close** (AGENTS.md):
- Code freeze on October 4 at noon, Colombia time.
- Submission on October 5 at midnight.
- Still to produce: 4–6 slides and a 3-minute video.

## 4. Running it locally

**Prerequisites:**
- Docker with Compose.
- `uv`.
- Bun 1.3 or later, only for the TypeScript side.

**Commands:**

```bash
make demo                 # the whole stack in replay mode; talking to the assistant needs an LLM key in .env (no recordings yet)
uv run pytest -q          # Python tests; the DB tests create their own disposable bank_test database
make design-tokens-check  # TypeScript: design tokens
make web-check            # TypeScript: contracts and both web apps
make web-client           # the customer app's dev server on the host (make web-backoffice for the back office); needs Bun
```

`make demo` serves the customer chat on http://localhost:5173 and the back office on http://localhost:5174 (login `agent@demo.local` / `demo-only-change-me`, development only).
