"""Regex slot extraction for the lexical baseline (es, pt, en).

Covers the slots with a stable surface form: email, card_number, card_last4,
otp_code, amount, currency, transaction_date and birth_date. Names, phones,
document numbers, document types and merchants need a model and are not
extracted here. Every rule is conservative: a missed slot is cheaper than a
wrong one, because the caller treats slots as hints, never as authority.

Bias: these rules were tuned on the synthetic train and validation splits, and
the provisional test split (decision.test.provisional.jsonl) has the same
author as the rules. Scores on it are optimistic until the human test set
replaces it.
"""

from __future__ import annotations

import re

from encoder.models import Slot

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_NUMBER = re.compile(r"(?<!\d)\d{4}(?:[ -]?\d{4}){3}(?!\d)")
# A digit run that is not part of a longer number ("1.250", "12/09").
_NOT_BEFORE = r"(?<!\d)(?<!\d[.,/-])"
_NOT_AFTER = r"(?!\d|[.,/-]\d)"
_CARD_LAST4 = re.compile(
    r"(?:terminad[ao]\s+e[nm]|termina\s+en|terminaci[oó]n|final|finais|"
    r"ending(?:\s+in)?|ends?\s+(?:in|with)|[uú]ltimos\s+(?:4\s+)?d[ií]gitos|"
    r"last\s+(?:4\s+)?digits|"
    r"tarjeta|cart[aã]o|card|pl[aá]stico)"
    r"(?:\s+[^\W\d]+){0,2}?\s+(\d{4})" + _NOT_AFTER,
    re.IGNORECASE,
)
_OTP = re.compile(_NOT_BEFORE + r"\d{6}" + _NOT_AFTER)
_OTP_CUE = re.compile(
    r"c[oó]d(?:igo)?|code|token|otp|passcode|verifica|sms|"
    r"confirmaci[oó]n|confirma[cç][aã]o|confirmation|mensaje|mensagem|message|"
    r"clave|chave|password|one-time",
    re.IGNORECASE,
)
# Short replies ("es 264819", "listo, 362791") answer an OTP prompt.
_OTP_SHORT_REPLY_WORDS = 4
_NUMBER = r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{1,2})?)"
_SYMBOL = r"(R\$|US\$|\$|€|£)"
_CODE = r"(USD|COP|BRL|EUR|GBP|MXN|ARS|CLP|PEN)"
_SYMBOL_AMOUNT = re.compile(_SYMBOL + r"\s?" + _NUMBER + r"(?!\d)")
_AMOUNT_SYMBOL = re.compile(r"(?<![\d.,])" + _NUMBER + r"\s?" + _SYMBOL)
_CODE_AMOUNT = re.compile(r"\b" + _CODE + r"\s?" + _NUMBER + r"(?!\d)")
_AMOUNT_CODE = re.compile(r"(?<![\d.,])" + _NUMBER + r"\s?" + _CODE + r"\b")
_DATE = re.compile(r"(?<!\d)(\d{2}/\d{2}/(\d{4})|(\d{4})-\d{2}-\d{2})(?!\d)")
_RELATIVE_DATE = re.compile(r"\b(?:ayer|hoy|ontem|hoje|yesterday|today)\b", re.I)
# Relative dates count only next to a transaction ("el cobro de ayer"), not in
# "perdí la tarjeta hoy".
_TRANSACTION_CUE = re.compile(
    r"cobr|carg|compr|d[eé]bit|transac|pag|gast|movim|lan[cç]amento|saque|"
    r"retir|charge|purchase|bought|spent|payment|withdraw",
    re.IGNORECASE,
)
_BIRTH_CUE = re.compile(r"nac[ií]|nasci|born|birth|dob\b", re.IGNORECASE)
# Dates this old are birth dates: transactions in scope are recent.
_LAST_BIRTH_YEAR = 2010


def _slot(slot_type: str, text: str, start: int, end: int) -> Slot:
    return Slot(type=slot_type, value=text[start:end], start=start, end=end)


def extract_regex_slots(text: str) -> list[Slot]:
    """Return non-overlapping slots in text order; earlier rules win ties."""
    candidates: list[Slot] = []

    for m in _EMAIL.finditer(text):
        candidates.append(_slot("email", text, m.start(), m.end()))
    for m in _CARD_NUMBER.finditer(text):
        candidates.append(_slot("card_number", text, m.start(), m.end()))
    for pattern, currency_group in (
        (_SYMBOL_AMOUNT, 1),
        (_CODE_AMOUNT, 1),
        (_AMOUNT_SYMBOL, 2),
        (_AMOUNT_CODE, 2),
    ):
        amount_group = 3 - currency_group
        for m in pattern.finditer(text):
            candidates.append(
                _slot("currency", text, m.start(currency_group), m.end(currency_group))
            )
            candidates.append(
                _slot("amount", text, m.start(amount_group), m.end(amount_group))
            )
    birth_cue = _BIRTH_CUE.search(text) is not None
    for m in _DATE.finditer(text):
        year = int(m.group(2) or m.group(3))
        is_birth = birth_cue or year <= _LAST_BIRTH_YEAR
        date_type = "birth_date" if is_birth else "transaction_date"
        candidates.append(_slot(date_type, text, m.start(1), m.end(1)))
    if _TRANSACTION_CUE.search(text):
        for m in _RELATIVE_DATE.finditer(text):
            candidates.append(_slot("transaction_date", text, m.start(), m.end()))
    for m in _CARD_LAST4.finditer(text):
        candidates.append(_slot("card_last4", text, m.start(1), m.end(1)))
    short_reply = len(text.split()) <= _OTP_SHORT_REPLY_WORDS
    if _OTP_CUE.search(text) or short_reply:
        for m in _OTP.finditer(text):
            candidates.append(_slot("otp_code", text, m.start(), m.end()))

    taken: list[Slot] = []
    for cand in candidates:
        if all(cand.end <= s.start or cand.start >= s.end for s in taken):
            taken.append(cand)
    return sorted(taken, key=lambda s: s.start)
