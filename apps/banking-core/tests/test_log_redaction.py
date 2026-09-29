"""The access log never records a session id (it opens the session's inbox)."""

import logging

import pytest
from banking_core.log_redaction import REDACTED_ID, redact

SESSION_ID = "sess_" + "a1" * 16


def test_a_session_id_is_redacted_wherever_it_appears() -> None:
    assert redact(f"/v1/sessions/{SESSION_ID}/simulated-inbox") == (
        f"/v1/sessions/{REDACTED_ID}/simulated-inbox"
    )
    assert redact("no session here") == "no session here"


def test_the_uvicorn_access_log_of_the_app_never_records_the_session_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import banking_core.main  # noqa: F401  (installs the filter)

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            f"/v1/sessions/{SESSION_ID}/simulated-inbox",
            "1.1",
            200,
        )

    assert SESSION_ID not in caplog.text
    assert f"/v1/sessions/{REDACTED_ID}/simulated-inbox" in caplog.text
