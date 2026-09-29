"""Masked transcript: what GET /v1/conversations/{id} may show."""

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from orchestrator.privacy.masking import Masker, MaskingError, RegexMasker
from orchestrator.session.models import ConversationState, MessageRole

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"

# The one masker that writes the stored transcript: customer turns, assistant
# blocks and agent messages all pass through it with the conversation's map.
TRANSCRIPT_MASKER: Masker = RegexMasker()


class TranscriptMessage(BaseModel):
    """A stored message as a transcript shows it: no metadata, no retry handle."""

    role: MessageRole
    content: str
    blocks: list[dict[str, Any]]
    created_at: datetime


def transcript_messages(state: ConversationState) -> list[TranscriptMessage]:
    """The messages a transcript may show, system prompts left out."""
    return [
        TranscriptMessage(
            role=m.role, content=m.content, blocks=m.blocks, created_at=m.created_at
        )
        for m in state.messages
        if m.role is not MessageRole.SYSTEM
    ]


def mask_for_transcript(
    text: str, placeholder_map: dict[str, str], masker: Masker
) -> str:
    """Mask text for storage, reusing the conversation's placeholders.

    Two passes: known raw values are replaced by their placeholders first
    (catches values the regexes only detect in context, such as a name after
    "me llamo"), then the regex masker runs. Fails closed to REDACTED.
    Updates `placeholder_map` in place with any new placeholder.
    """
    masked = text
    for placeholder, raw in sorted(
        placeholder_map.items(), key=lambda item: len(item[1]), reverse=True
    ):
        if raw:
            masked = masked.replace(raw, placeholder)
    try:
        result = masker.mask(masked, state=placeholder_map)
    except MaskingError:
        logger.warning("Transcript text failed masking; stored as redacted")
        return REDACTED
    if not masker.verify_safe(result.masked_text):
        return REDACTED
    # New placeholders join the conversation map so numbering stays consistent.
    placeholder_map.update(result.mapping)
    return result.masked_text
