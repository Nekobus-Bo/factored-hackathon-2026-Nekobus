"""Secrets the bank never asks for: masked, never kept, never repeated (E1)."""

import pytest
from orchestrator.privacy.masking import SECRET_REDACTION, RegexMasker

MASKER = RegexMasker()


@pytest.mark.parametrize(
    ("text", "secrets"),
    [
        (
            "mi clave del cajero es 4821 y el código de seguridad es 937",
            ["4821", "937"],
        ),
        ("a senha é 4821 e o código de segurança é 937", ["4821", "937"]),
        ("my PIN is 4821 and the CVV is 937", ["4821", "937"]),
        ("el PIN de la tarjeta: 0912", ["0912"]),
        ("mi nip es 4455", ["4455"]),
        ("mi contraseña: Hola1234", ["Hola1234"]),
        ("password = s3cret!", ["s3cret!"]),
    ],
)
def test_secrets_are_masked_and_never_kept(text, secrets):
    result = MASKER.mask(text)
    for secret in secrets:
        assert secret not in result.masked_text
        assert secret not in result.mapping.values()
    assert "[SECRET_1]" in result.masked_text
    # Rehydration gives the redaction, never the value: a reply or a tool
    # argument that repeats the placeholder cannot leak it.
    unmasked = MASKER.unmask(result.masked_text, result.mapping)
    assert SECRET_REDACTION in unmasked
    assert not any(secret in unmasked for secret in secrets)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my security code is 482193", "my security code is [OTP_1]"),
        ("el código de verificación es 482193", "el código de verificación es [OTP_1]"),
        ("token 654321", "token [OTP_1]"),
        ("mi contraseña es incorrecta", "mi contraseña es incorrecta"),
    ],
)
def test_one_time_codes_and_plain_words_are_not_secrets(text, expected):
    assert MASKER.mask(text).masked_text == expected


def test_a_secret_next_to_a_document_masks_both():
    result = MASKER.mask("Mi cédula es 1020304050 y mi PIN es 4821")
    assert result.masked_text == "Mi cédula es [DOC_1] y mi PIN es [SECRET_1]"
    assert result.mapping["[DOC_1]"] == "1020304050"
