# Decision Model Calibration Report

> [!WARNING]
> Scored split `test` is provisional synthetic (not human). It stands in for the human-written set (docs/labeling-rubric.md) and does not replace it. The encoder regex slot rules were tuned on train and validation by the same author as this set.

- **Scored split:** `test` (provenance: provisional synthetic (not human))
- **Date:** 2026-09-28
- **Task:** `decision` (Intent Classification & Slot Extraction)
- **Target Precision Constraint ($p_{min}$):** 0.90
  (chosen on validation, evaluated on test)
- **Execution Environment:** Darwin 27.0.0 (arm64), Python 3.12.14, PyTorch 2.14.0 (host, 4 threads)
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `tools/calibrate/configs/decision_synthetic.yaml` (`a1a92560c49c407f7bf4c9ad3af754750bcf9f36885b5139eab8d8c78e9d9fa6`)
- **Data Splits:**
- `data/eval/synthetic/decision.train.jsonl`: `a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984`
- `data/eval/synthetic/decision.validation.jsonl`: `50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699`
- `data/eval/synthetic/decision.test.provisional.jsonl`: `06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7`

## Calibration Summary Table

| Candidate Model | Mode | Language | Macro-F1 | Test min precision | ECE | Calibrated $\tau$ | Test coverage @ $\tau$ ($\tau$ from validation) | Slot F1 | p95 CPU (ms) | RAM model+inference Δ (MB) |
|---|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `tfidf_lr` | zeroshot | es | 0.793 | 0.316 | 0.491 | 0.366 | 22.7% | - | 0.2 | 32.2 |
| `tfidf_lr` | zeroshot | pt | 0.844 | 0.533 | 0.519 | 0.338 | 34.0% | - | 0.2 | 32.2 |
| `tfidf_lr` | zeroshot | en | 0.789 | 0.400 | 0.512 | 0.149 | 80.0% | - | 0.2 | 32.2 |
| `fastino/gliner2.5-multi-v1` | zeroshot | es | 0.466 | 0.000 | 0.113 | 0.964 | 2.0% | 0.215 | 72.8 | 1952.5 |
| `fastino/gliner2.5-multi-v1` | zeroshot | pt | 0.425 | 0.000 | 0.091 | 0.939 | 6.7% | 0.254 | 72.8 | 1952.5 |
| `fastino/gliner2.5-multi-v1` | zeroshot | en | 0.523 | 0.000 | 0.125 | 0.965 | 4.7% | 0.260 | 72.8 | 1952.5 |

## Evaluation Notes & Decisions

1. **Threshold $\tau$ Selection:** Calibrated strictly on the validation split
   to maximize coverage while enforcing per-class precision $\ge 0.90$.
   Reported coverage and precision reflect the `test` split.
2. **Deterministic Baseline:** Evaluated against `tfidf_lr`
   (TF-IDF + Logistic Regression).
3. **Inference Performance:** All latency (p95) and RAM measurements
   conducted on CPU (`device=cpu`).
4. **Fine-tuning & Calibration Splits:** GLiNER fine-tuning fits on train split,
   uses validation split for evaluation loss and threshold $\tau$ selection,
   and reports final metrics on the held-out test split.
