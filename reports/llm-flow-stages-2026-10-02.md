# LLM flow improvements, stage by stage

**Date:** 2026-10-02 (UTC). **Branch:** `feat/llm-flow`, off `feat/llm-bench`. **Tool:** [`tools/llmbench`](../tools/llmbench/README.md). **Source of the changes:** the team's LLM flow improvements proposal (groups A, B and E), measured one group at a time on six models.

> **What these numbers are.** The real `TurnEngine` and `LLMProvider` run against the llmbench **sandbox bank**, which uses banking-core's authorizer, FSM, policies and, from S1 on, its flow hint, with the data in memory. The encoder is off. The numbers are evidence for **choosing changes and models**, not system evidence; `make eval` is still a pending target. Local models ran once per stage at temperature 0. gpt-6-luna ran three times per stage, and gpt-6.1-sol three times at S0 and S4 only. sol needs temperature 1, so its runs vary.

## Summary

1. **The submission model goes from 3–4 to 10 of 12 completed flows, and from 16% to 51% of episodes.** gpt-6-luna with every improvement (S4) is close to where gpt-6.1-sol started (11 of 12 flows, 51% of episodes). sol itself rises to 11–12 of 12 and 62%.
2. **The flow hint (A1, ADR-0016) is the change that unblocks the flow.** On its own it doubles luna's completed flows (3–4 → 7), cuts luna's refusal loops from 18 to 4, and takes Granite 4.2 3B from 1 to 6 flows (14% → 43% of episodes). The stall it was built for (`continue_after_match`) goes from 0% to 100% for both luna and Granite 4.2 3B.
3. **The generated tool descriptions (B3) help single decisions but hurt whole conversations until the prompt arrives.** At S2, luna's probes jump from 60% to 85%, but its completed flows drop from 7 to 5–6 and it hands off more often (U8 × 15). Granite 4.2 3B drops from 6 flows to 2. The prompt v4 (S3) turns this around: luna reaches 9–10 flows and Granite 4.2 3B 5.
4. **Masking secrets (E1) works.** At S4 no model sent the PIN or CVV of the oversharing probes to the provider. Before S4, all of them did. Qwen3.5-4B and sol also pass the whole overshare probe; luna still proposes `customer.match` with a non-document placeholder there, and the engine guard refuses it.
5. **Tool routing still hurts the strongest model, even with the hint.** On top of S4, routing lifts luna's probes to 92% but drops its flows from 10 to 6–7. Keep it off.
6. **The local models do not close the gap.** The best local result is Granite 4.2 3B at S1 (6 of 12 flows, 43% of episodes). Qwen3.5-4B never completes more than 3 flows: it fails before any tool result arrives, so it never reads the hint. The ~1B models stay at 0 flows, and longer text makes Granite 4.0 1B worse (guard hits 57 → 89).
7. **No blocking unsafe outcome in any of the 32 runs.** The non-blocking ones that remain: U8 (a handoff missing elements), mostly luna at S2 and with routing; U5 (a claimed block with no receipt), only the local models, at most 3 per run.

## Stages

Each stage builds on the one before. Each is a commit, benchmarked from its own git worktree.

| Stage | Commit | Change (proposal item) |
|---|---|---|
| **S0** | `5ffbea9` | Baseline. Scorer fixes (U5 reads per sentence and skips negations; U6 ignores JSON amounts; the final state is read before the first handoff). 12 new probes (`continue_after_match`, `verify_only`, `next_after_refusal`, `overshare`) and 3 episodes that ask for verification first. Two new metrics: completed flows and refusal loops (F1, F3, F4) |
| **S1** | `469db07` | banking-core adds a `flow` hint to every tool result: state, allowed tools, next step, required states (A1, [ADR-0016](../docs/adr/0016-banking-core-states-the-next-step.md)) |
| **S2** | `0aa49f1` | Tool descriptions say the states each tool runs in (generated from the code floor) and what follows it (B3). Tools disabled in every state are no longer offered once the first hint is in (the safe half of A2) |
| **S3** | `cfe4df6` | Prompt `turn-engine/4` (B1, B2, E2):<br>• act on `flow.next` in the same turn<br>• offer the next step after a refusal<br>• treat indirect requests as requests<br>• anti-scam line with the code<br>• do not echo a PIN<br>• ask which card when there are several |
| **S4** | `5e75e23` | PINs, CVVs and passwords are masked as `[SECRET_n]` and never kept (E1) |
| **S4R** | `5e75e23` | Ablation: S4 with full state routing (`--route-tools`, the other half of A2) |

Not in this run, because the bench can't measure them: A3 (escalation triggers go through the decision-point process), C1–C4 (market and register), D1–D4 (bursts, documents, slang, multi-intent), G and H.

## Results

### Completed flows (of 12 per repeat)

Each value counts the happy-path, risk-threshold and messy episodes where banking-core accepted `card.block`, which requires identify, OTP and verify first. Hosted rows show one number per repeat.

| Model | S0 | S1 | S2 | S3 | S4 | S4R |
|---|---|---|---|---|---|---|
| gpt-6.1-sol | 11 / 10 / 11 | · | · | · | **11 / 12 / 12** | · |
| **gpt-6-luna** | 3 / 4 / 3 | 7 / 7 / 7 | 5 / 5 / 6 | 10 / 10 / 9 | **10 / 10 / 10** | 6 / 7 / 7 |
| qwen3.5-4b | 1 | 3 | 2 | 2 | 1 | 3 |
| granite-4.2-3b | 1 | **6** | 2 | 5 | 5 | 4 |
| qwen3-1.7b | 0 | 0 | 0 | 0 | 0 | 0 |
| granite-4.0-1b | 0 | 0 | 0 | 0 | 0 | 0 |

### Episodes passed (%)

| Model | S0 | S1 | S2 | S3 | S4 | S4R |
|---|---|---|---|---|---|---|
| gpt-6.1-sol | 51 | · | · | · | **62** | · |
| **gpt-6-luna** | 16 | 32 | 21 | 49 | **51** | 46 |
| qwen3.5-4b | 14 | 24 | 19 | 24 | 19 | 24 |
| granite-4.2-3b | 14 | **43** | 24 | 38 | 38 | 33 |
| qwen3-1.7b | 10 | 10 | 14 | 14 | 14 | 14 |
| granite-4.0-1b | 10 | 10 | 0 | 0 | 0 | 5 |

### Probes passed (%; min–max over three repeats)

| Model | S0 | S1 | S2 | S3 | S4 | S4R |
|---|---|---|---|---|---|---|
| gpt-6.1-sol | 78 (76–79) | · | · | · | 91 (90–93) | · |
| **gpt-6-luna** | 48 (48–48) | 60 (60–60) | 85 (83–86) | 85 (83–86) | 82 (81–83) | 92 (90–93) |
| qwen3.5-4b | 57 | 62 | 62 | 62 | 69 | 69 |
| granite-4.2-3b | 48 | 64 | 64 | 55 | 60 | 60 |
| qwen3-1.7b | 38 | 31 | 31 | 40 | 40 | 36 |
| granite-4.0-1b | 26 | 26 | 33 | 31 | 31 | 29 |

The probe percentages are not comparable with the first bench report: there are 42 probes now, against 30 then. The 12 new ones fail for almost every model at S0, and overshare fails by construction until S4.

### Refusal loops, guard hits and unsafe outcomes

| Model | Refusal loops S0 → S4 | Guard hits S0 → S4 | Blocking unsafe | Non-blocking, across all stages |
|---|---|---|---|---|
| gpt-6.1-sol | 1 → 0 | 0 → 0 | 0 | none |
| gpt-6-luna | **18 → 0** | 14 → 49 | 0 | U8 × 15 at S2, U8 × 8 at S4R |
| qwen3.5-4b | 1 → 0 | 15 → 14 | 0 | U5 × 2 at S4R |
| granite-4.2-3b | 4 → 0 | **57 → 11** | 0 | U5 × 1 at S4R |
| qwen3-1.7b | 0 → 0 | 46 → 46 | 0 | U5 × 1 at S0, S2 and S4R; U8 × 1 at S2 |
| granite-4.0-1b | 0 → 3 | 57 → 89 | 0 | U5 × 2–3 at S2–S4 |

luna's guard hits rise from S2 on because it calls `customer.match` before the customer has given a document, with a placeholder that isn't one (`[SECRET_1]`, or a `[DOC_1]` that doesn't exist). The engine rejects each of these before banking-core.

### Probes by skill, S0 → S1 → S4 (%)

| Skill | sol (S0 → S4) | luna | qwen3.5-4b | granite-4.2-3b | qwen3-1.7b | granite-4.0-1b |
|---|---|---|---|---|---|---|
| continue_after_match | 89 → 100 | 0 → **100** → 100 | 0 → 0 → 67 | 0 → **100** → 67 | 0 → 0 → 0 | 0 → 0 → 0 |
| verify_only | 100 → 100 | 0 → 0 → 78 | 0 → 33 → 67 | 0 → 0 → 0 | 0 → 0 → 0 | 0 → 0 → 0 |
| next_after_refusal | 100 → 100 | 67 → 100 → 100 | 0 → 67 → 0 | 0 → **100** → 67 | 0 → 0 → 67 | 0 → 0 → 0 |
| identify | 100 → 100 | 0 → 33 → 89 | 0 → 0 → 0 | 0 → 67 → 33 | 0 → 0 → 0 | 0 → 0 → 0 |
| injection | 0 → 100 | 0 → 0 → 0 | 100 → 100 → 67 | 33 → 33 → 67 | 0 → 0 → 0 | 0 → 0 → 0 |
| clarify | 100 → 100 | 0 → 0 → 78 | 100 → 100 → 67 | 67 → 67 → 33 | 67 → 67 → 67 | 0 → 0 → 0 |
| overshare | 0 → 100 | 0 → 0 → 0 | 0 → 0 → **100** | 0 → 0 → 67 | 0 → 0 → 0 | 0 → 0 → 0 |
| dispute_handoff | 100 → 100 | 100 → 100 → 100 | 100 → 100 → 100 | 100 → 100 → **0** | 67 → 0 → 0 | 0 → 67 → 33 |
| relay_refusal | 100 → 100 | 100 → 100 → 100 | 100 → 67 → 33 | 100 → 100 → 100 | 100 → 67 → 67 | 67 → 33 → 100 |
| honest_failure | 100 → 78¹ | 100 → 100 → 100 | 100 → 100 → 100 | 100 → 67 → 100 | 100 → 100 → 100 | 100 → 67 → 100 |

¹ Both of sol's misses are scorer false positives ("a technical error **prevented me from confirming** that your card was blocked"), fixed after the run (see [Bench issues](#bench-issues-found-during-the-run)). On this probe sol was right every time.

`no_guess_card` is left out: the probe was wrong (see [Bench issues](#bench-issues-found-during-the-run)).

### Latency

| Model | Call p50, S0 → S4 | Turn p95, S0 → S4 |
|---|---|---|
| gpt-6.1-sol | 2.3 s → 2.4 s | 9.0 s → 9.7 s |
| gpt-6-luna | 1.2 s → 1.2 s | 5.0 s → 4.9 s |
| qwen3.5-4b | 0.5 s → 0.4 s | 3.1 s → 1.9 s |
| granite-4.2-3b | 0.3 s → 0.4 s | 1.8 s → 1.8 s |

The hint, the longer descriptions and the prompt add 400–500 prompt tokens per call (luna 2,161 → 2,677), at no measurable latency cost.

## What each change did

| Change | Effect | Keep? |
|---|---|---|
| **A1** flow hint (S1) | The largest gain for every model that can call a tool before stalling: luna flows ×2, Granite 4.2 3B ×6, luna refusal loops 18 → 4. `continue_after_match` goes from 0 to 100% for luna and Granite 4.2 3B, and `next_after_refusal` reaches 100% for both (from 67% and 0%). No safety cost | **Yes** |
| **B3** generated descriptions, plus hiding disabled tools (S2) | Single decisions get better (luna probes 60 → 85%), but whole conversations get worse without the prompt: luna hands off more (U8 × 15) and completes fewer flows, Granite 4.2 3B drops 6 → 2, and the ~1B models make more guard hits. It does its job once S3's prompt is in | **Yes, together with S3**. Measure the description and the hiding separately next time |
| **B1, B2, E2** prompt v4 (S3) | luna's flows 5–6 → 9–10 and episodes 21 → 49%. Granite 4.2 3B recovers 2 → 5. luna's clarify 0 → 78%. No state or policy is in the text | **Yes** |
| **E1** secret masking (S4) | No PIN or CVV reaches the provider in any run, against every model leaking at S0. Qwen3.5-4B and sol pass overshare 100% | **Yes**: this fixes a real leak (rule 5) |
| **A2** full state routing (S4R) | Probes up (luna 82 → 92%), flows down for luna (10 → 6–7). Mixed for the local models | **No**, as ADR-0016 already decided |

## Verdict

- **Merge S1–S4 for the submission model.** luna completes 10 of 12 flows (it started at 3–4), with no blocking unsafe outcome and no extra latency. After the changes, the gap to gpt-6.1-sol is about 1 flow and 10 points of episodes, and sol still costs twice the latency and needs a temperature change. luna stays the model.
- **Next fix, from the transcripts:** luna proposes `customer.match` before the customer has given a document. The engine rejects it every time, but it shows up as 40–50 guard hits per run and it is luna's overshare failure. The `customer.match` description, or the ANONYMOUS hint, should say "needs a document the customer gave; if there is none, ask".
- **A local model is still not a replacement.** The best local configuration is Granite 4.2 3B at S1 (6 of 12 flows), and its best stage differs from luna's. Qwen3.5-4B fails before it ever reads a hint. Giving the hint before the first turn (the `ANONYMOUS` hint at session start) is the obvious next experiment for the local models.

## Bench issues found during the run

Each stage ran the bench code of its own commit, so these fixes (commit `714136b`) do not change the stage numbers above. They correct the reading of them.

1. **`no_guess_card` was wrong.** Its prefix had the customer say "perdí mi tarjeta **débito**", and the second card is a credit card, so blocking the debit card was the right reading, not a guess. The first bench report's claim that every model blocks one of two cards without asking does not hold. The prefix now names no card type.
2. **U5 missed negation by a verb.** It read "a technical error prevented me from confirming that your card was blocked" as a claim. It now treats `prevent…`, `impidió`/`impediu` and `failed to` as negations. The 7 flags on the first report's runs are unchanged.

## How the run went

| Event | Effect | What was done |
|---|---|---|
| The dev machine slept, and the network dropped for about 30 min | One local run (Granite 4.2 3B at S2) and two luna runs failed on connection errors. The CLI still exits 0 on errored turns | Runs with any LLM call error were discarded and repeated. `caffeinate` keeps the machine awake from then on |
| OpenAI limits gpt-6-luna to 200k tokens per minute for the org | Parallel luna runs hit `RateLimitError`, and five luna stage runs filled with errored turns | All five repeated one at a time, with 6 retries |
| A single timeout in gpt-6.1-sol at S0 | 1 of 758 calls, so 1 of 63 episodes counts as failed | Kept, and declared here |

All 32 runs kept for this report have no LLM call errors, except that one sol call.

- **Spend:** about 13.4M prompt tokens across the kept hosted runs, plus about 4M in the discarded ones.
- **Wall time:** about 2 h 30 min of runs. The local runs took about 40 min of GPU time on the RTX 3090.

## Reproduce

```bash
git worktree add /tmp/s1 469db07 && cd /tmp/s1
make llm-bench-serve MODEL=granite-4.2-3b    # local: llama-server on :8099
make llm-bench MODEL=granite-4.2-3b TAG=S1
make llm-bench MODEL=gpt-6-luna REPEAT=3 TAG=S1   # hosted: LLM_API_KEY; one luna run at a time (200k TPM)
```

The run files, with full transcripts, are in `tools/llmbench/results/stages/` (gitignored).
