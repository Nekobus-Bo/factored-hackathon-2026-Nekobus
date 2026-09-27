from __future__ import annotations

from collections.abc import Sequence


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
    gold_ids_list: Sequence[Sequence[str]],
    retrieved_ids_list: Sequence[Sequence[str]],
    k_list: Sequence[int] = (1, 3, 5),
) -> dict[str, float | None]:
    """Hit@k and MRR for cross-language retrieval.

    ``gold_ids_list[i]`` holds the snippets of query i's topics in the *other*
    languages, and ``retrieved_ids_list[i]`` the ranking from an index
    restricted to those languages. Queries with no cross-language gold are
    skipped; if none remain every metric is ``None`` (reported as n/a).
    """
    pairs = [
        (gold, ret)
        for gold, ret in zip(gold_ids_list, retrieved_ids_list, strict=True)
        if gold
    ]
    results: dict[str, float | None] = {}
    if not pairs:
        for k in k_list:
            results[f"cross_hit@{k}"] = None
        results["cross_mrr"] = None
        return results

    gold = [g for g, _ in pairs]
    retrieved = [r for _, r in pairs]
    for k in k_list:
        results[f"cross_hit@{k}"] = hit_at_k(gold, retrieved, k)
    results["cross_mrr"] = mrr(gold, retrieved)
    return results
