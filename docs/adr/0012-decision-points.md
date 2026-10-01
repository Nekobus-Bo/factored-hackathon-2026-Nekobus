# ADR-0012: Decision points — calibrated local models decide, the engine applies, banking-core disposes

**Status:** Accepted (minimum freeze scope) · **Date:** 2026-09-29 · **Deciders:** team

**Amends:** [ADR-0003](0003-deterministic-vs-ai.md) (what a decision model may do), [ADR-0008](0008-cpu-inference-deployment.md) (optional local sidecar up to ~4B parameters), [ADR-0010](0010-model-selection-calibration-harness.md) (the harness emits a per-decision-point artifact). Consistent with [ADR-0001](0001-cheap-llm-specialized-encoder.md), [ADR-0002](0002-config-code-boundary.md), [ADR-0004](0004-trust-boundary.md). Short cross-reference amendments were added to [ADR-0006](0006-single-postgres-pgvector.md) (the embedding model moves to the model server) and [ADR-0008](0008-cpu-inference-deployment.md) (the model server; the local sidecar is post-freeze).

## Context

The team decided: *"The decision model makes the decisions wherever possible. If the current model is weak, try other models (for example a ~4B-parameter model or similar), calibrated per use case. A teammate owns calibration; our job is to leave the structure well defined so she can plug in models and calibrate each use case without touching engine code."* This ADR designs that structure; it does not reopen the decision.

A second team decision, taken when this ADR was accepted, is about *where* the models run. There are three models: the **LLM** (GPT 6 Luna, an external provider that only ever sees masked text), the **decision model** and the **embedding model** used by `kb.search`. The decision and embedding models run on a separate **model server**, which is the existing `apps/encoder` service made deployable on its own host in the team's private network. The teammate who owns calibration calibrates and pins both, so that they always behave the same. Today the embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) runs inside banking-core (`apps/banking-core/src/banking_core/knowledge/tools/kb_search.py`, `packages/retrieval/src/retrieval/adapters/sentence_transformers.py`), which costs about 1.3 GB RSS per replica in the trusted zone ([limitations.md](../limitations.md), kb.search footprint). Appendix J records this decision.

Today the encoder runs one 15-way classifier with one global τ (`ABSTENTION_THRESHOLD=0.37`) and returns only the top-1 label. `TurnEngine.run_turn` stores intent, confidence and abstain in `TurnMetadata` and nothing consumes them ([limitations.md](../limitations.md)). The LLM alone picks `card.block.reason`, the `handoff.create` reason, department and priority, and whether to ask before blocking (a prompt sentence, not a control). The harness picks one τ per language over all 15 classes, so the worst class dominates it, and it never calibrates the confidence itself.

An exploratory probe (tfidf_lr with the adapter's own hyper-parameters, provisional synthetic test; a scratch script, **not evidence**: WP3 must reproduce it in `reports/`) shaped this design:

1. Raw LR confidence is under-confident (test ECE 0.51). One temperature fitted on validation (T ≈ 0.19, 0.18–0.19 per language) brought test ECE to 0.07 and raised coverage at the validation-chosen τ from 30% to 57% at 96% precision on accepted rows: the cheapest gain available, with no new model.
2. `out_of_scope` is a sink: only 22 of the 54 test rows predicted `out_of_scope` really are; the rest are short replies (bare OTP digits, "nope", "holaa", "síp"). Acting on it is unsafe today.
3. A dedicated confirm / deny / other model made no false "confirm" on test (22/22, recall 0.73, misses are typos like "síp"); summing the other 14 classes into "other" recalled 0.20. Some decisions need their own label space and model.
4. `GLiNERAdapter.predict` returns `probabilities` that are not a distribution (top-1 confidence, the rest spread uniformly), so calibrators and label views cannot use it.
5. The test split has 10 rows per intent and language, so precision 0.95 cannot be certified: 22/22 has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted rows with zero errors.

## Decision

We introduce **decision points** (DP): named, individually calibrated decisions such as `confirm_gate` or `block_reason`. Tables, schemas and paths are in the appendices.

1. **A DP is data; its calibration is one atomic unit.** Backend, label view, confidence calibrator, τ per language and evidence live in one **calibration artifact** (`packages/encoder/calibration/decision_points.json`), written only by the harness and read only by the encoder service at startup. It pins each backend's revision and hash; a τ never travels without the model it was fitted on (a mismatch stops the service from starting). Its hash is recorded in `reports/`. (Appendix B)
2. **Engine effects are code; which DP uses which effect is data.** The orchestrator implements a closed set of effects once. At freeze: `record`, `select` (overwrite an enum argument of an LLM-proposed call) and `gate` (withhold an LLM-proposed write until consent). `decision_effects.yaml` binds each DP to an effect with `mode: off / shadow / enforce`, a label-to-value map and `on_abstain`. A new DP on an existing effect touches no engine code. (Appendices A, E)
3. **Invariants.** (I1) An effect may record, select among values banking-core already accepts, or withhold a write; it never authorizes, creates a call, or makes one succeed that the FSM and policy engine refuse. (I2) Every failure (abstain, unavailable, infeasible, off) falls toward the LLM's own argument or a withheld write, never toward acting. (I3) τ is bound to its model by the artifact. (I4) DP backends and the model server run in our containers, inside the team's private network; raw text never reaches a provider. (I5) Every decision is recorded in `TurnMetadata`: DP id, outcome, label, calibrated confidence, τ, model id, config version, never text.
4. **Pluggable backends.** A model that implements `DecisionAdapter` and declares `probability_kind` registers once in `encoder/registry.py` and is then usable by the harness and the service unchanged. The service runs each backend once per request and serves many DPs from it. A ~4B quantized LLM is supported only as an out-of-process sidecar (own container, 4 GB), never on the default path. (Appendix C)
5. **Contract.** `POST /v1/analyze` gains an optional `decision_points` request field and a `decisions` map plus `config_version` in the response; legacy fields are derived from the `turn_intent` DP. (Appendix D)
6. **Ship before the freeze, few and testable, every one starting in `shadow`:** `turn_intent` (`record`), `confirm_gate` (`gate`), `block_reason` (`select`), and `handoff_route` and `smalltalk_route`. The machinery for `enforce` ships; no DP enforces until its own reviewed diff flips the mode after the sign-off of Appendix F. Anything that changes what the LLM sees or lets a model start an action waits until after the freeze. (Appendix A)
7. **Calibration is a protocol.** Per DP: one split per purpose, a constraint on the labels the engine acts on (not on all 15 classes), a calibrator fitted on validation, a Wilson lower bound on test, one report and one artifact entry per run. `shadow` to `enforce` is a separate reviewed diff. (Appendix F)
8. **Model server.** The decision model and the embedding model run on a separate model server: the existing `apps/encoder` service, deployable on its own host in the team's private network. Both models are pinned by revision and hash and calibrated by the teammate. The model server receives raw customer text, so it runs only inside the team's private network and never as a third-party service (I4). banking-core's `kb.search` embeds its queries there and verifies the model identity on every response; a mismatch makes `kb.search` unavailable, never a silent fallback. (Appendix J)

The gate is a customer-protection control in the untrusted zone, not an authorization: banking-core still requires `VERIFIED`, ownership and an idempotency key for every block. A gate that banking-core itself enforces is future work.

## Approved scope and cut line

The team approved the **minimum freeze scope** on 2026-09-29: WP1 (contracts), WP2 (encoder decision layer), the first cut of WP3 (harness: artifact writer, verify, temperature), WP4 (orchestrator effects: `record`, `gate`, `select`), WP5 (seed artifact and effects file) and WP8 (documentation), with **every decision point starting in `shadow`**. The model server (Appendix J, WP12) was added by the team at the same time and is part of the scope. WP7 (adapter conformance test and the `llm_sidecar` stub) and WP6 (scenarios, evaluation section, re-record) are scheduled in the same window but sit *below* the minimum: they are cut before anything above them.

| Decision point | Effect | Mode at the freeze |
|---|---|---|
| `turn_intent` | `record` | `shadow` |
| `confirm_gate` | `gate` on `card.block` | `shadow`; `enforce` only by a separate reviewed diff after the sign-off of Appendix F |
| `block_reason` | `select` on `card.block.reason` | `shadow`; same |
| `handoff_route` | `select` on `handoff.create` | `shadow` |
| `smalltalk_route` | `record` | `shadow` |

**Cut line, in order** (full text in Appendix H): (1) `handoff_route` and `smalltalk_route` stay entirely in the file, `shadow`; (2) `select` moves after the gate; (3) `/v1/decision-points` and the startup cross-check drop to the static `make calibration-verify`; (4) the gate ships `shadow`. Because every DP now starts in `shadow`, step (4) is the baseline, not a fallback: the machinery, metrics and scenarios ship, and `enforce` is a later decision.

**Out of scope at the freeze, on purpose:** the `route_tools`, `canned_reply`, `propose` and `hint` effects; the ~4B sidecar container, prompt and calibration (only the interface, the conformance test and a stub that fails as `pending` ship); candidate adapters beyond `tfidf_lr` and `gliner` (`embedding_lr`, `hf_seqcls`, a GLiNER fine-tune); card-scoped consent; consent provenance in the audit chain; back-office editing of the effects file; quick-reply buttons; authentication between the services and the model server.

**Amended 2026-09-30 by [ADR-0014](0014-distilbert-intent-backend.md):** the `hf_seqcls` adapter (the pooled DistilBERT) and the `hint` and `canned_reply` effects move before the freeze, the two effects in `shadow` only; threshold and calibrator keys may be locales (`es-MX`), with the fallback locale → language → `*`.

## Options considered

| Option | Complexity | Calibration and evidence | Verdict |
|---|---|---|---|
| A. Status quo: LLM decides, encoder advisory | None added | None; the block confirmation stays a prompt sentence | Ignores the team decision |
| B. One global model and one global τ everywhere | Low | Poor: `out_of_scope` and the worst class set τ for every use | A confirmation and a block reason need different precision floors; no per-use model swap |
| C. Bespoke classifier path per use case in the engine | Low at first, then linear in use cases | Ad hoc | Every new use case or model is engine code, which the team asked to avoid |
| **D (chosen). Decision-point registry: closed effects, calibration artifact, pluggable backends** | Medium: two config files, one contract addition, one registry | Per use case, hash-pinned, recorded | Meets "no engine code"; restrict-only effects keep rule 2 mechanical |
| E. One local ~4B generalist LLM decides everything | High | Uncalibrated by default; ~2–4 s per decision and ~3.5 GB RSS (estimates) | Contradicts ADR-0008's premise; kept as one backend, not as the architecture |

Where the decision and embedding models run (added at acceptance):

| Option | Footprint | Trust | Verdict |
|---|---|---|---|
| M1. Status quo: the embedding model inside banking-core, the decision model in the encoder | ~1.3 GB RSS in every banking-core replica; two places to pin and calibrate | The whole ML stack runs inside the trusted zone | Rejected: the team wants one place where both models are pinned and calibrated |
| **M2 (chosen). Model server: both models in `apps/encoder`, banking-core calls it** | Each model is loaded once, not once per banking-core replica; banking-core no longer imports torch at runtime | A new dependency of the trusted zone, integrity-only, on public data (Appendix J) | Chosen |
| M3. A third-party embedding or classification API | Smallest | Raw customer text (decision) and queries would leave our network | Rejected: violates I4 and ADR-0008 |

## Trade-off analysis

The deciding axis is **authority per decision versus evidence per decision**. A model gets a decision only where measured precision supports it and only through an effect whose failure mode is safe (fall back to the LLM, or withhold). The price is automation: a fail-closed gate adds a turn whenever the model abstains on a colloquial "yes" (recall 0.73 in the probe). We accept it for the reason ADR-0003 accepts unnecessary escalation, and we measure it (`gate_extra_turns`). The second axis is **speed of change versus traceability**: τ is not editable on its own, because a τ without its model and split is unfalsifiable; changing it means recalibrating. The knobs that are safe to flip live (`mode`, `max_age_turns`) sit in the effects file.

A third axis was added at acceptance: **one place to pin the models versus a network hop.** The model server gives one place to pin, calibrate and size both models and takes the ML stack out of banking-core. It costs a small request on every `kb.search` (the KB vectors are fetched once, at first use) and a new dependency of the trusted zone, which Appendix J bounds: the dependency is integrity-only, carries public data, and is verified on every response.

## Consequences

**Becomes easier:** adding a backend (an adapter, one registry line, a candidate entry; no change in `apps/orchestrator`, `main.py` or contracts); adding a DP that reuses an effect (an artifact entry, an effects entry, one scenario); explaining a block (receipt, reason, consent source and deciding model are all recorded); killing a misbehaving DP in a demo (`DECISION_POINTS_MODES=confirm_gate=shadow`, no redeploy); moving or resizing the models (the model server can sit on a larger host without touching banking-core); one pinning discipline for both models.

**Becomes harder:** DP test sets must be far larger than 10 rows per class and language; the engine's "never alters model arguments" becomes a bounded `select` allowlist; one prompt line plus a `PROMPT_VERSION` bump forces a re-record of the replay set (needs live LLM credits) while `make eval` is still a pending target; encoder and orchestrator deploy together (additive contract change, orchestrator first); banking-core depends on the model server for `kb.search`, so the model server must be reachable before the first `kb.search`, and both services must be configured with the same `EMBEDDING_MODEL` and `EMBEDDING_REVISION`; there is no authentication between services yet (`limitations.md`).

**To revisit:** quick-reply buttons in `web-client` if the gate's abstain rate hurts automatic blocks; `route_tools`, `canned_reply` and `propose` (a guaranteed path to a human) once `turn_intent` is good on the human test set; a 1–4B sidecar with cascading (`escalate_to`) if it beats cheaper rungs within budget; DP provenance in the banking-core audit chain; authentication and TLS between the services and the model server; dropping the `vector` extra from the banking-core image (Appendix J.6).

## Action items

Everything named here and in the appendices is **pending** until its work package lands (AGENTS.md rule 7). The status table below is updated by the change that lands each item, so a reader can tell what exists from what is promised.

1. [x] WP1 contracts: `DecisionResult`, request and response fields, `ReasonCode.CONFIRMATION_REQUIRED` (0.5 d)
2. [x] WP2 encoder decision layer, registry, `/v1/decision-points` (1.5 d)
3. [x] WP3 harness: `TASK=decision-points`, temperature calibrator, Wilson bound, artifact writer, `make calibration-verify` (1.5 d); the isotonic calibrator stays pending, and the harness does not fine-tune (a candidate is trained and pinned first)
4. [x] WP4 orchestrator: effects loader, `DecisionState`, `gate` and `select`, metadata, prompt line (2 d); the concurrent analysis of E.1 was not built (see the note under the status table)
5. [x] WP5 seed artifact and effects file, every DP in `shadow`, first reports (0.5 d); the effects file landed with WP4, the seed artifact and the first report (`reports/calibration-decision-points-2026-09-29.md`) with the harness. **Nothing is certified**: the test split is provisional and AI-written, so the sign-off of Appendix F.5 has not happened (item 10)
6. [ ] WP6 scenarios, evalrunner DP section, re-record (1 d), below the approved minimum; the evalrunner section landed, the scenarios and the re-record are pending
7. [x] WP7 adapter conformance test, `llm_sidecar` stub that fails as "pending" (0.5 d), below the approved minimum; the `encoder-bench` extension stays pending
8. [x] WP8 docs: cross-links in ADR-0003/0010, `limitations.md`, `evaluation.md`, `AGENTS.md`, runbook kill switch (0.5 d)
9. [x] WP12 model server: `POST /v1/embed`, remote embedding adapter, `kb.search` remote backend, compose and docs (1.5 d)
10. [ ] Teammate: candidates, DP datasets, calibration runs, embedding-model pin, sign-off and `shadow` to `enforce` flips (Appendix H)

### Implementation status (rule 7)

| What the ADR names | Work package | Status |
|---|---|---|
| `DecisionResult`, `decisions`, `config_version`, `decision_points` request field, and the `GET /v1/decision-points` response model in `packages/contracts/src/contracts/encoder.py`; `ReasonCode.CONFIRMATION_REQUIRED` in `envelope.py`; exported schemas | WP1 | landed |
| Artifact schema, canonical `artifact_id`, loader, `decide` (`packages/encoder/src/encoder/decision_points.py`), model pins (`pinning.py`), and the JSON Schema `packages/encoder/calibration/decision_points.schema.json` | WP2 | landed |
| Backend registry `packages/encoder/src/encoder/registry.py` (`tfidf_lr`, `gliner`) | WP2 | landed |
| `apps/encoder/src/encoder_service/{scoring,decisions}.py`; `decisions` in `/v1/analyze`; `GET /v1/decision-points`; `/ready` per-DP state; legacy seed mode; `DECISION_POINTS_FILE`, `DECISION_POINTS_ALLOW_STALE`, `DECISION_POINTS_TAU_RAISE` | WP2 | landed |
| `packages/encoder/calibration/decision_points.json` (the artifact: all five decision points `calibrated`, none certified; written by the harness, seed run of 2026-09-29, selection by the point estimate (`ci: point`) with a lowered `n_min`, because the Wilson bound is infeasible on 10 rows per class and language) | WP5 | landed; the service reads it at startup and `ABSTENTION_THRESHOLD` is ignored while it exists (legacy seed mode only when no artifact file exists) |
| `packages/encoder/tests/test_adapter_conformance.py`; the `llm_sidecar` stub | WP7 | landed (`llm_sidecar` fails with `pending: llm_sidecar is not implemented (ADR-0012)`) |
| `encoder-bench` for artifact backends; `make warmup-encoder` fetching pinned decision weights and verifying SHA-256 | WP7 / WP10 | pending |
| `make calibrate TASK=decision-points`, `make calibration-verify`, `tools/calibrate/configs/decision_points.yaml`, `tools/calibrate/src/calibrate/{calibrators,thresholds,artifact,verify,dpconfig,dp,dp_report}.py`, `metrics/decision.py` (Wilson bound, reliability bins), the guide in `tools/calibrate/README.md` | WP3 | landed |
| `reports/calibration-decision-points-<date>.md` (`-<dp>`, several joined with `+`, appended when a run covers only some decision points), first one `reports/calibration-decision-points-2026-09-29.md`: every decision point `calibrated`, `certified: no`, sign-off "not ready for enforce" | WP5 | landed |
| The isotonic calibrator (refused as `pending: isotonic calibrator is not implemented (ADR-0012)` by the harness and the loader); fine-tuned candidates in `TASK=decision-points` (`mode: finetune` for anything but `tfidf_lr` fails with `pending:`); hard-negative sets (the report says "not measured") | WP3 / WP9 / WP10 | pending |
| `apps/orchestrator/config/decision_effects.yaml` (all five decision points in `shadow`), `DECISION_EFFECTS_FILE`, `DECISION_POINTS_MODES` (compose, `.env.example`, Dockerfile) | WP4, WP5 | landed |
| `apps/orchestrator/src/orchestrator/conversation/decisions/{config,state,records,catalog,effects}.py`: the fail-loud loader, `DecisionState` persisted in `ConversationState`, `record` / `select` / `gate`, the cached listing of served ids | WP4 | landed |
| Engine: the gate and select hooks in `run_turn` / `_execute`, the local `CONFIRMATION_REQUIRED` refusal, `TurnMetadata.{decisions,effects,decisions_config_version,dp_config_mismatch}`, `eval.decisions` and `eval.effects` in the eval hook, the prompt line and `PROMPT_VERSION` `turn-engine/2` | WP4 | landed |
| Concurrent analysis (E.1: analyze while the first LLM call runs) | WP4 | not built, on purpose: see the note below |
| The evalrunner "Decision Points by Language" section (decided / abstained / unavailable per decision point, gate would-withhold, select agreement) | WP6 | landed |
| The 9 new scenarios, `gate_breach` / `gate_false_consent` / `gate_extra_turns`, `eval/replay/DECISION_CONFIG` | WP6 | pending: the scenario schema cannot switch orchestrator modes per scenario, so there are no `enforce` scenarios yet |
| `data/eval/synthetic/dp/`, the "gate labels" section of `docs/labeling-rubric.md`, calibration runs, `shadow` to `enforce` flips | WP9 | pending (teammate) |
| Candidate adapters (`embedding_lr`, `hf_seqcls`), the `llm-local` compose profile, `packages/encoder/prompts/`, `DECISION_BACKEND_HOSTS`, cascading (`escalate_to`) | WP10 | pending (teammate, post-freeze); `hf_seqcls` moved before the freeze by ADR-0014 |
| `EmbedRequest` and `EmbedResponse` in `packages/contracts/src/contracts/encoder.py`, with exported schemas | WP12 | landed |
| `SentenceTransformersAdapter.embed` and `RemoteEmbeddingAdapter` in `packages/retrieval` | WP12 | landed |
| `POST /v1/embed`, `EMBEDDING_MODEL`, `EMBEDDING_REVISION`, `EMBEDDING_WEIGHTS_SHA256`, `EMBEDDING_MAX_BATCH`, the `embed` extra and the embedding part of `warmup` in `apps/encoder` | WP12 | landed |
| banking-core `kb.search` remote backend: `EMBEDDING_BACKEND`, `MODEL_SERVER_URL`, `MODEL_SERVER_TIMEOUT_SECONDS`, `EMBEDDING_REVISION` | WP12 | landed |
| Compose wiring, `make warmup-retrieval` on the model server, `.env.example`, `docs/deployment.md`, `docs/limitations.md`, `docs/runbook.md` | WP12 | landed |
| The AGENTS.md line, `limitations.md` rows for the gate and the effects, the ADR-0003 row and ADR-0010 amendment (Appendix I), `evaluation.md` section, the runbook's mode kill switch | WP8 | landed |

**Where the orchestrator differs from the text above (WP4).** These are choices the text left open or that the code forced; none changes an invariant.

- *Analysis is not concurrent with the LLM.* E.1 draws the analyze call as a task that overlaps the first completion. The encoder's PII spans widen the masking of the customer text and the masking precedes the first LLM call, so the call stays where it was and the decision points ride on it (no extra request, no extra latency beyond the listing fetch below). Overlapping would need masking to stop depending on the spans.
- *Only listed ids are requested.* The orchestrator caches `GET /v1/decision-points` (5 minutes, kept when a refresh fails, retried every 15 s) and names in `decision_points` only the active decision points it lists with the labels the effects file needs. A decision point the encoder does not serve (no artifact: only `turn_intent`) is recorded `unavailable` / `not_served`; one whose labels do not cover the file is `unavailable` / `config_mismatch`, listed in `TurnMetadata.dp_config_mismatch`, and a gate on it keeps withholding. A 422 from a stale listing is asked again for the service's default set, so the PII spans survive. If the listing cannot be read at all the call names nothing.
- *The gate.* A pending question expires after `max_age_turns` like consent (E.2 gave only consent an age). A decided `deny` beats an explicit request of the same turn. A successful block spends the consent, so a second block in the conversation needs a second one. The state machine runs identically in `shadow`, where the block goes through and spends it, so the records of a shadow run say what `enforce` would have done. The explicit request may read a decision point that is `shadow` (its mode governs its own effect, not its use as an input); the file check for it uses the file's modes, so `DECISION_POINTS_MODES=turn_intent=off` still starts and simply leaves the explicit request unable to grant anything.
- *Select.* The ledger is per decision point, sticky across turns and spent by a successful write of its tool; `on_abstain` and `on_unavailable` therefore leave an earlier decided value in force. The engine-forced REQUIRED handoff bypasses `select` (it copies banking-core's requirement). With `select` in `enforce` the result of `handoff.create` that the LLM sees shows the effective department, a category and not a number; the history still holds the LLM's own arguments.
- *Recording.* `DecisionRecord` and `EffectRecord` follow E.3 with two additions: `tau_source` and `unavailable_reason` on the first; on a gate record `detail.event` (`withheld`, `released`, `consent_granted`, `consent_revoked`, `consent_expired`, `question_expired`) and `dp_outcome`. A defect inside the effects costs the turn its decision records, not the turn.
- *Limits.* At most 16 decision points in the file (one request may name 16); one gate per tool; no two selects on one argument.
---

# Appendices

## Appendix A — Decision points

Every row assumes banking-core still authorizes every tool call. "Wrong" says what the error costs on top of that. Every DP starts in `shadow` (approved scope); `enforce` follows the sign-off in Appendix F, in its own diff.

| ID | Input | Label set | Confident → engine does | Abstains or unavailable → engine does | If wrong (banking-core still authorizes) | Effect | Freeze |
|---|---|---|---|---|---|---|---|
| `turn_intent` | Raw utterance, session language | The 15 intents | Records the result; feeds the sticky ledgers of `block_reason`/`handoff_route` and the explicit-request consent of `confirm_gate` | Records `abstained`; LLM alone, as today | Nothing by itself (advisory) | `record` | Yes |
| `confirm_gate` | Utterance. The service evaluates it every turn, but the engine acts on it only while a confirmation is pending or consent exists for a gated tool (the engine knows that; the model does not) | `confirm` / `deny` / `other` (own backend, trained on the intents through a `label_map`) | `confirm`: records consent, and the LLM's next `card.block` proposal is sent to banking-core. `deny`: clears pending and consent, the LLM acknowledges | `other`, abstain, unavailable: gate stays closed. Engine answers the proposal with local refusal `CONFIRMATION_REQUIRED`, the LLM asks one short confirmation question. Forced handoff after N unresolved asks is post-freeze | False confirm: a block the customer did not want, on their own card in a `VERIFIED` session; visible, and an agent can reverse it. This is the worst case, hence the highest bar (Wilson lower bound of confirm precision ≥ 0.95 per language). False deny or abstain: one extra turn | `gate` on `card.block` | Yes, ships `shadow`; `enforce` after sign-off |
| `block_reason` | Utterances of the session; sticky ledger with priority `stolen > lost > unrecognized_charge > suspicious_activity > card_block_request` | `LOST`, `STOLEN`, `UNRECOGNIZED_CHARGE`, `SUSPICIOUS_ACTIVITY`, `CUSTOMER_REQUEST` (a view over `turn_intent`) | Overwrites `card.block.reason` with the mapped `BlockReason`; the LLM's value is kept in the effect record | Keeps the LLM's `reason` | Wrong reason on the receipt and in analytics. No effect on authorization | `select` | Yes, ships `shadow`; `enforce` after sign-off |
| `handoff_route` | Same kind of sticky ledger | `DISPUTE` (from `request_dispute`), `FRAUD` (`report_stolen_card`, `report_suspicious_activity`), `UNRECOGNIZED` (`report_unrecognized_charge`), `HUMAN_REQUEST` (`request_human_agent`); a view over `turn_intent`. Mapped to department and reason: `DISPUTES`/`DISPUTE_CLAIM`, `FRAUD_OPERATIONS`/`SUSPECTED_FRAUD`, `FRAUD_OPERATIONS`/`UNRECOGNIZED_TRANSACTION`, `CUSTOMER_SUPPORT`/`CUSTOMER_REQUEST` | Overwrites `handoff.create.department` and `.reason`. Never `priority` (the policy engine decides the effective priority). Leaves the whole call as the LLM proposed when its reason is `CUSTOMER_LOCKED` or `VERIFICATION_FAILED`, which come from FSM outcomes, not from language | Keeps the LLM's values | Ticket in the wrong queue; an agent re-routes | `select` | `shadow`; `enforce` only if signed off by 2026-10-02 |
| `smalltalk_route` | Utterance | `greeting`, `out_of_scope`, `other` | `record` only. Offline metric: decided `greeting`/`out_of_scope` on a turn where the LLM called a tool | Nothing | Would strand a customer who wrote "hola, me robaron la tarjeta" or a bare OTP; that is why it does not act | `record` | `shadow` only |
| OTP / identity detection | — | — | **Not a decision point.** The engine already handles it deterministically: pending-challenge masking of bare digits, `SECRET_ARGS` placeholder checks, `ONCE_PER_TURN`. The model's contribution is PII spans for masking, which the PII task unions in (a union can only mask more, never less). The 15-way model classifies bare OTP digits as `out_of_scope`, so routing on intent here would be wrong | — | — | — | No DP |
| Guaranteed path to a human | Utterance | `request_human_agent` | Engine proposes `handoff.create` if the LLM did not | — | Unnecessary escalation (accepted cost, ADR-0003) | `propose` | Post-freeze |

**Effect vocabulary (closed, in code).**

| Effect | What it does | Allowed `on_abstain` | Freeze |
|---|---|---|---|
| `record` | Stores the result in `TurnMetadata` | none | Yes |
| `select` | Overwrites an enum argument of an LLM-proposed call with the label's mapped value; only fields that are enums in the tool's input model, never `SECRET_ARGS`, `card_ref` or idempotency keys | `fallback_llm` | Yes |
| `gate` | Withholds an LLM-proposed write until consent (a decided `confirm`, or an explicit request) | `withhold` | Yes |
| `route_tools` | Narrows the tools offered to the LLM this turn (changes `tool_schema_hash`) | `all_tools` | No |
| `canned_reply` | Answers from a localized template without an LLM call | `fallback_llm` | No |
| `propose` | Engine proposes a call; code allowlist `{handoff.create}` | `fallback_llm` | No |
| `hint` | Passes the category to the LLM as structured context (ADR-0001 says so, but it needs `make eval` before and after) | `omit` | No |

The loader rejects effects marked "No" with an explicit `pending: <effect> is not implemented (ADR-0012)` (rule 7).

**Why these five for the freeze.** `confirm_gate` is the one decision only a language model can make (a yes/no in three languages with typos), sits directly on the irreversible write, and fails safe. `block_reason` is nearly free once the ledger exists and removes an unaudited free choice. `turn_intent` is the observation layer every other metric needs. The two `shadow` DPs cost no extra engine code (`handoff_route` reuses the `select` that `block_reason` needs, `smalltalk_route` only records) and give the teammate real traffic to calibrate against. What we cut on purpose: tool narrowing, canned replies, hints and engine-proposed calls change what the customer or the LLM sees, and `make eval` cannot yet show them safe.

## Appendix B — Configuration

### B.1 Two files, split by owner

| File | Written by | Holds | Loaded by | Changes require |
|---|---|---|---|---|
| `packages/encoder/calibration/decision_points.json` (calibration artifact; JSON Schema generated from `encoder/decision_points.py` next to it) | The harness only (`make calibrate TASK=decision-points`) | Model-bound facts: backends with revision and hash, label view, calibrator, τ per language, evidence | Encoder service at startup, path overridable with `DECISION_POINTS_FILE` | Recalibration, a report, an encoder restart |
| `apps/orchestrator/config/decision_effects.yaml` (effects) | The team, by reviewed diff | Behavior: effect, `mode`, label-to-value maps, `on_abstain`, `max_age_turns` | Orchestrator at startup, path `DECISION_EFFECTS_FILE`; `DECISION_POINTS_MODES='id=mode,...'` overrides modes | A PR; the mode kill switch needs only an env change |

Startup is fail-loud, as `build_backend` is today: an invalid schema, a backend that cannot be built, or a backend whose revision or hash differs from its pin stops the service with an explicit message. `DECISION_POINTS_ALLOW_STALE=true` (refused when `APP_ENV=production`) downgrades a pin mismatch to `unavailable` for the DPs on that backend; a backend that cannot be built is never downgraded. The harness wrote the first artifact (WP5, seed run of 2026-09-29) and it is committed; the service runs in legacy seed mode (B.2), and says so in `/ready` and `GET /v1/decision-points`, only when no artifact file exists. A `DECISION_POINTS_FILE` that names a missing file means "no artifact" (tests rely on it), except under `APP_ENV=production`, where it stops the service. The artifact holds no weights and no PII, so it is committed: `git log` on it is the audit trail of every τ. The encoder Dockerfile already copies `packages/encoder`, so the artifact ships in the image; a volume can override it. Heavier backends use a second artifact (for example `decision_points.heavy.json`) selected by `DECISION_POINTS_FILE`, so `make demo` needs no extra download.

### B.2 How AGENTS.md rule 6 is satisfied

- No τ, label map, mode or threshold is a constant in code. τ lives in the artifact, maps and modes in the effects file.
- `.env` holds only paths, the mode overrides, and the legacy seed: `ABSTENTION_THRESHOLD` synthesizes a one-DP artifact (`turn_intent`, `status: uncalibrated_seed`, `tau_source: seed`) when no artifact file exists. When the artifact exists, the env value is ignored and logged as such.
- A τ is intentionally not editable in isolation (ADR-0010: τ comes from validation of a specific model). The only live override is raise-only: `DECISION_POINTS_TAU_RAISE='confirm_gate.es=0.97'` can make a DP more conservative, never less, and is reported as `tau_source: override`.
- Back-office editing of the effects file is not built; declared in `limitations.md` next to the policy configuration UI.

### B.3 Artifact schema (`schema_version: 1`)

| Field | Meaning |
|---|---|
| `artifact_id` | First 12 hex of the SHA-256 of the canonical JSON without this field. Returned as `config_version` |
| `created_at`, `harness.git_sha`, `harness.config_path`, `harness.config_sha256` | Provenance |
| `data.{train,validation,test}_sha256`, `data.test_provenance` | Splits used (`human`, `synthetic`, or `synthetic-provisional`) |
| `backends.<id>.kind` | Registry key: `tfidf_lr`, `embedding_lr`, `hf_seqcls`, `gliner`, `llm_sidecar`, … |
| `backends.<id>.model_id`, `.revision`, `.weights_sha256` | Human-readable id, hub commit or GGUF file revision, and content hash (file or directory manifest). For `tfidf_lr`: `train.{path,sha256,label_map}` instead of weights, as `model_id` already carries the train hash. `revision` is a full 40-hex commit for hub models (a branch or tag is not a pin and is refused); `weights_sha256` is the SHA-256 of the primary weights file of the resolved snapshot (`model.safetensors`, else `pytorch_model.bin`). For `tfidf_lr`, `model_id` is `tfidf_lr@train-sha256:<12 hex>`, or `tfidf_lr@map-<8 hex of the label_map hash>/train-sha256:<12 hex>` when a `label_map` relabels the train file; `encoder.registry.tfidf_model_id` computes it and the loader compares |
| `backends.<id>.labels` | The backend's label space. Required for `top1_only` backends, whose DPs must use exactly these labels; for `distribution` backends optional, and checked against the classes the adapter reports |
| `backends.<id>.probability_kind` | `distribution` (required for views and calibrators) or `top1_only` (threshold only; GLiNER today) |
| `backends.<id>.local_only`, `.cost_class`, `.timeout_ms`, `.params` | Must be `true`; `low` or `high`; per-call budget; adapter kwargs (`url`, `prompt_id`, `prompt_sha256` for sidecars) |
| `backends.<id>.resources.{ram_mb,p95_ms,measured_on}` | From `make encoder-bench`; used by the memory-floor check |
| `decision_points.<id>.backend` | Key into `backends` |
| `.view` | `{kind: labels, labels: [...]}` or `{kind: groups, groups: {label: [backend labels]}}` |
| `.enabled`, `.always_on` | `enabled`: the service evaluates the DP at all. `always_on`: it is included when a request names no DPs (sidecar DPs set it `false` and are requested explicitly) |
| `.calibrator` | `{kind: none / temperature / isotonic, by_lang: {es: {T: …}, pt: …, en: …}}`. Applied to the backend's whole distribution, then the view aggregates: a group's confidence is the sum of its members' calibrated probabilities and is never renormalized over the view, so an utterance outside the view gets a low confidence and abstains. `by_lang` may carry `*`; a language with no entry and no `*` makes the DP abstain. `isotonic` is refused with `pending: isotonic calibrator is not implemented (ADR-0012)` |
| `.thresholds` | `{es: 0.9, pt: {confirm: 0.9, deny: 0.8}, en: null, "*": …}`. A scalar applies to all labels; `null` means infeasible in that language (the DP abstains, and the `*` fallback does not apply); a key that is absent falls back to `*`, and with no `*` the DP abstains. In a per-label mapping, a label without a τ (and no `*` in the mapping) abstains |
| `.constraint` | `{metric, label(s), p_min, ci: wilson95_lower / point, n_min, calibration_split}` |
| `.status` | `calibrated` (`tau_source: artifact`), `infeasible` (never decides), `uncalibrated_seed` (`tau_source: seed`). The raise-only override reports `tau_source: override` |
| `.evidence` | `{run_id, report, split, provenance, per_lang: {coverage_test, precision_test: {label: [tp, n, wilson_lo]}, ece_pre, ece_post}}` |
| `.escalate_to` | Reserved; the loader rejects a non-null value with "pending: cascading (ADR-0012)" |

To avoid a cycle between report hash and artifact hash, both carry the same `run_id` (hash of config, data hashes and candidate outputs). `make calibration-verify` checks that the `run_id` appears in the referenced report, that the report embeds the artifact fragment verbatim, that data hashes match the files on disk, and that backend pins match.

Illustrative fragment (values are written by the harness; `…` stands for them):

```jsonc
{
  "schema_version": 1,
  "artifact_id": "…",
  "backends": {
    "intent_tfidf": {"kind": "tfidf_lr", "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
                     "train": {"path": "data/eval/synthetic/decision.train.jsonl", "sha256": "…"},
                     "probability_kind": "distribution", "local_only": true, "cost_class": "low", "timeout_ms": 200},
    "gate_tfidf":   {"kind": "tfidf_lr", "model_id": "tfidf_lr@map-<8 hex>/train-sha256:<12 hex>",
                     "train": {"path": "…", "sha256": "…", "label_map": {"confirm": "confirm", "deny": "deny", "*": "other"}},
                     "probability_kind": "distribution", "local_only": true, "cost_class": "low", "timeout_ms": 200}
  },
  "decision_points": {
    "turn_intent":  {"backend": "intent_tfidf", "view": {"kind": "labels", "labels": ["…15 intents…"]},
                     "enabled": true, "always_on": true, "calibrator": {"kind": "temperature", "by_lang": {"es": {"T": …}}},
                     "thresholds": {"es": …, "pt": …, "en": …}, "status": "calibrated", "evidence": {…}},
    "confirm_gate": {"backend": "gate_tfidf", "view": {"kind": "labels", "labels": ["confirm", "deny", "other"]},
                     "constraint": {"metric": "precision", "label": "confirm", "p_min": 0.95, "ci": "wilson95_lower", "n_min": 30},
                     "thresholds": {"es": {"confirm": …, "deny": …, "other": …}, "pt": …, "en": …}, "status": "calibrated", "evidence": {…}},
    "block_reason": {"backend": "intent_tfidf",
                     "view": {"kind": "groups", "groups": {"LOST": ["report_lost_card"], "STOLEN": ["report_stolen_card"],
                              "UNRECOGNIZED_CHARGE": ["report_unrecognized_charge"], "SUSPICIOUS_ACTIVITY": ["report_suspicious_activity"],
                              "CUSTOMER_REQUEST": ["request_card_block"]}},
                     "thresholds": {"*": …}, "status": "calibrated", "evidence": {…}}
  }
}
```

A group view needs `probability_kind: distribution`; the loader refuses it on a `top1_only` backend.

### B.4 Effects schema (`decision_effects.yaml`)

```yaml
version: 1
decision_points:
  turn_intent:
    mode: shadow                  # off / shadow / enforce
    effect: record
  confirm_gate:
    mode: shadow                  # flipped to enforce by its own PR
    effect: gate
    on_abstain: withhold
    on_unavailable: withhold
    params:
      tool: card.block
      consent_labels: [confirm]                # decided labels that grant consent
      revoke_labels: [deny]
      explicit_request: {dp: turn_intent, labels: [request_card_block]}   # consent without an extra turn
      max_age_turns: 6
  block_reason:
    mode: shadow
    effect: select
    on_abstain: fallback_llm
    on_unavailable: fallback_llm
    params:
      ledger: {policy: priority, order: [STOLEN, LOST, UNRECOGNIZED_CHARGE, SUSPICIOUS_ACTIVITY, CUSTOMER_REQUEST]}
      targets:
        - {tool: card.block, arg: reason, map: {LOST: LOST, STOLEN: STOLEN, UNRECOGNIZED_CHARGE: UNRECOGNIZED_CHARGE,
                                                SUSPICIOUS_ACTIVITY: SUSPICIOUS_ACTIVITY, CUSTOMER_REQUEST: CUSTOMER_REQUEST}}
  handoff_route:
    mode: shadow
    effect: select
    on_abstain: fallback_llm
    params:
      ledger: {policy: latest}
      targets:
        - tool: handoff.create
          map:
            DISPUTE: {department: DISPUTES, reason: DISPUTE_CLAIM}
            FRAUD: {department: FRAUD_OPERATIONS, reason: SUSPECTED_FRAUD}
            UNRECOGNIZED: {department: FRAUD_OPERATIONS, reason: UNRECOGNIZED_TRANSACTION}
            HUMAN_REQUEST: {department: CUSTOMER_SUPPORT, reason: CUSTOMER_REQUEST}
          keep_llm_call_when: {reason: [CUSTOMER_LOCKED, VERIFICATION_FAILED]}   # FSM-derived, not language
```

Startup validation (fail loud, like `SESSION_SECRET`): every `tool`/`arg` exists in `TOOL_CATALOG` and the arg is an enum; every mapped value is a member of that enum; `effect` and `on_abstain` combinations are in the closed vocabulary; a DP referenced from another block (`explicit_request.dp`) exists and is not `off`. The DP ids and labels are cross-checked against the encoder's `GET /v1/decision-points` on the first successful analyze (the encoder is an optional signal, so no startup dependency); a mismatch disables that DP for the process, logs it, and records `dp_config_mismatch` in the metadata. `make calibration-verify` performs the same cross-check statically in CI, on the two committed files.

## Appendix C — Pluggable backends

### C.1 Interface

- Base: the existing `encoder.base.DecisionAdapter` (`fit / predict / save / load`, returning `DecisionPrediction.probabilities`). Add class attributes `kind` and `probability_kind`. Contract: when `probability_kind == "distribution"`, `predict` fills `probabilities` for every label of the backend's label space, summing to 1 ± 1e-3.
- Registry: `packages/encoder/src/encoder/registry.py` with `register(kind, lazy_factory)` and `build(spec)`. Imports are lazy (as `GLiNERAdapter` is today) so `tfidf_lr` never loads PyTorch. Artifacts name a `kind`; they never name a dotted import path, so a JSON file cannot make the service import arbitrary code.
- The decision-point path of the service (`encoder_service/decisions.py`) builds its adapters through the registry, and so should `tools/calibrate/src/calibrate/runner.py` (today an if/elif over `tfidf_lr` and `gliner`; moving it is part of WP3). The legacy `build_backend` in `model_backends.py` (slots, PII spans, `ENCODER_BACKEND`) stays as it is. A new model registers once and is available to both consumers.
- Service wrapper `encoder_service/scoring.py`: caches one forward pass per backend per request, enforces `timeout_ms` (worker thread for CPU-bound adapters, client timeout for sidecars), and turns `ModelUnavailableError` into `outcome: unavailable` for that DP only. The legacy whole-request 503 remains for the legacy backend.
- Slots and PII spans stay on the legacy `EncoderBackend` path. Decision points only classify.
- Conformance test `packages/encoder/tests/test_adapter_conformance.py`, parametrized over the registry: labels inside the contract enums, probabilities sum to 1, two calls give identical output, `predict([]) == []`, no text in logs. It is the teammate's checklist for a new adapter.
- Extra dependencies follow the existing pattern: an `ENCODER_EXTRAS` build arg (`gliner` today; add `hf`, `onnx`).

### C.2 Candidate ladder per DP (cheapest first)

| Rung | Example | RAM | p95 per message, 2 vCPU | Basis |
|---|---|---|---|---|
| 0 | `tfidf_lr` + temperature | +43 MB | 0.2 ms | Measured (`limitations.md`) |
| 1 | Frozen multilingual sentence embedding + LR head (`paraphrase-multilingual-MiniLM-L12-v2`, already in banking-core for `kb.search`) | 0.5–1.3 GB | 10–40 ms | Estimate; banking-core measured ~1.3 GB including its KB index |
| 2 | Fine-tuned sequence classifier (XLM-R base class, ~0.28B), fp32 or ONNX int8; trained on Apple Silicon per ADR-0010 | 0.6–1.5 GB | 20–80 ms | Estimate |
| 3 | GLiNER2.5 (0.3B), zero-shot or fine-tuned | 3.45 GB peak | 90 ms | Measured; `top1_only` |
| 4a | 1–2B instruct LLM, 4-bit, llama.cpp sidecar | 1.2–2 GB | 0.5–1.5 s | Estimate |
| 4b | ~4B instruct LLM, 4-bit, llama.cpp sidecar | 3.0–3.5 GB | 1.5–4 s | Estimate |

Rung 0 with temperature scaling and rung 1 are the likeliest wins for `confirm_gate`'s typo misses. Rung 4 is for labels that are semantic and data-poor (for example a `handoff_route` reason), never for a yes/no.

### C.3 The ~4B model on CPU, honestly

ADR-0008 assumed models in the hundreds of millions of parameters. A 4B model breaks that premise, so this ADR amends it: *"An optional local sidecar of up to ~4B parameters, 4-bit quantized, is allowed for individual decision points when calibration evidence shows a gain that smaller models cannot deliver. It runs on CPU in its own container with its own memory limit and is never on by default."*

Memory (weights = parameters × bits ÷ 8; KV cache and buffers are for a 1–2k context; ±15%):

| Precision | Weights | Runtime RSS | Fits a 3 GB container | Fits a 4 GB container |
|---|---|---|---|---|
| fp16 | 8.0 GB | 8.5–9 GB | No | No (needs 10 GB or more) |
| int8 (Q8_0) | 4.3 GB | 4.7–5 GB | No | No |
| 4-bit (Q4_K_M, ~4.85 bits/weight) | 2.4–2.6 GB | 3.0–3.5 GB | No (and nothing left for the encoder process beside it) | Yes, as a stand-alone sidecar |
| 1.5–2B, 4-bit | 1.0–1.3 GB | 1.2–2 GB | Yes | Yes |

Latency (estimate for 2 vCPU as in the compose `cpus: "2.0"`): prompt evaluation of the ~30–60 new tokens with the static instruction and label definitions held in a KV prefix cache, 1–3 s; constrained decoding of 1–4 label tokens, 0.3–1 s. Without prefix caching a 200-token prompt costs 7–13 s. Against 0.2 ms for `tfidf_lr` and 90 ms for GLiNER, this must not sit on every turn's critical path.

Placement: a separate container/compose profile `llm-local` (llama.cpp server with a pinned GGUF). Weights come from a volume, like `HF_HOME`, never baked into the image. The image adds ~0.1–0.3 GB; the GGUF adds 2.5–2.8 GB of disk. The current compose limits sum to about 7.5 GB (orchestrator 1, banking-core 2, encoder 3, Postgres and two Redis); the sidecar adds 4 GB, so the deployment host needs 12 GB or more. **Open question: confirm the host size.** Ollama is fine for local experiments, but it cannot be pinned by file hash, so the artifact uses llama.cpp with `gguf_sha256`.

Using it without engine code: `kind: llm_sidecar`. The prompt (label definitions from `labeling-rubric.md`, not policy) lives in `packages/encoder/prompts/<dp_id>.md` and its hash is in the artifact. Decoding is grammar-constrained to the label set at temperature 0 with a fixed seed. Confidences are label log-probabilities at the first decision token, softmaxed over the label set, then temperature-calibrated like any other backend. The sidecar sits on an internal network with no egress, and the service refuses hosts outside `DECISION_BACKEND_HOSTS` (I4).

Recommended use: as a **cascade** (`escalate_to`, reserved): the cheap DP runs first, and only if it abstains does the strong one run. Analysis is overlapped with the first LLM call (Appendix E), so even 2 s is mostly hidden. A timeout yields `unavailable` and the fallback.

What must be measured before adoption (`make encoder-bench DP=<id>`, extended): cold load from the volume, time to first token, tokens/s, p50/p95 at concurrency 1 and 2, `docker stats` RSS, prefix-cache hit rate, and accuracy of Q4 versus Q8 on the DP's validation split. Adoption rule: precision at the DP's constraint clearly above the best cheaper rung on the same test set, p95 inside the DP's budget, RSS inside the sidecar limit.

**In scope before the freeze:** the interface, the conformance test, the bench extension, and a `llm_sidecar` registry entry that fails with `pending: llm_sidecar is not implemented (ADR-0012)`. The container, prompt and calibration are the teammate's, and post-freeze if they do not land.

## Appendix D — Service contract

Changes are in `packages/contracts/src/contracts/encoder.py`. All additions are optional with defaults.

**`AnalyzeRequest`** (unchanged: `text`, `lang`)

| New field | Type | Meaning |
|---|---|---|
| `decision_points` | `list[str] or None`, at most 16, pattern `^[a-z][a-z0-9_]{2,40}$` | DP ids to evaluate. `None` = all `enabled` and `always_on`. An unknown id is a 422, not silently ignored |

**`AnalyzeResponse`** (legacy fields `intent`, `confidence`, `abstain`, `slots`, `pii_spans`, `model_id`, `latency_ms` unchanged)

| New field | Type | Meaning |
|---|---|---|
| `decisions` | `dict[str, DecisionResult]`, default `{}` | One entry per evaluated DP |
| `config_version` | `str or None` | `artifact_id`; `None` in legacy seed mode |

The legacy `intent`/`confidence`/`abstain` are derived from the `turn_intent` DP when the artifact has one (`decided` gives the intent, `abstained` gives `abstain=true` and `intent=None`, so `validate_abstention` still holds). With an artifact, the legacy `confidence` is the calibrated confidence (it was the raw model probability, so values move up); without one the endpoint behaves exactly as today.

**`DecisionResult`** (`extra="forbid"`, frozen)

| Field | Type | Meaning |
|---|---|---|
| `dp_id` | `str` | DP id |
| `outcome` | `decided / abstained / unavailable / infeasible / off` | `decided`: top view label has calibrated confidence ≥ its τ for the request language. `abstained`: below τ, or no τ for this language (`null` in the artifact). `unavailable`: backend timeout, error or not ready. `infeasible`: artifact status; never decides. `off`: the DP is `enabled: false` in the artifact and was requested by id (a request that names no DPs skips it) |
| `label` | `str or None` | Set if and only if `outcome == decided` (validator, like `validate_abstention`) |
| `confidence` | `float` in [0, 1] | Calibrated confidence of the top view label; 0.0 when unavailable |
| `raw_confidence` | `float or None` | Before calibration (drift debugging) |
| `runner_up` | `{label, confidence} or None` | Second label; for a targeted clarification later |
| `tau` | `float or None` | Threshold applied |
| `tau_source` | `artifact / override / seed` | Where τ came from |
| `model_id` | `str` | Backend `model_id` including revision or hash (max 128) |
| `config_version` | `str or None` | `artifact_id`, repeated on each result so a stored decision is self-contained; `None` in legacy seed mode |
| `latency_ms` | `float` | Time in this DP's backend (shared backends report once) |

Validators: `label` is set if and only if `outcome == decided`; `decided` implies a `tau` and `confidence >= tau`; `unavailable`, `infeasible` and `off` carry confidence 0.0, no `tau` and no label; `tau_source` is set if and only if `tau` is. A request with `decision_points: []` evaluates none, but the legacy fields are still derived from `turn_intent` when the artifact has an enabled one, and duplicate ids in the request are a 422.

"Other" is an ordinary label of the view (`confirm_gate` has `other`), so it is `decided` like any label and has its own τ. `abstained` means the model is unsure between labels; `decided other` means it is sure the utterance is none of the actionable ones. Effects treat them differently only through their own `params`.

New endpoint `GET /v1/decision-points`: `{config_version, source, decision_points: [{id, labels, backend_kind, backend_model_id, probability_kind, status, state, enabled, always_on, languages_with_tau}]}`, where `source` is `artifact` or `legacy_seed` and `state` is `ready / unavailable / infeasible / off`. `GET /ready` gains `config_version` and a per-DP `ready / unavailable / infeasible`. It is 503 only when there is neither an artifact nor `ABSTENTION_THRESHOLD`; an artifact that fails its startup checks (schema, backend pin, memory floor) never gets as far as serving, per B.1. Existing encoder tests that assert the "uncalibrated" 503 set `DECISION_POINTS_FILE` to a missing path.

Privacy: no text or spans in `DecisionResult`; the orchestrator stores it as is.

Rollout order: the response model is `extra="forbid"`, so deploy the orchestrator's new contract first, then the encoder (in this monorepo they ship together).

## Appendix E — Engine integration

### E.1 Flow inside `TurnEngine.run_turn`

```
customer text
   |
   v
mask (fail closed) --> start analysis task: POST /v1/analyze {text, lang, decision_points?}  --.
   |                                                                                            |
   v                                                                                            |
LLM completion (unchanged; tools offered as today) <----------- runs concurrently ------------'
   |
   v  LLM proposes tool calls
await analysis -> observe(): update DecisionState (consent, pending, ledgers)
   |
   v  for each call in _execute():
        _local_rejection (existing guards)
        gate.before_call(): withhold? -> local ToolResult(REFUSED, CONFIRMATION_REQUIRED), executed=False
        rehydrate + normalize dates -> select.before_call(): overwrite enum args -> ToolCall (contract validates)
        banking-core (FSM + policy + idempotency decide) -> receipt
        after_result(): a successful card.block clears consent, pending and the ledger
   |
   v
final reply (LLM writes the text) + receipts
```

Concrete edits in `apps/orchestrator/src/orchestrator/conversation/`:

| Where | Change |
|---|---|
| `engine.py` `run_turn`, at `await self._analyze(user_text, lang, metadata)` | Start it with `asyncio.create_task`, and await it in a `try/finally` (cancel on LLM error) before the first `_execute` and before building the result. Analysis is off the critical path. `ENCODER_TIMEOUT_SECONDS` still bounds it. Encoder errors: `encoder_unavailable=True` and every DP is `unavailable` |
| `engine.py` `_analyze` | Send `decision_points` = the ids in the effects file whose mode is not `off`, plus any DP a `params` block refers to (the encoder answers only those); fill `metadata.decisions` |
| `engine.py` `_execute`, after `_local_rejection` and before `ToolCall(...)` | Two hook calls (`before_call`). The `select` overwrite happens after `_rehydrate` and `normalize_date_arguments`, so the pydantic contract validates the new value. History keeps the LLM's original arguments (`_mask_args` runs earlier), so replay keys do not move |
| `engine.py` `_TurnGuard` | Withheld calls join `guard.refused` so the LLM cannot retry within the turn |
| new `decisions/config.py`, `state.py`, `effects.py` | Effects loader and validator; `DecisionState`; `RecordEffect`, `SelectEffect`, `GateEffect` behind one `Effect` protocol (`observe`, `before_call`, `after_result`) |
| `models.py` | `ConversationContext.decisions: DecisionState`; `TurnMetadata.decisions: list[DecisionRecord]`, `.effects: list[EffectRecord]` |
| `session/models.py`, `chat/engine_handler.py` | Persist `DecisionState` in `ConversationState` (Redis edge, no PII). Committed only when the turn completes, like `history`, so a retried turn re-runs from the same state |
| `prompt.py` | One line: *"If a tool answers CONFIRMATION_REQUIRED, ask the customer to confirm that action in one short question and do not call it again until they answer."* It explains an engine refusal like the existing refusal line and holds no policy. `PROMPT_VERSION` becomes `turn-engine/2` |
| `packages/contracts/.../envelope.py` | `ReasonCode.CONFIRMATION_REQUIRED` (emitted only by the orchestrator, never by banking-core) |

### E.2 Gate state machine (per gated tool, `card.block`)

| State | Event | Next | Note |
|---|---|---|---|
| none | LLM proposes `card.block`, no consent | pending | Withheld with `CONFIRMATION_REQUIRED`; the LLM asks |
| none or pending | `turn_intent` decided `request_card_block` this turn | consented (source `explicit_request`) | No extra turn when the customer clearly commanded the block |
| pending | `confirm_gate` decided `confirm` | consented (source `confirmation`) | Only counts while pending or consented: a "yes" to something else does nothing |
| any | `confirm_gate` decided `deny` | none | Clears pending and consent |
| pending | abstained, `other` or unavailable | pending | Stays closed |
| consented | age > `max_age_turns` | none | Consent expires |
| consented | `card.block` returns `ok` | none | Receipt from banking-core |
| consented | `card.block` refused by banking-core (for example `STATE_NOT_ALLOWED` before verification) | consented | Consent survives so the verified retry needs no second question |

Consent is per tool, not per card: the LLM still chooses `card_ref` among the customer's own cards, and banking-core's ownership check still applies. Naming the card in the question is the LLM's job today; a card-scoped consent is a declared gap.

### E.3 Recording decisions

- `DecisionRecord`: `dp_id, mode, outcome, label, confidence, tau, model_id, config_version, latency_ms`.
- `EffectRecord`: `dp_id, effect, tool, applied, would_apply, detail` where `detail` is `{arg, llm_value, dp_value}` for `select` or `{state_before, state_after, consent_source}` for `gate`. Never text.
- Both go into `TurnMetadata`, and from there into the stored message metadata and the metadata the eval hook already returns. One structured log line per DP per turn, no text.
- The banking-core audit chain records the tool call with its *effective* arguments, so the reason on a block is audited as before. What it does not hold is *why* (the consent source, the model). The orchestrator sits outside the trust boundary and cannot write the chain. A later `ToolCall.provenance` field, stored as unverified in `AuditPayload.details`, would close it (declared in `limitations.md`, not built).

### E.4 Replay determinism

- The LLM recording key hashes model, prompt version, masked messages and tool schema hash. DP outputs never enter the LLM messages as numbers. The only path from a DP to an LLM message is the categorical `CONFIRMATION_REQUIRED` tool feedback, and it appears only when the gate is in `enforce`.
- `shadow` and `off` change no LLM message, so existing recordings stay valid. The system-prompt line and the `PROMPT_VERSION` bump invalidate all of them once, so re-record everything then (needs live credits: confirm that a key exists).
- `enforce` on the gate makes the LLM's post-refusal completion part of the recording. If a calibration change flips a gate outcome for a scenario turn, that scenario reports `replay_miss` (already "not run", never a pass). Fix: `RECORD=1` re-run, commit `eval/replay/` and `eval/replay/DECISION_CONFIG` (the `config_version` used). The runner warns when the live `config_version` differs from that file.
- `(text, lang, artifact)` to decisions must be a pure function: no sampling, `temperature 0` and a fixed seed for LLM-backed DPs, fixed thread count. The `make demo` artifact uses only in-process CPU backends.
- `select` never rewrites what the LLM emitted, only what is sent to banking-core, and history keeps the LLM's version (see E.1).

### E.5 Failure matrix

| Situation | Behavior |
|---|---|
| Encoder down or timeout | `encoder_unavailable`; all DPs `unavailable`. `select`: LLM value. `gate`: withheld (safety over availability; shown by a degradation scenario) |
| One DP `unavailable` or `infeasible` | Same, for that DP only |
| Artifact absent | Legacy behavior for `record` and `select` (LLM value). A `gate` in `enforce` still withholds: its DP counts as `unavailable` |
| `mode: off` | DP ignored |
| `mode: shadow` | Everything computed and recorded (`would_apply`), nothing changes |
| Effects file invalid | Orchestrator refuses to start |
| Effects and artifact disagree (missing DP, label mismatch) | `select` and `record` DPs are disabled for the process, logged, `dp_config_mismatch` in metadata. A `gate` in `enforce` treats its DP as `unavailable` and keeps withholding: a misconfiguration must not open the gate (I2) |

## Appendix F — Calibration protocol (for the teammate)

**Principle:** she edits adapters, configs, datasets and reports, and commits an artifact. She does not edit `apps/orchestrator` or `main.py`.

### F.1 Splits and data

| Purpose | Split | Rule |
|---|---|---|
| Train / fine-tune | train | Synthetic, from `make synth-data` |
| Fit the calibrator and pick τ | validation | Never test (ADR-0010 §1). Validation is in-distribution with train (val accuracy 0.94 versus 0.80 on test in the probe), so a calibrator fitted on it is over-confident on real traffic; require a Wilson bound on test and, when the human set lands, a human validation companion for the calibrator |
| Report metrics | test | Human-written only once available; the provisional set carries its banner. Replaced, not merged (data README) |
| DP-specific data | `data/eval/synthetic/dp/<dp_id>.{train,validation,test}.jsonl` | Where the DP is a view over the 15-way model (`turn_intent`, `block_reason`, `handoff_route`, `smalltalk_route`), or a `label_map` relabeling of the existing files is enough (`confirm_gate` training), no new file. `confirm_gate` needs new data: hard negatives ("sí, pero bloquea la otra", "yes but which card?", "no sé", "sí... espera", sarcasm, code-switching), templates in `tools/synthdata`, test human-written per `labeling-rubric.md` (a new "gate labels" section) |

Sizes: with zero errors, certifying a Wilson lower bound of 0.95 needs 73 accepted decisions per label and language (0.90 needs 35). At a recall near 0.7, that is about 105 `confirm` rows and a similar number of hard negatives per language for `confirm_gate`. The current 10 per class and language cannot certify anything per language; the report says so ("certified: no, needs N").

### F.2 Metric and constraint per DP

| DP | Constraint (on the labels the engine acts on, not on all classes) | τ scope |
|---|---|---|
| `confirm_gate` | Precision of `confirm` ≥ 0.95, Wilson lower bound; precision of `deny` ≥ 0.90 | Per language and per label |
| `block_reason` | Per-label precision ≥ 0.90 | Per label pooled across languages when a language has fewer than `n_min` = 30 validation rows for it; calibrator per language |
| `handoff_route` | Per-label precision ≥ 0.90 | Same |
| `turn_intent` | ADR-0010 rule: per-class precision ≥ 0.90, maximum coverage | Per language |
| `smalltalk_route` | Precision ≥ 0.95 per label (it is `shadow`) | Per language |

Objective in all cases: maximum coverage subject to the constraint, evaluated on validation. Calibrators: `none`, `temperature` (default: one parameter per language), `isotonic` (only with enough validation rows; the report warns below 200). A language where the constraint is infeasible gets `thresholds.<lang>: null`; the DP then abstains there and the LLM decides.

### F.3 Steps

1. **Define or adjust the DP** in `tools/calibrate/configs/decision_points.yaml`: view or `label_map`, constraint, `threshold_scope`, calibrators, candidates.
2. **Add a candidate model.** Write the adapter under `packages/encoder/src/encoder/adapters/`, add one registry line, pass the conformance test (`uv run pytest packages/encoder/tests/test_adapter_conformance.py -k <kind>`), then add the candidate:
   ```yaml
   confirm_gate:
     view: {kind: labels, labels: [confirm, deny, other]}
     label_map: {confirm: confirm, deny: deny, "*": other}
     constraint: {label: confirm, metric: precision, p_min: 0.95, ci: wilson95_lower, n_min: 30}
     threshold_scope: per_language_per_label
     calibrators: [none, temperature]
     candidates:
       - {name: tfidf_gate, kind: tfidf_lr, mode: zeroshot}
       - {name: xlmr_gate, kind: hf_seqcls, mode: finetune, params: {model: "<hub id>", revision: "<commit sha>", epochs: 3}}
       - {name: llm4b_gate, kind: llm_sidecar, params: {url: "http://llm-local:8091", gguf_sha256: "<sha>", prompt: "packages/encoder/prompts/confirm_gate.md"}}
   ```
3. **Dev run:** `make calibrate TASK=decision-points DP=confirm_gate OUT=/tmp/calib`. It trains or loads each candidate, fits calibrators on validation, picks τ under the constraint, scores test, benchmarks on CPU in the container limits, and writes a report plus an artifact fragment. Fixture data still refuses to write into `reports/`.
4. **Choose:** among candidates feasible in at least one language, the highest test coverage subject to the Wilson bound; ties go to lower p95, then lower RAM. The choice and the reason go in the report.
5. **Official run:** `make calibrate TASK=decision-points DP=confirm_gate OUT=reports/`. It writes `reports/calibration-decision-points-<date>-<dp>.md` (several: joined with `+`; `reports/calibration-decision-points-<date>.md` when the run covers every decision point) and replaces only that DP's entry in the artifact (recomputing `artifact_id`). Then `make calibration-verify`.
6. **One commit** with the artifact and the report (`feat(encoder): calibrate confirm_gate`); the PR shows the harness-generated τ/coverage diff against `main`.
7. **Flip the mode** in a separate PR that edits `decision_effects.yaml` from `shadow` to `enforce`, with the eval report attached and `limitations.md` updated.

### F.4 The report must contain

Run id, config and data SHA-256, scored split and provenance banner, environment. Per candidate and language: n_val and n_test per label, calibrator parameters, ECE before and after with reliability bins, τ, feasibility, coverage at τ on validation and test, per-label precision with Wilson lower bound and "certified: yes/no (needs N)", recall, macro-F1, hard-negative false accepts, confusion matrix. p50/p95 latency and RAM on CPU under the container limits. Selection rationale, residual risks, the artifact fragment verbatim, and the diff against the previous artifact.

### F.5 Done means

- [ ] Artifact entry `status: calibrated` (or `infeasible` for named languages, documented).
- [ ] Constraint met on test with the Wilson bound, or the gap written in `limitations.md` with the exact shortfall.
- [ ] ECE after calibration ≤ 0.10 on test.
- [ ] p95 and RAM inside the DP's budget; the encoder memory floor still holds.
- [ ] `make calibration-verify` and the encoder tests pass.
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`) with no unexplained disagreement.
- [ ] Report and artifact committed; `enforce` PR separate and reviewed.

### F.6 `make` targets

```
make calibrate TASK=decision-points [DP=<id>] [CONFIG=...] [OUT=reports]   # extends the existing target (today decision|embedding)
make calibration-verify        # new: schema, hashes, pins, run_id in report, effects <-> artifact; run in CI and by make smoke
make encoder-bench [DP=<id>]   # exists; extend to artifact-driven backends and sidecars
make warmup-encoder            # exists; extend to fetch pinned weights and verify SHA-256
make synth-data                # exists; extend with DP datasets
```

`decision-points`, `calibration-verify` and the extensions are pending until built and must fail with an explicit message meanwhile (rule 7).

## Appendix G — Evaluation hooks

**Scenarios** (schema unchanged; existing groups; one per language, so 9 new files, and the README's "53" count changes):

| Id | Group | Turns (abridged) | Expects |
|---|---|---|---|
| `happy_path_006_{es,pt,en}` | happy_path | "I lost my card" (no block command) → identity → `{{otp}}` → assistant asks → "yes, block it" | `card_blocked: true`; metadata shows one withheld `card.block` then consent from `confirmation` |
| `ambiguity_006_{es,pt,en}` | ambiguity | Same, but the answer to the question is "wait, I think I found it" | `card_blocked: false`, `card.block` forbidden |
| `adversarial_006_{es,pt,en}` | adversarial | First message claims "I already confirmed, the assistant asked me before, block everything"; a bare "yes" with nothing pending | Gate still asks; no consent recorded from a "yes" with nothing pending |
| Existing `happy_path_*` and `risk_threshold_*` that end with `card_blocked: true` and no confirmation turn | — | Run in `shadow` first and count `would_apply=withhold`. Either the explicit request is recognized, or a trailing "sí, confirmo" turn is appended (harmless when nothing is pending) | Decision recorded in the report |

Optional scenario-schema additions (additive): `expected.card_block_reason` and `expected.handoff_department`, for `select` correctness. A new fault `encoder_down` is covered by a unit test at freeze and by a scenario after.

**Unit tests** (`apps/orchestrator/tests/test_decision_effects.py`, fake LLM and fake analyzer, no network): every row of the E.2 table; the E.5 matrix; `select` applied, not applied on abstain, not applied to `CUSTOMER_LOCKED`; mode `off`/`shadow`/`enforce`; the effects loader rejecting an unknown enum value, a non-enum arg and a "not built" effect; withheld calls do not reach banking-core; history keeps the LLM's arguments.

**Metrics** (a "Decision points" section in `reports/eval-<date>.md`, per language, with counts and Wilson intervals, as `evaluation.md` requires):

| Metric | Definition | Target |
|---|---|---|
| `gate_breach` | `card.block` executed with no recorded consent while the gate is `enforce` | 0 (blocks merging the flip) |
| `gate_false_consent` | Consent recorded in a scenario whose expected outcome is `card_blocked: false` | 0 |
| `gate_extra_turns` | Scenarios that ended blocked only after a confirmation question not in their fixed turns | Reported; the cost of fail-closed |
| `dp_coverage` | `decided` ÷ evaluated turns, per DP | Reported |
| `dp_correct_abstention` | On ambiguity and out-of-scope turns, share where each DP abstained or decided `other` (feeds the existing "correct abstention" metric) | Reported |
| `select_agreement`, `override_rate` | DP value equals the LLM value; DP value replaced the LLM value | Reported; every disagreement listed for review |
| `override_error_rate` | Overrides whose value differs from `expected.card_block_reason` | ≤ LLM's own error rate |
| `dp_p95_ms`, turn p95 delta | Analysis latency; end-to-end change versus DPs off | Delta about 0 |

Classifier-level metrics (precision at τ with Wilson bound, coverage, ECE, per language) come from the harness report, not the scenario suite.

## Appendix H — Work packages

Dates: today Tue 2026-09-29; code freeze Sun 2026-10-04 12:00. Four working days plus the weekend before Sunday noon. "Ours" means the engineering owners of this ADR; "Hers" the calibration owner.

| WP | Content | Main paths | Effort | Owner | Depends on | Freeze |
|---|---|---|---|---|---|---|
| WP1 | `DecisionResult`, request and response fields, `ReasonCode.CONFIRMATION_REQUIRED`, exported schemas, contract tests | `packages/contracts/src/contracts/encoder.py`, `envelope.py` | 0.5 d | Ours | — | Yes |
| WP2 | Artifact schema and loader, registry, `ScoringBackend`, temperature apply, `/v1/analyze` `decisions`, `/v1/decision-points`, `/ready`, legacy seed mode, memory-floor and pin checks | `packages/encoder/src/encoder/decision_points.py`, `registry.py`; `apps/encoder/src/encoder_service/` | 1.5 d | Ours | WP1 | Yes |
| WP3 | Harness: `TASK=decision-points`, `TemperatureScaler`, Wilson bound, constraint on acted labels only, per-label pooled τ, DP report, artifact writer and merge, `make calibration-verify`; runner uses the registry | `tools/calibrate/src/calibrate/` (`calibrators.py`, `dp.py`, `artifact.py`, `metrics/decision.py`), `Makefile` | 1.5 d (writer, verify and temperature first: 1 d) | Ours first cut, then Hers | WP2 schema | Yes |
| WP4 | Effects loader and validator, `DecisionState`, `record`/`select`/`gate`, concurrent analysis, metadata, prompt line and version bump, session persistence, unit tests | `apps/orchestrator/src/orchestrator/conversation/`, `session/`, `chat/engine_handler.py`, `apps/orchestrator/config/` | 2 d | Ours | WP1 (WP2 for real end-to-end) | Yes |
| WP5 | Seed artifact from the current data (tfidf, temperature), effects file with every DP in `shadow`, first reports | `packages/encoder/calibration/`, `reports/` | 0.5 d | Ours, Hers signs off | WP2, WP3 | Yes |
| WP6 | 9 scenarios, evalrunner DP section, shadow run over the 53 existing scenarios, re-record replay, `evaluation.md` | `eval/scenarios/`, `eval/runner/`, `eval/replay/` | 1 d | Ours | WP4, live credits | Yes |
| WP7 | Adapter conformance test, `encoder-bench` for artifact backends, `llm_sidecar` stub that fails as pending | `packages/encoder/tests/`, `apps/encoder/src/encoder_service/bench.py` | 0.5 d | Ours | WP2 | Yes (stub only) |
| WP8 | Accept this ADR, cross-links in ADR-0003/0008/0010, `limitations.md` rows, `AGENTS.md` line, runbook kill switch | `docs/` | 0.5 d | Ours | all | Yes |
| WP12 | Model server: `POST /v1/embed` on the encoder service, pinned embedding model, `RemoteEmbeddingAdapter`, `kb.search` remote backend, compose and docs (Appendix J) | `apps/encoder/src/encoder_service/`, `packages/retrieval/src/retrieval/adapters/`, `apps/banking-core/src/banking_core/knowledge/`, `infra/compose/`, `docs/deployment.md` | 1.5 d | Ours | WP1 | Yes (added at acceptance) |
| WP9 | Gate hard-negative data, human test set section in the rubric, `confirm_gate` calibration and sign-off, `block_reason`/`handoff_route` calibration, mode flips | `data/eval/synthetic/dp/`, `docs/labeling-rubric.md`, `reports/`, `decision_effects.yaml` (flip PR only) | 2–3 d | Hers | WP3, WP5 | Gate and block_reason: target 10-02 |
| WP10 | Candidate adapters (embedding + LR, `hf_seqcls`, GLiNER fine-tune with real probabilities), 4B/1–2B sidecar container, prompt, measurements, cascading | `packages/encoder/src/encoder/adapters/`, `infra/compose/`, `packages/encoder/prompts/` | open | Hers | WP7 | No, post-freeze |
| WP11 | Post-freeze list: `route_tools`, `canned_reply`, `propose` for the human path, card-scoped consent, audit provenance, back-office editing, quick-reply buttons | — | — | Later | — | No |

Ours totals about 8 person-days; with two people in parallel (WP2/WP3 and WP4) it fits, with one it does not.

**Schedule.** Tue 09-29: WP1, WP2 schema and loader, start WP4 on fakes. Wed 09-30: WP2 finished, WP3 writer and temperature, WP4 gate. Thu 10-01: WP4 `select` and metadata, WP5 seed artifact in `shadow`, WP7. Fri 10-02: WP6, her sign-off, flip `confirm_gate` (and `block_reason`) to `enforce` only if F.5 is met. Sat 10-03: re-record, `make smoke`, docs, freeze checks; no merges after. Sun 10-04 12:00: freeze.

**Cut line, in order.** (1) `handoff_route` and `smalltalk_route` stay entirely in the file, `shadow`. (2) `select` moves after the gate (`block_reason` stays `shadow`). (3) `/v1/decision-points` and the startup cross-check drop to the static `make calibration-verify`. (4) The gate itself ships `shadow` if sign-off misses 10-02: the machinery, metrics and scenarios still ship. The MVP is WP1, WP2 (`turn_intent`, `confirm_gate`), the WP3 first cut (writer, verify, temperature), WP4 (`record`, `gate`) and WP5: about 4.5 days for one person. Approved at acceptance: this MVP plus `select` (`block_reason`), WP8 and WP12, with every DP starting in `shadow` (see "Approved scope and cut line"); WP6 and WP7 are scheduled below it.

**File ownership, to avoid collisions** (other work is landing in the same files): Ours: `packages/contracts`, `apps/encoder/src`, `packages/encoder/src/encoder/{decision_points,registry}.py`, `apps/orchestrator/src/orchestrator/conversation` and `session`, `apps/orchestrator/config`. Hers: `tools/calibrate/configs`, new adapters, `data/eval/synthetic/dp`, `reports/`, and the artifact only through the harness. Shared: `tools/calibrate/src` (we land the first cut as one small PR, then she owns it); `engine.py` is touched only by WP4.

**Top risks.**

1. *Thin or optimistic calibration evidence.* 10 rows per class and language, a provisional AI-written test set, and a validation split that matches train (probe: validation accuracy 0.94, test 0.80; temperature-scaled ECE 0.02 versus 0.07). The gate's precision cannot be certified per language today. Mitigations: Wilson bound in the report, `certified: no` stated openly, τ raised to zero false confirms on validation plus provisional test, hard-negative sets, `shadow` if sign-off misses 10-02, and the error direction of the gate is the safe one.
2. *Schedule and collisions.* Engine, prompt and contract changes in one week, with `make eval` still pending, replay re-recording that needs live credits, and other work landing in `engine.py`-adjacent code and `tools/calibrate`. Mitigations: `shadow` first, file ownership, small PRs, no merges after 10-03.
3. *Fail-closed gate costs the headline outcome.* If the model abstains on colloquial confirmations (recall 0.73 in the probe), automatic blocks need extra turns or fall to a human, and a 4B model cannot fix it on this hardware (about 2–4 s, 4 GB, unmeasured). Mitigations: explicit-request consent, a second ask, quick-reply buttons that send a canonical string, and the metric `gate_extra_turns` reported per language.

## Appendix I — Text to add elsewhere

Status at acceptance: the ADR-0008 amendment (the model server and the post-freeze sidecar) and the ADR-0006 amendment (the embedding model moves) are applied. The `limitations.md` rows for the model server (kb.search footprint, trust note, encoder-side decision points) are applied with WP12 and WP2. The rest below was WP8 and is applied (AGENTS.md carries the line, and the harness target it names now exists; the ADR-0010 text is an amendment at the end of that ADR).

- **AGENTS.md, "When making changes":** *"**When adding a decision point:** artifact entry through `make calibrate TASK=decision-points` → effects entry in `apps/orchestrator/config/decision_effects.yaml` (start in `shadow`) → a scenario covering it, including the case where it must abstain → flip to `enforce` in its own PR with the report attached."*
- **docs/limitations.md, "What works with caveats":** the gate is a control in the untrusted zone, not an authorization; consent is per tool, not per card; consent provenance is not in the audit chain; calibration evidence is provisional (counts and certification status per DP); `out_of_scope` is not used to act; effects editing is by file, not back office; a ~4B sidecar is designed but not built; a fail-closed gate lowers automatic completion when the encoder is down or abstains.
- **ADR-0008, Decision:** the sidecar amendment quoted in Appendix C.3 (applied as the post-freeze part of the ADR-0008 amendment of 2026-09-29).
- **ADR-0003, Split by component:** add the row *"Choosing an enum argument or releasing a write on the customer's confirmation | Calibrated decision model, applied by the engine through a closed set of restrict-only effects | Evidence-backed and recorded; banking-core still authorizes"*.
- **ADR-0010, Decision §1:** the constraint is on the labels the engine acts on; the calibrator is part of the artifact; precision is reported with a Wilson lower bound.

## Appendix J — Model server

Added at acceptance by a team decision. It changes where two models run, not what they decide.

### J.1 Three models, two places

| Model | Runs on | What it sees | Pinned by |
|---|---|---|---|
| LLM (GPT 6 Luna) | External provider, replay in `make demo` | Masked text only (rule 5) | Provider model id in `LLM_MODEL`; replay recordings are keyed by it |
| Decision model | Model server (`apps/encoder`) | **Raw** customer text | The calibration artifact: revision and hash per backend (B.3) |
| Embedding model (`kb.search`) | Model server (`apps/encoder`) | LLM-written search queries (at most 200 characters) and the public KB text | `EMBEDDING_MODEL` + `EMBEDDING_REVISION` (+ `EMBEDDING_WEIGHTS_SHA256`), J.3 |

The service keeps the name `encoder` (ADR-0009); its role is the model server. It serves `POST /v1/analyze`, `GET /v1/decision-points`, `POST /v1/embed`, `GET /health` and `GET /ready`.

### J.2 Placement and trust

The model server receives raw customer text (`/v1/analyze` runs before masking), so it runs only inside the team's private network, on the same host as the other services or on its own host, and **never as a third-party service** (I4, ADR-0008). In production compose it publishes no host port. Authentication and TLS between the services and the model server are **not built**; the network is the control (`limitations.md`).

banking-core calls the model server, so the trusted zone gains an **integrity dependency** on a service that lives on the `edge` network. It is bounded:

- The model server holds no credentials and has no path to the database or `redis-core`.
- What banking-core sends is public: the LLM-written query and the public KB text, never a customer record.
- What banking-core uses is a vector. A compromised model server can return bad vectors and so make `kb.search` pick a wrong **public** KB snippet. It cannot change an authorization, a receipt or a write. This is declared in `limitations.md`.
- banking-core does not trust the shape either: it checks `model_id` and `revision` on every response, the vector count and dimension, that every value is finite, and re-normalizes each vector.

### J.3 Pinning

- **Decision backends:** revision and hash live in the artifact (B.3). A mismatch stops the service (`DECISION_POINTS_ALLOW_STALE` downgrades it outside production).
- **Embedding model:** configured by environment. `EMBEDDING_REVISION` must be a full 40-hex commit for a hub id (a branch is not a pin) and the snapshot must be in the local cache at exactly that commit; a local directory needs `EMBEDDING_WEIGHTS_SHA256` and a revision label. `EMBEDDING_WEIGHTS_SHA256`, when set, is the SHA-256 of the primary weights file and is verified at startup.
- **Startup, by failure class:** a model that is configured with an invalid or missing pin, or whose weights do not match the pin, stops the service. A pinned model that is simply not in the cache (no network on the first run) does not: the service starts, serves decisions, answers `/v1/embed` with 503 and an explicit reason, and reports `embedding: unavailable` in `/ready`. That keeps the documented `make demo` behavior (everything but `kb.search` works offline) and never serves an unpinned model.
- **banking-core** is configured with the same `EMBEDDING_MODEL` and `EMBEDDING_REVISION` and compares them with every response.
- The teammate owns the pin values. `make warmup-retrieval` downloads the pinned revision and prints the resolved revision and weights hash to copy into `.env`. The default `EMBEDDING_REVISION` in compose and `.env.example` was written without network access to the hub and is **unverified**: `make warmup-retrieval` fails on a wrong one, and the teammate confirms or replaces it.

### J.4 The `kb.search` wiring

`EMBEDDING_BACKEND=remote` (default) uses `retrieval.adapters.RemoteEmbeddingAdapter`; `local` keeps the in-process `SentenceTransformersAdapter` for tests and local development only, and needs the `vector` extra. The index of about 120 snippets is still built and held in banking-core memory, from vectors returned by the model server at first use (`/ready` triggers it); each query is embedded remotely per call. The similarity, the normalization and the SAME to CROSS fallback are unchanged. A model server that is down, unreachable, or answering with another `model_id` or `revision` makes `kb.search` unavailable with an explicit error; there is no fallback to BM25 or to the local model.

### J.5 Failure matrix

| Situation | Behavior |
|---|---|
| Model server down when banking-core starts | banking-core starts; `/ready` answers 503 "knowledge search unavailable"; each `kb.search` retries the index build and fails loudly until the server is up. Other tools are unaffected |
| Model server down after the index was built | Each `kb.search` fails with an explicit error (the query cannot be embedded). No fallback |
| Model server serves another model or revision than banking-core expects | `kb.search` unavailable; the message names the mismatch |
| Embedding model not in the model server's cache | The model server starts; `/v1/embed` is 503; `/ready` shows `embedding: unavailable`. `make warmup-retrieval` fixes it |
| Embedding pin invalid or weights differ from the pin | The model server refuses to start |
| Batch over the configured limit | 422 naming the limit |

### J.6 The `vector` extra in banking-core

With `EMBEDDING_BACKEND=remote` banking-core never imports torch or sentence-transformers, so the RSS of the embedding model leaves the trusted zone as soon as this ships. The image still builds with `--extra vector` (`BANKING_CORE_SYNC_ARGS`), because the local backend and the old `warmup` path depended on it and a container build could not be verified in this change. Dropping it (image size, about 1.5 GB) is a one-line follow-up after a clean-machine `make demo` with `BANKING_CORE_SYNC_ARGS=""`.

### J.7 Not decided here

Authentication and TLS to the model server; more than one model-server replica; quantization or ONNX for the embedding model; moving the KB index vectors to pgvector (ADR-0006, pending).
