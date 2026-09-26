# ADR-0009: Monorepo structure and service names

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

This is a polyglot monorepo: two Python services, two TypeScript frontends, a model package, data and evaluation. It is read by people who did not write it — the judges — and with little time.

The criterion is not elegance but **recognition**: a developer understands a repository because it resembles others they have seen. The concrete test we set: someone who has never opened it should be able to answer in 30 seconds **what gets deployed and where the code for each thing lives**.

## Decision

**`apps/` + `packages/`**, the most widespread workspace convention.

- `apps/` — **everything that deploys**, regardless of language: `banking-core`, `orchestrator`, `web-client`, `web-backoffice`.
- `packages/` — **everything that is imported**: `contracts`, `encoder`, `retrieval`, `design-tokens`.
- `data/` — medallion layers: `raw → staging → curated`, plus `eval`.
- `infra/`, `tools/`, `eval/`, `reports/`, `docs/`, `demo/` — supporting material, out of the root.

One-line rule: **if it deploys it goes in `apps/`, if it is imported it goes in `packages/`.**

### Service names

The two services are named **`orchestrator`** and **`banking-core`**.

We rejected calling the first one `bff`. The Backend For Frontend pattern describes a thin adaptation layer between one UI and several APIs, and this service does something else: it holds the session, coordinates the loop with the model, invokes the encoder, masks PII and translates all of it into tool contract calls. More importantly, **its reason to exist is not serving the frontend, it is being on the untrusted side of the boundary** ([ADR-0004](0004-trust-boundary.md)), and the name suggested otherwise. Finally, it serves two frontends, so "per frontend" no longer applies.

The pair `orchestrator` / `banking-core` communicates the architecture without opening a document: one coordinates, the other owns the data.

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
- `packages/encoder` moves to `apps/encoder` if we decide to serve it as a separate process.
- `web-client` and `web-backoffice` merge into one app if a single person owns the frontend; in that case `packages/design-tokens` stops making sense.

## Action items

1. [ ] Create the tree and move what exists
2. [ ] `packages/contracts` with type generation for Python and TypeScript
3. [ ] Same internal shape across all apps (`src/`, `tests/`, `Dockerfile`)
4. [ ] `infra/compose` with a development file and a production override
5. [ ] `AGENTS.md` with the conventions derived from this structure
6. [ ] CI running `make up` and `make smoke` on every push
