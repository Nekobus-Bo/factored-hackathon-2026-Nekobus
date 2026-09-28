"""Keep conversation ids out of logs.

A conversation_id is a capability: whoever holds it can read the transcript
and send turns. Logs (including uvicorn's access log, which records the path)
get a redacted form instead.
"""

import logging
import re

_CONVERSATION_ID_RE = re.compile(r"conv_[0-9a-f]{32}")
REDACTED_ID = "conv_[redacted]"


def redact(text: str) -> str:
    return _CONVERSATION_ID_RE.sub(REDACTED_ID, text)


class RedactConversationIds(logging.Filter):
    """Rewrites a record's message and args so no conversation id is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: redact(v) if isinstance(v, str) else v
                for k, v in record.args.items()
            }
        return True


def install_redaction(logger_names: tuple[str, ...] = ("uvicorn.access",)) -> None:
    """Attach the filter once to each named logger (idempotent)."""
    for name in logger_names:
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactConversationIds) for f in target.filters):
            target.addFilter(RedactConversationIds())
