"""Regex slot extraction used by the lexical baseline."""

import pytest
from encoder.regex_slots import extract_regex_slots


def _slots(text: str) -> list[tuple[str, str]]:
    found = extract_regex_slots(text)
    for s in found:
        assert text[s.start : s.end] == s.value
    return [(s.type, s.value) for s in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Tengo un cobro de $85.000 en Falabella de ayer",
            [("currency", "$"), ("amount", "85.000"), ("transaction_date", "ayer")],
        ),
        (
            "Compra de R$ 1.250,90 no cartão final 4321",
            [("currency", "R$"), ("amount", "1.250,90"), ("card_last4", "4321")],
        ),
        ("a charge of 45.50 USD", [("amount", "45.50"), ("currency", "USD")]),
        ("disputa por 150.50 € en Shell", [("amount", "150.50"), ("currency", "€")]),
        ("por COP150.50", [("currency", "COP"), ("amount", "150.50")]),
        ("block my card ending in 6543, please", [("card_last4", "6543")]),
        ("mi tarjeta terminada en 2468, se me cayó", [("card_last4", "2468")]),
        ("El código que me llegó es 592814", [("otp_code", "592814")]),
        ("listo, 362791", [("otp_code", "362791")]),
        ("mi correo es ana.ruiz@example.com", [("email", "ana.ruiz@example.com")]),
        ("PAN 4111 1111 1111 1111", [("card_number", "4111 1111 1111 1111")]),
        ("nací el 23/06/1979", [("birth_date", "23/06/1979")]),
        ("fecha 1994-03-27, doc 98765432X", [("birth_date", "1994-03-27")]),
        ("el cargo del 12/09/2026", [("transaction_date", "12/09/2026")]),
    ],
)
def test_extracts_expected_slots(text, expected):
    assert _slots(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Relative date without a transaction: not a transaction_date.
        "Hola, extravié mi tarjeta de crédito hoy en el aeropuerto",
        # Six digits inside a formatted document number are not an OTP.
        "Mi código postal y mi CPF 318.604.927-55",
        # A long message with a six-digit number and no OTP cue.
        "quiero saber si puedo pagar 150000 en cuotas este mes",
        # Four digits inside an amount are not a card_last4.
        "la tarjeta 1.250 pesos",
    ],
)
def test_conservative_rules_extract_nothing_wrong(text):
    types = {t for t, _ in _slots(text)}
    assert not types & {"transaction_date", "otp_code", "card_last4"}


def test_slots_do_not_overlap():
    found = extract_regex_slots("cartão final 4321 código 482910 R$50 hoje compra")
    spans = sorted((s.start, s.end) for s in found)
    for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
        assert end <= start
