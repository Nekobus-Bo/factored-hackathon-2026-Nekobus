# ADR-0014: Pooled DistilBERT as the decision backend, locale-keyed thresholds, and the hint and clarification effects

**Status:** Accepted · amended 2026-10-01 ([below](#amendment-2026-10-01-intent_hint-and-clarify_route-in-enforce-without-an-evaluation-run)) · **Date:** 2026-09-30 · **Deciders:** TODO (team)

**Amends:** [ADR-0012](0012-decision-points.md) (`hf_seqcls` moves before the freeze; `hint` and `canned_reply` are built, in `shadow`; threshold keys may be locales), [ADR-0010](0010-model-selection-calibration-harness.md) §5 (how weights are published), [ADR-0008](0008-cpu-inference-deployment.md) (weights are baked into the encoder image), [ADR-0001](0001-cheap-llm-specialized-encoder.md) (the decision model and the "structured context").

## Context

[ADR-0001](0001-cheap-llm-specialized-encoder.md) named GLiNER as the leading decision model, and [ADR-0012](0012-decision-points.md) shipped the decision points on `tfidf_lr`, trained on template data. The regional work ([reports/intent-models-regional-datasets.md](../../reports/intent-models-regional-datasets.md)) measured something better:

- **The model.** One multilingual DistilBERT (`lxyuan/distilbert-base-multilingual-cased-sentiments-student`, new 15-way head) fine-tuned on the pooled grounded datasets (pt-BR, es-MX, es-AR; 4,500 train rows).
- **The result.** Mean accuracy 0.76 over six evaluation sets at about 10 ms per message on CPU. It is best on all three provisional tests, and zero-shot models collapse on real text. Out-of-scope recall on real text (0.47–0.75) is a known, declared gap.

Three things keep it out of the app today:

1. The weights exist only in a notebook's memory, and the notebooks never kept the softmax, so no τ was ever fitted for this model.
2. The decision-point machinery keys τ and the calibrator by language only (`es`, `pt`, `en`). The datasets are per market, and a Mexican and an Argentine customer share one τ.
3. [ADR-0012](0012-decision-points.md) left out two things before the freeze:
   - the `hint` effect, which gives the LLM the classification ADR-0001 promised;
   - the `canned_reply` effect, which asks for clarification on abstention, as ADR-0003 says.

   It cut them because they change what the LLM sees and `make eval` cannot yet show them safe.

## Decision

1. **The pooled DistilBERT is registry kind `hf_seqcls`.**
   - It is trained offline by a script ported from the notebook, then pinned: the harness still does not fine-tune anything but `tfidf_lr`.
   - It serves `turn_intent`, `block_reason`, `handoff_route` and `smalltalk_route` from a second artifact, `packages/encoder/calibration/decision_points.distilbert.json`, selected by `DECISION_POINTS_FILE` (ADR-0012 B.1).
   - `confirm_gate` keeps its own `gate_tfidf` backend.
   - Slots and PII spans stay on the legacy `ENCODER_BACKEND` path (ADR-0012 C.1).
   - It classifies `es`, `pt` and `en`. English has no grounded training rows; its τ comes from the template English validation rows, and when that τ is infeasible the decision points abstain in English.
2. **Weights ship inside the encoder image, from a weights-only seed image.**
   - The trained directory (weights, tokenizer, and a manifest with per-file SHA-256) is packed once into a `FROM scratch` image. That image is published on Docker Hub, public and multi-platform (amd64 and arm64), and referenced by digest. Anonymous Docker Hub pulls are rate-limited per IP; one pull per clean build is well inside the limit.
   - `apps/encoder/Dockerfile` copies it in a layer placed before the dependency and code layers. Code-only rebuilds reuse that layer, and only a retrain produces a new seed image.
   - At runtime the weights never need the network.
   - The pin chain is: the Dockerfile's digest → the manifest → the artifact's `revision` (`<name>:<12 hex of the manifest SHA-256>`) and `weights_sha256`.
   - The service stops at startup on any mismatch, as ADR-0012 B.1 already requires.
3. **Threshold and calibrator keys may be locales.**
   - The closed set is `pt-BR`, `es-MX`, `es-AR`, `es-CO` and `en-US`. A key is chosen as the first present of locale, then language, then `*`.
   - A key present with `null` means infeasible: the decision point abstains and does not fall back.
   - τ and temperature always come from the same key.
   - `locale` becomes an optional field of the chat and encoder contracts, from which the language is derived.
   - es-CO and en-US have no grounded data and resolve to `es` and `en`.
4. **`hint` and `canned_reply` are implemented and bound to two new decision points, `intent_hint` and `clarify_route`, both shipped in `shadow`.**
   - `hint` passes one categorical line to the LLM: the decided intent, or `uncertain` on abstention. It never carries a number or text.
   - `canned_reply` answers an abstention with a fixed localized question and makes no LLM call, only before the LLM has engaged in the conversation (Appendix B).
   - `enforce` for either one is a separate reviewed diff that edits only `decision_effects.yaml`, with an evaluation run attached (ADR-0012 F.3 step 7).
5. **Masking gains Mexican and Argentine identifiers** (CURP, RFC, CUIT/CUIL) and the MXN and ARS currency cues. A locale is not safe to serve until they exist ([AGENTS.md](../../AGENTS.md) rule 5).

Invariants I1–I5 of ADR-0012 hold unchanged. The hint is context, not authority, and the canned reply only asks: neither calls a tool nor widens what banking-core accepts.

## Options considered

| Option | Why not chosen |
|---|---|
| A new `ENCODER_BACKEND=distilbert` on the legacy path | It would bypass the artifact, the per-decision-point τ and the pins that ADR-0012 built for exactly this |
| Weights from the Hugging Face cache via `make warmup-encoder` | It needs network at first start and a volume; the team wanted a self-contained image |
| Weights in Git LFS | The free quota (1 GB storage, 1 GB/month bandwidth) is spent by every clone and every CI run |
| Build from the local weights directory only | A clean machine cannot build the image, which fails the runbook's clean-machine check |
| `hint` and `canned_reply` after the freeze (ADR-0012 as written) | It leaves ADR-0001's "structured context" and ADR-0003's clarification unbuilt. `shadow` removes the risk that motivated the cut, because outbound messages stay byte-identical |
| `enforce` before the freeze | `make eval` is still a stub, and the replays would need re-recording with live credits. Reversed for `intent_hint` and `clarify_route` on 2026-10-01 (amendment below) |

## Trade-off analysis

**The model.** The deciding axis is measured quality on real text at CPU cost. The pooled model is about 50× more costly than `tfidf_lr` in latency (10 ms against 0.2 ms), still well inside the turn budget. On real Brazilian complaints the template-trained models score 0.08, and on the provisional tests the pooled model gains 4 to 5 points over any single-country model.

**The weights.** A seed image costs one public Docker Hub repository. In return, a clean machine needs no cache, no token and no network at runtime.

**The effects.** Building them before the freeze adds orchestrator code in the last week. `shadow` keeps every outbound message and replay key unchanged until evidence exists, which was the reason for the cut.

## Consequences

**Becomes easier:**
- the same model and the same pins serve every environment;
- τ can be tuned for a market;
- the hint and the clarification can be switched on with one reviewed line, once evidence exists.

**Becomes harder:**
- The encoder image grows by about 0.55 GB.
- The seed image must stay public and multi-platform, or every encoder build breaks.
- A retrain is a new digest, a new calibration and, once an effect is `enforce`, a re-record of the replays. With `hint` in `enforce`, recordings are bound to the (weights digest, `artifact_id`) pair.
- The training data (`data/staging/`) is not versioned. Retraining needs the local datasets, or the LLM cache, or new paid calls; the manifest records their hashes. `make calibration-verify` warns, not fails, when those unversioned evidence files are absent.
- The weights are derived from public complaint and review text. The seed image may only be made public once the terms of those sources allow it.

**To revisit:**
- an ONNX or int8 build, if the measured RAM or p95 exceeds the encoder budget;
- a per-locale model, if the pooled model loses a market by more than its seed spread on human-labelled data.

## Action items

1. [x] Training script, `hf_seqcls` adapter, manifest and registry entry, with a conformance test on a tiny model
2. [x] Seed image build and push (`make encoder-weights-image`), Dockerfile stage, compose defaults
3. [x] Locale keys in the artifact, the harness and `decide`; the DistilBERT artifact and its report
4. [x] `locale` through the contracts, the orchestrator and the eval runner
5. [x] CURP, RFC and CUIT/CUIL masking
6. [ ] `hint` and `canned_reply` effects in `shadow` and scenarios (done); **the live evaluation run is pending** (no LLM key: dry run only)
7. [x] `limitations.md`, `evaluation.md`, `runbook.md`, `deployment.md`

### Implementation status (rule 7)

| What this ADR names | Status |
|---|---|
| `hf_seqcls` kind, `encoder.weights` manifest, `make pool-data-regional`, `make train-encoder`, `make encoder-weights-image` | landed. The trained model reproduces the report (mean accuracy 0.777 over its six sets against 0.761) |
| Seed image `docker.io/paodanchacon/pattern_blue-encoder-weights@sha256:459d30a9…` (amd64, arm64), the `weights` stage of `apps/encoder/Dockerfile`, compose and deploy defaults (`embed hf`, the DistilBERT artifact), `make warmup-encoder` verifying the artifact's pins | landed |
| `packages/encoder/calibration/decision_points.distilbert.json` and `reports/calibration-decision-points-2026-09-30-distilbert.md` | landed; nothing certified |
| Locale keys (`resolve_key`), `locales:` and `report_tag` in the harness, `locale` in `AnalyzeRequest`, the chat API, the session, the Zod mirror and the eval runner | landed (the Zod tests were not run: no bun on the dev host) |
| `hint` and `canned_reply` effects, `intent_hint` and `clarify_route` in both artifacts | landed; in `enforce` since 2026-10-01 (amendment below) |
| CURP, RFC and CUIT/CUIL masking | landed |
| The live evaluation before and after `enforce`, and replay recordings | pending (needs an LLM key) |

---

## Amendment 2026-10-01: `intent_hint` and `clarify_route` in `enforce`, without an evaluation run

**Decision.** `intent_hint` (`hint`) and `clarify_route` (`canned_reply`) move from `shadow` to `enforce` in `apps/orchestrator/config/decision_effects.yaml`, the default every environment loads: the local stack, `make demo` and Cloud Run. The other five decision points stay in `shadow`. The team wants the DistilBERT to have a visible effect in the presentation, and these two are the least risky:

- `hint` is context, not authority: one categorical line (the decided intent, or `uncertain`), never a number or customer text, never written to history.
- `canned_reply` only asks: before the LLM has answered, at most once, never with a gate, an OTP challenge or a tool result in flight (Appendix B).
- Neither calls a tool or widens what banking-core accepts. Invariants I1–I5 of ADR-0012 hold.

**Not met, declared.** Two requirements of [ADR-0012](0012-decision-points.md) Appendix F are not met:

- **No evaluation run is attached** (F.3 step 7). `make eval` is a stub, and the runner's `proposed` system replays the LLM and has no recordings.
- **Neither decision point is certified** (F.5): 0 of 45 scopes of `intent_hint` and 0 of 21 of `clarify_route` clear the Wilson bound ([report](../../reports/calibration-decision-points-2026-10-01-clarify_route+intent_hint.md)); the test sets are too small to certify anything.

This reverses the "`enforce` before the freeze" row of the options above, for these two only, and the gap is in [limitations.md](../limitations.md).

**Consequences.**

- What reaches the LLM changes: one more system line on every turn where `intent_hint` decides or abstains with a τ.
- A vague opening can get the fixed localized question with no LLM call.
- A wrong hint can steer the LLM's wording or its choice of the next step, but not an authorization: banking-core still decides every tool call.
- A wrong abstention costs one unnecessary question.
- Replays, once recorded, are bound to the (weights digest, `artifact_id`) pair, as above.

**Kill switch.** `DECISION_POINTS_MODES=intent_hint=shadow,clarify_route=shadow` ([runbook](../runbook.md)): an environment change, no code change. On Cloud Run it is the `decision_points_modes` variable and `make gcp-apply`.

**Action item.** The live evaluation of action item 6, `shadow` against `enforce` for these two, is still the evidence for keeping them on. A worse result reverts this amendment.

---

## Appendix A — Seed image and pin chain

```
packages/encoder/weights/distilbert-intent-pooled/      (gitignored, written by make train-encoder)
  config.json  model.safetensors  tokenizer.json  tokenizer_config.json  special_tokens_map.json  vocab.txt  manifest.json
        |  make encoder-weights-image: verify manifest -> buildx --platform linux/amd64,linux/arm64 -> push
        v
docker.io/<namespace>/pattern_blue-encoder-weights@sha256:<digest>   (FROM scratch; context is the directory above)
        |  apps/encoder/Dockerfile: ARG ENCODER_WEIGHTS_IMAGE (the single source of the digest)
        v
/app/packages/encoder/weights/distilbert-intent-pooled/   (inside the encoder image)
        |  registry: resolve_pinned_model (weights SHA-256 + revision label) -> verify_manifest -> labels == Intent
        v
artifact backend intent_distilbert {revision: "distilbert-intent-pooled:<12 hex>", weights_sha256, params.weights_image}
```

The manifest holds:
- the base model and its 40-hex commit;
- the labels in id order;
- the SHA-256 and row count of each training split;
- the hyperparameters (4 epochs, AdamW 5e-5, batch 32, seed, 128 tokens to train, 256 to score);
- the library versions and validation metrics per locale;
- a SHA-256 for every file.

Serving and calibration both truncate at 256 tokens, the value the report measured.

## Appendix B — The clarification condition and the hint

**Clarification.** `canned_reply` fires only when every one of these holds, evaluated after masking and before the first LLM call:
1. `clarify_route` is in `enforce`.
2. Its outcome is `abstained` and it has a τ. Unavailable, infeasible and `off` never fire it.
3. The LLM has not answered any turn of this conversation yet.
4. Fewer than `max_consecutive` canned replies have been sent (default 1). After that, the LLM takes over, with the `uncertain` hint.
5. No gate is pending, no OTP challenge is pending, and the history holds no tool result.

**Hint.** In `enforce`, the hint is one system message placed after the system prompt. It holds only the decided intent label (validated against `Intent`) or `uncertain`, is never written to history, and is omitted when the decision point is unavailable or has no τ. In `shadow`, both effects compute and record `would_apply` and change nothing that is sent.
