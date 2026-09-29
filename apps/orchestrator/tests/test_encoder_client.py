"""The encoder client names decision points and lists the ones the service knows.

An unknown id makes the whole analyze call fail with a 422 (ADR-0012), so the
client keeps the request byte-for-byte what it was when no id is named, and
surfaces the HTTP status of a failure for the caller to act on.
"""

import json
from typing import Any

import httpx
import pytest
import respx
from orchestrator.config import Settings
from orchestrator.encoder_client import EncoderClient, EncoderUnavailableError

ENCODER_URL = "http://encoder.test"

ANALYZE_OK = {
    "intent": "report_lost_card",
    "confidence": 0.93,
    "abstain": False,
    "slots": [],
    "pii_spans": [],
    "model_id": "encoder-test",
    "latency_ms": 12.0,
}

DECISION_POINTS = {
    "config_version": "abc123def456",
    "source": "artifact",
    "decision_points": [
        {
            "id": "turn_intent",
            "labels": ["report_lost_card", "request_card_block"],
            "backend_kind": "tfidf_lr",
            "backend_model_id": "tfidf_lr@train-sha256:a563c0c445d6",
            "probability_kind": "distribution",
            "status": "calibrated",
            "state": "ready",
            "enabled": True,
            "always_on": True,
            "languages_with_tau": ["es", "pt", "en"],
        }
    ],
}


def client() -> EncoderClient:
    return EncoderClient(base_url=ENCODER_URL, timeout=1.0, settings=Settings())


@pytest.fixture
def router() -> Any:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


async def test_an_analyze_without_decision_points_sends_the_legacy_body(
    router: Any,
) -> None:
    route = router.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )

    await client().analyze("perdí mi tarjeta", "es")

    assert json.loads(route.calls.last.request.content) == {
        "text": "perdí mi tarjeta",
        "lang": "es",
    }


async def test_named_decision_points_go_in_the_request(router: Any) -> None:
    route = router.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )

    await client().analyze("sí", "es", decision_points=["turn_intent"])

    body = json.loads(route.calls.last.request.content)
    assert body["decision_points"] == ["turn_intent"]


async def test_an_empty_list_is_sent_as_an_empty_list(router: Any) -> None:
    route = router.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(200, json=ANALYZE_OK)
    )

    await client().analyze("sí", "es", decision_points=[])

    assert json.loads(route.calls.last.request.content)["decision_points"] == []


async def test_a_422_carries_its_status(router: Any) -> None:
    router.post(f"{ENCODER_URL}/v1/analyze").mock(
        return_value=httpx.Response(422, json={"detail": "unknown decision points"})
    )

    with pytest.raises(EncoderUnavailableError) as raised:
        await client().analyze("sí", "es", decision_points=["confirm_gate"])

    assert raised.value.status_code == 422


async def test_a_timeout_has_no_status(router: Any) -> None:
    router.post(f"{ENCODER_URL}/v1/analyze").mock(side_effect=httpx.ReadTimeout("t"))

    with pytest.raises(EncoderUnavailableError) as raised:
        await client().analyze("sí", "es")

    assert raised.value.status_code is None


async def test_decision_points_are_listed(router: Any) -> None:
    router.get(f"{ENCODER_URL}/v1/decision-points").mock(
        return_value=httpx.Response(200, json=DECISION_POINTS)
    )

    listing = await client().decision_points()

    assert listing.config_version == "abc123def456"
    assert [dp.id for dp in listing.decision_points] == ["turn_intent"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"detail": "uncalibrated"}),
        httpx.Response(200, json={"source": "nonsense"}),
        httpx.Response(200, content=b"not json"),
    ],
    ids=["503", "invalid-payload", "not-json"],
)
async def test_a_listing_failure_is_an_unavailable_error(
    router: Any, response: httpx.Response
) -> None:
    router.get(f"{ENCODER_URL}/v1/decision-points").mock(return_value=response)

    with pytest.raises(EncoderUnavailableError):
        await client().decision_points()


async def test_an_unreachable_listing_is_an_unavailable_error(router: Any) -> None:
    router.get(f"{ENCODER_URL}/v1/decision-points").mock(
        side_effect=httpx.ConnectError("down")
    )

    with pytest.raises(EncoderUnavailableError, match="unreachable"):
        await client().decision_points()
