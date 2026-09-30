"""Turn `{slot}` placeholders into fictitious values with exact character offsets.

Shared by the LLM-generated train/validation splits and the provisional test split, so both
carry the same fictitious-PII guarantee as tools/synthdata (docs/labeling-rubric.md §3).
"""

import random
import re
from typing import Any

from tools.synthdata.fillers import DOCUMENT_PROFILES, get_fillers

# Allowed placeholders per intent, and whether every message must carry at least one.
# Mirrors the slot usage of tools/synthdata/templates_pt.py.
PLACEHOLDERS: dict[str, tuple[list[str], bool]] = {
    "report_unrecognized_charge": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
    "request_dispute": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
    "report_lost_card": (["card_last4"], False),
    "report_stolen_card": (["card_last4"], False),
    "request_card_block": (["card_last4"], False),
    "report_suspicious_activity": (["card_last4", "transaction_date"], False),
    "provide_identity_data": (
        ["full_name", "document_type", "document_number", "birth_date", "email", "phone"],
        True,
    ),
    "provide_otp_code": (["otp_code"], True),
    "check_balance": (["card_last4"], False),
    "check_recent_transactions": (["card_last4"], False),
}

# Brazilian values for the non-PII slots; PII slots keep the fictitious values from tools/synthdata.
BR_FILLERS: dict[str, list[str]] = {
    "amount": [
        "15,90", "29,99", "47,50", "89,90", "120,00", "150,00", "237,45", "349,90",
        "500,00", "780,00", "1.200,00", "1.899,90", "2.450,00", "35", "60", "250",
    ],
    "currency": ["R$"],
    "merchant": [
        "iFood", "Mercado Livre", "Magalu", "Americanas", "Shopee", "Amazon", "Uber", "Rappi",
        "Netflix", "Spotify", "Drogasil", "Carrefour", "Pão de Açúcar", "Renner", "Casas Bahia",
        "Posto Ipiranga", "Shell", "Riachuelo", "Centauro", "Kabum", "Steam", "Assaí", "Atacadão",
        "Smart Fit", "Cinemark",
    ],
    "transaction_date": [
        "ontem", "hoje", "12/09/2026", "03/09/2026", "28/08/2026", "21/09/2026", "15/09/2026", "07/09/2026",
    ],
    "birth_date": [
        "12/04/1985", "24/11/1992", "08/07/1978", "30/09/1983", "19/01/1995", "05/12/1980", "17/03/1990", "22/06/1975",
    ],
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_DOCUMENT_WORD = re.compile(r"(?i)\b(cpf|rg|passaporte|cnpj|rne|crnm)\b")


def placeholder_problem(template: str, intent: str) -> str:
    """Return why a template cannot be filled for this intent, or an empty string if it can."""
    allowed, required = PLACEHOLDERS.get(intent, ([], False))
    names = _PLACEHOLDER.findall(template)
    if any(name not in allowed for name in names):
        return "unknown or disallowed placeholder"
    if required and not names:
        return "required placeholder missing"
    if re.search(r"[{}]", _PLACEHOLDER.sub("", template)):
        return "stray brace"
    return ""


def fill(template: str, intent: str, rng: random.Random) -> tuple[str, list[dict[str, Any]]]:
    """Fill every placeholder and return the text with slots at exact offsets.

    Raises ValueError when the template is not valid for the intent.
    """
    problem = placeholder_problem(template, intent)
    if problem:
        raise ValueError(problem)
    values = {**get_fillers("pt", rng), **{k: rng.choice(v) for k, v in BR_FILLERS.items()}}
    names = _PLACEHOLDER.findall(template)
    if "document_number" in names and "document_type" not in names:
        # The text names the document itself ("cpf {document_number}"): the number must match that type
        named = _DOCUMENT_WORD.search(template)
        surface = named.group(1).lower() if named else "cpf"
        profile = rng.choice([d for d in DOCUMENT_PROFILES["pt"] if d["surface"].lower() == surface])
        values["document_number"] = profile["number"]

    text, slots = "", []
    # re.split with one capture group alternates literal text (even indexes) and placeholder names (odd)
    for i, part in enumerate(_PLACEHOLDER.split(template.strip())):
        if i % 2 == 0:
            text += part
            continue
        value = values[part]
        slot: dict[str, Any] = {"type": part, "value": value, "start": len(text), "end": len(text) + len(value)}
        if part == "document_type":
            slot["normalized"] = values["document_type_normalized"]
        slots.append(slot)
        text += value
    for slot in slots:
        assert text[slot["start"] : slot["end"]] == slot["value"], slot
    return text, slots
