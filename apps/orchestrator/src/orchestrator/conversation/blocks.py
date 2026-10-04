"""Message-block allowlist for model output (docs/security-privacy.md §3)."""

import json
import logging
import re
from typing import Any

from contracts import (
    MESSAGE_BLOCK_ADAPTER,
    MODEL_EMITTABLE_BLOCK_TYPES,
    TOOL_CATALOG,
    TextBlock,
)
from contracts.envelope import VerificationState
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4000

# Names only the model's context uses: banking-core itself, the session states and
# the tools, in catalog (`customer.match`) and function (`customer_match`) form. A
# reply line that holds one is the model repeating its context (the flow line, a
# tool result) to the customer. A guardrail in code, not in the prompt (ADR-0002).
_INTERNAL_NAMES = re.compile(
    "|".join(
        [
            r"banking[- ]core",
            r"\bflow\.next\b",
            *(rf"\b{state.value}\b" for state in VerificationState),
            *(
                rf"\b{re.escape(name)}\b"
                for tool in TOOL_CATALOG
                for name in (tool, tool.replace(".", "_"))
            ),
        ]
    ),
    re.IGNORECASE,
)
_STATE_NAMES = frozenset(state.value for state in VerificationState)


def _names_internal(line: str) -> bool:
    for match in _INTERNAL_NAMES.finditer(line):
        # The states are matched as written: "verified" is a word a reply may use,
        # `VERIFIED` is the engine's.
        word = match.group(0)
        if word.upper() in _STATE_NAMES and word not in _STATE_NAMES:
            continue
        return True
    return False


def withhold_internal_lines(text: str) -> tuple[str, int]:
    """Drop the lines of a reply that name the model's context. Returns the text
    left (possibly empty) and how many lines were dropped; logs the count only,
    never the text."""
    lines = text.split("\n")
    kept = [line for line in lines if not _names_internal(line)]
    withheld = len(lines) - len(kept)
    if withheld:
        logger.warning("Withheld %d reply line(s) naming internal context", withheld)
    return "\n".join(kept).strip(), withheld


def drop_repeated_lines(texts: list[str]) -> tuple[list[str], int]:
    """Drop every line that repeats an earlier line of the same reply, across its
    text blocks: the model sometimes writes its answer twice in one completion.
    Lines compare with their whitespace collapsed. Returns the texts left (a block
    left empty is dropped) and how many lines went; logs the count only."""
    seen: set[str] = set()
    kept_texts: list[str] = []
    dropped = 0
    for text in texts:
        kept: list[str] = []
        for line in text.split("\n"):
            key = " ".join(line.split())
            if key and key in seen:
                dropped += 1
                continue
            seen.add(key)
            kept.append(line)
        left = "\n".join(kept).strip()
        if left:
            kept_texts.append(left)
    if dropped:
        logger.warning("Dropped %d repeated reply line(s)", dropped)
    return kept_texts, dropped


def _as_text_block(text: str) -> TextBlock | None:
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_TEXT_LENGTH:
        logger.warning("Assistant text truncated to %d chars", MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]
    return TextBlock(text=text)


def filter_model_blocks(content: str | None) -> tuple[list[TextBlock], list[str]]:
    """Turn model output into allowlisted blocks.

    Plain text becomes one text block. A JSON object `{"blocks": [...]}` is
    parsed block by block: only MODEL_EMITTABLE_BLOCK_TYPES that validate
    against the contract survive; the rest are dropped and logged by type
    only (never by content). Returns (blocks, dropped block types).
    """
    if not content or not content.strip():
        return [], []

    parsed: Any = None
    stripped = content.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None

    if not (isinstance(parsed, dict) and isinstance(parsed.get("blocks"), list)):
        block = _as_text_block(content)
        return ([block] if block else []), []

    kept: list[TextBlock] = []
    dropped: list[str] = []
    for raw in parsed["blocks"]:
        block_type = raw.get("type") if isinstance(raw, dict) else None
        label = block_type if isinstance(block_type, str) else "<invalid>"
        if label not in MODEL_EMITTABLE_BLOCK_TYPES:
            dropped.append(label)
            continue
        try:
            block = MESSAGE_BLOCK_ADAPTER.validate_python(raw)
        except ValidationError:
            dropped.append(label)
            continue
        if isinstance(block, TextBlock):
            kept.append(block)
        else:  # pragma: no cover - guarded by the emittable allowlist above
            dropped.append(label)

    if dropped:
        logger.warning("Dropped non-allowlisted model blocks: %s", sorted(dropped))
    return kept, dropped
