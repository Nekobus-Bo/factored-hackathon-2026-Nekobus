from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def hit_at_k(
    relevant_ids_list: Sequence[Sequence[str]],
    retrieved_ids_list: Sequence[Sequence[str]],
    k: int,
) -> float:
    """Calculate Hit@k retrieval accuracy."""
    if len(relevant_ids_list) != len(retrieved_ids_list):
        raise ValueError("Relevant IDs and retrieved IDs must have identical lengths")
    if not relevant_ids_list:
        return 0.0

    hits = 0
    for rel_ids, ret_ids in zip(relevant_ids_list, retrieved_ids_list, strict=True):
        rel_set = set(rel_ids)
        top_k = ret_ids[:k]
        if any(doc_id in rel_set for doc_id in top_k):
            hits += 1

    return float(hits / len(relevant_ids_list))


def mrr(
    relevant_ids_list: Sequence[Sequence[str]],
    retrieved_ids_list: Sequence[Sequence[str]],
) -> float:
    """Calculate Mean Reciprocal Rank (MRR)."""
    if len(relevant_ids_list) != len(retrieved_ids_list):
        raise ValueError("Relevant IDs and retrieved IDs must have identical lengths")
    if not relevant_ids_list:
        return 0.0

    total_rr = 0.0
    for rel_ids, ret_ids in zip(relevant_ids_list, retrieved_ids_list, strict=True):
        rel_set = set(rel_ids)
        rr = 0.0
        for rank, doc_id in enumerate(ret_ids, start=1):
            if doc_id in rel_set:
                rr = 1.0 / rank
                break
        total_rr += rr

    return float(total_rr / len(relevant_ids_list))


def cross_language_eval(
    queries: Sequence[Any],
    retrieved_ids_list: Sequence[Sequence[str]],
    kb_lang_map: dict[str, str],
    k_list: Sequence[int] = (1, 3, 5),
) -> dict[str, float]:
    """Calculate Hit@k and MRR for cross-language queries
    (query lang != target snippet lang).
    """
    cross_relevant: list[Sequence[str]] = []
    cross_retrieved: list[Sequence[str]] = []

    for q, ret_ids in zip(queries, retrieved_ids_list, strict=True):
        q_lang = getattr(q, "lang", None) or (
            q.get("lang") if isinstance(q, dict) else ""
        )
        rel_ids = getattr(q, "relevant_ids", None) or (
            q.get("relevant_ids", []) if isinstance(q, dict) else []
        )

        # Check if query targets a snippet in a different language
        is_cross = any(
            kb_lang_map.get(doc_id) is not None and kb_lang_map.get(doc_id) != q_lang
            for doc_id in rel_ids
        )
        if is_cross:
            cross_relevant.append(rel_ids)
            cross_retrieved.append(ret_ids)

    if not cross_relevant:
        results: dict[str, float | None] = {f"cross_hit@{k}": None for k in k_list}
        results["cross_mrr"] = None
        return results

    results: dict[str, float | None] = {
        f"cross_hit@{k}": hit_at_k(cross_relevant, cross_retrieved, k) for k in k_list
    }
    results["cross_mrr"] = mrr(cross_relevant, cross_retrieved)
    return results
