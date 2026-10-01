# ADR-0002: Boundary between configuration and code

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

A bank cannot wait for a deployment cycle to change a risk threshold, add a response or cover a new customer service case. We want an engine where **behavior is data**, not one where every workflow is programmed.

The approach carries two risks: that "everything is configurable" becomes an unverifiable claim, and that configuration turns into a way around the security controls.

## Decision

An explicit, verifiable boundary:

| **Configuration** (database, edited from the back office) | **Code** (typed contract, reviewed) |
|---|---|
| Intents and slots of the classification schema | The tools: real banking operations |
| Knowledge snippets and their retrieval | The policy engine and its evaluator |
| Message templates, forms and buttons | The verification state machine |
| Policy rules, thresholds and amount mode (handoff required / recommended) | The trust boundary and authentication |
| Which tools each state enables | The message block schema |
| Agent queue priority | The audit log |

**Rule:** a new workflow that recombines existing tools is pure configuration. One that needs a new banking operation needs code, and that operation ships with its contract, its tests and its entry in the policy engine.

**Security constraint:** configuration **cannot override policy**. Configurable behavior is injected as model context; authorization is evaluated in `banking-core` against the policy table. A configuration string saying "skip identity verification" has no effect, because the model is not what authorizes (see [ADR-0003](0003-deterministic-vs-ai.md) and [ADR-0004](0004-trust-boundary.md)). All configuration is schema-validated before it is saved.

## Options considered

### Option A: one hand-coded workflow

**Pros:** shortest path to a polished demo.
**Cons:** it is a script, not a product; every new case is a sprint; the "production-ready" argument does not hold.

### Option B (chosen): generic engine with an explicit boundary

**Pros:** business changes bypass engineering; generality can be demonstrated live; separates responsibilities between risk/operations and engineering.
**Cons:** more moving parts up front; configuration needs validation; flexibility can be mistaken for laxity if the boundary is not written down.

### Option C: everything in the prompt

**Pros:** maximum apparent flexibility.
**Cons:** the prompt as a configuration surface is also an attack surface; no validation, no versioning; impossible to audit. Rejected.

## Trade-off analysis

We pay up-front complexity for two things the rubric rewards: **controlled automation** and **production thinking**. The written boundary is what keeps flexibility from reading as loss of control: anyone can check what can change without engineering and what cannot, and why.

## Consequences

**Becomes easier:** adding a second workflow during the demo without touching code; letting operations tune thresholds; versioning behavior.

**Becomes harder:** every configurable surface needs a schema and validation; we must prove configuration cannot escalate privileges (adversarial scenario in the suite).

**To revisit:** if a case appears where the separation feels artificial, it gets documented in `limitations.md` rather than quietly breaking the rule.

## Action items

1. [x] Configuration tables with versioning and schema validation (policy config and tool policy; see the amendment of 2026-09-29 for what exists)
2. [ ] Back-office UI for policies, thresholds and templates (policies and thresholds: done, the Guardrails screen of `apps/web-backoffice`, [ADR-0013](0013-front-ends-bff-takeover.md); templates: pending, they are not a configuration table yet)
3. [ ] Adversarial scenario: malicious configuration attempting to disable verification
4. [ ] Demo script for the second workflow via configuration, with the diff on screen (the back-office Guardrails screen or the admin API call, [runbook](../runbook.md) demo step 5; the scripted demo is pending)

## Amendment 2026-09-29: what "a workflow by configuration" means

**Context.** The decision promises that a workflow which recombines existing tools is pure configuration, and the demo shows a second workflow added live. Until now that was not true: the tool matrix (`config.tool_policy`) had no versioning, no audit and no API, and the read tools were enabled at seed, so nothing could be added.

**Decision.** The rule above stands, and its meaning is now concrete and checkable:

- **A workflow by configuration is a combination of tools already in the catalog, enabled in the versioned tool policy.** `config.tool_policy` holds one document per version (`version`, `is_active`, and a `matrix` from each tool to the verification states that enable it, `[]` meaning disabled), like `config.policy_config`. The active version is read on every authorization, with no cache, so a change applies to the next tool call in every process.
- **Configuration only restricts the code floor.** `CODE_FLOOR` in `packages/contracts` stays the ceiling ([ADR-0003](0003-deterministic-vs-ai.md) Appendix A). A change naming a state outside a tool's floor, or an unknown tool, is refused with a 422 that names the tool and the states; nothing is clamped or partly applied. A stored version that somehow exceeds the floor is refused at authorization time (`CODE_FLOOR_VIOLATION`).
- **The seed can only disable.** `POLICY_SEED_DISABLED_TOOLS` (default `account.get_summary`) lists the tools that start with no state enabled; it is read once, when the table is empty, and again only by the demo reset. `transaction.list_recent` stays enabled because the compromised-card workflow needs it to identify the disputed charge.
- **Every change is audited.** `PUT /v1/admin/tool-policy` (same bearer auth as `/v1/admin/policy-config`) saves the tools it names as a new active version, in the same transaction as an `admin.tool_policy.updated` audit row holding the version, the previous version and each tool's before and after states (no PII). If the audit row cannot be written, the version is not saved. Seeding version 1 is audited the same way (actor `system`, `source: seed`), as a change from the catalog defaults. `GET /v1/admin/tool-policy` returns the policy in force and the floor. Writers are serialized, and at most one version can be active.
- **A disabled tool is a normal refusal.** The call is refused as `STATE_NOT_ALLOWED`, audited like any refused call with the flag `TOOL_DISABLED`, and the orchestrator relays it as it does every refusal ("explain it plainly"). The model is still offered every catalog tool: the orchestrator does not read the policy, so a disabled tool is found by trying it.
- **The demo is reproducible.** `POST /v1/admin/demo/reset-fixtures` returns the tool policy to the seed, as a new version only if it differs, and reports `tool_policy_version` and `tool_policy_changed`.

**What still needs code.** A workflow that needs an operation the catalog lacks (a new tool) ships with its contract, its implementation, its policy-engine entry, an FSM state that enables it and a scenario covering it, including the case where it must not run (AGENTS.md).

**Consequences.**

- *Easier:* the second workflow is one audited change, reversible by another, with no deployment; the evaluation runner sets a scenario's tools the same way (`initial_state.tool_policy`), so a scenario states the configuration it needs.
- *Harder:* the tool policy is now a security-relevant table. Whoever holds the admin token can switch tools off, including `handoff.create`: the floor is a ceiling, not a minimum ([limitations](../limitations.md)).
- *Still pending:* the other surfaces the table above lists (intents, message templates, queue priority), which are not configuration tables yet.
