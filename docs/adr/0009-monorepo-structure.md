# ADR-0009: Monorepo structure and service names

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

This is a polyglot monorepo: two Python services, two TypeScript frontends, a model package, data and evaluation. It is read by people who did not write it — the judges — and with little time.

The criterion is not elegance but **recognition**: a developer understands a repository because it resembles others they have seen. The concrete test we set: someone who has never opened it should be able to answer in 30 seconds **what gets deployed and where the code for each thing lives**.

## Decision

**`apps/` + `packages/`**, the most widespread workspace convention.

- `apps/` — **everything that deploys**, regardless of language: `banking-core`, `orchestrator`, `encoder`, `web-client`, `web-backoffice`.
- `packages/` — **everything that is imported**: `contracts`, `encoder`, `retrieval`, `design-tokens`.
- `data/` — medallion layers: `raw → staging → curated`, plus `eval`.
- `infra/`, `tools/`, `eval/`, `reports/`, `docs/`, `demo/` — supporting material, out of the root.

One-line rule: **if it deploys it goes in `apps/`, if it is imported it goes in `packages/`.**

### Service names

The backend deployables are named **`banking-core`**, **`orchestrator`**, and **`encoder`**.

We rejected calling the orchestrator `bff`. The Backend For Frontend pattern describes a thin adaptation layer between one UI and several APIs, and this service does something else: it holds the session, coordinates the loop with the model, invokes the encoder service, masks PII and translates all of it into tool contract calls. More importantly, **its reason to exist is not serving the frontend, it is being on the untrusted side of the boundary** ([ADR-0004](0004-trust-boundary.md)), and the name suggested otherwise. Finally, it serves two frontends, so "per frontend" no longer applies.

The **`encoder`** separation decouples model serving: `packages/encoder` keeps model logic, intent/slot schemas, and inference utilities, while `apps/encoder` is a thin HTTP server serving CPU inference locally.

The pair `orchestrator` / `banking-core` communicates the architecture without opening a document: one coordinates, the other owns the data.

The frontends are **`web-client`** and **`web-backoffice`**. The metrics panel is a section of `web-backoffice`, not an independent app or separate port.

## Options considered

### Option A (chosen): `apps/` + `packages/`

| Dimension | Assessment |
|---|---|
| Recognition | High: de facto workspace convention |
| Polyglot fit | Good: the bucket assumes no language |
| Adoption cost | Low |

**Pros:** a single list of deployables; `packages/contracts` gets its own obvious home; workspace tooling understands it without extra configuration.
**Cons:** the vocabulary comes from the JavaScript ecosystem and someone may read it as biased in a mostly-Python repository.

### Option B: `services/` + `libs/`

**Pros:** natural vocabulary for backend developers.
**Cons:** "service" carries the idea of a server process, so frontends do not fit and end up in a third bucket. That was the flaw in the first draft: `services/` for Python and `web/` for the frontend forced you to look in two places to know what deploys.

### Option C: domain-oriented (`identity/`, `cards/`, `disputes/`)

**Pros:** all the code for a capability lives together; scales very well across teams.
**Cons:** requires stable domain boundaries. With the domain still being discovered and nine days ahead, this is the one we would most likely end up reorganizing halfway through.

## Trade-off analysis

The real axis is **readability for an outside reader with little time**, not development efficiency: at this scale all three options are equally workable. Option A wins because it reduces to a single question — does it deploy or is it imported? — what the others require project knowledge to answer.

The accepted cost is vocabulary: JavaScript-flavored names in a repository with more Python than TypeScript. Minor next to having one single list of deployables.

## Consequences

**Becomes easier:** finding your way without a guide; adding a new deployable without debating where it goes; sharing contracts between Python and TypeScript from a place with its own name.

**Becomes harder:** internal symmetry across apps has to be maintained, because readability depends on all of them having the same shape; and the discipline of keeping the root clean has to hold.

**To revisit:**
- Encoder served as a separate process: decided. `packages/encoder` keeps model logic and schemas, while `apps/encoder` is deployed as a thin server.
- Merging `web-client` and `web-backoffice`: deferred until the frontends are designed. If consolidated, `packages/design-tokens` would no longer be needed.

## Action items

1. [ ] Create the tree and move what exists
2. [ ] `packages/contracts` with type generation for Python and TypeScript
3. [ ] Same internal shape across all apps (`src/`, `tests/`, `Dockerfile`)
4. [ ] `infra/compose` with a development file and a production override
5. [ ] `AGENTS.md` with the conventions derived from this structure
6. [ ] CI running `make up` (⚠️ pending) and `make smoke` (⚠️ pending) on every push

## Amendment 2026-09-29: the TypeScript workspace, the front-end stack and the design tokens

**Context.** The decision says where TypeScript code lives, not how it is built. The front ends and their shared visual primitives now start, and the design system already exists as a published Claude Artifact.

**Decision.**

- **A Bun workspace at the root** covers the TypeScript side: `package.json` with `workspaces: ["packages/*", "apps/*"]` and a committed `bun.lock`. The entries are globs on purpose: Bun skips a directory that has no `package.json` (every Python package and app), but a workspace named in full without one is an error (`Workspace not found`). `apps/web-client` and `apps/web-backoffice` join by adding their own `package.json`. Python stays on uv; the two workspaces share the tree, not the tooling.
- **The front-end stack** for `web-client` and `web-backoffice`: Bun with its own HTML and CSS bundler (no Vite), React, TypeScript, Zod for what crosses the contract, XState v5 (a global machine for the session and the theme, local machines per component) and Zag.js / Ark UI for accessible headless parts.
- **`packages/design-tokens` is sourced from the design-system artifact** ([link](https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV)), which stays the source of truth. `src/` holds verbatim copies of its `tokens.json` and `components/bundle.css`; a Bun script generates `dist/` (`tokens.css`, `tokens.ts`, `fonts.html`), which is committed so apps and CI need no build step. `make design-tokens-check` runs in CI and fails when `dist/` drifts from `src/`, when a component reads an undefined variable, or when the dark and light themes stop defining the same variables. Details: [packages/design-tokens/README.md](../../packages/design-tokens/README.md).

**Consequences.**

- *Easier:* both front ends share one look and one theme mechanism (`data-theme` on `<html>`), and a token that a component needs but nobody defined is a failing test, not a visual bug found in the demo.
- *Harder:* CI has a second toolchain, the sync from the artifact is manual, and the fonts come from Google Fonts, a network dependency of the demo ([limitations](../limitations.md)).
- *Unchanged:* the "to revisit" note above. If the two front ends merge, the package can be inlined; nothing here depends on there being two.

## Amendment 2026-09-30: `lab/`, the exploratory sandbox

**Context.** Dataset exploration and model comparisons (zero-shot, fine-tuned, LLM-generated data) are written as marimo notebooks. They neither deploy nor are imported, so neither `apps/` nor `packages/` fits, and `tools/` holds runnable utilities with tests, which notebooks are not.

**Decision.** A top-level `lab/` holds the notebooks (`lab/notebooks/<type>__<subject>.py`) and their written findings. It is its own uv project (`lab/pyproject.toml`), so its heavy, fast-moving dependencies stay out of the workspace lock. `make lab` opens it. Notebooks read the organization's dataset from `data/raw/factored/` (or `DATA_DIR`), store no outputs, and write anything derived from the data or from LLM calls to ignored paths only (`data/staging/`, `lab/.cache/`, `lab/profiling/out/`).

**Consequences.**

- *Easier:* exploration has a home that does not dilute what deploys, and its findings sit next to the notebooks that produced them.
- *Harder:* the root gains one more directory, and `lab/` is excluded from ruff and CI, so a notebook can break unnoticed. Nothing under `apps/` or `packages/` may import from it. A result that matters moves out: to `tools/` with a `make` target and tests, and its evidence to `reports/`.
