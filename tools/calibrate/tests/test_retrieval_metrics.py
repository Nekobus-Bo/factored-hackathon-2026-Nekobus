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
    """Verify cross-language retrieval filters queries
    by cross-lingual target snippet.
    """
    queries = [
        {"id": "q1", "lang": "es", "relevant_ids": ["d_pt"]},  # cross-language
        {"id": "q2", "lang": "es", "relevant_ids": ["d_es"]},  # same language
    ]
    retrieved = [
        ["d_pt", "d_other"],
        ["d_es", "d_other"],
    ]
    kb_lang_map = {"d_pt": "pt", "d_es": "es", "d_other": "pt"}

    res = cross_language_eval(queries, retrieved, kb_lang_map, k_list=[1, 3])
    assert math.isclose(res["cross_hit@1"], 1.0, rel_tol=1e-5)
    assert math.isclose(res["cross_mrr"], 1.0, rel_tol=1e-5)


def test_cross_language_eval_no_cross_queries():
    """Verify cross-language retrieval returns None when no cross queries exist."""
    queries = [
        {"id": "q1", "lang": "es", "relevant_ids": ["d_es"]},
    ]
    retrieved = [
        ["d_es"],
    ]
    kb_lang_map = {"d_es": "es"}
    res = cross_language_eval(queries, retrieved, kb_lang_map, k_list=[1, 3])
    assert res["cross_hit@1"] is None
    assert res["cross_hit@3"] is None
    assert res["cross_mrr"] is None
