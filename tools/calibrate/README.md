# Model Calibration Harness

Unified calibration harness for local decision models (intent classification + slot extraction) and embedding models (policy retrieval) for Pattern Blue.

Per [ADR-0001](../../docs/adr/0001-cheap-llm-specialized-encoder.md), [ADR-0008](../../docs/adr/0008-cpu-inference-deployment.md), and [ADR-0010](../../docs/adr/0010-model-selection-calibration-harness.md), all runtime inference, latency, and RAM benchmarks execute strictly on CPU, while fine-tuning leverages local Apple Silicon MPS acceleration when available.

## The 3 Commands You Need

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
- Decision report: `<OUT>/calibration-decision-YYYY-MM-DD.md`
- Embedding report: `<OUT>/calibration-embedding-YYYY-MM-DD.md`

## Testing & Linting

Run harness unit tests (harness tests are not in default testpaths on purpose: they pull PyTorch):
```bash
uv run --package calibrate pytest -q tools/calibrate/tests
```

Lint and format checks:
```bash
uv run ruff check .
uv run ruff format --check .
```
