import json
from pathlib import Path

import pytest
from retrieval import KBSnippet, KBValidationError, KnowledgeBase


def _snippet(topic: str | None, lang: str, snippet_id: str | None = None) -> KBSnippet:
    return KBSnippet(
        id=snippet_id or f"{topic}.{lang}",
        topic_id=topic,
        lang=lang,
        title="t",
        text="x",
    )


def test_bundled_kb_loads_40_topics_in_three_languages() -> None:
    kb = KnowledgeBase.from_jsonl()
    assert len(kb) == 120
    langs = {s.lang for s in kb.snippets}
    assert langs == {"es", "pt", "en"}
    assert len({s.topic_id for s in kb.snippets}) == 40


def test_id_must_match_topic_and_lang() -> None:
    with pytest.raises(KBValidationError, match="does not match"):
        KnowledgeBase([_snippet("card.01", "es", snippet_id="card.01.pt")])


def test_duplicate_id_is_rejected() -> None:
    with pytest.raises(KBValidationError, match="duplicate"):
        KnowledgeBase([_snippet("card.01", "es"), _snippet("card.01", "es")])


def test_unsupported_lang_is_rejected() -> None:
    with pytest.raises(KBValidationError, match="unsupported lang"):
        KnowledgeBase([_snippet("card.01", "fr")])


def test_from_jsonl_requires_topic(tmp_path: Path) -> None:
    path = tmp_path / "kb.jsonl"
    path.write_text(
        json.dumps({"id": "a", "lang": "es", "title": "t", "text": "x"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(KBValidationError, match="no topic_id"):
        KnowledgeBase.from_jsonl(path)


def test_from_jsonl_reports_the_bad_line(tmp_path: Path) -> None:
    path = tmp_path / "kb.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(KBValidationError, match=r"kb.jsonl:1"):
        KnowledgeBase.from_jsonl(path)


def test_cross_language_gold_returns_the_topic_in_other_languages() -> None:
    kb = KnowledgeBase(
        [_snippet("a.01", lang) for lang in ("es", "pt", "en")]
        + [_snippet("b.01", lang) for lang in ("es", "pt")]
    )
    assert kb.cross_language_gold(["a.01.es"], "es") == ["a.01.en", "a.01.pt"]
    assert kb.cross_language_gold(["a.01.pt", "b.01.pt"], "pt") == [
        "a.01.en",
        "a.01.es",
        "b.01.es",
    ]


def test_cross_language_gold_is_empty_without_topics() -> None:
    kb = KnowledgeBase([_snippet(None, "es", snippet_id="kb_es_001")])
    assert kb.cross_language_gold(["kb_es_001"], "es") == []
