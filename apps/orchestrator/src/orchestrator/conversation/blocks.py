"""Message-block allowlist for model output (docs/security-privacy.md §3)."""

import json
import logging
from typing import Any

from contracts import MESSAGE_BLOCK_ADAPTER, MODEL_EMITTABLE_BLOCK_TYPES, TextBlock
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4000


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
