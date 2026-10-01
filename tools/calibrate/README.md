# Model Calibration Harness

Calibration harness for the local models of Pattern Blue: **decision points** (the calibrated decisions of [ADR-0012](../../docs/adr/0012-decision-points.md)), the decision model (intent classification and slot extraction) and the embedding models (policy retrieval).

Per [ADR-0001](../../docs/adr/0001-cheap-llm-specialized-encoder.md), [ADR-0008](../../docs/adr/0008-cpu-inference-deployment.md), and [ADR-0010](../../docs/adr/0010-model-selection-calibration-harness.md), all runtime inference, latency, and RAM benchmarks execute strictly on CPU, while fine-tuning leverages local Apple Silicon MPS acceleration when available.

| Task | Command | Writes |
|---|---|---|
| Decision points | `make calibrate TASK=decision-points` | `reports/calibration-decision-points-<date>.md` and the artifact `packages/encoder/calibration/decision_points.json` |
| Verify the artifact | `make calibration-verify` | nothing; exits non-zero on a finding |
| Decision model | `make calibrate TASK=decision` | `reports/calibration-decision-<date>.md` |
| Embedding model | `make calibrate TASK=embedding` | `reports/calibration-embedding-<date>.md` |

---

# Decision points (ADR-0012)

A **decision point** (DP) is a named decision such as `confirm_gate` ("did the customer say yes?") or `block_reason`. Each one has its own label view, backend, confidence calibrator and threshold τ per language. They live in one **calibration artifact**, `packages/encoder/calibration/decision_points.json`, which **only this harness writes** and only the encoder service reads (at startup). You never edit it by hand: its `artifact_id` is a hash of its content, and a hand edit stops the service and fails `make calibration-verify`.

You calibrate; you do not edit `apps/orchestrator` or `main.py`. What each DP *does* (record, select, gate) and whether it is `shadow` or `enforce` is the orchestrator's effects file, changed by a separate reviewed PR.

## Where things are

| What | Where |
|---|---|
| What a run asks: views, candidates, constraints | `tools/calibrate/configs/decision_points.yaml` (no thresholds in it: τ is *found*) |
| The result the service reads | `packages/encoder/calibration/decision_points.json` (+ `decision_points.schema.json`) |
| The evidence for it | `reports/calibration-decision-points-<date>[-<dp>].md` |
| Backends (a model behind a `kind`) | `packages/encoder/src/encoder/registry.py`, adapters in `packages/encoder/src/encoder/adapters/` |
| Data | `data/eval/synthetic/` (`decision.{train,validation}.jsonl`, `decision.test.provisional.jsonl`; DP-specific files go in `data/eval/synthetic/dp/`) |
| The harness | `tools/calibrate/src/calibrate/` (`dp.py` pipeline, `thresholds.py`, `calibrators.py`, `artifact.py`, `verify.py`, `dp_report.py`) |

## Run one

From the repository root:

```bash
# Dev run: writes the report and a merged copy of the artifact under OUT. The committed artifact is not touched.
make calibrate TASK=decision-points OUT=/tmp/calib
make calibrate TASK=decision-points DP=confirm_gate OUT=/tmp/calib        # one or more DPs: DP=a,b

# Try a dev artifact in a local encoder service without touching git
# (paths in the artifact are relative to the repository root, so start it from there):
DECISION_POINTS_FILE=/tmp/calib/decision_points.json \
  uv run --package encoder-service uvicorn encoder_service.main:app --port 8090
curl -s localhost:8090/v1/decision-points        # config_version = the dev artifact_id

# Official run: OUT=reports (the default). Merges the DPs into the committed artifact.
make calibrate TASK=decision-points DP=confirm_gate
make calibration-verify
```

An **official** run is one whose `OUT` is the repository's `reports/` directory; it replaces only the DPs it ran in the committed artifact and recomputes `artifact_id`. Anything else is a **dev** run. Fixture data (`tools/calibrate/fixtures/`) is refused for `reports/`.

Run from a **clean git tree**: the artifact records `harness.git_sha` (with `-dirty` if tracked files differ). A run is deterministic: the same config and data give the same `run_id`.

Two checks stop a merge that would leave the artifact inconsistent: the existing file must be valid and unedited, and a backend cannot change (a retrained model, a new train hash) under a DP that is not in the same run, because a τ never travels without the model it was fitted on. Omit `DP=` to recalibrate everything that shares the backend.

### Without PyTorch

The decision-points task and `calibration-verify` never import PyTorch (a test guards that), but `uv run --package calibrate` installs it. Where the PyTorch wheels cannot be downloaded, build an environment by hand and skip the sync:

```bash
uv sync --frozen --package encoder-service          # tfidf_lr, scikit-learn, pydantic; no torch
uv pip install psutil pyyaml pytest pytest-asyncio httpx ruff   # from PyPI
uv pip install --no-deps -e tools/calibrate
make calibrate TASK=decision-points OUT=/tmp/calib UV_RUN_FLAGS=--no-sync
make calibration-verify UV_RUN_FLAGS=--no-sync
.venv/bin/python -m pytest -q tools/calibrate        # PyTorch-only tests are skipped
```

## What a run does

For each DP and each candidate backend (ADR-0012, Appendix F):

1. **Builds the backend through `encoder.registry`**, the call the service makes at startup. A candidate that calibrates here loads there.
2. **Fits a temperature per language on validation.** `p ** (1/T)`, renormalized, applied to the backend's whole distribution before the view aggregates it. The raw TF-IDF model is under-confident (T ≈ 0.19 sharpens it). A language with fewer than `calibrator_min_rows` validation rows gets no calibrator, so the DP abstains there.
3. **Chooses τ on validation: maximum coverage subject to the precision constraint on the *acted* labels** (the labels the engine acts on, not all classes). `threshold_scope` decides the shape: one τ per language (`per_language`), one per language and label (`per_language_per_label`), or per label pooled across languages when a language has fewer than `n_min` validation rows of it (`per_label_pooled`). A language where nothing satisfies the constraint gets `null`: the DP abstains there and the LLM decides.
4. **Scores test at that τ.** Coverage, precision with its Wilson 95% lower bound, recall, ECE before and after, macro-F1, a confusion matrix, and whether the constraint is **certified**.
5. **Picks a candidate** (feasible first, then most certified scopes, then the highest test coverage on the acted labels, then lower p95, then lower RAM), writes **one report** and **merges the DP entries** into the artifact.

Every confidence and decision is computed by `encoder.decision_points.decide`, the function the service runs, so a number in the report is the number it serves. Test is never used to fit or to choose τ (ADR-0010 §1).

### Selection versus certification

Two different questions, deliberately apart:

- **Selection** (`constraint.ci`, on validation): how τ is picked. `point` uses the raw precision; `wilson95_lower` uses the Wilson lower bound and is stricter.
- **Certification** (always, on test): the **Wilson 95% lower bound** of precision must reach `p_min` for every acted label in every scope that has a τ. Certifying 0.95 needs at least **73** accepted decisions with zero errors (0.90 needs 35). The current test set has 10 rows per intent and language, AI-written (`synthetic-provisional`), so **nothing certifies today** and every report says so, with the number it still needs.

The seed config selects with `point` and a lowered `n_min` (10, the rows that exist), because `wilson95_lower` cannot be met with ten validation rows. When validation is large enough (about 73 accepted rows per label and language), set `ci: wilson95_lower` and `n_min: 30` back and recalibrate.

## Read the report

`reports/calibration-decision-points-<date>.md`, top to bottom:

- **Banner and provenance.** The test split's provenance (`human`, `synthetic`, `synthetic-provisional`), the run id, the config and data SHA-256s. If the banner says provisional, read every precision number as an estimate.
- **Certification status.** One row per DP: `certified` yes/no and how many scopes clear the Wilson bound.
- **Summary.** Per DP and language: τ, T, coverage on validation and test, *acted* coverage on test (decisions on acted labels ÷ all rows), ECE before → after.
- **Per DP:**
  - *Calibrator*: T and the log loss before → after. "At the search bound" means the fit is not identified.
  - *Thresholds*: τ and what it was fitted on (language or pooled). **"not binding"** means the constraint rejected nothing on validation, so τ is only the lowest confidence seen and validation says nothing about how low is safe. That is the signature of a validation set that is too easy (it shares its generating process with train); trust test and the Wilson bound, not that τ.
  - *Precision on test*: per label, decided / correct / precision / **Wilson 95% lower** / recall / floor. A precision of 1.0 on 7 decisions has a lower bound of 0.65.
  - *Certification*: per scope and label, "needs N" is the number of accepted zero-error decisions still missing.
  - *Reliability* and *confusion*: calibration by confidence bin, and truth versus decided label on test (`(abstained)` is its own column, `(outside the view)` a row for utterances no label of a group view covers).
  - *Hard negatives*: not measured until a hard-negative set exists (WP9). Unknown is not zero.
  - *Artifact fragment*: the entry as written, **verbatim**. `make calibration-verify` looks for this exact text.
  - *Diff against the previous artifact*: what changed for this DP.
  - *Definition of done (F.5)*: the checklist, with the measurable boxes filled in.
- **Residual risks.**

## Add a candidate backend (a new model)

A candidate is a model behind a registry `kind`. The service and the harness build it the same way, so it is written once.

1. **Write the adapter** in `packages/encoder/src/encoder/adapters/` implementing `encoder.base.DecisionAdapter`. Declare the class attributes `kind` and `probability_kind`:
   - `distribution`: `predict` fills `probabilities` for **every** label of the backend, summing to 1 (±1e-3). Required for temperature calibration and for group views.
   - `top1_only`: only the top label and its confidence mean anything (GLiNER today). Such a candidate needs `calibrator: none`, a `labels` view and `labels:` naming exactly the backend's labels; τ is a plain threshold.
2. **Register it** with one line in `packages/encoder/src/encoder/registry.py` (`register("my_kind", lazy_loader)`; import the model library inside the loader so `tfidf_lr` never loads PyTorch). An artifact names a `kind`, never an import path. Hub models must be pinned by a full 40-hex commit (`revision`) and the weights hash (`weights_sha256`): a branch is not a pin.
3. **Pass the conformance test.** Add one entry to `BUILDERS` in `packages/encoder/tests/test_adapter_conformance.py` and run `uv run pytest packages/encoder/tests/test_adapter_conformance.py -k my_kind`.
4. **Add the candidate to the config**, under `backends:` and in the DP's `candidates:` (several candidates in a DP are compared and the best is chosen):

   ```yaml
   backends:
     xlmr_gate:
       kind: my_kind
       model_id: "my-model@2026-10"      # human-readable id (with the revision or hash)
       revision: "<40-hex commit>"
       weights_sha256: "<sha256 of the primary weights file>"
       probability_kind: distribution
       timeout_ms: 500                   # per-call budget; a timeout is `unavailable`
       params: {model: "org/name"}       # adapter kwargs
   decision_points:
     confirm_gate:
       candidates: [gate_tfidf, xlmr_gate]
   ```

   The harness builds candidates through the registry, so **fine-tuning is not run by `TASK=decision-points`**: train and pin the weights first, then point the candidate at them. `mode: finetune` for anything but `tfidf_lr` fails with `pending:`. The `isotonic` calibrator and cascading (`escalate_to`) are also `pending:`, as in the loader.
5. **Dev-run it and compare:** `make calibrate TASK=decision-points DP=confirm_gate OUT=/tmp/calib`. The report's candidate table and rationale show why one won. A real GLiNER or transformer candidate has not been run through this path in the sandbox that built it (no model download); the plumbing is tested with a fake `top1_only` adapter.
6. `make encoder-bench` for artifact-driven backends is still pending (WP7), so p95 and RAM in the report are host measurements of one process, not the container limits. Check them under the limits before you trust a heavy candidate.

## Add or change a decision point

Add the DP to `decision_points.yaml` (view: `labels` or `groups` over the backend's labels; a `label_map` relabels intents into the view, as `confirm_gate` does; `constraint`; `threshold_scope`), calibrate it, and follow the effects steps below. A DP that needs its own data sets `data:` with the three paths (for example `data/eval/synthetic/dp/<dp_id>.{train,validation,test}.jsonl`). Paths are relative to the repo root, and **only `data/eval/synthetic/decision.train.jsonl` is copied into the encoder image**: a `tfidf_lr` backend that trains from another file will not start in the container until the Dockerfile copies it.

When the human-written test set lands it **replaces** `decision.test.provisional.jsonl` in the config (the provisional file is deleted, not merged), and every DP is recalibrated.

## What "done" means (Appendix F.5)

A DP is ready for a sign-off when every box is true for its report:

- [ ] Artifact entry `status: calibrated` (or `infeasible` for named languages, documented).
- [ ] Constraint met **on test with the Wilson bound** (`certified: yes`), or the exact shortfall is written in `docs/limitations.md`.
- [ ] ECE after calibration ≤ 0.10 on test.
- [ ] p95 and RAM inside the DP's budget (`timeout_ms`); the encoder's memory floor still holds.
- [ ] `make calibration-verify` and the encoder tests pass (`uv run pytest apps/encoder packages/encoder/tests`).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`) with no unexplained disagreement.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

The harness fills in the measurable ones; **a person signs off**. The seed artifact (2026-09-29) meets none of the certification boxes: its test set is provisional and too small.

**Commit shape.** One commit with the artifact and its report, `feat(encoder): calibrate confirm_gate`. Both files change together: the report's fragment must match the artifact, and `make calibration-verify` fails if it does not.

## From shadow to enforce

Every DP starts in `shadow`: the orchestrator computes and records what it *would* do (`would_apply`) and changes nothing. Moving one to `enforce` is **its own PR** that edits only the mode of that DP in `apps/orchestrator/config/decision_effects.yaml` (`mode: shadow` → `enforce`), with:

- the calibration report attached and the F.5 checklist above complete,
- the eval or shadow evidence (`gate_breach` must be 0 for the gate: ADR-0012, Appendix G; the evalrunner section is WP6),
- `docs/limitations.md` updated for what is still open.

Do not fold that flip into a calibration commit. The rest of the effects file is the orchestrator owners'.

Kill switch and safe adjustments, no recalibration and no redeploy of the artifact:

- `DECISION_POINTS_MODES='confirm_gate=shadow'` on the orchestrator turns one DP back to shadow (ADR-0012, B.1; it is part of WP4, so check it has landed).
- `DECISION_POINTS_TAU_RAISE='confirm_gate.es=0.97'` on the encoder can only make a DP **more conservative**. If test shows a false accept, raise τ this way and recalibrate later; do not tune τ on test.

## `make calibration-verify`

Static, cheap (no training, no network), meant for CI. It fails when:

- the artifact does not validate, or its `artifact_id` does not match its content (a hand edit);
- `decision_points.schema.json` is stale (regenerate: `uv run python -m encoder.decision_points packages/encoder/calibration/decision_points.schema.json`);
- a backend pin no longer holds: the train file changed since calibration (**this is what happens if you run `make synth-data` and commit the new train file: recalibrate**), the `model_id` disagrees with its train hash, or a hub model lacks a commit or weights hash;
- a DP has status `uncalibrated_seed`, is `calibrated` with no τ anywhere, or has a τ in a language without a calibrator;
- a DP's evidence names a report that is missing, does not contain the run id, or does not embed the DP's fragment verbatim, or its data files no longer hash as recorded;
- the orchestrator's `decision_effects.yaml` (when it exists) names a DP or a label the artifact does not serve.

A changed *config* file is only a warning: it can gain a DP without invalidating the rest.

---

# Decision and embedding models (ADR-0010)

> [!IMPORTANT]
> When testing or verifying with fixtures (`tools/calibrate/fixtures/`), ALWAYS specify `OUT=/tmp/calib`.
> The `reports/` directory is versioned evidence reserved exclusively for evaluations run on real data (`data/eval/synthetic/`).

### 1. Calibrate Decision Models (Zero-Shot & Baseline)
Compares `tfidf_lr` deterministic baseline against `gliner2.5_multi` on Spanish and Portuguese:
```bash
make calibrate TASK=decision OUT=/tmp/calib
```
Calibrates the abstention threshold $\tau$ on the validation split (enforcing per-class precision $\ge 0.90$) and reports Macro-F1, ECE, coverage at $\tau$, slot F1, p95 CPU latency, and peak RAM on the held-out test split. If no threshold meets $p_{\min}$, it explicitly reports $\tau$ as infeasible with the best observed minimum precision.

### 2. Calibrate Embedding Models (BM25 vs Dense Bi-Encoder)
Compares `bm25` lexical baseline against multilingual `sentence_transformers` on Spanish and Portuguese:
```bash
make calibrate TASK=embedding OUT=/tmp/calib
```
Evaluates Hit@1, Hit@3, Hit@5, MRR, and cross-language retrieval (e.g. Spanish query matching Portuguese policy snippet), measuring p95 CPU latency and memory footprint.

### 3. Run Fine-Tuning or Real Data Evaluation
Run fine-tuning on domain data splits using Apple Silicon MPS acceleration:
```bash
make calibrate TASK=embedding CONFIG=tools/calibrate/configs/embedding_finetune.yaml OUT=/tmp/calib
```
Or for the decision task:
```bash
make calibrate TASK=decision CONFIG=tools/calibrate/configs/decision_finetune.yaml OUT=/tmp/calib
```
Decision configs accept either `data_path` (one file with all splits) or `data_paths` (a list; each file keeps its own `split` field). To calibrate on the synthetic train/validation splits plus the provisional test split (see [data/eval/synthetic/README.md](../../data/eval/synthetic/README.md)):
```bash
make calibrate TASK=decision CONFIG=tools/calibrate/configs/decision_synthetic.yaml OUT=/tmp/calib
```
The decision task accepts `eval_split: test|validation` (default `test`): the split whose rows are scored. The report states the scored split and its provenance (`human`, `synthetic`, or "provisional synthetic (not human)" for `source=synthetic-provisional`). For the decision task, `eval_split: validation` is flagged as optimistic: $\tau$ and the metrics then come from the same split.

When running full calibration on real curated data splits (`data/eval/synthetic/`), output directly to `reports/`:
```bash
make calibrate TASK=decision CONFIG=path/to/real_data_config.yaml OUT=reports/
```

---

## Output Reports

Reports are written as timestamped, self-contained Markdown files containing SHA-256 hashes of input configurations and datasets:
- Decision-points report: `<OUT>/calibration-decision-points-YYYY-MM-DD.md` (with `-<dp>` appended when a run covers only some DPs, so it never overwrites the report that backs the others)
- Decision report: `<OUT>/calibration-decision-YYYY-MM-DD.md`
- Embedding report: `<OUT>/calibration-embedding-YYYY-MM-DD.md`

## Testing & Linting

Run harness unit tests (harness tests are not in default testpaths on purpose: the older tasks pull PyTorch; CI runs them with `uv run --package calibrate pytest -q tools/calibrate`):
```bash
uv run --package calibrate pytest -q tools/calibrate/tests
```

Lint and format checks:
```bash
uv run ruff check .
uv run ruff format --check .
```
