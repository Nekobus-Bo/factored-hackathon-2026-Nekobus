# Project documentation

AI-first customer service system for banking — Factored AI & Data Hackathon 2026.

> **TODO (phase 0):** simulated fintech name, team members and repository link.

## How to read this if you are a judge

In this order, about 15 minutes:

1. **[00-problem.md](00-problem.md)** — which workflow we chose, why, and what we left out on purpose.
2. **[adr/0001](adr/0001-cheap-llm-specialized-encoder.md)**, **[adr/0002](adr/0002-config-code-boundary.md)** and **[adr/0003](adr/0003-deterministic-vs-ai.md)** — the three decisions that shape the system.
3. **[evaluation.md](evaluation.md)** — how we prove it works: baseline, suite, metrics and results.
4. **[limitations.md](limitations.md)** — what does not work, what is missing, what we would do next.
5. **[runbook.md](runbook.md)** — how to run it on your machine in under 10 minutes.

## Full index

| Document | Contents |
|---|---|
| [00-problem.md](00-problem.md) | Problem, users, workflow, scope, KPIs |
| [data.md](data.md) | Sources, contracts, quality, splits, labeling |
| [labeling-rubric.md](labeling-rubric.md) | Guidelines and taxonomy for human-written test sets |
| [evaluation.md](evaluation.md) | Metrics, failure taxonomy, protocol, results |
| [security-privacy.md](security-privacy.md) | Threat model, PII, encryption, audit |
| [limitations.md](limitations.md) | Known limits and future work |
| [runbook.md](runbook.md) | Installation, operation and demo |
| [../AGENTS.md](../AGENTS.md) | Conventions for working in the repository |

## Architecture decision records

| # | Decision | Status |
|---|---|---|
| [0001](adr/0001-cheap-llm-specialized-encoder.md) | Cheap generic LLM + small specialized encoder | Accepted |
| [0002](adr/0002-config-code-boundary.md) | Boundary between configuration and code | Accepted |
| [0003](adr/0003-deterministic-vs-ai.md) | What AI decides and what deterministic logic decides | Accepted |
| [0004](adr/0004-trust-boundary.md) | Trust boundary and threat model | Accepted |
| [0005](adr/0005-application-level-encryption.md) | Application-level encryption with blind index | Accepted |
| [0006](adr/0006-single-postgres-pgvector.md) | A single PostgreSQL with pgvector, plus Redis | Accepted |
| [0007](adr/0007-no-llm-biometrics.md) | No LLM-based biometric verification | Accepted |
| [0008](adr/0008-cpu-inference-deployment.md) | CPU inference and private-environment deployment | Accepted |
| [0009](adr/0009-monorepo-structure.md) | Monorepo structure and service names | Accepted |
| [0010](adr/0010-model-selection-calibration-harness.md) | Model selection and calibration harness | Accepted |
| [0011](adr/0011-hybrid-seed-dataset-ingest.md) | Hybrid seed: synthetic demo identities plus the delivered dataset through a pluggable ingest | Accepted |
| [0012](adr/0012-decision-points.md) | Decision points: calibrated local models decide, the engine applies, banking-core disposes; the model server | Accepted (minimum freeze scope) |
| [0013](adr/0013-front-ends-bff-takeover.md) | Front ends, their BFFs and the human takeover | Accepted |
| [0014](adr/0014-distilbert-intent-backend.md) | Pooled DistilBERT as the decision backend, locale-keyed thresholds, hint and clarification effects | Accepted |
| [0015](adr/0015-gcp-cloud-run-terraform.md) | The presentation environment on Google Cloud Run, defined in Terraform | Accepted |
| [0016](adr/0016-banking-core-states-the-next-step.md) | banking-core states the next step: every tool result carries an advisory flow hint | Accepted |

Every ADR follows the same format: context, decision, options considered, trade-off analysis, consequences and action items.
