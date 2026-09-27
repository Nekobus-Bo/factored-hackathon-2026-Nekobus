"""Unit tests for crypto module: envelope, blind indexing, and normalization."""

import uuid

import pytest
from banking_core.crypto import (
    DecryptionError,
    InvalidKeyError,
    NormalizationError,
    RecordEncryptor,
    build_field_aad,
    build_record_aad,
    compute_blind_index,
    decrypt_field,
    decrypt_with_dek,
    encrypt_field,
    encrypt_with_dek,
    generate_dek,
    normalize_document,
    normalize_email,
    normalize_phone,
    unwrap_dek,
    wrap_dek,
)
from banking_core.db.config import get_database_url
from banking_core.models.enums import BlockReason, DocumentType


def test_encrypt_decrypt_round_trip() -> None:
    """Test encrypt and decrypt round trip with location-bound AAD."""
    master_key = "test-master-key-32-bytes-long!!"
    pk = uuid.uuid4()
    aad = build_field_aad("core_bank", "customer", "document_number_enc", pk)
    secret_text = "Sensitive customer data: 12345"

    # Field-level envelope round trip
    encrypted = encrypt_field(secret_text, aad=aad, master_key=master_key)
    assert encrypted.startswith("v1:")
    assert secret_text not in encrypted

    decrypted = decrypt_field(encrypted, aad=aad, master_key=master_key)
    assert decrypted == secret_text

    # RecordEncryptor round trip (shared DEK across multiple fields for same record)
    record_enc = RecordEncryptor(
        schema="core_bank",
        table="customer",
        record_id=pk,
        master_key=master_key,
    )
    enc_field1 = record_enc.encrypt("email_enc", "alice@example.com")
    enc_field2 = record_enc.encrypt("phone_enc", "+573001234567")

    aad_email = build_field_aad("core_bank", "customer", "email_enc", pk)
    aad_phone = build_field_aad("core_bank", "customer", "phone_enc", pk)

    dec_email = decrypt_field(enc_field1, aad=aad_email, master_key=master_key)
    dec_phone = decrypt_field(enc_field2, aad=aad_phone, master_key=master_key)
    assert dec_email == "alice@example.com"
    assert dec_phone == "+573001234567"

    # Raw DEK round trip
    dek = generate_dek()
    rec_aad = build_record_aad("core_bank", "customer", pk)
    wrapped_dek = wrap_dek(dek, master_key, aad=rec_aad)
    unwrapped_dek = unwrap_dek(wrapped_dek, master_key, aad=rec_aad)
    assert unwrapped_dek == dek

    dek_enc = encrypt_with_dek("message body", dek, aad=aad)
    assert decrypt_with_dek(dek_enc, dek, aad=aad) == "message body"


def test_tampered_ciphertext_rejected() -> None:
    """Test that tampering with any portion of the ciphertext is rejected."""
    master_key = "test-master-key-super-secret-12"
    pk = uuid.uuid4()
    aad = build_field_aad("core_bank", "customer", "full_name_enc", pk)
    encrypted = encrypt_field("genuine-banking-payload", aad=aad, master_key=master_key)

    parts = encrypted.split(":")
    prefix, wrapped_dek, field_ct = parts

    # 1. Tamper with the field ciphertext
    tampered_bytes = bytearray(field_ct.encode("ascii"))
    tampered_bytes[-1] = ord("A") if tampered_bytes[-1] != ord("A") else ord("B")
    tampered_ct = tampered_bytes.decode("ascii")
    tampered_token = f"{prefix}:{wrapped_dek}:{tampered_ct}"

    with pytest.raises(DecryptionError):
        decrypt_field(tampered_token, aad=aad, master_key=master_key)

    # 2. Tamper with the wrapped DEK
    tampered_dek_bytes = bytearray(wrapped_dek.encode("ascii"))
    tampered_dek_bytes[-1] = (
        ord("X") if tampered_dek_bytes[-1] != ord("X") else ord("Y")
    )
    tampered_dek_str = tampered_dek_bytes.decode("ascii")
    tampered_envelope = f"{prefix}:{tampered_dek_str}:{field_ct}"

    with pytest.raises(DecryptionError):
        decrypt_field(tampered_envelope, aad=aad, master_key=master_key)

    # 3. Direct DEK decrypt tampering
    dek = generate_dek()
    dek_token = encrypt_with_dek("hello world", dek, aad=aad)
    token_bytes = bytearray(dek_token.encode("ascii"))
    token_bytes[-2] = ord("Z") if token_bytes[-2] != ord("Z") else ord("W")

    with pytest.raises(DecryptionError):
        decrypt_with_dek(token_bytes.decode("ascii"), dek, aad=aad)


def test_wrong_master_key_rejected() -> None:
    """Test that attempting to decrypt with a different master key fails."""
    correct_key = "master-key-correct-password-alpha"
    wrong_key = "master-key-wrong-password-beta"
    pk = uuid.uuid4()
    aad = build_field_aad("core_bank", "customer", "full_name_enc", pk)
    secret = "secret-account-balance-99999"

    encrypted = encrypt_field(secret, aad=aad, master_key=correct_key)

    with pytest.raises(InvalidKeyError):
        decrypt_field(encrypted, aad=aad, master_key=wrong_key)

    # DEK unwrap with wrong key fails
    dek = generate_dek()
    rec_aad = build_record_aad("core_bank", "customer", pk)
    wrapped = wrap_dek(dek, correct_key, aad=rec_aad)
    with pytest.raises(InvalidKeyError):
        unwrap_dek(wrapped, wrong_key, aad=rec_aad)


def test_swap_attacks_rejected() -> None:
    """Test that swapping ciphertext across rows or across columns fails."""
    master_key = "test-master-key-swap-defense-123"
    row_a = uuid.uuid4()
    row_b = uuid.uuid4()

    # 1. Row swap: attacker copies email_enc from Row A to Row B
    aad_row_a_email = build_field_aad("core_bank", "customer", "email_enc", row_a)
    aad_row_b_email = build_field_aad("core_bank", "customer", "email_enc", row_b)

    token_row_a = encrypt_field(
        "attacker@bank.com", aad=aad_row_a_email, master_key=master_key
    )

    # Attempt to decrypt Row A token in Row B context fails
    with pytest.raises((InvalidKeyError, DecryptionError)):
        decrypt_field(token_row_a, aad=aad_row_b_email, master_key=master_key)

    # 2. Column swap: attacker copies email_enc to phone_enc in the same Row A
    aad_row_a_phone = build_field_aad("core_bank", "customer", "phone_enc", row_a)

    with pytest.raises(DecryptionError):
        decrypt_field(token_row_a, aad=aad_row_a_phone, master_key=master_key)


def test_record_encryptor_swap_attacks_rejected() -> None:
    """Test row-swap and column-swap defense using the RecordEncryptor helper."""
    master_key = "test-master-key-swap-defense-123"
    rec_a = RecordEncryptor(
        schema="core_bank",
        table="customer",
        record_id=uuid.uuid4(),
        master_key=master_key,
    )
    rec_b = RecordEncryptor(
        schema="core_bank",
        table="customer",
        record_id=uuid.uuid4(),
        master_key=master_key,
    )

    # Encrypt email under Record A
    email_token = rec_a.encrypt_field("email_enc", "alice@example.com")

    # 1. Normal decrypt on Record A succeeds
    assert rec_a.decrypt_field("email_enc", email_token) == "alice@example.com"
    assert rec_a.decrypt("email_enc", email_token) == "alice@example.com"

    # 2. Row swap: attacker copies email_enc from Record A to Record B
    with pytest.raises((InvalidKeyError, DecryptionError)):
        rec_b.decrypt_field("email_enc", email_token)

    # 3. Column swap: attacker copies email_enc to phone_enc in the same Record A
    with pytest.raises(DecryptionError):
        rec_a.decrypt_field("phone_enc", email_token)


def test_fail_closed_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing environment variables fail closed."""
    pk = uuid.uuid4()
    aad = build_field_aad("core_bank", "customer", "email_enc", pk)

    # 1. Missing MASTER_KEY
    monkeypatch.delenv("MASTER_KEY", raising=False)
    with pytest.raises(InvalidKeyError, match="MASTER_KEY"):
        encrypt_field("test@example.com", aad=aad)
    with pytest.raises(InvalidKeyError, match="MASTER_KEY"):
        decrypt_field("v1:dummy:dummy", aad=aad)

    # 2. Missing BLIND_INDEX_SALT
    monkeypatch.delenv("BLIND_INDEX_SALT", raising=False)
    with pytest.raises(InvalidKeyError, match="BLIND_INDEX_SALT"):
        compute_blind_index(
            "test@example.com", "email", document_type=DocumentType.NATIONAL_ID
        )

    # 3. Missing POSTGRES_PASSWORD in db/config
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        get_database_url()


def test_blind_index_deterministic_per_field_and_different_across_fields() -> None:
    """Test blind index determinism and field isolation."""
    salt = "master-blind-index-salt-secret-999"
    raw_value = "1020304050"

    # Determinism check
    idx_doc1 = compute_blind_index(
        raw_value,
        "document_number",
        salt=salt,
        normalize=False,
        document_type=DocumentType.NATIONAL_ID,
    )
    idx_doc2 = compute_blind_index(
        raw_value,
        "document_number",
        salt=salt,
        normalize=False,
        document_type=DocumentType.NATIONAL_ID,
    )
    assert idx_doc1 == idx_doc2
    assert len(idx_doc1) == 64

    # Isolation check: different fields produce different digests for same value
    idx_email = compute_blind_index(raw_value, "email", salt=salt, normalize=False)
    idx_phone = compute_blind_index(raw_value, "phone", salt=salt, normalize=False)

    assert idx_doc1 != idx_email
    assert idx_doc1 != idx_phone
    assert idx_email != idx_phone

    # Different salt produces different blind index
    idx_doc_diff_salt = compute_blind_index(
        raw_value,
        "document_number",
        salt="another-salt",
        normalize=False,
        document_type=DocumentType.NATIONAL_ID,
    )
    assert idx_doc1 != idx_doc_diff_salt


def test_normalization_cases() -> None:
    """Test normalization rules for doc, email, and phone."""
    # 1. Document normalization:
    # numeric (NATIONAL_ID, TAX_ID) vs alphanumeric (PASSPORT, FOREIGN_ID)
    assert (
        normalize_document("12.345.678-9", document_type=DocumentType.NATIONAL_ID)
        == "123456789"
    )
    assert (
        normalize_document("TAX-900.123.456-7", document_type="TAX_ID") == "9001234567"
    )
    assert (
        normalize_document("pas-12345-ab", document_type=DocumentType.PASSPORT)
        == "PAS12345AB"
    )
    assert (
        normalize_document("for-987.654-x", document_type="FOREIGN_ID") == "FOR987654X"
    )

    # Rejection of unknown types
    with pytest.raises(NormalizationError, match="Unknown or invalid document type"):
        normalize_document("123456", document_type="CC")
    with pytest.raises(NormalizationError, match="Unknown or invalid document type"):
        normalize_document("123456", document_type="PASAPORTE")

    # Rejection of colons
    with pytest.raises(NormalizationError, match="cannot contain ':'"):
        normalize_document("NATIONAL_ID:123456", document_type=DocumentType.NATIONAL_ID)

    with pytest.raises(NormalizationError):
        normalize_document("no-digits", document_type=DocumentType.NATIONAL_ID)
    with pytest.raises(NormalizationError):
        normalize_document("---", document_type=DocumentType.PASSPORT)

    # Document blind index includes document type prefix
    salt = "test-salt-123"
    bidx_nat = compute_blind_index(
        "12.345.678-9",
        "document_number",
        salt=salt,
        document_type=DocumentType.NATIONAL_ID,
    )
    bidx_pass = compute_blind_index(
        "12.345.678-9",
        "document_number",
        salt=salt,
        document_type=DocumentType.PASSPORT,
    )
    assert bidx_nat != bidx_pass  # Different types produce different blind indexes

    bidx_nat2 = compute_blind_index(
        "123456789",
        "document_number",
        salt=salt,
        document_type=DocumentType.NATIONAL_ID,
    )
    assert bidx_nat == bidx_nat2

    # Missing document_type must be rejected
    with pytest.raises(NormalizationError, match="document_type is required"):
        compute_blind_index("123456789", "document_number", salt=salt)

    # Colons in document values must be rejected
    with pytest.raises(NormalizationError):
        compute_blind_index(
            "123:456",
            "document_number",
            salt=salt,
            document_type=DocumentType.NATIONAL_ID,
        )
    with pytest.raises(NormalizationError):
        compute_blind_index(
            "123:456",
            "document_number",
            salt=salt,
            normalize=False,
            document_type=DocumentType.NATIONAL_ID,
        )

    # 2. Email normalization: trim + lowercase
    assert normalize_email("  User@Example.COM  ") == "user@example.com"
    assert normalize_email("MARCELO@Pattern.Blue") == "marcelo@pattern.blue"
    assert (
        normalize_email("\tcustomer.service@bank.com\n") == "customer.service@bank.com"
    )
    with pytest.raises(NormalizationError):
        normalize_email("   ")

    # 3. Phone normalization: must start with '+'
    assert normalize_phone("+57 300 123 4567") == "+573001234567"
    assert normalize_phone("+1 (555) 019-2834") == "+15550192834"
    assert normalize_phone(" +57-310-555-0100 ") == "+573105550100"

    # Numbers without '+' must be rejected
    with pytest.raises(
        NormalizationError, match="must include an international prefix"
    ):
        normalize_phone("3001234567")
    with pytest.raises(NormalizationError):
        normalize_phone("invalid-phone")


def test_block_reason_enum_values() -> None:
    """Verify BlockReason enum has all required values matching packages/contracts."""
    expected_values = {
        "LOST",
        "STOLEN",
        "UNRECOGNIZED_CHARGE",
        "SUSPICIOUS_ACTIVITY",
        "CUSTOMER_REQUEST",
    }
    actual_values = {member.value for member in BlockReason}
    assert actual_values == expected_values
