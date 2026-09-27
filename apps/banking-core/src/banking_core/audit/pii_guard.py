"""PII guard for ops.audit_log payloads.

Rejects payloads containing unmasked PII (emails, phone numbers, full PANs,
or national document numbers). Allows masked values, opaque references, enums,
and numeric identifiers.
"""

import re
from typing import Any

try:
    from contracts.envelope import (
        MASKED_EMAIL_PATTERN,
        MASKED_PAN_PATTERN,
        MASKED_PHONE_PATTERN,
    )
except ImportError:
    # Fallback to contracts patterns if contracts package is not on sys.path
    MASKED_PAN_PATTERN = r"(\*{4}[\s-]?\*{4}[\s-]?\*{4}[\s-]?\d{4}|\*{4,12}\d{4})"
    MASKED_EMAIL_PATTERN = r"[a-zA-Z0-9]\*+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    MASKED_PHONE_PATTERN = r"(\+?\d{1,3}[-\s]?)?(\d{1,4}[-\s]?)?(\*+[-\s]?)+\d{2,4}"

# Regex for unmasked email addresses
_UNMASKED_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_MASKED_EMAIL_RE = re.compile(rf"^{MASKED_EMAIL_PATTERN}$")

# Regex for masked PAN and masked phone
_MASKED_PAN_RE = re.compile(rf"^{MASKED_PAN_PATTERN}$")
_MASKED_PHONE_RE = re.compile(rf"^{MASKED_PHONE_PATTERN}$")

# Opaque reference pattern (e.g. card_xyz123, hnd_456, chal_789)
_OPAQUE_REF_RE = re.compile(
    r"^(card|hnd|otp|chal|ticket|handoff|session|req|idem)[_-][A-Za-z0-9*_-]{4,64}$"
)

# Standard UUID and ISO timestamp patterns
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISO_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T|\s)\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_HEX_HASH_RE = re.compile(r"^[0-9a-fA-F]{32,64}$")

# Unmasked phone patterns (e.g. +57 300 123 4567, 300-123-4567, +1-800-555-0199)
_PHONE_CANDIDATE_RE = re.compile(
    r"(\+?\d{1,3}[-\s.]?)?\(?\d{2,4}\)?[-\s.]?\d{3,4}[-\s.]?\d{3,4}"
)

# Document number key names
_DOC_KEYS = frozenset(
    {
        "document_number",
        "doc_number",
        "national_id",
        "id_number",
        "cedula",
        "passport_number",
        "tax_id",
    }
)
_PHONE_KEY_FRAGMENTS = ("phone", "mobile", "celular", "tel", "contact_number")
_PAN_KEY_FRAGMENTS = ("card", "pan")


class PiiLeakError(ValueError):
    """Raised when an unmasked PII pattern is detected in an audit log payload."""

    pass


def _check_string_for_pii(value: str, key_context: str | None = None) -> None:
    """Validate a single string value against PII leak rules."""
    s = value.strip()
    if not s:
        return

    # 1. Allowed UUIDs, ISO dates, hashes
    if _UUID_RE.match(s) or _ISO_TIMESTAMP_RE.match(s) or _HEX_HASH_RE.match(s):
        return

    # 2. Allowed opaque references with PAN guard (reject >= 12 digits)
    if _OPAQUE_REF_RE.match(s):
        digits_count = sum(1 for c in s if c.isdigit())
        if digits_count >= 12:
            raise PiiLeakError(
                f"Opaque reference contains >=12 digits (PAN guard): '{s}'"
            )
        return

    # 3. Check for Email
    if "@" in s:
        if _MASKED_EMAIL_RE.match(s):
            return
        if _UNMASKED_EMAIL_RE.search(s):
            raise PiiLeakError(f"Unmasked email detected in payload: '{s}'")

    # 4. Check for Document Number under doc keys
    if key_context and key_context.lower() in _DOC_KEYS:
        if not s.startswith("****") and "*" not in s:
            raise PiiLeakError(
                f"Unmasked document number detected under key '{key_context}': '{s}'"
            )

    # 5. Check for Phone Number under phone keys
    if key_context and any(pk in key_context.lower() for pk in _PHONE_KEY_FRAGMENTS):
        clean = re.sub(r"[\s().-]", "", s)
        digits = sum(1 for c in clean if c.isdigit())
        if digits >= 7 and "*" not in s:
            raise PiiLeakError(
                f"Unmasked phone number detected under '{key_context}': '{s}'"
            )

    # 6. Check for Masked PAN or Masked Phone
    if _MASKED_PAN_RE.match(s) or _MASKED_PHONE_RE.match(s):
        return

    # 7. Check for Full PAN (12 to 19 digits, possibly separated by spaces or dashes)
    clean_digits = re.sub(r"[\s-]", "", s)
    if clean_digits.isdigit() and 12 <= len(clean_digits) <= 19:
        raise PiiLeakError(f"Unmasked payment card PAN detected in payload: '{s}'")

    # Check for embedded 13-19 digit PAN inside text
    pan_matches = re.findall(r"\b(?:\d[ -]?){13,19}\b", s)
    for match in pan_matches:
        digits_only = re.sub(r"\D", "", match)
        if 13 <= len(digits_only) <= 19:
            raise PiiLeakError(
                f"Unmasked payment card PAN detected in payload: '{match}'"
            )

    # 8. Check for formatted unmasked phone numbers in general strings
    phone_match = _PHONE_CANDIDATE_RE.search(s)
    if phone_match:
        matched_str = phone_match.group(0)
        digits = sum(1 for c in matched_str if c.isdigit())
        has_formatting = any(c in matched_str for c in ("+", "-", " ", "(", ")"))
        if digits >= 7 and "*" not in matched_str and has_formatting:
            raise PiiLeakError(f"Unmasked phone number detected in payload: '{s}'")


def check_payload(payload: Any, key_context: str | None = None) -> None:
    """Recursively inspect payload structure for unmasked PII.

    Raises:
        PiiLeakError: If unmasked email, phone, PAN, or document number is found.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            k_str = str(k)
            # Inspect dictionary keys as string values for PII
            _check_string_for_pii(k_str, key_context="key")
            check_payload(v, key_context=k_str)
    elif isinstance(payload, (list, tuple, set)):
        for item in payload:
            check_payload(item, key_context=key_context)
    elif isinstance(payload, str):
        _check_string_for_pii(payload, key_context=key_context)
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        s_num = (
            str(int(payload))
            if isinstance(payload, int)
            or (isinstance(payload, float) and payload.is_integer())
            else str(payload)
        )
        _check_string_for_pii(s_num, key_context=key_context)
