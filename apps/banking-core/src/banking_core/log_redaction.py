"""Keep session ids out of the access log.

The simulated inbox is read at ``GET /v1/sessions/{session_id}/simulated-inbox``
(ADR-0007), so the session id, which used to travel only in a header, is now in a
URL path that uvicorn's access log records. Whoever holds a live session id can
read that session's OTP code until it expires, so logs get a redacted form.
"""

import logging
import re

_SESSION_ID_RE = re.compile(r"sess_[0-9a-f]{32}")
REDACTED_ID = "sess_[redacted]"


def redact(text: str) -> str:
    return _SESSION_ID_RE.sub(REDACTED_ID, text)


class RedactSessionIds(logging.Filter):
    """Rewrites a record's message and args so no session id is emitted."""

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
        if not any(isinstance(f, RedactSessionIds) for f in target.filters):
            target.addFilter(RedactSessionIds())
