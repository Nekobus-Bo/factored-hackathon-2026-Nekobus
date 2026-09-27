import math

from calibrate.metrics.retrieval import cross_language_eval, hit_at_k, mrr


def test_hit_at_k_hand_computed():
    """Verify Hit@k on hand-computed 4-query retrieval case."""
    relevant_ids = [["d1"], ["d2"], ["d3"], ["d4"]]
    retrieved_ids = [
        ["d1", "d2", "d3"],  # relevant d1 is at rank 1 -> hit@1=1, hit@3=1
        ["d1", "d2", "d3"],  # relevant d2 is at rank 2 -> hit@1=0, hit@3=1
        ["d1", "d2", "d3"],  # relevant d3 is at rank 3 -> hit@1=0, hit@3=1
        ["d1", "d2", "d3"],  # relevant d4 is missing   -> hit@1=0, hit@3=0
    ]

    h1 = hit_at_k(relevant_ids, retrieved_ids, k=1)
    h3 = hit_at_k(relevant_ids, retrieved_ids, k=3)

    assert math.isclose(h1, 0.25, rel_tol=1e-5), f"Expected 0.25, got {h1}"
    assert math.isclose(h3, 0.75, rel_tol=1e-5), f"Expected 0.75, got {h3}"


def test_mrr_hand_computed():
    """Verify MRR on hand-computed 4-query retrieval case: 11/24 ~= 0.458333."""
    relevant_ids = [["d1"], ["d2"], ["d3"], ["d4"]]
    retrieved_ids = [
        ["d1", "d2", "d3"],  # rank 1 -> 1.0
        ["d1", "d2", "d3"],  # rank 2 -> 0.5
        ["d1", "d2", "d3"],  # rank 3 -> 1/3
        ["d1", "d2", "d3"],  # rank inf -> 0.0
    ]

    score = mrr(relevant_ids, retrieved_ids)
    expected = 11.0 / 24.0

    assert math.isclose(score, expected, rel_tol=1e-5), (
        f"Expected {expected}, got {score}"
    )


def test_cross_language_eval_hand_computed():
    """Cross-language metrics only count queries that have cross-language gold."""
    gold = [
        ["t1.pt", "t1.en"],  # rank 1 hit
        ["t2.pt", "t2.en"],  # rank 2 hit
        [],  # no cross-language gold: skipped
    ]
    retrieved = [
        ["t1.en", "t3.pt"],
        ["t3.pt", "t2.pt"],
        ["whatever"],
    ]
    res = cross_language_eval(gold, retrieved, k_list=[1, 3])
    assert math.isclose(res["cross_hit@1"], 0.5, rel_tol=1e-5)
    assert math.isclose(res["cross_hit@3"], 1.0, rel_tol=1e-5)
    assert math.isclose(res["cross_mrr"], 0.75, rel_tol=1e-5)


def test_cross_language_eval_no_cross_queries():
    """Every metric is None when no query has cross-language gold."""
    res = cross_language_eval([[]], [["d_es"]], k_list=[1, 3])
    assert res["cross_hit@1"] is None
    assert res["cross_hit@3"] is None
    assert res["cross_mrr"] is None
