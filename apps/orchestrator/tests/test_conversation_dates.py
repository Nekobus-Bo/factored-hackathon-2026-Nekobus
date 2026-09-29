"""Customer-typed dates become ISO before banking-core validates them."""

import json
from typing import Any

import httpx
import pytest
import respx
from contracts import TOOL_CATALOG
from orchestrator.conversation import ConversationContext
from orchestrator.conversation.dates import (
    date_arguments,
    normalize_date,
    normalize_date_arguments,
)

from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import (
    ANALYZE_OK,
    BANKING_URL,
    ENCODER_URL,
    SESSION_ID,
    FakeBankingCore,
    make_engine,
)


@pytest.mark.parametrize(
    ("lang", "typed", "iso"),
    [
        # es and pt are day-first, whatever the separator
        ("es", "15/03/1985", "1985-03-15"),
        ("es", "15-03-1985", "1985-03-15"),
        ("es", "15.03.1985", "1985-03-15"),
        ("es", "5/3/1985", "1985-03-05"),
        ("es", "03/04/1985", "1985-04-03"),
        ("es", "29/02/1984", "1984-02-29"),
        ("pt", "15/03/1985", "1985-03-15"),
        ("pt", "03/04/1985", "1985-04-03"),
        ("pt", "1.2.2001", "2001-02-01"),
        # en is month-first unless the first part can only be a day
        ("en", "03/15/1985", "1985-03-15"),
        ("en", "03/04/1985", "1985-03-04"),
        ("en", "15/03/1985", "1985-03-15"),
        ("en", "12/31/1999", "1999-12-31"),
        ("en", "3.4.1985", "1985-03-04"),
        # year-first is year-month-day in every language
        ("es", "1985/03/15", "1985-03-15"),
        ("en", "1985.3.5", "1985-03-05"),
        # surrounding whitespace is not part of the date
        ("es", " 15/03/1985 ", "1985-03-15"),
    ],
)
def test_numeric_dates_become_iso(lang: Any, typed: str, iso: str) -> None:
    assert normalize_date(typed, lang) == iso


@pytest.mark.parametrize("lang", ["es", "pt", "en"])
@pytest.mark.parametrize("iso", ["1985-03-15", "2001-12-31", "1984-02-29"])
def test_iso_input_is_left_alone(lang: Any, iso: str) -> None:
    assert normalize_date(iso, lang) == iso
    assert normalize_date(f" {iso} ", lang) == f" {iso} "


@pytest.mark.parametrize(
    ("lang", "typed"),
    [
        # not calendar dates
        ("es", "31/02/1990"),
        ("pt", "31/02/1990"),
        ("en", "02/31/1990"),
        ("en", "31/02/1990"),
        ("es", "29/02/1985"),
        ("es", "00/01/1990"),
        ("es", "15/00/1990"),
        ("es", "15/13/1985"),
        ("en", "13/13/1985"),
        ("en", "00/10/1990"),
        ("es", "1985-02-31"),
        ("es", "1985/13/01"),
        # day-first languages do not guess a US date
        ("es", "03/15/1985"),
        ("pt", "12/31/1999"),
        # not unambiguous numeric dates
        ("es", "15/03/85"),
        ("en", "3/15/85"),
        ("es", "15/03-1985"),
        ("es", "15/03/19850"),
        ("es", "150/03/1985"),
        ("es", "15 03 1985"),
        ("es", "15 de marzo de 1985"),
        ("en", "March 15 1985"),
        ("es", "1985-03-15T00:00:00"),
        ("es", "15/03/1985 extra"),
        ("es", "[DATE_1]"),
        ("es", "١٥/٠٣/١٩٨٥"),
        ("es", ""),
    ],
)
def test_anything_else_is_left_for_contract_validation(lang: Any, typed: str) -> None:
    assert normalize_date(typed, lang) == typed


def test_only_date_typed_arguments_are_normalized() -> None:
    assert date_arguments("customer.match") == ("birth_date",)
    assert not any(
        date_arguments(tool) for tool in TOOL_CATALOG if tool != "customer.match"
    )

    args: dict[str, Any] = {
        "document_type": "NATIONAL_ID",
        "document_number": "15/03/1985",
        "birth_date": "15/03/1985",
    }
    normalize_date_arguments("customer.match", args, "es")
    assert args == {
        "document_type": "NATIONAL_ID",
        "document_number": "15/03/1985",
        "birth_date": "1985-03-15",
    }

    # Absent, null or non-string values are none of the normalizer's business.
    for unchanged in ({"document_type": "PASSPORT"}, {"birth_date": None}):
        copy = dict(unchanged)
        normalize_date_arguments("customer.match", copy, "es")
        assert copy == unchanged


@pytest.fixture
def mock_services() -> Any:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{ENCODER_URL}/v1/analyze").mock(
            return_value=httpx.Response(200, json=ANALYZE_OK)
        )
        yield router


MATCH_WITH_BIRTH_DATE = tool_call(
    "call_1",
    "customer_match",
    {
        "document_type": "NATIONAL_ID",
        "document_number": "[DOC_1]",
        "birth_date": "[DATE_1]",
    },
)


@pytest.mark.parametrize(
    ("lang", "text", "typed", "iso"),
    [
        (
            "es",
            "Mi cédula es 1020304050, nací el 15/03/1985",
            "15/03/1985",
            "1985-03-15",
        ),
        ("pt", "Meu CPF é 1020304050, nasci em 15/03/1985", "15/03/1985", "1985-03-15"),
        ("en", "My ID is 1020304050, born on 03/15/1985", "03/15/1985", "1985-03-15"),
    ],
)
async def test_customer_match_receives_the_birth_date_as_iso(
    mock_services: Any, lang: Any, text: str, typed: str, iso: str
) -> None:
    banking = FakeBankingCore()
    mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    llm = ScriptedLLM([Step(tool_calls=[MATCH_WITH_BIRTH_DATE]), Step(content="Ok.")])
    context = ConversationContext(session_id=SESSION_ID, language=lang)

    result = await make_engine(llm).run_turn(context, text)

    assert context.placeholder_map["[DATE_1]"] == typed
    assert banking.calls_to("customer.match")[0]["args"] == {
        "document_type": "NATIONAL_ID",
        "document_number": "1020304050",
        "birth_date": iso,
    }
    assert result.metadata.tool_outcomes[0].executed is True
    # The raw date lives only in the server-side mapping and the request.
    assert typed not in json.dumps(context.history)
    assert typed not in llm.payload_dump()


async def test_an_impossible_birth_date_is_rejected_locally(
    mock_services: Any,
) -> None:
    banking = FakeBankingCore()
    route = mock_services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=banking)
    llm = ScriptedLLM([Step(tool_calls=[MATCH_WITH_BIRTH_DATE]), Step(content="Ok.")])
    context = ConversationContext(session_id=SESSION_ID, language="es")

    result = await make_engine(llm).run_turn(
        context, "Mi cédula es 1020304050, nací el 31/02/1990"
    )

    assert route.call_count == 0
    outcome = result.metadata.tool_outcomes[0]
    assert outcome.executed is False
    assert outcome.reason_code is not None
    assert outcome.reason_code.value == "INVALID_ARGUMENTS"
