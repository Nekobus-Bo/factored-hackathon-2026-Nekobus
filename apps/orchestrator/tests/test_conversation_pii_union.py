"""The turn masks the union of the regexes and the encoder's PII spans.

The encoder now runs first, on the raw text, and its spans widen the masking of
what leaves for the provider (AGENTS rule 5). The tests read what the engine
hands to the LLM layer, where the raw name must never appear, and pin the
fail-closed edges: an encoder that is down means regex-only masking (never
less), and spans that cannot be placed mean nothing is sent.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from orchestrator.conversation import ConversationContext
from orchestrator.conversation.prompt import REPHRASE_MESSAGES
from orchestrator.llm.replay import compute_recording_key

from .fake_llm import ScriptedLLM, Step
from .test_conversation_engine import (
    ANALYZE_OK,
    ENCODER_URL,
    SESSION_ID,
    make_engine,
)

NAME = "Carlos Gómez"
TEXT = f"hola, {NAME} aquí, perdí mi tarjeta"

Spans = Callable[[str], list[dict[str, Any]]]


def spans_at(kind: str, needle: str) -> Spans:
    def build(text: str) -> list[dict[str, Any]]:
        start = text.index(needle)
        return [{"type": kind, "start": start, "end": start + len(needle)}]

    return build


def no_spans(text: str) -> list[dict[str, Any]]:
    return []


@pytest.fixture
def encoder() -> Any:
    """respx router; `encoder.mock_spans(fn)` makes the encoder answer with them."""
    with respx.mock(assert_all_called=False) as router:

        def mock_spans(spans: Spans) -> Any:
            def handler(request: httpx.Request) -> httpx.Response:
                text = json.loads(request.content)["text"]
                return httpx.Response(
                    200, json={**ANALYZE_OK, "pii_spans": spans(text)}
                )

            return router.post(f"{ENCODER_URL}/v1/analyze").mock(side_effect=handler)

        router.mock_spans = mock_spans  # type: ignore[attr-defined]
        yield router


def context(**fields: Any) -> ConversationContext:
    return ConversationContext(session_id=SESSION_ID, language="es", **fields)


# ---------------------------------------------------- what the encoder adds


async def test_a_name_only_the_encoder_finds_never_reaches_the_llm(
    encoder: Any,
) -> None:
    encoder.mock_spans(spans_at("NAME", NAME))
    llm = ScriptedLLM([Step(content="Hola [NAME_1], ¿me confirmas tu cédula?")])
    ctx = context()

    result = await make_engine(llm).run_turn(ctx, TEXT)

    payload = llm.payload_dump()
    assert "Carlos" not in payload and "Gómez" not in payload
    assert llm.calls[0]["messages"][-1] == {
        "role": "user",
        "content": "hola, [NAME_1] aquí, perdí mi tarjeta",
    }
    assert ctx.placeholder_map == {"[NAME_1]": NAME}
    assert "Carlos" not in json.dumps(ctx.history, ensure_ascii=False)
    # the customer gets their own name back, not the placeholder
    assert result.blocks[0].text == f"Hola {NAME}, ¿me confirmas tu cédula?"  # type: ignore[union-attr]
    assert result.metadata.encoder_pii_spans == 1
    assert result.metadata.encoder_spans_added == 1
    assert result.metadata.masking_regex_only is False


async def test_the_same_name_keeps_its_placeholder_on_the_next_turn(
    encoder: Any,
) -> None:
    encoder.mock_spans(spans_at("NAME", NAME))
    llm = ScriptedLLM([Step(content="Ok."), Step(content="Ok.")])
    ctx = context()
    engine = make_engine(llm)

    await engine.run_turn(ctx, TEXT)
    await engine.run_turn(ctx, f"otra vez, {NAME}, sigo esperando")

    users = [m["content"] for m in ctx.history if m["role"] == "user"]
    assert users == [
        "hola, [NAME_1] aquí, perdí mi tarjeta",
        "otra vez, [NAME_1], sigo esperando",
    ]
    assert ctx.placeholder_map == {"[NAME_1]": NAME}


async def test_without_encoder_spans_the_regexes_alone_miss_that_name(
    encoder: Any,
) -> None:
    """The gap the union closes, kept as a documented contrast."""
    encoder.mock_spans(no_spans)
    llm = ScriptedLLM([Step(content="Ok.")])

    result = await make_engine(llm).run_turn(context(), TEXT)

    assert NAME in llm.payload_dump()
    assert result.metadata.encoder_pii_spans == 0
    assert result.metadata.masking_regex_only is False


async def test_the_encoder_gets_the_raw_text_and_runs_before_the_llm(
    encoder: Any,
) -> None:
    route = encoder.mock_spans(spans_at("NAME", NAME))
    llm = ScriptedLLM([Step(content="Ok.")])
    seen_before_llm: list[int] = []
    original = llm.complete

    async def spy(*args: Any, **kwargs: Any) -> Any:
        seen_before_llm.append(route.call_count)
        return await original(*args, **kwargs)

    llm.complete = spy  # type: ignore[method-assign]

    await make_engine(llm).run_turn(
        context(), "correo ana@bank.com y soy Luis Pérez, " + TEXT
    )

    request = json.loads(route.calls[0].request.content)
    assert request["text"] == "correo ana@bank.com y soy Luis Pérez, " + TEXT
    assert seen_before_llm == [1]


async def test_an_encoder_span_wider_than_a_regex_match_replaces_it(
    encoder: Any,
) -> None:
    encoder.mock_spans(spans_at("DOC", "CC 1020304050"))
    llm = ScriptedLLM([Step(content="Ok.")])
    ctx = context()

    await make_engine(llm).run_turn(
        ctx, "mi cédula es CC 1020304050 y soy Ana Pérez"
    )

    assert ctx.history[0]["content"] == "mi cédula es [DOC_1] y soy [NAME_1]"
    assert ctx.placeholder_map == {"[DOC_1]": "CC 1020304050", "[NAME_1]": "Ana Pérez"}
    assert "1020304050" not in llm.payload_dump()


async def test_offsets_hold_with_emoji_and_accents_before_the_span(
    encoder: Any,
) -> None:
    encoder.mock_spans(spans_at("NAME", "Ñandú Gómez"))
    llm = ScriptedLLM([Step(content="Ok.")])
    ctx = context()

    text = "😀🎉 ¡Hola! Señora Ñandú Gómez necesita ayuda"

    await make_engine(llm).run_turn(ctx, text)

    expected = "😀🎉 ¡Hola! Señora [NAME_1] necesita ayuda"
    assert ctx.history[0]["content"] == expected


async def test_spans_outside_the_text_are_ignored_and_the_turn_works(
    encoder: Any,
) -> None:
    encoder.mock_spans(lambda text: [{"type": "NAME", "start": 900, "end": 950}])
    llm = ScriptedLLM([Step(content="Ok.")])
    ctx = context()

    result = await make_engine(llm).run_turn(ctx, "perdí mi tarjeta")

    assert ctx.history[0]["content"] == "perdí mi tarjeta"
    assert result.metadata.encoder_pii_spans == 1
    assert result.metadata.encoder_spans_added == 0


async def test_offsets_stay_in_raw_coordinates_while_an_otp_is_pending(
    encoder: Any,
) -> None:
    """The bare-code pre-pass shifts the text; the encoder's offsets do not move."""
    encoder.mock_spans(spans_at("NAME", "María Gómez"))
    otp_sent = json.dumps({"tool": "otp.send", "status": "ok", "data": {}})
    ctx = context(history=[{"role": "tool", "tool_call_id": "c0", "content": otp_sent}])
    llm = ScriptedLLM([Step(content="Ok.")])

    await make_engine(llm).run_turn(ctx, "264819 María Gómez")

    user = [m for m in ctx.history if m["role"] == "user"][-1]
    assert user["content"] == "[OTP_1] [NAME_1]"
    assert ctx.placeholder_map == {"[OTP_1]": "264819", "[NAME_1]": "María Gómez"}


# ------------------------------------------------- the same input, the same key


async def test_same_text_and_encoder_output_give_the_same_llm_payload(
    encoder: Any,
) -> None:
    encoder.mock_spans(spans_at("NAME", NAME))
    payloads = []
    for _ in range(2):
        llm = ScriptedLLM([Step(content="Ok.")])
        await make_engine(llm).run_turn(context(), TEXT, turn_id="t1")
        payloads.append(llm.calls[0]["messages"])

    assert payloads[0] == payloads[1]
    keys = {compute_recording_key("m", "1", messages) for messages in payloads}
    assert len(keys) == 1


async def test_spans_the_regexes_already_cover_do_not_move_the_llm_payload(
    encoder: Any,
) -> None:
    text = "mi correo es ana@bank.com, nasci em 4 de março de 1988, soy Luis Pérez"
    payloads = []
    for spans in (
        no_spans,
        lambda t: [
            *spans_at("EMAIL", "ana@bank.com")(t),
            *spans_at("DATE", "4 de março de 1988")(t),
            *spans_at("NAME", "Luis Pérez")(t),
        ],
    ):
        encoder.mock_spans(spans)
        llm = ScriptedLLM([Step(content="Ok.")])
        result = await make_engine(llm).run_turn(context(), text, turn_id="t1")
        payloads.append(llm.calls[0]["messages"])
        assert result.metadata.encoder_spans_added == 0

    assert payloads[0] == payloads[1]
    assert payloads[0][-1]["content"] == (
        "mi correo es [EMAIL_1], nasci em [DATE_1], soy [NAME_1]"
    )


# ------------------------------------------------- the encoder is not available


def down_503() -> Any:
    return httpx.Response(503, json={"detail": "uncalibrated"})


def bad_payload() -> Any:
    return httpx.Response(200, json={"intent": "nonsense"})


@pytest.mark.parametrize(
    "failure",
    [
        down_503(),
        bad_payload(),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
    ids=["503", "invalid-payload", "timeout", "unreachable"],
)
async def test_encoder_down_means_regex_only_masking_and_the_turn_goes_on(
    encoder: Any, failure: Any
) -> None:
    encoder.post(f"{ENCODER_URL}/v1/analyze").mock(
        side_effect=failure if isinstance(failure, Exception) else None,
        return_value=None if isinstance(failure, Exception) else failure,
    )
    llm = ScriptedLLM([Step(content="Hola, ¿en qué te ayudo?")])
    ctx = context()

    result = await make_engine(llm).run_turn(
        ctx, "mi correo es ana@bank.com. " + TEXT
    )

    assert result.metadata.encoder_unavailable is True
    assert result.metadata.masking_regex_only is True
    assert result.metadata.encoder is None
    assert result.metadata.masking_failed is False
    assert result.blocks[0].text == "Hola, ¿en qué te ayudo?"  # type: ignore[union-attr]
    # exactly the regex masking: the email is hidden, the name is not
    payload = llm.payload_dump()
    assert "ana@bank.com" not in payload
    assert NAME in payload


class _ExplodingEncoder:
    async def analyze(self, text: str, lang: Any = None) -> Any:
        raise RuntimeError(f"model crashed on {text!r}")


async def test_an_unexpected_encoder_error_also_degrades_and_is_not_logged_with_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = ScriptedLLM([Step(content="Ok.")])
    engine = make_engine(llm)
    engine.encoder = _ExplodingEncoder()
    caplog.set_level(logging.WARNING, logger="orchestrator.conversation.engine")

    result = await engine.run_turn(context(), "mi correo es ana@bank.com. " + TEXT)

    assert result.metadata.masking_regex_only is True
    assert "ana@bank.com" not in llm.payload_dump()
    assert "RuntimeError" in caplog.text
    assert "ana@bank.com" not in caplog.text and "Gómez" not in caplog.text


async def test_no_encoder_configured_is_regex_only_by_design_not_a_degradation() -> (
    None
):
    llm = ScriptedLLM([Step(content="Ok.")])
    engine = make_engine(llm)
    engine.encoder = None

    result = await engine.run_turn(context(), TEXT)

    assert result.metadata.masking_regex_only is False
    assert result.metadata.encoder_unavailable is False


# ----------------------------------------------------------- refuse, never leak


async def test_spans_that_cannot_be_placed_send_nothing(encoder: Any) -> None:
    """A typed text shaped like a stored placeholder cannot be aligned."""
    encoder.mock_spans(spans_at("NAME", "Pedro"))
    llm = ScriptedLLM([])
    ctx = context(placeholder_map={"[NAME_1]": "Ana"})

    result = await make_engine(llm).run_turn(ctx, "[NAME_1] y Pedro")

    assert llm.calls == []
    assert result.metadata.masking_failed is True
    assert result.blocks[0].text == REPHRASE_MESSAGES["es"]  # type: ignore[union-attr]
    assert ctx.history == []
    assert ctx.placeholder_map == {"[NAME_1]": "Ana"}
