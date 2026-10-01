# AGENTS.md

Conventions for this repository. Written so that anyone — person or agent — can work here without reading everything first.

If anything here contradicts `docs/`, `docs/` wins: this file holds working rules, that folder holds the reasoning.

## What this is

AI-first customer service system for banking. Main workflow: **compromised card**, with two outcomes — automatic card block, and human handoff for the dispute. Full context in [docs/00-problem.md](docs/00-problem.md).

## Structure

`apps` + `packages` monorepo. **If it deploys it goes in `apps/`, if it is imported it goes in `packages/`.** See [ADR-0009](docs/adr/0009-monorepo-structure.md).

| Path | What it is |
|---|---|
| `apps/banking-core` | Trusted zone. Data, tools, policies, FSM, audit. The only service with database credentials |
| `apps/orchestrator` | Untrusted zone. Chat, session, LLM, PII masking |
| `apps/encoder` | Model server: serves the local decision, extraction and embedding models. Runs on CPU, inside the private network |
| `apps/web-client` | Simulated fintech and chat bubble |
| `apps/web-backoffice` | Queue, handoff, guardrails, metrics |
| `packages/contracts` | Tools, message blocks and policies. Source of truth for types. Python package plus a TypeScript entry (`@pattern-blue/contracts`, Zod, in `ts/`) for the front ends, checked against the exported JSON Schemas |
| `packages/encoder` | Intent, slots, PII model logic. Runs on CPU |
| `packages/retrieval` | Knowledge base and hybrid index |
| `packages/design-tokens` | Design tokens and `pb-*` component CSS, synced from the design-system artifact. Bun workspace package; generated `dist/` is committed |
| `data/` | `raw → staging → curated`, plus `eval` |
| `eval/` | Scenarios, replay recordings, runner |
| `infra/` | Compose, database init, deployment |
| `tools/` | Development utilities |
| `demo/` | Walkthrough scripts and prerecorded sessions for replay mode |
| `reports/` | Versioned evaluation, calibration, and data quality evidence |

Every app has the same internal shape: `src/`, `tests/`, `Dockerfile`. **Symmetry is half of readability**: an app that looks different inside has to be learned separately.

## Non-negotiable rules

These come from the ADRs. A change that violates one is rejected no matter how well it works:

1. **`orchestrator` never touches the database.** It only calls `banking-core` tools through the contract. If you need new data, add a tool, not a query.
2. **The model proposes, `banking-core` disposes.** The FSM and the policy engine decide; the LLM never does. ([ADR-0003](docs/adr/0003-deterministic-vs-ai.md))
3. **Policies do not live in the prompt.** A guardrail inside a prompt is not a guardrail. ([ADR-0002](docs/adr/0002-config-code-boundary.md))
4. **No write is taken on faith.** Every action returns a receipt re-read from the database, and accepts an idempotency key.
5. **No PII leaves unmasked** toward the LLM provider. ([docs/security-privacy.md](docs/security-privacy.md))
6. **Thresholds and behavior are configuration**, not constants in code. What is in `.env` is only the initial seed.
7. **Nothing promised in `docs/` that does not exist.** If a command or path is not there yet, mark it pending and fail with an explicit message.

## Workflow

```bash
make help     # list available commands
make demo     # one-command local startup: build, warmup, up, seed, smoke
              # (replay recordings are pending: talking to the assistant needs an LLM key in .env)
make up       # services
make seed     # seed from data/raw
make smoke    # installation check
make eval     # baseline vs proposed system
make design-tokens-check   # TypeScript side: design tokens vs their source, typecheck, tests (needs Bun)
make web-check             # TypeScript side: @pattern-blue/contracts (incl. drift vs the exported JSON Schemas) and each apps/web-*: typecheck, tests (needs Bun)
```

Not every target is implemented yet; `make help` lists what exists and pending targets fail with an explicit message.

`make` is the single entry point. If you add a script, expose it as a target.

## When making changes

**Before writing code:** if the task changes an architectural decision, write or update the ADR first. Half a page: context, options, decision, consequences.

**When adding a tool:** schema in `packages/contracts/src/contracts/tools/` → implementation in `apps/banking-core/src/*/tools/` → entry in the policy engine → FSM state that enables it → scenario in `eval/scenarios/` covering it, including the case where it must **not** run.

**When adding a workflow:** first check whether it is configuration only. If it needs code, that means a new banking operation is required, and that ships with a contract and tests.

**When adding a decision point:** artifact entry through `make calibrate TASK=decision-points` (then `make calibration-verify`; guide in `tools/calibrate/README.md`, [ADR-0012](docs/adr/0012-decision-points.md) Appendix F) → effects entry in `apps/orchestrator/config/decision_effects.yaml` (start in `shadow`) → a scenario covering it, including the case where it must abstain → flip to `enforce` in its own PR with the report attached and `docs/limitations.md` updated.

**When touching prompts or the model:** run `make eval` before and after. A prompt change without evaluation is not an improvement, it is a bet.

**When closing a task:** update `docs/limitations.md` if something was left half done. A declared gap is worth more than a discovered one.

## Languages

- **Code, paths, names, comments, commit messages and documentation:**
  English. This holds regardless of the language used to talk to whoever is
  writing the code: a conversation in Spanish still produces English
  artifacts.
- **Internal system instructions (prompts, schemas, policies):** English.
- **Evaluation scenario content:** Spanish, Portuguese and English — those are test data, not documentation, and they are not translated.
- **Customers are served in their own language.** Spanish, Portuguese and English are supported; metrics are reported per language.

## Commits and branches

- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Scope with the app or package name: `feat(banking-core): card.block tool`.
- Branches: `feat/<short-thing>`, off `main`.
- Small, frequent commits. The history gets reviewed: it should show construction, not a final dump.

## Data

The organization's dataset is **not versioned**. It goes in `data/raw/` locally and is in `.gitignore`. The files in `reports/` **are** versioned: they are the evidence behind the metrics we report.

## Things we do not do, on purpose

LLM-based biometric verification ([ADR-0007](docs/adr/0007-no-llm-biometrics.md)), autonomous dispute resolution, and any shortcut that gives the model authority. If a task seems to ask for one of these, stop and ask.

## Pending: rename the amount modes

**PENDING, not done.** If time allows before the freeze, rename the stored policy amount modes `flag` and `block` to `recommend` and `require`: the DB values (with a migration), the admin API, the env seeds (`POLICY_SEED_AMOUNT_MODE`), the eval scenarios and the docs. Today the docs only relabel them ("handoff recommended" for `flag`, "handoff required" for `block`, see [ADR-0003](docs/adr/0003-deterministic-vs-ai.md)), because `block` does not block anything: `card.block` is never refused for amount, the mode decides whether a handoff is required. Until the rename lands, keep writing `flag` and `block` in code and data.

## Project close

Submission: **October 5, midnight Colombia time**. Code freeze the day before at noon; what remains is documentation, slides (4–6), a 3-minute video and a clean-machine check. Checklist at the end of [docs/runbook.md](docs/runbook.md).
