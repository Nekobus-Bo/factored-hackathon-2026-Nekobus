"""Fernet encryption at rest: the placeholder map, and agent text as written."""

import pytest
from orchestrator.session.crypto import CryptoError, PlaceholderEncryptor

TEXT = "Hola, soy Ana. Tu tarjeta 4111 1111 1111 1111 y tu correo carla@example.com."


def test_text_round_trips_through_the_ciphertext() -> None:
    encryptor = PlaceholderEncryptor("secret-a")

    token = encryptor.encrypt_text(TEXT)

    assert encryptor.decrypt_text(token) == TEXT


@pytest.mark.parametrize(
    "text", ["", " ", "ñandú á é í ó ú ü ¿¡", "línea\ncon salto", "日本語 🙂"]
)
def test_any_text_round_trips(text: str) -> None:
    encryptor = PlaceholderEncryptor("secret-a")

    assert encryptor.decrypt_text(encryptor.encrypt_text(text)) == text


def test_the_ciphertext_is_ascii_and_holds_no_part_of_the_text() -> None:
    token = PlaceholderEncryptor("secret-a").encrypt_text(TEXT)

    assert token.isascii()
    for part in ("Ana", "4111", "carla", "example.com", "Hola"):
        assert part not in token


def test_the_same_text_encrypts_to_a_different_ciphertext_each_time() -> None:
    encryptor = PlaceholderEncryptor("secret-a")

    assert encryptor.encrypt_text(TEXT) != encryptor.encrypt_text(TEXT)


def test_another_secret_cannot_read_the_text() -> None:
    token = PlaceholderEncryptor("secret-a").encrypt_text(TEXT)

    with pytest.raises(CryptoError):
        PlaceholderEncryptor("secret-b").decrypt_text(token)


@pytest.mark.parametrize(
    "token",
    ["", "   ", "not-a-fernet-token", "gAAAAA", "é"],
    ids=["empty", "blank", "garbage", "truncated", "non-ascii"],
)
def test_a_token_that_is_not_ciphertext_is_a_crypto_error(token: str) -> None:
    with pytest.raises(CryptoError):
        PlaceholderEncryptor("secret-a").decrypt_text(token)


def test_a_tampered_ciphertext_is_a_crypto_error() -> None:
    encryptor = PlaceholderEncryptor("secret-a")
    token = encryptor.encrypt_text(TEXT)
    flipped = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(CryptoError):
        encryptor.decrypt_text(flipped)


def test_a_failure_never_carries_the_text(caplog: pytest.LogCaptureFixture) -> None:
    encryptor = PlaceholderEncryptor("secret-a")
    token = encryptor.encrypt_text(TEXT)

    with caplog.at_level("DEBUG"):
        with pytest.raises(CryptoError) as error:
            PlaceholderEncryptor("secret-b").decrypt_text(token)

    assert "Ana" not in str(error.value) and "4111" not in str(error.value)
    assert caplog.records == []  # the text pair logs nothing at all


def test_an_unencodable_text_is_a_crypto_error_that_does_not_echo_it() -> None:
    lone_surrogate = "sin par \ud800 4111 1111 1111 1111"

    with pytest.raises(CryptoError) as error:
        PlaceholderEncryptor("secret-a").encrypt_text(lone_surrogate)

    assert "4111" not in str(error.value)


def test_the_map_pair_is_unchanged() -> None:
    encryptor = PlaceholderEncryptor("secret-a")

    token = encryptor.encrypt_map({"[NAME_1]": "Ana"})

    assert encryptor.decrypt_map(token) == {"[NAME_1]": "Ana"}
    assert encryptor.encrypt_map({}) == ""
    assert encryptor.decrypt_map("") == {}
