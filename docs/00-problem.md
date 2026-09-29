# Problem statement

**Date:** 2026-09-26 · **Submission:** 2026-10-05 · **Status:** phase 0 closed except identity items (name, team, license)

## 1. The business problem

A bank handles a high volume of customer service interactions where the bottleneck is not missing information but the human time spent verifying identity, gathering account context and executing an action that is simple yet irreversible. At the same time, automating badly costs more than not automating at all: an action taken on the wrong account, another customer's data disclosed, or an unwarranted card block carry regulatory and reputational cost that no efficiency gain offsets.

The problem we solve is not "answering questions". It is **deciding safely when to act, when to ask and when to hand the case to a person** — and being able to defend that decision afterwards.

## 2. Users

| User | What they need | How it is measured |
|---|---|---|
| Bank customer | Resolve their problem without waiting for a human, in their own language | Time to resolution, cases closed without escalation |
| Human agent | Receive the case already verified and with context, not a raw transcript | Reading time before they can act |
| Operations / risk | Change policy without waiting for a deployment; audit every decision | Policy change lead time, traceability |

## 3. Chosen workflow

**Compromised card**: the customer reports a charge they do not recognize, a lost card, or suspicious use.

We chose it because it is the only one of the four proposed workflows that contains **both outcomes** in a single conversation:

- **Automatic resolution** — a precautionary card block, which is reversible, bounded and verifiable against account state.
- **Human escalation** — the chargeback dispute, which involves judgment, the customer's money and evidence, and which we deliberately do **not** automate.

That lets a single demo session show what we consider the heart of the challenge: a system that acts when authorized and stops when it is not.

### 3.1 Generality demonstrated, not claimed

The system is built as a **configurable generic engine**: intents, knowledge, message templates and policies live in the database and are edited from the back office (see [ADR-0002](adr/0002-config-code-boundary.md)). Rather than leave that as a claim, we demonstrate it:

- The compromised-card workflow is **evaluated in depth**, with real data from the dataset and the full suite.
- A **second workflow** (account and payment inquiries, read-only) is added **live during the demo, without touching code** — configuration and rules only. It is covered by a 5-case smoke test, not the full suite.

Generality is a property of the system; depth is a property of our submission. We would rather both be verifiable in 3 minutes.

## 4. Out of scope (and why)

| Out of scope | Reason |
|---|---|
| Real biometric verification (selfie against ID document) | Requires a certified provider with liveness detection; a vision LLM gives neither a calibrated score nor spoof detection. See [ADR-0007](adr/0007-no-llm-biometrics.md). We leave the interface defined and a simulated provider behind it. |
| Real outbound OTP delivery | The OTP is not sent by email, SMS or any other external channel: the web client simulates a "you got an email with the code" notice from an in-app inbox, behind the delivery port a real provider would implement ([ADR-0007](adr/0007-no-llm-biometrics.md)). The model never chooses the channel. |
| End-to-end dispute resolution | A judgment call with monetary impact. It is our test case for "AI should not be autonomous just because it can be". |
| Customer onboarding / credit origination | A different workflow; adds nothing to the depth of the chosen one. |
| Real multi-tenancy | Anticipated in the data model (schema separation), not implemented. |

## 5. Success criteria

**Product**

- Automated resolution rate over eligible cases: **TODO — baseline and target**
- Unsafe outcomes (taxonomy in [evaluation.md](evaluation.md)): **target 0**
- Handoffs with complete context (verified facts, actions, verification method, open questions): **100%**
- p95 latency per turn: **TODO**
- Cost per resolved conversation: **TODO**

**Engineering**

- A third party brings the system up with one command and reproduces the reported metrics.
- Every action on an account lands in a verifiable audit log.
- Changing a risk policy requires no deployment.

## 6. Languages

The system's internal instructions (skills, schemas, policies) are in English, for consistency and because that is where models are most stable. **Customers interact in their own language** and the system replies in it; the interface and catalog data are internationalized. The commitment is behavioral, not translational: we report metrics **broken down by language** (Spanish, Portuguese and English), because a global average can hide one language performing badly. See [evaluation.md](evaluation.md).

## 7. Assumptions

1. The dataset provided by Factored is the source of truth for the simulated banking core. **TODO: confirm entity coverage after day-1 exploration.**
2. There are no ready-to-use intent labels. If there are, the labeling plan in [data.md](data.md) reduces to validation.
3. Judges test the system within an agreed window, not in continuous operation.

## 8. Map against the evaluation criteria

| Pillar | Where it lives in this submission |
|---|---|
| Works and is runnable | [runbook.md](runbook.md), test environment, `make demo` |
| Documented rationale | This document and the 10 ADRs |
| AI engineering | `orchestrator`, policy engine in `banking-core`, frontends, deployment |
| Data engineering | Ingestion, contracts, quality, lineage — [data.md](data.md) |
| Data analytics | Operational metrics panel and per-language breakdown |
| Machine learning | Decision classifier: baseline vs zero-shot vs fine-tuned, calibrated threshold |
