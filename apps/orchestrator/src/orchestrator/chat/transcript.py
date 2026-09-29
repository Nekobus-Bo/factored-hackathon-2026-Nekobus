"""The transcript: what GET /v1/conversations/{id} and the agent API may show.

Everything stored in clear is masked, and customer and assistant messages are
shown as stored. An agent's message is shown as the agent wrote it: the masked
`content` is what redis-edge holds in clear, and the text as written is read
back here from its ciphertext (`Message.content_enc`). This module is the only
reader of that ciphertext, next to the agent route that writes it.
"""

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from orchestrator.privacy.masking import Masker, MaskingError, RegexMasker
from orchestrator.session.crypto import CryptoError, PlaceholderEncryptor
from orchestrator.session.models import ConversationState, Message, MessageRole

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"

# The one masker that writes the stored transcript: customer turns, assistant
# blocks and agent messages all pass through it with the conversation's map.
TRANSCRIPT_MASKER: Masker = RegexMasker()


class TranscriptMessage(BaseModel):
    """A stored message as a transcript shows it.

    No metadata, no retry handle, no ciphertext: `content` is the text to read.
    """

    role: MessageRole
    content: str
    blocks: list[dict[str, Any]]
    created_at: datetime


def text_as_written(message: Message, encryptor: PlaceholderEncryptor) -> str:
    """The text a reader is shown for a message.

    An agent message that kept its text gives it back as written. Any other
    message, and an agent message stored before the text was kept, gives its
    masked `content`. If the ciphertext cannot be read (a corrupted value, a
    changed SESSION_SECRET) the masked `content` is shown instead and a warning
    is logged: never an error to the reader, and never the text in the log.
    """
    if message.role is not MessageRole.AGENT or message.content_enc is None:
        return message.content
    try:
        return encryptor.decrypt_text(message.content_enc)
    except CryptoError:
        logger.warning(
            "An agent message could not be decrypted; its masked text is shown"
        )
        return message.content


def transcript_messages(
    state: ConversationState, encryptor: PlaceholderEncryptor
) -> list[TranscriptMessage]:
    """The messages a transcript may show, system prompts left out."""
    return [
        TranscriptMessage(
            role=m.role,
            content=text_as_written(m, encryptor),
            blocks=m.blocks,
            created_at=m.created_at,
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
