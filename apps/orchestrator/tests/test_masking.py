"""Unit tests for PII masking and rehydration (ADR-0001, ADR-0004, AGENTS rule 5).

Verifies:
- Replacement of emails with [EMAIL_n]
- Replacement of 13-19 digit PAN card numbers with [CARD_n]
- Replacement of phone numbers with [PHONE_n]
- Replacement of document numbers (CPF, SSN, DNI dots, labeled docs) with [DOC_n]
- Replacement of birth dates and conversational name intros with placeholders
- Currency amounts are preserved and not incorrectly treated as PII
- Comprehensive verify_safe checks across all PII categories
- Real customer turns from eval/scenarios contain zero surviving PII
"""

import json

import pytest
from contracts import PiiType
from orchestrator.privacy.masking import MaskingError, RegexMasker


def test_regex_masker_email_and_stability() -> None:
    masker = RegexMasker()
    text = (
        "Hello, my email is alice@bank.com and backup is alice@bank.com "
        "or bob@other.org."
    )
    res = masker.mask(text)

    # alice@bank.com should use the same placeholder both times
    assert "alice@bank.com" not in res.masked_text
    assert "bob@other.org" not in res.masked_text
    assert "[EMAIL_1]" in res.masked_text
    assert "[EMAIL_2]" in res.masked_text
    assert res.mapping["[EMAIL_1]"] == "alice@bank.com"
    assert res.mapping["[EMAIL_2]"] == "bob@other.org"

    # Unmask restores exact text
    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert unmasked == text


def test_regex_masker_pan_variations() -> None:
    masker = RegexMasker()
    # 16-digit with spaces, with dashes, and contiguous
    text = "Cards: 4532 1234 5678 9012 and 4111-2222-3333-4444 and 5555666677778888."
    res = masker.mask(text)

    assert "4532 1234 5678 9012" not in res.masked_text
    assert "4111-2222-3333-4444" not in res.masked_text
    assert "5555666677778888" not in res.masked_text
    assert "[CARD_1]" in res.masked_text
    assert "[CARD_2]" in res.masked_text
    assert "[CARD_3]" in res.masked_text

    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert unmasked == text


def test_regex_masker_phone_numbers() -> None:
    masker = RegexMasker()
    text = "Contact me at +57 300 1234567 or tel: (555) 234-5678."
    res = masker.mask(text)

    assert "+57 300 1234567" not in res.masked_text
    assert "[PHONE_1]" in res.masked_text

    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert unmasked == text


def test_regex_masker_documents() -> None:
    masker = RegexMasker()
    text = "Documents: CPF 123.456.789-01, SSN 123-45-6789, CC 1.020.345.678."
    res = masker.mask(text)

    assert "123.456.789-01" not in res.masked_text
    assert "123-45-6789" not in res.masked_text
    assert "1.020.345.678" not in res.masked_text
    assert "[DOC_1]" in res.masked_text
    assert "[DOC_2]" in res.masked_text
    assert "[DOC_3]" in res.masked_text

    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert unmasked == text


@pytest.mark.parametrize(
    "text, raw",
    [
        ("mi CURP es GODE561231HDFRRN09, gracias", "GODE561231HDFRRN09"),
        ("mi curp: gode561231mdfrrn04", "gode561231mdfrrn04"),
        ("RFC GODE561231GR8 para la factura", "GODE561231GR8"),
        ("el RFC de la empresa es ABC010203XY1", "ABC010203XY1"),
        ("mi CUIT es 20-12345678-9", "20-12345678-9"),
        ("cuil 27123456784 por favor", "27123456784"),
    ],
)
def test_mexican_and_argentine_identifiers_are_masked(text: str, raw: str) -> None:
    masker = RegexMasker()
    res = masker.mask(text)
    assert raw not in res.masked_text
    assert "[DOC_1]" in res.masked_text
    assert masker.verify_safe(res.masked_text)
    assert not masker.verify_safe(text)
    assert masker.unmask(res.masked_text, res.mapping) == text


@pytest.mark.parametrize(
    "text",
    ["me cobraron MXN 3500 en Amazon", "un cargo de 1.250.000 ARS que no hice"],
)
def test_mexican_and_argentine_amounts_are_not_documents(text: str) -> None:
    masker = RegexMasker()
    assert masker.mask(text).masked_text == text
    assert masker.verify_safe(text)


def test_masking_state_preservation_across_turns() -> None:
    masker = RegexMasker()
    # Turn 1
    res1 = masker.mask("User email is john@bank.com.")
    assert "[EMAIL_1]" in res1.masked_text

    # Turn 2: reuses john@bank.com and introduces new email
    res2 = masker.mask(
        "Sending from john@bank.com to support@bank.com.",
        state=res1.mapping,
    )
    assert "[EMAIL_1]" in res2.masked_text
    assert "[EMAIL_2]" in res2.masked_text
    assert res2.mapping["[EMAIL_1]"] == "john@bank.com"
    assert res2.mapping["[EMAIL_2]"] == "support@bank.com"


@pytest.mark.parametrize(
    ("raw_text", "secret_val"),
    [
        ("Mi cédula es 1020304050", "1020304050"),
        ("Mi número de documento es 1020304050", "1020304050"),
        ("cpf 12345678900", "12345678900"),
        ("llámame al 3001234567", "3001234567"),
        ("nací el 01/01/1950", "01/01/1950"),
        ("meu nome é Mariana Silva", "Mariana Silva"),
        ("Él se llama Carlos Gómez", "Carlos Gómez"),
        ("Sou a mãe da Mariana Silva", "Mariana Silva"),
        ("My name is Alice Johnson", "Alice Johnson"),
        ("My passport number is P12345678", "P12345678"),
        ("Mi código de verificación es 654321", "654321"),
        ("OTP 998877", "998877"),
    ],
)
def test_reviewer_p1_leaks_masked_and_blocked(raw_text: str, secret_val: str) -> None:
    masker = RegexMasker()

    # 1. Unmasked string must be blocked by verify_safe
    assert masker.verify_safe(raw_text) is False, (
        f"verify_safe should have rejected: {raw_text}"
    )

    # 2. Masking must replace secret value with a placeholder
    res = masker.mask(raw_text)
    assert secret_val not in res.masked_text
    assert any(f"[{cat}_" in res.masked_text for cat in masker.categories)

    # 3. Masked text must pass verify_safe
    assert masker.verify_safe(res.masked_text) is True

    # 4. Rehydration must restore original secret value
    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert secret_val in unmasked


def test_currency_amounts_not_mistaken_for_pii() -> None:
    masker = RegexMasker()
    amounts = [
        "Veo un cobro de $45.000 en Falabella",
        "Cobro de $ 20.000.000 en mi tarjeta",
        "Identifiquei um débito de R$ 120,00 da Amazon",
        "Transfer of 50000 USD was flagged",
        "Pagó 30000 COP en el restaurante",
    ]
    for text in amounts:
        res = masker.mask(text)
        # Amounts should not be replaced by DOC or CARD placeholders
        assert "[DOC_" not in res.masked_text
        assert "[CARD_" not in res.masked_text
        assert masker.verify_safe(res.masked_text) is True


def test_scenario_customer_turns_seeded_pii_eliminated() -> None:
    """Fixture test verifying literal customer turns from eval/scenarios."""
    masker = RegexMasker()

    scenario_turns = [
        (
            "Mi cédula es 1020304050 y mi nombre es Carlos Gómez.",
            ["1020304050", "Carlos Gómez"],
        ),
        (
            "Meu CPF é 123.456.789-00 e meu nome é Mariana Silva.",
            ["123.456.789-00", "Mariana Silva"],
        ),
        (
            "Mi número de documento es 1020304050.",
            ["1020304050"],
        ),
        (
            "My passport number is P12345678 and my name is Alice Johnson.",
            ["P12345678", "Alice Johnson"],
        ),
        (
            "Consulta o saldo do CPF 000.000.000-01.",
            ["000.000.000-01"],
        ),
        (
            "llámame al 3001234567 y nací el 01/01/1950",
            ["3001234567", "01/01/1950"],
        ),
    ]

    for turn, seeded_piis in scenario_turns:
        # Pre-check: raw turn must fail verify_safe
        assert masker.verify_safe(turn) is False

        # Post-check: masking removes all seeded PII values
        res = masker.mask(turn)
        for pii in seeded_piis:
            assert pii not in res.masked_text, (
                f"PII '{pii}' survived in '{res.masked_text}'"
            )

        # Masked text is completely safe
        assert masker.verify_safe(res.masked_text) is True


def test_verify_safe_detects_unmasked_pii() -> None:
    masker = RegexMasker()
    # Safe text
    assert masker.verify_safe("User [EMAIL_1] called about [CARD_1]") is True
    assert masker.verify_safe("Doc [DOC_1] belongs to [NAME_1]") is True

    # Unsafe residual PII
    assert masker.verify_safe("Raw card 4111222233334444") is False
    assert masker.verify_safe("Contact user@example.com") is False
    assert masker.verify_safe("Call 3001234567") is False
    assert masker.verify_safe("ID 1020304050") is False
    assert masker.verify_safe("DOB: 01/01/1950") is False
    assert masker.verify_safe("My name is John Doe") is False
    assert masker.verify_safe("Código de verificación: 123456") is False
    assert masker.verify_safe("OTP 998877") is False
    assert masker.verify_safe("Safe with [OTP_1] and [DATE_1]") is True


def test_masker_categories_equal_pii_type() -> None:
    """Masker categories must match contracts PiiType single source of truth."""
    masker = RegexMasker()
    assert masker.categories == set(PiiType)
    assert RegexMasker.CATEGORIES == set(PiiType)
    assert masker.categories == {"DOC", "NAME", "PHONE", "EMAIL", "CARD", "DATE", "OTP"}


def test_date_placeholder_and_round_trip() -> None:
    """Birth dates become [DATE_n] placeholders and rehydrate cleanly."""
    masker = RegexMasker()
    text = "Mi fecha de nacimiento es 15/08/1985 y nací el 01/01/1950."
    assert masker.verify_safe(text) is False

    res = masker.mask(text)
    assert "15/08/1985" not in res.masked_text
    assert "01/01/1950" not in res.masked_text
    assert "[DATE_1]" in res.masked_text
    assert "[DATE_2]" in res.masked_text
    assert "[DOC_" not in res.masked_text
    assert masker.verify_safe(res.masked_text) is True

    # Rehydration restores original dates
    unmasked = masker.unmask(res.masked_text, res.mapping)
    assert unmasked == text


def test_otp_placeholder_and_round_trip() -> None:
    """OTP codes after cue become [OTP_n] placeholders and rehydrate cleanly."""
    masker = RegexMasker()
    test_cases = [
        ("Mi código de verificación es 654321", "654321"),
        ("El código que recibí es 123456", "123456"),
        ("OTP: 998877", "998877"),
        ("token 582190", "582190"),
        ("My verification code is 492018", "492018"),
        ("O código de verificação é 849201", "849201"),
        ("Por favor ingresa el código: 482910", "482910"),
    ]
    for raw_text, secret_otp in test_cases:
        assert masker.verify_safe(raw_text) is False
        res = masker.mask(raw_text)
        assert secret_otp not in res.masked_text
        assert "[OTP_1]" in res.masked_text
        assert "[DOC_" not in res.masked_text
        assert masker.verify_safe(res.masked_text) is True

        # Rehydration restores original OTP
        unmasked = masker.unmask(res.masked_text, res.mapping)
        assert unmasked == raw_text


def test_otp_bare_code_key_in_tool_arguments() -> None:
    """A bare "code"/"otp" key in JSON tool arguments is an OTP cue."""
    masker = RegexMasker()
    for raw_args, secret in (
        ('{"code": "123456"}', "123456"),
        ('{"otp":"4821"}', "4821"),
        ('{"card_ref": "card_ab12cd34", "code": "99887766"}', "99887766"),
    ):
        assert masker.verify_safe(raw_args) is False
        res = masker.mask(raw_args)
        assert secret not in res.masked_text
        assert "[OTP_1]" in res.masked_text
        assert json.loads(res.masked_text)  # still valid JSON
        assert masker.unmask(res.masked_text, res.mapping) == raw_args

    # Already masked stays as is; an unquoted numeric code fails closed
    assert masker.mask('{"code": "[OTP_1]"}').masked_text == '{"code": "[OTP_1]"}'
    with pytest.raises(MaskingError):
        masker.mask('{"code":123456}')
