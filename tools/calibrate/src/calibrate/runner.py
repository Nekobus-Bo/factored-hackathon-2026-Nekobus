from __future__ import annotations

import gc
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
import yaml
from encoder.adapters import GLiNERAdapter, TFIDFLRAdapter
from encoder.models import DecisionExample
from retrieval.adapters import BM25Adapter, HybridAdapter, SentenceTransformersAdapter
from retrieval.adapters.hybrid import DEFAULT_RRF_K
from retrieval.kb import KnowledgeBase
from retrieval.models import KBSnippet, QueryExample
from retrieval.search import Retriever, SearchMode

from calibrate.benchmark import benchmark_cpu_inference
from calibrate.metrics.decision import (
    calibrate_tau,
    evaluate_at_tau,
    expected_calibration_error,
    macro_f1,
    per_class_precision,
    slot_f1,
)
from calibrate.metrics.retrieval import (
    cross_language_eval,
    hit_at_k,
    mrr,
)
from calibrate.report import render_decision_report, render_embedding_report

logger = logging.getLogger(__name__)

# Adapter registries for custom / test-only adapters
ADAPTER_REGISTRY: dict[str, Any] = {}
DECISION_ADAPTER_REGISTRY: dict[str, Any] = {}
RETRIEVAL_ADAPTER_REGISTRY: dict[str, Any] = {}


def load_decision_dataset(jsonl_path: str | Path) -> list[DecisionExample]:
    """Load decision examples from JSONL."""
    examples: list[DecisionExample] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            data = json.loads(line)
            examples.append(DecisionExample(**data))
    return examples


def load_kb_dataset(jsonl_path: str | Path) -> list[KBSnippet]:
    """Load knowledge base snippets from JSONL."""
    snippets: list[KBSnippet] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            data = json.loads(line)
            snippets.append(KBSnippet(**data))
    return snippets


def load_queries_dataset(jsonl_path: str | Path) -> list[QueryExample]:
    """Load evaluation queries from JSONL."""
    queries: list[QueryExample] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            data = json.loads(line)
            queries.append(QueryExample(**data))
    return queries


def guard_fixture_output(data_paths: list[str | Path], out_dir: str | Path) -> None:
    """Guard against writing fixture-based calibration reports to reports/.

    Reports under reports/ are versioned empirical evidence from real data.
    Fixture runs are meant for testing and smoke verification (e.g. OUT=/tmp/calib).
    """
    out_path = Path(out_dir).resolve()
    repo_root = Path(__file__).resolve().parents[4]
    reports_dir = (repo_root / "reports").resolve()

    try:
        is_under_reports = out_path == reports_dir or reports_dir in out_path.parents
    except Exception:
        is_under_reports = False

    if not is_under_reports:
        return

    fixtures_dir = (repo_root / "tools" / "calibrate" / "fixtures").resolve()
    for dp in data_paths:
        resolved_dp = Path(dp).resolve()
        if (
            resolved_dp == fixtures_dir
            or fixtures_dir in resolved_dp.parents
            or "fixtures" in resolved_dp.parts
        ):
            raise ValueError(
                f"Refusing to write fixture calibration report to versioned "
                f"reports directory '{out_dir}'. Fixture data in "
                "tools/calibrate/fixtures/ must only be run with a temporary "
                "output path (e.g., OUT=/tmp/calib or make calibrate TASK=... "
                "OUT=/tmp/calib). Only real evaluation data may be written to reports/."
            )


def resolve_decision_data_paths(config: dict[str, Any]) -> list[str]:
    """Return the decision data files from `data_paths` (list) or `data_path`.

    Every file keeps its own `split` field; the files are concatenated.
    """
    paths = config.get("data_paths")
    if paths is None:
        return [config.get("data_path", "tools/calibrate/fixtures/decision.jsonl")]
    if config.get("data_path") is not None:
        raise ValueError("Set either data_path or data_paths, not both")
    if not isinstance(paths, list) or not paths:
        raise ValueError("data_paths must be a non-empty list of JSONL paths")
    return [str(p) for p in paths]


EVAL_SPLITS = ("test", "validation")


def resolve_eval_split(config: dict[str, Any]) -> str:
    """Return the split to score (`eval_split`, default `test`)."""
    eval_split = config.get("eval_split", "test")
    if eval_split not in EVAL_SPLITS:
        raise ValueError(
            f"eval_split must be one of {', '.join(EVAL_SPLITS)}, got {eval_split!r}"
        )
    return eval_split


def run_decision_calibration(config_path: str | Path, out_dir: str | Path) -> Path:
    """Run calibration pipeline for decision task."""
    cfg_p = Path(config_path)
    with open(cfg_p, encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)

    data_files = resolve_decision_data_paths(config)
    guard_fixture_output(data_files, out_dir)

    p_min = float(config.get("p_min", 0.9))
    mode = config.get("mode", "zeroshot")
    languages = config.get("languages", ["es", "pt", "en"])

    examples = [e for path in data_files for e in load_decision_dataset(path)]
    train_exs = [e for e in examples if e.split == "train"]
    val_exs = [e for e in examples if e.split == "validation"]
    eval_split = resolve_eval_split(config)
    test_exs = [e for e in examples if e.split == eval_split]

    candidate_intents = sorted(set(e.intent for e in examples))
    all_slots = set()
    for e in examples:
        for s in e.slots:
            all_slots.add(s.type)
    candidate_slots = sorted(all_slots)

    report_rows: list[dict[str, Any]] = []

    candidates_cfg = config.get("candidates", [])
    adapter: Any = None
    for cand in candidates_cfg:
        del adapter
        gc.collect()
        process = psutil.Process()
        baseline_ram_mb = process.memory_info().rss / (1024 * 1024)

        adapter_type = cand.get("type")
        model_id = cand.get("model_id", adapter_type)
        cand_name = cand.get("name", model_id)

        logger.info("Evaluating decision candidate: %s (%s)", cand_name, adapter_type)

        if adapter_type in DECISION_ADAPTER_REGISTRY:
            factory = DECISION_ADAPTER_REGISTRY[adapter_type]
            adapter = factory(cand)
        elif adapter_type in ADAPTER_REGISTRY:
            factory = ADAPTER_REGISTRY[adapter_type]
            adapter = factory(cand)
        elif adapter_type == "tfidf_lr":
            adapter = TFIDFLRAdapter(name=cand_name)
            # Baseline is always fitted on train split
            adapter.fit(train_exs)
        elif adapter_type == "gliner":
            adapter = GLiNERAdapter(model_id=model_id, name=cand_name, device="cpu")
            if mode == "finetune":
                epochs = int(cand.get("epochs", config.get("epochs", 2)))
                adapter.fit(train_exs, val_exs, epochs=epochs)
                weights_dir = Path("packages/encoder/weights") / cand_name
                adapter.save(weights_dir)
                adapter.load(weights_dir)
        else:
            raise ValueError(f"unknown adapter type: {adapter_type}")

        # Benchmark CPU latency & peak RAM on test split
        test_texts = [e.text for e in test_exs]
        bench_res = benchmark_cpu_inference(
            infer_fn=lambda txt, ad=adapter: ad.predict(
                [txt], candidate_intents, candidate_slots
            ),
            items=test_texts,
            warmup=1,
            baseline_ram_mb=baseline_ram_mb,
        )

        for lang in languages:
            val_lang = [e for e in val_exs if e.lang == lang]
            test_lang = [e for e in test_exs if e.lang == lang]

            if not test_lang:
                report_rows.append(
                    {
                        "model_id": model_id,
                        "mode": mode,
                        "lang": lang,
                        "no_data": True,
                        "macro_f1": None,
                        "min_precision": None,
                        "ece": None,
                        "tau": None,
                        "is_feasible": False,
                        "p_min": p_min,
                        "best_min_precision": None,
                        "coverage_at_tau": None,
                        "slot_f1": None,
                        "p95_latency_ms": bench_res.p95_latency_ms,
                        "peak_ram_mb": bench_res.peak_ram_mb,
                    }
                )
                continue

            # Calibrate threshold tau on validation split
            if val_lang:
                val_preds = adapter.predict(
                    [e.text for e in val_lang],
                    candidate_intents=candidate_intents,
                    candidate_slots=candidate_slots,
                )
                y_true_val = [e.intent for e in val_lang]
                y_pred_val = [p.intent for p in val_preds]
                conf_val = [p.confidence for p in val_preds]
                tau_res = calibrate_tau(y_true_val, y_pred_val, conf_val, p_min=p_min)
                tau = tau_res.tau
                is_feasible = tau_res.is_feasible
                best_min_p = tau_res.best_min_precision
            else:
                tau = None
                is_feasible = False
                best_min_p = 0.0

            # Evaluate on held-out test split
            test_preds = adapter.predict(
                [e.text for e in test_lang],
                candidate_intents=candidate_intents,
                candidate_slots=candidate_slots,
            )
            y_true_test = [e.intent for e in test_lang]
            y_pred_test = [p.intent for p in test_preds]
            conf_test = [p.confidence for p in test_preds]

            macro_f1_score = macro_f1(y_true_test, y_pred_test)
            precisions = per_class_precision(y_true_test, y_pred_test)
            min_prec = min(precisions.values()) if precisions else 0.0
            ece = expected_calibration_error(y_true_test, y_pred_test, conf_test)
            cov_at_tau, _, _ = evaluate_at_tau(y_true_test, y_pred_test, conf_test, tau)

            # Slot F1 evaluation: tfidf_lr does not extract slots
            if adapter_type == "tfidf_lr":
                slot_f1_score = None
            elif any(p.slots for p in test_preds) or any(e.slots for e in test_lang):
                true_slots_all = [e.slots for e in test_lang]
                pred_slots_all = [p.slots for p in test_preds]
                slot_f1_score = slot_f1(true_slots_all, pred_slots_all)
            else:
                slot_f1_score = None

            report_rows.append(
                {
                    "model_id": model_id,
                    "mode": mode,
                    "lang": lang,
                    "macro_f1": macro_f1_score,
                    "min_precision": min_prec,
                    "ece": ece,
                    "tau": tau,
                    "is_feasible": is_feasible,
                    "p_min": p_min,
                    "best_min_precision": best_min_p,
                    "coverage_at_tau": cov_at_tau,
                    "slot_f1": slot_f1_score,
                    "p95_latency_ms": bench_res.p95_latency_ms,
                    "peak_ram_mb": bench_res.peak_ram_mb,
                }
            )

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    report_content = render_decision_report(
        date_str=today_str,
        config_path=str(cfg_p),
        data_paths=[str(p) for p in data_files],
        rows=report_rows,
        p_min=p_min,
        eval_split=eval_split,
        eval_sources=sorted({e.source for e in test_exs}),
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / f"calibration-decision-{today_str}.md"
    report_file.write_text(report_content, encoding="utf-8")
    logger.info("Saved decision report to %s", report_file)
    return report_file


def run_embedding_calibration(config_path: str | Path, out_dir: str | Path) -> Path:
    """Run calibration pipeline for embedding/retrieval task."""
    cfg_p = Path(config_path)
    with open(cfg_p, encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)

    kb_file = config.get("kb_path", "tools/calibrate/fixtures/kb.jsonl")
    queries_file = config.get("queries_path", "tools/calibrate/fixtures/queries.jsonl")
    guard_fixture_output([kb_file, queries_file], out_dir)

    k_list = config.get("k_list", [1, 3, 5])
    mode = config.get("mode", "zeroshot")
    languages = config.get("languages", ["es", "pt", "en"])

    kb = load_kb_dataset(kb_file)
    knowledge_base = KnowledgeBase(kb)

    eval_split = resolve_eval_split(config)
    queries = load_queries_dataset(queries_file)
    train_queries = [q for q in queries if q.split == "train"]
    val_queries = [q for q in queries if q.split == "validation"]
    eval_queries = [q for q in queries if q.split == eval_split]
    max_k = max(k_list)

    report_rows: list[dict[str, Any]] = []

    candidates_cfg = config.get("candidates", [])
    adapter: Any = None
    retriever: Retriever | None = None
    for cand in candidates_cfg:
        del adapter, retriever
        gc.collect()
        process = psutil.Process()
        baseline_ram_mb = process.memory_info().rss / (1024 * 1024)

        adapter_type = cand.get("type")
        model_id = cand.get("model_id", adapter_type)
        cand_name = cand.get("name", model_id)

        logger.info("Evaluating embedding candidate: %s (%s)", cand_name, adapter_type)

        if adapter_type in RETRIEVAL_ADAPTER_REGISTRY:
            adapter = RETRIEVAL_ADAPTER_REGISTRY[adapter_type](cand)
        elif adapter_type == "bm25":
            adapter = BM25Adapter(name=cand_name)
        elif adapter_type == "sentence_transformers":
            adapter = SentenceTransformersAdapter(
                model_id=model_id, name=cand_name, device="cpu"
            )
        elif adapter_type == "hybrid":
            adapter = HybridAdapter(
                lexical=BM25Adapter(name=f"{cand_name}_bm25"),
                dense=SentenceTransformersAdapter(
                    model_id=model_id, name=f"{cand_name}_dense", device="cpu"
                ),
                rrf_k=int(cand.get("rrf_k", DEFAULT_RRF_K)),
                name=cand_name,
            )
            model_id = f"hybrid_rrf(bm25 + {model_id})"
        else:
            raise ValueError(f"unknown adapter type: {adapter_type}")

        if mode == "finetune" and adapter_type == "sentence_transformers":
            epochs = int(cand.get("epochs", config.get("epochs", 1)))
            adapter.fit(train_queries, kb, val_queries=val_queries, epochs=epochs)
            weights_dir = Path("packages/retrieval/weights") / cand_name
            adapter.save(weights_dir)
            adapter.load(weights_dir)

        # Indexes the whole KB once; the language filter is applied per query.
        retriever = Retriever(knowledge_base, adapter)

        # Benchmark CPU search latency & peak RAM on the evaluated queries
        bench_res = benchmark_cpu_inference(
            infer_fn=lambda q, r=retriever: r.search(
                q.text, lang=q.lang, k=max_k, mode=SearchMode.SAME
            ),
            items=eval_queries,
            warmup=1,
            baseline_ram_mb=baseline_ram_mb,
        )

        for lang in languages:
            eval_lang = [q for q in eval_queries if q.lang == lang]
            if not eval_lang:
                row_data: dict[str, Any] = {
                    "model_id": model_id,
                    "mode": mode,
                    "lang": lang,
                    "no_data": True,
                    "mrr": None,
                    "p95_latency_ms": bench_res.p95_latency_ms,
                    "peak_ram_mb": bench_res.peak_ram_mb,
                }
                for k in k_list:
                    row_data[f"hit@{k}"] = None
                    row_data[f"cross_hit@{k}"] = None
                row_data["cross_mrr"] = None
                report_rows.append(row_data)
                continue

            # Same-language: the index is restricted to the query's language.
            retrieved_ids = [
                [
                    r.snippet_id
                    for r in retriever.search(
                        q.text, lang=q.lang, k=max_k, mode=SearchMode.SAME
                    )
                ]
                for q in eval_lang
            ]
            relevant_ids = [q.relevant_ids for q in eval_lang]

            row_data = {
                "model_id": model_id,
                "mode": mode,
                "lang": lang,
                "mrr": mrr(relevant_ids, retrieved_ids),
                "p95_latency_ms": bench_res.p95_latency_ms,
                "peak_ram_mb": bench_res.peak_ram_mb,
            }

            for k in k_list:
                row_data[f"hit@{k}"] = hit_at_k(relevant_ids, retrieved_ids, k)

            # Cross-language: same topics, index restricted to the other languages.
            cross_gold = [
                knowledge_base.cross_language_gold(q.relevant_ids, q.lang)
                for q in eval_lang
            ]
            cross_retrieved = [
                [
                    r.snippet_id
                    for r in retriever.search(
                        q.text, lang=q.lang, k=max_k, mode=SearchMode.CROSS
                    )
                ]
                if gold
                else []
                for q, gold in zip(eval_lang, cross_gold, strict=True)
            ]
            row_data.update(
                cross_language_eval(cross_gold, cross_retrieved, k_list=k_list)
            )

            report_rows.append(row_data)

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    report_content = render_embedding_report(
        date_str=today_str,
        config_path=str(cfg_p),
        data_paths=[str(kb_file), str(queries_file)],
        rows=report_rows,
        k_list=k_list,
        eval_split=eval_split,
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / f"calibration-embedding-{today_str}.md"
    report_file.write_text(report_content, encoding="utf-8")
    logger.info("Saved embedding report to %s", report_file)
    return report_file
