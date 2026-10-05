# Problem statement and the solution as built

**Written:** 2026-09-26 · **Updated:** 2026-10-04, at code freeze · **Submission:** 2026-10-05

The first half of this document is the problem as we framed it on day one; it has not changed. The second half is what the project does about it today, with the evidence for each claim and the gaps we know of. Everything named here exists in the repository; what does not is marked pending.

## 1. The business problem

A bank handles a high volume of customer service interactions where the bottleneck is not missing information but the human time spent verifying identity, gathering account context and executing an action that is simple yet irreversible. At the same time, automating badly costs more than not automating at all: an action taken on the wrong account, another customer's data disclosed, or an unwarranted card block carry regulatory and reputational cost that no efficiency gain offsets.

The problem we solve is not "answering questions". It is **deciding safely when to act, when to ask and when to hand the case to a person** — and being able to defend that decision afterwards.

## 2. Users

| User | What they need | How it is measured | What they get today |
|---|---|---|---|
| Bank customer | Resolve their problem without waiting for a human, in their own language | Time to resolution, cases closed without escalation | A chat in Spanish, Portuguese or English (`apps/web-client`) that verifies them with a code from a simulated inbox, blocks the card, and hands off to a person when it must. After a handoff it asks whether the assistant helped ([ADR-0017](adr/0017-assistant-feedback-after-handoff.md)) |
| Human agent | Receive the case already verified and with context, not a raw transcript | Reading time before they can act | A queue and a case page (`apps/web-backoffice`) showing the structured brief, the transcript and the customer's feedback. The agent takes over the conversation, replies, and closes or escalates the case ([ADR-0013](adr/0013-front-ends-bff-takeover.md), [ADR-0018](adr/0018-agent-decisions-on-a-case.md)) |
| Operations / risk | Change policy without waiting for a deployment; audit every decision | Policy change lead time, traceability | The Guardrails screen: amount thresholds per currency, the handoff mode and the tool-by-state matrix. Each save is a new audited version that applies to the next call. A metrics page reads from the audit log and the queue, and `make verify-audit` checks the hash chain |

## 3. Chosen workflow

**Compromised card**: the customer reports a charge they do not recognize, a lost card, or suspicious use.

We chose it because it is the only one of the four proposed workflows that contains **both outcomes** in a single conversation:

- **Automatic resolution** — a precautionary card block, which is reversible, bounded and verifiable against account state.
- **Human escalation** — the chargeback dispute, which involves judgment, the customer's money and evidence, and which we deliberately do **not** automate.

That lets a single demo session show what we consider the heart of the challenge: a system that acts when authorized and stops when it is not.

### 3.1 Generality demonstrated, not claimed

The system is built as a **configurable engine**: policies and the tools enabled in each verification state live in versioned database tables and are edited from the back office ([ADR-0002](adr/0002-config-code-boundary.md)). A second workflow — account and payment inquiries, read-only — is added **live, without touching code**:

- `account.get_summary`, a tool already in the catalog, starts disabled in the versioned tool policy.
- An operator enables it from the Guardrails tool matrix (or with the admin API call in the [runbook](runbook.md)).
- The change is audited, can never go beyond the code floor, and needs no deployment or restart.

It is covered by the 8 `account_inquiry` scenarios of the suite's 66, three of them with the tool disabled. All 8 passed in the live run (§6). Intents, message templates and queue priority are **not** editable yet; they are still code ([limitations](limitations.md)).

Generality is a property of the system; depth is a property of our submission.

## 4. How the project solves it

Every customer message goes through the same path:

1. **The encoder reads the raw text first.** A small local CPU model server (`apps/encoder`) runs inside the private network. It detects intent, PII spans and the decision points.
2. **The orchestrator masks before the LLM sees anything.** PII is replaced with placeholders, and the LLM gets only the masked text.
3. **The LLM proposes.** It writes the reply and proposes tool calls.
4. **banking-core disposes.** Its state machine and policy engine authorize or refuse each call ([ADR-0003](adr/0003-deterministic-vs-ai.md)). It runs the operation, re-reads the result from the database as a receipt, and writes an audit row.

The orchestrator holds no database credentials ([ADR-0004](adr/0004-trust-boundary.md)). The sections below take the three decisions — act, ask, hand off — and the means to defend them.

### 4.1 Act: the card block

- `card.block` runs only in the `VERIFIED` state, only on a card the customer owns, and only with an idempotency key.
- Its receipt is re-read from the database, so a claimed block without a receipt is an unsafe outcome the evaluation looks for (U5).
- A repeat block is answered from the stored receipt, not executed twice (U4).
- In the live run, every happy-path block scenario ended with the card blocked, in es, pt and en (§6).

### 4.2 Ask: identity and ambiguity

- **Identity:** a document match (`customer.match`) followed by a one-time code. The code goes to a simulated inbox the chat shows as "you got an email". The model never sees it and never chooses the channel ([ADR-0007](adr/0007-no-llm-biometrics.md)).
- **Attempt limits:** OTP failures are counted per customer, across sessions, and lock the customer out. Failed document matches are counted per document. New conversations are limited per client address.
- **The next step comes from banking-core, not the prompt.** Every tool result says which state the session is in and what comes next ([ADR-0016](adr/0016-banking-core-states-the-next-step.md)). It is advisory: the model still has to call the tool, and banking-core still decides.
- **A vague opening gets a fixed question.** When the local model abstains, `clarify_route` asks a fixed clarifying question instead of letting the LLM guess ([ADR-0014](adr/0014-distilbert-intent-backend.md)).

### 4.3 Hand off: the dispute

- **A brief, not a transcript.** `handoff.create` stores a summary built on the server with four elements: verified facts, actions taken, verification method and open questions.
- **Above the amount threshold, the handoff is required.** In that mode (stored as `block`), banking-core marks the case and the orchestrator creates the handoff if the model did not. The model can never lower its priority. The amount is read from the database for the linked charge, never from what the model says.
- **A dispute needs one identity attempt first** ([ADR-0003](adr/0003-deterministic-vs-ai.md), amendment 2026-10-02). A request for a human always passes.
- **Once an agent takes over, the LLM never sees the conversation again.** The agent's text reaches the customer as written.
- **Case decisions never move money.** The agent closes the case (approved, rejected, resolved) or escalates it to another department. A refund or a chargeback would be a banking operation of its own.

### 4.4 Defend: every decision is traceable

- **Hash-chained audit log:** an append-only log in Postgres records every tool call, policy change, claim and decision, with its outcome. `make verify-audit` checks the chain.
- **Detective mode** ([ADR-0019](adr/0019-detective-mode.md)) shows, in a panel beside the chat (a header button, or an action under each reply; on a window too narrow for the panel, in place of the conversation), the masked timeline of that turn: what the encoder decided, what the LLM was sent, which tools it proposed, what banking-core answered, and the token count. It is on locally and opt-in on Cloud Run.
- **Back-office metrics** count from rows that already exist: blocks, OTP outcomes, handoffs by status and priority, case outcomes and the customers' feedback.

### 4.5 Keep the model out of authority

- **Policies live in the database, not the prompt** ([ADR-0002](adr/0002-config-code-boundary.md)). A prompt injection can change what the model proposes, never what banking-core authorizes. The adversarial scenarios show a dangerous call refused or never proposed (U1, U7 at 0).
- **PII is masked by the union of two detectors.** Text sent to the LLM provider is masked by regexes plus the encoder's PII spans, and a failed check sends nothing.
  - Covered: emails, card numbers, documents (including Mexican and Argentine IDs), phones, codes, written-out dates, and labelled PINs, CVVs and passwords, which are never kept.
  - Known misses are in [limitations](limitations.md).
- **Data at rest is encrypted per field, with a blind index for lookups** ([ADR-0005](adr/0005-application-level-encryption.md)).
- **Retries are safe.** A repeated message (`client_message_id`) or write (idempotency key) is answered once.

### 4.6 Served in the customer's market, not just their language

Customers in es-CO, es-MX, es-AR and pt-BR do not write like a textbook. The intent model was trained on data grounded in their real text:
- Reclame Aqui complaints for Brazil;
- app-store reviews for Mexico and Argentina;
- tuquejasuma.com forum complaints for Colombia.

One pooled multilingual DistilBERT serves all four markets, with thresholds per locale, in about 20 ms on CPU ([ADR-0014](adr/0014-distilbert-intent-backend.md)). Knowledge questions are answered from a 120-snippet base in es/pt/en, searched with Granite embeddings and a score floor tuned on regional questions ([ADR-0006](adr/0006-single-postgres-pgvector.md)).

### 4.7 The LLM follows the flow, and we measured it

A sandbox bank runs banking-core's real authorizer, FSM and policies in memory (`tools/llmbench`). We measured each change in it stage by stage ([report](../reports/llm-flow-stages-2026-10-02.md)): the flow hint, tool descriptions generated from the code floor, prompt `turn-engine/4` and secret masking.
- The submission model, gpt-6-luna, went from 3–4 to 10 of 12 completed flows.
- A local Qwen3.6-35B-A3B that fits a 24 GB card reached the same 10 of 12.
- No blocking unsafe outcome appeared in any of the 32 runs.

### 4.8 Where it runs

- **Locally:** `make demo` brings up the whole stack with one command on the judge's machine ([runbook](runbook.md)). It is the five apps plus Postgres with pgvector and two Redis instances.
- **Presentation environment:** Google Cloud Run, defined in Terraform ([ADR-0015](adr/0015-gcp-cloud-run-terraform.md), [deployment](deployment.md)). The back office can be opened to judges, each with their own login, for an evaluation window.

## 5. How it was built

From the commit history, which is meant to show construction rather than a final dump:

| Date | What landed |
|---|---|
| 09-26 | Service shells, the trust-zone networks, contracts, field encryption with blind index, the data model |
| 09-27 | State machine, policy engine, hash-chained audit, idempotency, identity and read tools, the turn engine, PII masking, the evaluation runner, the first encoder and retrieval baselines, the calibration harness |
| 09-28 | `kb.search`, the dataset ingest, the admin API, card block and handoff wired end to end |
| 09-29 | A bug sweep and hardening: cross-session attempt limits, the amount guardrail read from the database, the simulated OTP inbox, the versioned tool policy, `make demo`, decision points with calibration, the model server, both front ends and the human takeover |
| 09-30 – 10-01 | Regionally grounded datasets, the pooled DistilBERT with per-locale thresholds, es-CO, Granite retrieval, the encoder on Cloud Run |
| 10-02 | The LLM bench, the flow hint, prompt v4, secret masking, the live end-to-end evaluation, customer feedback, the identity attempt before a dispute, agents closing and escalating cases |
| 10-03 – 10-04 | Fixes from the Cloud Run run, back-office access for judges, detective mode |

## 6. Success criteria: target and measured

Measured on one live end-to-end run of the whole stack, model gpt-6-luna, 2026-10-02 ([report](../reports/eval-live-2026-10-02-gpt-6-luna.md)). That run covered 58 scenarios; the 5 fault-injection scenarios were not run. **It is one run, called live, not replayable**: the replay-based `make eval` and its baseline are pending (§11).

| Criterion | Target | Measured (es / pt / en) |
|---|---|---|
| Scenarios passing every check | — | 36 of 58 |
| Unsafe outcomes ([evaluation.md](evaluation.md) §3) | **0** | **0** in every language. U1, U4, U5 and U7 are checked automatically and pass. U2, U3, U6 and U8 have no automatic check and are listed for human review |
| Handoffs with complete context | **100%** | **100%** (5/5 · 3/3 · 5/5) |
| Correct abstention | — | 75% (3/4) · 67% (2/3) · 100% (4/4) |
| Unnecessary escalation | — | 0% (0/4) · 0% (0/4) · 0% (0/2) |
| Automated resolution | No target set: needs the baseline | 27.3% (6/22) · 27.8% (5/18) · 16.7% (3/18) |
| p95 latency per turn | — | 4.4 s · 4.3 s · 2.6 s |
| Cost per conversation | — | about $0.0005 (LLM tokens only) |

How to read it:
- **Automated resolution is counted over every scenario in a language, not only the eligible ones.** Most of the suite is made of cases that must not be closed automatically (identity failures, not the holder, disputes, injection). The figure is not a rate over eligible cases.
- **The failures are mostly about which tools the model proposed, not about safety.** Two examples: a happy path where the model handed off instead of blocking, and `not_the_holder` scenarios that ended without the handoff they expected. banking-core refused or never received an unsafe call.
- **A local model nearly matches the hosted one.** The same run with Qwen3.6-35B-A3B passed 35 of 58, also with 0 unsafe outcomes ([report](../reports/eval-live-2026-10-02-qwen3.6-35b-a3b-think.md)).

**Engineering**

| Criterion | State |
|---|---|
| A third party brings the system up with one command and reproduces the reported metrics | `make demo` exists. The clean-machine check is still to do, and a chat turn needs an LLM key until replay recordings exist. Metrics reproduce with `make eval-live` and a key, not offline |
| Every action on an account lands in a verifiable audit log | Done: hash-chained, append-only by trigger, `make verify-audit`. External anchoring of the head hash is pending |
| Changing a risk policy requires no deployment | Done: the Guardrails screen and the admin API write a new audited version that applies to the next call |

## 7. Out of scope (and why)

| Out of scope | Reason |
|---|---|
| Real biometric verification (selfie against ID document) | Requires a certified provider with liveness detection; a vision LLM gives neither a calibrated score nor spoof detection ([ADR-0007](adr/0007-no-llm-biometrics.md)). The interface is defined, with a simulated provider behind it |
| Real outbound OTP delivery | The code is shown in a simulated in-app inbox, behind the delivery port a real provider would implement ([ADR-0007](adr/0007-no-llm-biometrics.md)). Consequence: in the demo, whoever sees the browser sees the code, so the OTP does not prove possession of a channel |
| End-to-end dispute resolution | A judgment call with monetary impact: our test case for "AI should not be autonomous just because it can be". Agents record a decision; nothing moves money |
| Handing a conversation back from the agent to the assistant | It needs a rule for what the assistant may know of the human turns, which was not designed |
| Customer onboarding / credit origination | A different workflow; adds nothing to the depth of the chosen one |
| Real multi-tenancy | Anticipated in the data model (schema separation), not implemented |

## 8. Languages

The system's internal instructions (prompts, schemas, policies) are in English. **Customers interact in their own language** and the system replies in it; the interface and catalog data are in es, pt and en. The commitment is behavioral, not translational: every metric is reported **per language**, and the scenarios with a market are also reported per market (es-CO, es-MX, es-AR, pt-BR).

The weak spot is English. The intent model was never trained on it, so it abstains on most English messages and the LLM carries more of the work there ([limitations](limitations.md)).

## 9. Assumptions, resolved

1. **The dataset is the source of truth for the simulated bank.** It is loaded through a pluggable ingest ([ADR-0011](adr/0011-hybrid-seed-dataset-ingest.md), [data quality](../reports/data-quality-factored.md)):
   - 150,000 customers read, 5,000 loaded under the default cap;
   - 3,970 cards and 10,823 transactions in a 90-day window;
   - the ARS risk threshold derived from its exchange rates.

   What it lacks shaped the rest of the project ([characterization](../lab/dataset-characterization.md)):
   - its conversation text is 42 template utterances;
   - it has no Portuguese;
   - its fraud flag carries no signal on behavioural features (ROC-AUC 0.507).
2. **There are no usable intent labels.** Confirmed. We built a synthetic set and then regionally grounded ones (§4.6). The test splits are provisional: written by an AI, not double-labelled by humans ([labeling rubric](labeling-rubric.md)).
3. **Judges run the system on their own machine with `make demo`.** Nothing depends on a server of ours being up. The Cloud Run environment is for the team's live presentation ([deployment.md](deployment.md), section 7).

## 10. Map against the evaluation criteria

| Pillar | Where it lives |
|---|---|
| Works and is runnable | `make demo`, [runbook.md](runbook.md); the Cloud Run presentation environment |
| Documented rationale | This document, 19 ADRs in [adr/](adr/), [limitations.md](limitations.md) |
| AI engineering | The `orchestrator` turn engine and masking, the `banking-core` policy engine and FSM, decision points ([ADR-0012](adr/0012-decision-points.md)), detective mode, both front ends, the LLM bench |
| Data engineering | Ingest with per-rule counts, contracts, quality reports, field encryption — [data.md](data.md), [reports/](../reports/) |
| Data analytics | The back-office metrics page; per-language and per-market evaluation reports |
| Machine learning | Intent: TF-IDF baseline vs zero-shot (GLiNER, Laya, a reranker) vs a fine-tuned pooled DistilBERT, with temperature scaling and thresholds per locale ([report](../reports/intent-models-regional-datasets.md)). Retrieval: BM25 vs MiniLM vs Granite (same-language Hit@1 0.366 / 0.494 / 0.719, [ADR-0006](adr/0006-single-postgres-pgvector.md)) |

## 11. What is still open

The full list, with the evidence behind each item, is in [limitations.md](limitations.md). The ones that matter most:

- **`make eval` and the baseline system are pending.** The baseline is the same LLM with no policy engine. The only end-to-end evidence is the live run of §6, which cannot be replayed, and no replay recordings exist.
- **Most decision points run in `shadow`.**
  - In `shadow` the local model decides and records what it would have done, but nothing changes.
  - Only `intent_hint` (one advisory line to the LLM) and `clarify_route` (the fixed clarifying question) act, in `enforce`.
  - The rest, including the consent gate before a block, wait for calibration that is certified, not provisional.
- **The calibration and test evidence is synthetic or silver-labelled.** No threshold is certified at its target precision; the human-labelled test set is pending.
- **PII masking has known misses**, such as a name with no introductory phrase when the light encoder backend runs. They are listed, not hidden.
- **The clean-machine check of `make demo`** is still to do before submission ([runbook](runbook.md) checklist).
