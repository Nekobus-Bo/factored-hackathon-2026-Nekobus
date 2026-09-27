from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path
from typing import Any


def file_sha256(path: str | Path) -> str:
    """Calculate SHA-256 hash of a file."""
    p = Path(path)
    if not p.is_file():
        return "N/A"
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_execution_environment_info() -> str:
    """Detect dynamic execution environment (host/container, OS, Python, PyTorch)."""
    is_container = (
        Path("/.dockerenv").exists()
        or Path("/run/.containerenv").exists()
        or os.path.exists("/.dockerenv")
    )
    container_str = "container" if is_container else "host"
    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    py_ver = platform.python_version()
    try:
        import torch

        torch_ver = getattr(torch, "__version__", "unknown")
        torch_threads = torch.get_num_threads()
        threads_str = f", {torch_threads} threads"
    except Exception:
        torch_ver = "unknown"
        threads_str = ""

    return (
        f"{os_info}, Python {py_ver}, PyTorch {torch_ver} "
        f"({container_str}{threads_str})"
    )


def render_decision_report(
    date_str: str,
    config_path: str,
    data_paths: list[str],
    rows: list[dict[str, Any]],
    p_min: float,
) -> str:
    """Generate Markdown report for decision task."""
    cfg_hash = file_sha256(config_path)
    env_info = get_execution_environment_info()

    data_hashes_md = "\n".join(f"- `{p}`: `{file_sha256(p)}`" for p in data_paths)

    table_header = (
        "| Candidate Model | Mode | Language | Macro-F1 | "
        "Test min precision | ECE | Calibrated $\\tau$ | "
        "Test coverage @ $\\tau$ ($\\tau$ from validation) | Slot F1 | "
        "p95 CPU (ms) | RAM model+inference Δ (MB) |\n"
        "|---|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )

    table_rows = []
    for r in rows:
        if r.get("no_data"):
            row_str = (
                f"| `{r['model_id']}` | {r['mode']} | {r['lang']} | "
                f"no data | no data | no data | no data | no data | - | "
                f"{r['p95_latency_ms']:.1f} | {r['peak_ram_mb']:.1f} |"
            )
            table_rows.append(row_str)
            continue

        min_p_str = (
            f"{r['min_precision']:.3f}" if r.get("min_precision") is not None else "-"
        )
        slot_f1_str = f"{r['slot_f1']:.3f}" if r.get("slot_f1") is not None else "-"

        if r.get("is_feasible") and r.get("tau") is not None:
            tau_display = f"{r['tau']:.3f}"
            cov_display = f"{r['coverage_at_tau']:.1%}"
        else:
            p_min_val = r.get("p_min", p_min)
            best_mp = r.get("best_min_precision", 0.0)
            tau_display = (
                f"infeasible at p_min={p_min_val:.2f} "
                f"(best min precision {best_mp:.3f})"
            )
            cov_display = "-"

        row_str = (
            f"| `{r['model_id']}` | {r['mode']} | {r['lang']} | "
            f"{r['macro_f1']:.3f} | {min_p_str} | {r['ece']:.3f} | "
            f"{tau_display} | {cov_display} | {slot_f1_str} | "
            f"{r['p95_latency_ms']:.1f} | {r['peak_ram_mb']:.1f} |"
        )
        table_rows.append(row_str)

    table_body = "\n".join(table_rows)

    return f"""# Decision Model Calibration Report

- **Date:** {date_str}
- **Task:** `decision` (Intent Classification & Slot Extraction)
- **Target Precision Constraint ($p_{{min}}$):** {p_min:.2f}
  (chosen on validation, evaluated on test)
- **Execution Environment:** {env_info}
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `{config_path}` (`{cfg_hash}`)
- **Data Splits:**
{data_hashes_md}

## Calibration Summary Table

{table_header}
{table_body}

## Evaluation Notes & Decisions

1. **Threshold $\\tau$ Selection:** Calibrated strictly on the validation split
   to maximize coverage while enforcing per-class precision $\\ge {p_min:.2f}$.
   Reported coverage and precision reflect held-out test split behavior.
2. **Deterministic Baseline:** Evaluated against `tfidf_lr`
   (TF-IDF + Logistic Regression).
3. **Inference Performance:** All latency (p95) and RAM measurements
   conducted on CPU (`device=cpu`).
4. **Fine-tuning & Calibration Splits:** GLiNER fine-tuning fits on train split,
   uses validation split for evaluation loss and threshold $\\tau$ selection,
   and reports final metrics on the held-out test split.
"""


def render_embedding_report(
    date_str: str,
    config_path: str,
    data_paths: list[str],
    rows: list[dict[str, Any]],
    k_list: list[int],
    eval_split: str = "test",
) -> str:
    """Generate Markdown report for embedding/retrieval task."""
    cfg_hash = file_sha256(config_path)
    env_info = get_execution_environment_info()

    data_hashes_md = "\n".join(f"- `{p}`: `{file_sha256(p)}`" for p in data_paths)

    k_cols = " | ".join(f"Hit@{k}" for k in k_list)
    cross_cols = " | ".join(f"Cross Hit@{k}" for k in k_list)
    k_align = " | ".join("---:" for _ in k_list)
    table_header = (
        f"| Candidate Model | Mode | Language | {k_cols} | MRR | "
        f"{cross_cols} | Cross MRR | p95 CPU (ms) | "
        "RAM model+inference Δ (MB) |\n"
        f"|---|---|:---:|{k_align}|---:|{k_align}|---:|---:|---:|"
    )

    table_rows = []
    for r in rows:
        if r.get("no_data"):
            hit_vals = " | ".join("no data" for _ in k_list)
            row_str = (
                f"| `{r['model_id']}` | {r['mode']} | {r['lang']} | "
                f"{hit_vals} | no data | {hit_vals} | no data | "
                f"{r['p95_latency_ms']:.1f} | {r['peak_ram_mb']:.1f} |"
            )
            table_rows.append(row_str)
            continue

        hit_vals = " | ".join(
            f"{r[f'hit@{k}']:.3f}" if r.get(f"hit@{k}") is not None else "-"
            for k in k_list
        )
        mrr_str = f"{r['mrr']:.3f}" if r.get("mrr") is not None else "-"
        cross_hit = " | ".join(
            f"{r[f'cross_hit@{k}']:.3f}"
            if r.get(f"cross_hit@{k}") is not None
            else "n/a"
            for k in k_list
        )
        cross_mrr_val = r.get("cross_mrr")
        cross_mrr = f"{cross_mrr_val:.3f}" if cross_mrr_val is not None else "n/a"
        row_str = (
            f"| `{r['model_id']}` | {r['mode']} | {r['lang']} | "
            f"{hit_vals} | {mrr_str} | {cross_hit} | {cross_mrr} | "
            f"{r['p95_latency_ms']:.1f} | {r['peak_ram_mb']:.1f} |"
        )
        table_rows.append(row_str)

    table_body = "\n".join(table_rows)

    return f"""# Embedding Model Calibration Report

- **Date:** {date_str}
- **Task:** `embedding` (Knowledge Base Policy Retrieval)
- **Evaluated split:** `{eval_split}`
- **Execution Environment:** {env_info}
  (MPS/CUDA for training if available, CPU for inference benchmarking)

## Artifact Provenance & Hashes

- **Configuration:** `{config_path}` (`{cfg_hash}`)
- **Data Splits:**
{data_hashes_md}

## Calibration Summary Table

{table_header}
{table_body}

## Evaluation Notes & Decisions

1. **Retrieval Baseline:** Evaluated against `bm25` lexical search.
2. **Dense Retrieval:** Evaluated using bi-encoder SentenceTransformers on CPU;
   `hybrid` fuses BM25 and the dense ranking with reciprocal rank fusion.
3. **Same-language (Hit@k, MRR):** the index is restricted to the query's language.
4. **Cross-language (Cross Hit@k, Cross MRR):** the same query against an index
   restricted to the other languages; gold is the query's topic in those
   languages. `n/a` when the KB snippets carry no `topic_id`.
5. **Latency & Resource Footprint:** Measured strictly on CPU (`device=cpu`).
"""
