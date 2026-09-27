"""Knowledge base loader with structural validation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import ValidationError

from retrieval.models import KBSnippet

SUPPORTED_LANGS: tuple[str, ...] = ("es", "pt", "en")

# packages/retrieval/src/retrieval/kb.py -> packages/retrieval/kb/snippets.jsonl
DEFAULT_KB_PATH = Path(__file__).resolve().parents[2] / "kb" / "snippets.jsonl"


class KBValidationError(ValueError):
    """Raised when the knowledge base file breaks its structural contract."""


class KnowledgeBase:
    """Validated, immutable collection of KB snippets.

    Checks: unique ids, a supported language, and, when a snippet declares a
    topic, an id of the form ``<topic_id>.<lang>`` with one snippet per topic
    and language.
    """

    def __init__(
        self, snippets: Iterable[KBSnippet], *, require_topic: bool = False
    ) -> None:
        self.snippets: tuple[KBSnippet, ...] = tuple(snippets)
        self._by_id: dict[str, KBSnippet] = {}
        self._by_topic: dict[str, dict[str, str]] = {}
        for s in self.snippets:
            if s.id in self._by_id:
                raise KBValidationError(f"duplicate snippet id '{s.id}'")
            if s.lang not in SUPPORTED_LANGS:
                raise KBValidationError(
                    f"snippet '{s.id}' has unsupported lang '{s.lang}'"
                )
            if s.topic_id is None:
                if require_topic:
                    raise KBValidationError(f"snippet '{s.id}' has no topic_id")
            else:
                expected_id = f"{s.topic_id}.{s.lang}"
                if s.id != expected_id:
                    raise KBValidationError(
                        f"snippet id '{s.id}' does not match topic_id and lang "
                        f"(expected '{expected_id}')"
                    )
                self._by_topic.setdefault(s.topic_id, {})[s.lang] = s.id
            self._by_id[s.id] = s

    @classmethod
    def from_jsonl(cls, path: str | Path = DEFAULT_KB_PATH) -> KnowledgeBase:
        """Load and validate a JSONL knowledge base; every snippet needs a topic."""
        snippets: list[KBSnippet] = []
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    snippets.append(KBSnippet.model_validate(json.loads(line)))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise KBValidationError(
                        f"{path}:{line_no}: invalid snippet: {exc}"
                    ) from exc
        return cls(snippets, require_topic=True)

    def __len__(self) -> int:
        return len(self.snippets)

    def get(self, snippet_id: str) -> KBSnippet:
        return self._by_id[snippet_id]

    def lang_of(self, snippet_id: str) -> str | None:
        snippet = self._by_id.get(snippet_id)
        return snippet.lang if snippet else None

    def cross_language_gold(
        self, relevant_ids: Sequence[str], query_lang: str
    ) -> list[str]:
        """Same topics as ``relevant_ids``, in every language except the query's.

        Returns an empty list when the snippets carry no topic, so callers can
        report cross-language metrics as not available.
        """
        gold: list[str] = []
        for rid in relevant_ids:
            snippet = self._by_id.get(rid)
            if snippet is None or snippet.topic_id is None:
                continue
            for lang, sid in sorted(self._by_topic[snippet.topic_id].items()):
                if lang != query_lang and sid not in gold:
                    gold.append(sid)
        return gold
