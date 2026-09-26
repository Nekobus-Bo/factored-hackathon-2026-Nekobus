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
| Policy rules, thresholds and mode (blocking / flag) | The trust boundary and authentication |
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

1. [ ] Configuration tables with versioning and schema validation
2. [ ] Back-office UI for policies, thresholds and templates
3. [ ] Adversarial scenario: malicious configuration attempting to disable verification
4. [ ] Demo script for the second workflow via configuration, with the diff on screen
