"""Outbound PII Masking and Rehydration (ADR-0001, ADR-0004, AGENTS Rule 5).

Guarantees:
- Fail-closed: if masking fails or residual unmasked PII is detected, the operation
  raises MaskingError and nothing is transmitted outbound to the LLM provider.
- Stable placeholders: entities of the same type and value maintain consistent
  placeholders ([CARD_1], [EMAIL_1], etc.) across turns within a session.
- Two-way mapping: placeholders are stored server-side to rehydrate responses
  for the client or tool caller.
"""

import logging
import re
from abc import ABC, abstractmethod

from contracts import PiiType
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.privacy.written_dates import find_written_dates

logger = logging.getLogger(__name__)


class MaskingError(Exception):
    """Raised when PII masking fails or residual unmasked PII is detected."""


class MaskResult(BaseModel):
    """Result of PII masking containing masked text and bidirectional mappings."""

    model_config = ConfigDict(extra="forbid")

    masked_text: str = Field(
        ..., description="Text with PII replaced by stable placeholders"
    )
    mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Placeholder to original PII mapping (kept server-side)",
    )
    reverse_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Original PII to placeholder mapping",
    )


class Masker(ABC):
    """Abstract interface for PII masking implementations."""

    CATEGORIES: set[str] = {p.value for p in PiiType}
    categories: set[str] = CATEGORIES

    @abstractmethod
    def mask(
        self,
        text: str,
        state: dict[str, str] | None = None,
    ) -> MaskResult:
        """Replace PII in text with stable placeholders.

        Args:
            text: Plain text potentially containing PII.
            state: Optional existing mapping (placeholder -> original or
                original -> placeholder) to preserve consistent entity
                numbering across turns.
        """
        ...

    @abstractmethod
    def unmask(self, text: str, mapping: dict[str, str]) -> str:
        """Replace placeholders in text with original values."""
        ...

    @abstractmethod
    def verify_safe(self, text: str) -> bool:
        """Strict check ensuring text contains no raw, unmasked PII."""
        ...


def mask_json_string_values(
    value: object, masker: Masker, state: dict[str, str]
) -> object:
    """Mask JSON string values while preserving contract-validated numeric fields."""
    if isinstance(value, str):
        result = masker.mask(value, state=state)
        state.update(result.mapping)
        if not masker.verify_safe(result.masked_text):
            raise MaskingError("residual PII after masking")
        return result.masked_text
    if isinstance(value, list):
        return [mask_json_string_values(item, masker, state) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise MaskingError("JSON object keys must be strings")
        return {
            key: mask_json_string_values(item, masker, state)
            for key, item in value.items()
        }
    # Tool contracts use strict integer types for amounts; masking the JSON
    # encoding as text would misclassify those values as document numbers.
    return value


class RegexMasker(Masker):
    """Fail-closed Regex-based PII masker and validator.

    Identifies and masks:
    - Payment Card Numbers / PAN (13-19 digits, separators allowed) ([CARD_n])
    - Emails ([EMAIL_n])
    - Document numbers (CPF, SSN, DNI dots, Passports, Labeled docs) ([DOC_n])
    - Birth dates / Dates, numeric or written out in es/pt/en ([DATE_n])
    - One-time passcodes / OTP codes after cue ([OTP_n]), including a bare
      "code"/"otp" key in JSON tool-call arguments
    - Runs of >= 7 digits not associated with a currency amount ([DOC_n])
    - Phone numbers (E.164, national, and explicit phone intros) ([PHONE_n])
    - Names with honorifics/salutations and conversational intros ([NAME_n])
    """

    CATEGORIES: set[str] = {p.value for p in PiiType}
    categories: set[str] = CATEGORIES

    # 1. PAN / Card Numbers: 13 to 19 digits (with optional spaces or dashes)
    PAN_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

    # 2. Email pattern
    EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    # 3. Formatted documents
    CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
    SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    DNI_DOTS_RE = re.compile(r"\b\d{1,3}(?:\.\d{3}){2,3}\b")
    PASSPORT_RE = re.compile(r"\b[A-Za-z]{1,2}\d{6,8}\b")

    # 4. Document labels followed by filler words and document number
    DOC_LABEL_RE = re.compile(
        r"\b(?:"
        r"número\s+de\s+documento|"
        r"numero\s+de\s+documento|"
        r"num\s+de\s+documento|"
        r"cédula\s+de\s+ciudadanía|"
        r"cedula\s+de\s+ciudadania|"
        r"cédula|"
        r"cedula|"
        r"documento|"
        r"dni|"
        r"cc|"
        r"cpf|"
        r"rut|"
        r"nit|"
        r"id|"
        r"doc|"
        r"passport(?:\s+number)?|"
        r"pasaporte(?:\s+número)?|"
        r"passaporte(?:\s+número)?"
        r")\b"
        r"(?:\s+(?:es|é|is|de|do|da|del|número|numero|nº|no|#))*"
        r"\s*[:#\-]?\s*"
        r"(?!\[[A-Z]+_\d+\])([A-Za-z0-9.\-\/]{6,20})\b",
        re.IGNORECASE,
    )

    # 5. Birth dates / dates
    BIRTHDATE_RE = re.compile(
        r"\b(?:"
        r"(?:nací\s+el|naci\s+el|nascid[oa]\s+em|born\s+(?:on|in)|"
        r"fecha\s+de\s+nacimiento|data\s+de\s+nascimento|date\s+of\s+birth|dob)"
        r"\s*[:#\-]?\s*"
        r")?"
        r"(?!\[[A-Z]+_\d+\])"
        r"(\b(?:\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4}|\d{4}[\/\.-]\d{1,2}[\/\.-]\d{1,2})\b)",
        re.IGNORECASE,
    )

    # 6. One-time passcodes / OTP codes after cue (4-8 digits)
    OTP_RE = re.compile(
        r"\b(?:"
        r"código\s+de\s+verificación|"
        r"codigo\s+de\s+verificacion|"
        r"código\s+de\s+verificação|"
        r"codigo\s+de\s+verificacao|"
        r"verification\s+code|"
        r"código\s+de\s+seguridad|"
        r"codigo\s+de\s+seguridad|"
        r"security\s+code|"
        r"código|"
        r"codigo|"
        r"code|"
        r"otp|"
        r"token"
        r")\b"
        r"\s*[:#\-]?"
        r"(?:\s+(?:es|é|is|de|do|da|del|foi|fue|número|numero|nº|no|#|temporal|enviado|recebido|recibido|received|sent|sms|que\s+(?:me\s+)?(?:llegó|llego|recibí|recibi|recebi|enviaron)|me\s+llegó|me\s+llego))*"
        r"\s*[:#\-]?\s*"
        r"(?!\[[A-Z]+_\d+\])\b(\d{4,8})\b",
        re.IGNORECASE,
    )

    # 6b. Bare "code"/"otp" keys in JSON tool-call arguments act as an OTP cue.
    # Only quoted values are rewritten (keeps the JSON valid); an unquoted
    # numeric value is caught by verify_safe and fails closed.
    OTP_ARG_KEY_RE = re.compile(
        r'"(?:code|otp)"\s*:\s*"(?!\[[A-Z]+_\d+\])(\d{4,8})"',
        re.IGNORECASE,
    )
    OTP_ARG_KEY_ANY_RE = re.compile(
        r'"(?:code|otp)"\s*:\s*"?(\d{4,8})\b',
        re.IGNORECASE,
    )

    # 7. Phone numbers
    PHONE_INTRO_RE = re.compile(
        r"\b(?:"
        r"llámame\s+al|llamame\s+al|llamar\s+al|"
        r"ligue\s+(?:para|no)?|ligar\s+(?:para|no)?|"
        r"call\s+me\s+at|"
        r"(?:teléfono|telefono|telefone|celular|cel|móvil|movil|phone)\s*(?:es|é|is|de|do|da|del)?"
        r")\s*[:#\-]?\s*"
        r"(?!\[[A-Z]+_\d+\])(\+?\d[\d\s.\-()]{6,15}\d)\b",
        re.IGNORECASE,
    )
    E164_PHONE_RE = re.compile(
        r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{2,9}\b"
    )
    NATIONAL_PHONE_RE = re.compile(
        r"(?!\[[A-Z]+_\d+\])\b3\d{9}\b|"
        r"(?:(?:\bphone|\btel|\bcelular|\bmóvil|\bcell)\s*[:#]?\s*(?:\(\d{2,4}\)|\b\d{2,4})[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b)|"
        r"(?:\(\d{2,4}\)[-\s]?\d{3,4}[-\s]?\d{3,4}\b)|"
        r"(?:\b\d{2,4}[-\s]\d{3,4}[-\s]\d{3,4}\b)"
    )

    # 8. Name intros and salutations
    NAME_INTRO_RE = re.compile(
        r"\b(?:"
        r"my\s+name\s+is|"
        r"(?:his|her|their)\s+name\s+is|"
        r"me\s+llamo|"
        r"(?:él|el|ella)\s+se\s+llama|"
        r"se\s+llama|"
        r"mi\s+nombre\s+es|"
        r"(?:su|el)\s+nombre\s+es|"
        r"chamo-me|"
        r"chama-se|"
        r"meu\s+nome\s+é|"
        r"o\s+nome\s+dele\s+é|"
        r"o\s+nome\s+dela\s+é|"
        r"sou\s+a\s+mãe\s+d[ao]|"
        r"sou\s+o\s+pai\s+d[ao]|"
        r"sou\s+(?:o|a)\s+(?:filh[oa]|espos[ao]|irmã[o]?)\s+d[ao]|"
        r"sou\s+(?:o|a)|"
        r"soy\s+la\s+madre\s+de|"
        r"soy\s+el\s+padre\s+de|"
        r"soy\s+(?:el|la)\s+(?:hij[oa]|espos[ao]|herman[oa])\s+de|"
        r"soy|"
        r"titular\s+(?:es|é|is)"
        r")\s+"
        r"(?!\[[A-Z]+_\d+\])([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)\b",
        re.IGNORECASE,
    )
    NAME_SALUTATION_RE = re.compile(
        r"\b(?:Sr\.|Sra\.|Srta\.|Don|Doña|Dona|Mr\.|Mrs\.|Ms\.|Dr\.|Dra\.)\s+"
        r"(?!\[[A-Z]+_\d+\])([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)\b"
    )

    # 9. Unclassified sequence of >=7 digits (avoiding currency amounts)
    DIGITS_RUN_RE = re.compile(r"\b\d[\d\s.\-]{5,}\d\b")
    CURRENCY_PREFIX_RE = re.compile(
        r"(?:[\$€£]|R\$|\b(?:USD|COP|BRL|EUR|valor(?:\s+de)?|cobro(?:\s+de)?|monto(?:\s+de)?|quantia(?:\s+de)?|débito(?:\s+de)?|debito(?:\s+de)?|transfer\s+of))\s*$",
        re.IGNORECASE,
    )
    CURRENCY_SUFFIX_RE = re.compile(
        r"^\s*(?:USD|COP|BRL|EUR|dólares|dolares|pesos|reais|euros|centavos)\b",
        re.IGNORECASE,
    )

    # Placeholder format pattern for rehydration, derived from contracts PiiType
    _CATEGORIES_PATTERN = "|".join(sorted(p.value for p in PiiType))
    PLACEHOLDER_RE = re.compile(rf"\[({_CATEGORIES_PATTERN})_(\d+)\]")

    def _init_counters(
        self,
        mapping: dict[str, str],
    ) -> dict[str, int]:
        """Determine next index for each entity type based on existing mapping."""
        counters = {p.value: 0 for p in PiiType}
        for placeholder in mapping.keys():
            m = self.PLACEHOLDER_RE.match(placeholder)
            if m:
                cat, idx_str = m.group(1), m.group(2)
                idx = int(idx_str)
                if idx > counters.get(cat, 0):
                    counters[cat] = idx
        return counters

    def _is_currency_amount(self, text: str, start: int, end: int) -> bool:
        """Check if a numeric match is preceded or followed by currency markers."""
        prefix = text[:start]
        suffix = text[end:]
        return bool(
            self.CURRENCY_PREFIX_RE.search(prefix)
            or self.CURRENCY_SUFFIX_RE.search(suffix)
        )

    def mask(
        self,
        text: str,
        state: dict[str, str] | None = None,
    ) -> MaskResult:
        """Mask PII in text using stable placeholders. Fail-closed on error."""
        if not text:
            return MaskResult(masked_text="", mapping={}, reverse_mapping={})

        try:
            mapping: dict[str, str] = {}
            rev_mapping: dict[str, str] = {}
            if state:
                for k, v in state.items():
                    if k.startswith("[") and k.endswith("]"):
                        mapping[k] = v
                        rev_mapping[v] = k
                    else:
                        rev_mapping[k] = v
                        mapping[v] = k

            counters = self._init_counters(mapping)

            def get_or_create_placeholder(category: str, raw_val: str) -> str:
                clean_val = raw_val.strip()
                if clean_val in rev_mapping:
                    return rev_mapping[clean_val]
                counters[category] += 1
                placeholder = f"[{category}_{counters[category]}]"
                mapping[placeholder] = clean_val
                rev_mapping[clean_val] = placeholder
                return placeholder

            masked = text

            # 1. PAN / Cards (13-19 digits)
            for m in list(self.PAN_RE.finditer(masked)):
                raw_match = m.group(0)
                digits_only = re.sub(r"\D", "", raw_match)
                if 13 <= len(digits_only) <= 19 and not raw_match.startswith("["):
                    placeholder = get_or_create_placeholder("CARD", raw_match)
                    masked = masked.replace(raw_match, placeholder)

            # 2. Emails
            for m in list(self.EMAIL_RE.finditer(masked)):
                raw_match = m.group(0)
                if not raw_match.startswith("["):
                    placeholder = get_or_create_placeholder("EMAIL", raw_match)
                    masked = masked.replace(raw_match, placeholder)

            # 3. Formatted documents (CPF, SSN, Passport)
            for pat in (self.CPF_RE, self.SSN_RE, self.PASSPORT_RE):
                for m in list(pat.finditer(masked)):
                    raw_match = m.group(0)
                    if not raw_match.startswith("["):
                        placeholder = get_or_create_placeholder("DOC", raw_match)
                        masked = masked.replace(raw_match, placeholder)

            # Formatted DNI dots (only if not a currency amount)
            for m in list(self.DNI_DOTS_RE.finditer(masked)):
                raw_match = m.group(0)
                if not raw_match.startswith("[") and not self._is_currency_amount(
                    masked, m.start(), m.end()
                ):
                    placeholder = get_or_create_placeholder("DOC", raw_match)
                    masked = masked.replace(raw_match, placeholder)

            # 4. Labeled document numbers (e.g. cédula, CPF, DNI, passport)
            for m in list(self.DOC_LABEL_RE.finditer(masked)):
                doc_num = m.group(1)
                if not doc_num.startswith("["):
                    placeholder = get_or_create_placeholder("DOC", doc_num)
                    masked = masked.replace(doc_num, placeholder)

            # 5. Birth dates / dates
            for m in list(self.BIRTHDATE_RE.finditer(masked)):
                date_val = m.group(1)
                if not date_val.startswith("["):
                    placeholder = get_or_create_placeholder("DATE", date_val)
                    masked = masked.replace(date_val, placeholder)

            # 5b. Written-out dates ("4 de marzo de 1988", "March 4, 1988"),
            # replaced by position so a longer date never loses its head to a
            # shorter one that happens to be its suffix ("4 ..." inside "14 ...").
            written_dates = find_written_dates(masked)
            if written_dates:
                pieces: list[str] = []
                cursor = 0
                for found in written_dates:
                    pieces.append(masked[cursor : found.start])
                    pieces.append(
                        get_or_create_placeholder(
                            "DATE", masked[found.start : found.end]
                        )
                    )
                    cursor = found.end
                pieces.append(masked[cursor:])
                masked = "".join(pieces)

            # 6. One-time passcodes / OTP codes after cue (4-8 digits)
            for m in list(self.OTP_RE.finditer(masked)):
                otp_val = m.group(1)
                if not otp_val.startswith("["):
                    placeholder = get_or_create_placeholder("OTP", otp_val)
                    masked = masked.replace(otp_val, placeholder)

            for m in list(self.OTP_ARG_KEY_RE.finditer(masked)):
                otp_val = m.group(1)
                placeholder = get_or_create_placeholder("OTP", otp_val)
                masked = masked.replace(otp_val, placeholder)

            # 6. Phone intros & numbers (e.g. llámame al 3001234567)
            for m in list(self.PHONE_INTRO_RE.finditer(masked)):
                phone_val = m.group(1)
                if not phone_val.startswith("["):
                    placeholder = get_or_create_placeholder("PHONE", phone_val)
                    masked = masked.replace(phone_val, placeholder)

            # 7. E.164 and National Phones
            for m in list(self.E164_PHONE_RE.finditer(masked)):
                raw_match = m.group(0)
                if not raw_match.startswith("["):
                    placeholder = get_or_create_placeholder("PHONE", raw_match)
                    masked = masked.replace(raw_match, placeholder)

            for m in list(self.NATIONAL_PHONE_RE.finditer(masked)):
                raw_match = m.group(0)
                digits_only = re.sub(r"\D", "", raw_match)
                if 7 <= len(digits_only) <= 12 and not raw_match.startswith("["):
                    placeholder = get_or_create_placeholder("PHONE", raw_match)
                    masked = masked.replace(raw_match, placeholder)

            # 8. Name intros & salutations
            for m in list(self.NAME_SALUTATION_RE.finditer(masked)):
                name_match = m.group(1)
                if not name_match.startswith("["):
                    placeholder = get_or_create_placeholder("NAME", name_match)
                    masked = masked.replace(name_match, placeholder)

            for m in list(self.NAME_INTRO_RE.finditer(masked)):
                name_match = m.group(1)
                if not name_match.startswith("["):
                    placeholder = get_or_create_placeholder("NAME", name_match)
                    masked = masked.replace(name_match, placeholder)

            # 9. Generic runs of >= 7 digits not associated with a currency amount
            for m in list(self.DIGITS_RUN_RE.finditer(masked)):
                raw_match = m.group(0)
                if raw_match.startswith("[") or raw_match.endswith("]"):
                    continue
                digits_only = re.sub(r"\D", "", raw_match)
                if len(digits_only) >= 7:
                    if not self._is_currency_amount(masked, m.start(), m.end()):
                        placeholder = get_or_create_placeholder("DOC", raw_match)
                        masked = masked.replace(raw_match, placeholder)

            # Fail-closed check: verify no PII remains unmasked
            if not self.verify_safe(masked):
                raise MaskingError(
                    "Outbound message contains unmasked PII after regex masking"
                )

            return MaskResult(
                masked_text=masked,
                mapping=mapping,
                reverse_mapping=rev_mapping,
            )
        except Exception as exc:
            logger.error("Masking failed: %s", exc)
            if isinstance(exc, MaskingError):
                raise
            raise MaskingError(f"PII masking execution failed: {exc}") from exc

    def unmask(self, text: str, mapping: dict[str, str]) -> str:
        """Rehydrate model output by replacing placeholders with original values."""
        if not text or not mapping:
            return text

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            return mapping.get(token, token)

        return self.PLACEHOLDER_RE.sub(repl, text)

    def verify_safe(self, text: str) -> bool:
        """Strict check ensuring text contains no raw, unmasked PII.

        Must fail closed on raw emails, PANs, formatted documents, document labels
        followed by raw values, phone numbers, name intros with raw names, birth dates,
        and unclassified runs of >= 7 digits (unless currency amounts).
        """
        if not text:
            return True

        # 1. Emails
        if self.EMAIL_RE.search(text):
            return False

        # 2. PANs (13-19 digits)
        for m in self.PAN_RE.finditer(text):
            val = m.group(0)
            if val.startswith("[") and val.endswith("]"):
                continue
            digits = re.sub(r"\D", "", val)
            if 13 <= len(digits) <= 19:
                return False

        # 3. Formatted documents (CPF, SSN, Passport)
        for pat in (self.CPF_RE, self.SSN_RE, self.PASSPORT_RE):
            for m in pat.finditer(text):
                val = m.group(0)
                if not (val.startswith("[") and val.endswith("]")):
                    return False

        # DNI dots (if not currency)
        for m in self.DNI_DOTS_RE.finditer(text):
            val = m.group(0)
            if not (val.startswith("[") and val.endswith("]")):
                if not self._is_currency_amount(text, m.start(), m.end()):
                    return False

        # 4. Document labels followed by raw values
        for m in self.DOC_LABEL_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        # 5. Birth dates / dates
        for m in self.BIRTHDATE_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        # 5b. Written-out dates
        if find_written_dates(text):
            return False

        # 6. One-time passcodes / OTP codes after cue (4-8 digits)
        for m in self.OTP_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        if self.OTP_ARG_KEY_ANY_RE.search(text):
            return False

        # 6. Phone intros & E.164
        for m in self.PHONE_INTRO_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        if self.E164_PHONE_RE.search(text):
            return False

        for m in self.NATIONAL_PHONE_RE.finditer(text):
            val = m.group(0)
            if not (val.startswith("[") and val.endswith("]")):
                digits = re.sub(r"\D", "", val)
                if 7 <= len(digits) <= 12:
                    return False

        # 7. Name intros & salutations with unmasked names
        for m in self.NAME_INTRO_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        for m in self.NAME_SALUTATION_RE.finditer(text):
            val = m.group(1)
            if not (val.startswith("[") and val.endswith("]")):
                return False

        # 8. Unclassified sequence of >=7 digits (unless currency amounts)
        for m in self.DIGITS_RUN_RE.finditer(text):
            val = m.group(0)
            if val.startswith("[") and val.endswith("]"):
                continue
            digits = re.sub(r"\D", "", val)
            if len(digits) >= 7 and not self._is_currency_amount(
                text, m.start(), m.end()
            ):
                return False

        return True
