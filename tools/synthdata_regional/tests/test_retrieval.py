"""The kb.search test-question generator: call plan, reply parsing, the snippet-copy filter
and the per-topic selection. No LLM is called."""

import json

import polars as pl
import pytest

from tools.synthdata_regional import retrieval
from tools.synthdata_regional.locales import get_locale


@pytest.mark.parametrize("code", ["es-MX", "es-AR", "es-CO", "pt-BR"])
def test_one_call_per_topic_plus_the_not_covered_ones(code):
    loc = get_locale(code)
    calls = retrieval.plan_calls(loc, retrieval.kb_snippets())
    kinds = dict(calls.group_by("kind").len().iter_rows())
    assert kinds == {"in_scope": 40, "out_of_scope_banking": 2, "off_topic": 2}
    in_scope = calls.filter(pl.col("kind") == "in_scope")
    # Gold is the topic's snippet in the locale's language, never another language
    assert all(ids[0].endswith(f".{loc.lang}") for ids in in_scope["relevant_ids"])
    scope = calls.filter(pl.col("kind") == "out_of_scope_banking")["relevant_ids"].to_list()
    assert scope == [[f"{retrieval.SCOPE_TOPIC}.{loc.lang}"]] * 2
    assert calls.filter(pl.col("kind") == "off_topic")["relevant_ids"].to_list() == [[], []]


def test_every_kb_family_has_themes_for_real_phrases():
    families = {t.split(".")[0] for t in retrieval.kb_snippets()["topic_id"]}
    assert families <= set(retrieval.FAMILY_THEMES)


def test_replies_are_read_by_length_and_bad_items_skipped():
    calls = pl.DataFrame([{"call": 0, "kind": "in_scope", "topic_id": "t.01", "relevant_ids": ["t.01.es"]}])
    reply = {"text": json.dumps({"short": ["hola", "", 3], "long": ["un mensaje más largo"]})}
    rows = retrieval.collect(calls, [reply])
    assert [(r["length"], r["text"]) for r in rows] == [("short", "hola"), ("long", "un mensaje más largo")]
    assert retrieval.collect(calls, [{"text": "not json"}]) == []


def test_a_message_that_copies_four_words_of_its_snippet_is_caught():
    snippet = "El bloqueo preventivo suspende de inmediato cualquier transacción de compra."
    assert retrieval.copies_snippet("quiero que suspende de inmediato cualquier cosa", snippet)
    assert not retrieval.copies_snippet("congelen mi tarjeta ya, porfa", snippet)


def test_selection_keeps_two_short_and_one_long_per_topic():
    rows = [{"call": 0, "kind": "in_scope", "topic_id": "t.01", "relevant_ids": ["t.01.es"],
             "length": length, "text": f"{length} {i}"}
            for i, length in enumerate(["short", "short", "short", "long", "long"])]
    rows += [{"call": 1, "kind": "in_scope", "topic_id": "t.02", "relevant_ids": ["t.02.es"],
              "length": "short", "text": "solo uno"}]
    kept, deficit = retrieval.select(pl.DataFrame(rows))
    first = kept.filter(pl.col("topic_id") == "t.01")
    assert sorted(first["length"].to_list()) == ["long", "short", "short"]
    assert deficit == {"in_scope:t.02": 2}


def test_pt_br_gets_its_own_prompt_wording():
    assert retrieval.wording(get_locale("pt-BR"))["bank_country"] == "a Brazilian"
    assert retrieval.wording(get_locale("es-AR"))["bank_country"] == "an Argentine"
