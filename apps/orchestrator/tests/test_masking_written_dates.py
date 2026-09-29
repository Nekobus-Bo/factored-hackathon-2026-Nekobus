"""Written-out dates are PII: masked as [DATE_n] in es, pt and en (AGENTS rule 5).

The numeric forms ("15/03/1985") are covered in test_masking.py. Here: "4 de
marzo de 1988", "March 4, 1988" and their variants, and the text next to them
that is not a date and must reach the model unchanged.
"""

import json
import unicodedata

import pytest
from orchestrator.privacy.masking import (
    RegexMasker,
    mask_json_string_values,
)
from orchestrator.privacy.written_dates import find_written_dates

ES = [
    "4 de marzo de 1988",
    "4 de Marzo de 1988",
    "4 DE MARZO DE 1988",
    "4 marzo 1988",
    "4 de marzo del 1988",
    "1º de mayo de 1990",
    "1ro de enero de 2000",
    "4 de setiembre de 1988",
    "4 mar 1988",
    "4 mar. 1988",
    "4-mar-1988",
    "12 dic 1979",
    "12 ene 1979",
]
PT = [
    "4 de março de 1988",
    "4 de Março de 1988",
    "4 de marco de 1988",  # accent optional
    "4 de " + unicodedata.normalize("NFD", "março") + " de 1988",  # combining mark
    "4 março 1988",
    "1o de maio de 1990",
    "4 de setembro de 1988",
    "12 de dezembro de 1979",
    "12 dez 1979",
    "12 out 1979",
    "4 mai 1988",
    "4 fev 1988",
]
EN = [
    "March 4, 1988",
    "March 4 1988",
    "march 4th, 1988",
    "MARCH 4, 1988",
    "4 March 1988",
    "4th of March 1988",
    "4th of March, 1988",
    "Mar 4 1988",
    "Mar. 4, 1988",
    "4 mar 1988",
    "Sept 12, 1979",
    "Dec 12, 1979",
    "May 5, 1990",
]


@pytest.mark.parametrize("written", [*ES, *PT, *EN])
def test_written_date_is_masked_and_round_trips(written: str) -> None:
    masker = RegexMasker()
    text = f"Nací el {written}, gracias."
    res = masker.mask(text)

    assert res.masked_text == "Nací el [DATE_1], gracias."
    assert res.mapping == {"[DATE_1]": written}
    assert masker.verify_safe(res.masked_text)
    assert masker.unmask(res.masked_text, res.mapping) == text


@pytest.mark.parametrize("written", [*ES[:3], *PT[:3], *EN[:3]])
def test_raw_written_date_is_not_safe(written: str) -> None:
    masker = RegexMasker()
    assert not masker.verify_safe(f"born on {written}")


def test_date_is_masked_next_to_other_pii_and_accented_text() -> None:
    masker = RegexMasker()
    text = "Señora Ñandú: mi correo es ana@bank.com, nasci em 4 de março de 1988 ✓"
    res = masker.mask(text)

    assert "1988" not in res.masked_text
    assert "ana@bank.com" not in res.masked_text
    assert res.masked_text.startswith("Señora Ñandú: mi correo es [EMAIL_1], ")
    assert res.masked_text.endswith(" ✓")
    assert res.mapping["[DATE_1]"] == "4 de março de 1988"
    assert masker.unmask(res.masked_text, res.mapping) == text


def test_same_date_shares_a_placeholder_and_new_ones_continue_the_count() -> None:
    masker = RegexMasker()
    first = masker.mask("El 4 de marzo de 1988 y otra vez 4 de marzo de 1988.")
    assert first.masked_text == "El [DATE_1] y otra vez [DATE_1]."

    second = masker.mask("Y March 5, 1990", state=first.mapping)
    assert second.masked_text == "Y [DATE_2]"
    assert second.mapping["[DATE_1]"] == "4 de marzo de 1988"


def test_a_date_is_never_cut_by_a_shorter_date_it_ends_with() -> None:
    masker = RegexMasker()
    text = "14 de marzo de 1988 y 4 de marzo de 1988"
    res = masker.mask(text)

    assert res.masked_text == "[DATE_1] y [DATE_2]"
    assert res.mapping == {
        "[DATE_1]": "14 de marzo de 1988",
        "[DATE_2]": "4 de marzo de 1988",
    }


def test_leading_article_stays_outside_the_masked_date() -> None:
    masker = RegexMasker()
    res = masker.mask("I was born on the 4th of March, 1988.")

    assert res.masked_text == "I was born on the [DATE_1]."
    assert res.mapping == {"[DATE_1]": "4th of March, 1988"}


def test_two_written_dates_in_a_row() -> None:
    masker = RegexMasker()
    res = masker.mask("Del 4 de marzo de 1988 al 5 de mayo de 1990")

    assert res.masked_text == "Del [DATE_1] al [DATE_2]"


def test_impossible_calendar_day_is_still_masked() -> None:
    """Masking follows what was typed; whether the calendar agrees is not its job."""
    masker = RegexMasker()
    res = masker.mask("Nací el 31 de febrero de 1990")

    assert res.masked_text == "Nací el [DATE_1]"


def test_written_date_inside_a_json_tool_argument_is_masked() -> None:
    masker = RegexMasker()
    args = {"document_type": "NATIONAL_ID", "birth_date": "4 de marzo de 1988"}
    state: dict[str, str] = {}

    masked = mask_json_string_values(args, masker, state)

    assert masked == {"document_type": "NATIONAL_ID", "birth_date": "[DATE_1]"}
    assert state["[DATE_1]"] == "4 de marzo de 1988"
    assert "1988" not in json.dumps(masked)


@pytest.mark.parametrize(
    "text",
    [
        # a month or a day alone is not a value that identifies anyone
        "mayo",
        "Fue en mayo.",
        "March madness",
        "May I ask something?",
        "12 de octubre",
        "cobro del 4 de agosto",
        "marzo de 1988",
        "March 1988",
        "mayo 2024",
        # amounts and numbers next to month-like words
        "gasté 1988 pesos",
        "cobro de $1,988.00 en mayo",
        "USD 2000 en marzo",
        "3 mar 1234",
        "tarjeta terminada en 2001",
        # a month name is a whole word
        "4 mark 1988",
        "Marzipan 4 1988",
        "4 de marzo de 1788",
        "4 de marzo de 21988",
        # words that are not months
        "4 de septiembres de 1988",
    ],
)
def test_text_that_is_not_a_written_date_is_left_alone(text: str) -> None:
    masker = RegexMasker()
    res = masker.mask(text)

    assert res.masked_text == text
    assert res.mapping == {}
    assert masker.verify_safe(text)
    assert find_written_dates(text) == []
