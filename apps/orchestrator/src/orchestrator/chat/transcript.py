"""Masked transcript: what GET /v1/conversations/{id} may show."""

import logging

from orchestrator.privacy.masking import Masker, MaskingError

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"


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
