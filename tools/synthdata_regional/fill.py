"""Turn `{slot}` placeholders into fictitious values with exact character offsets.

Shared by the LLM-generated train/validation splits and the provisional test split, so both
carry the same fictitious-PII guarantee as tools/synthdata (docs/labeling-rubric.md §3).
PII slots (names, emails, OTPs, card digits) come from tools/synthdata; documents, phones,
amounts, merchants and dates come from the locale.
"""

import random
import re
from typing import Any

from tools.synthdata.fillers import get_fillers
from tools.synthdata_regional.locales import PLACEHOLDERS, Locale, document_profiles

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


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


def slot_values(loc: Locale, template: str, rng: random.Random) -> dict[str, str]:
    """Draw one consistent set of values; the draw order is fixed so seeded outputs stay reproducible."""
    values = {**get_fillers(loc.lang, rng), **{k: rng.choice(v) for k, v in loc.fillers.items()}}
    if loc.document_profiles is not None:
        profile = rng.choice(loc.document_profiles)
        values.update(document_type=profile["surface"], document_type_normalized=profile["normalized"],
                      document_number=profile["number"])
    names = _PLACEHOLDER.findall(template)
    if "document_number" in names and "document_type" not in names:
        # The text names the document itself ("mi DNI {document_number}"): the number must match that type
        named = re.search(loc.document_word_rx, template)
        surface = named.group(1).lower() if named else loc.default_document
        profile = rng.choice([d for d in document_profiles(loc) if d["surface"].lower() == surface])
        values["document_number"] = profile["number"]
    return values


def fill(loc: Locale, template: str, intent: str, rng: random.Random) -> tuple[str, list[dict[str, Any]]]:
    """Fill every placeholder and return the text with slots at exact offsets.

    Raises ValueError when the template is not valid for the intent.
    """
    problem = placeholder_problem(template, intent)
    if problem:
        raise ValueError(problem)
    values = slot_values(loc, template, rng)
    text, slots = "", []
    # re.split with one capture group alternates literal text (even indexes) and placeholder names (odd)
    for i, part in enumerate(_PLACEHOLDER.split(template.strip())):
        if i % 2 == 0:
            text += part
            continue
        value = values[part]
        if part == "transaction_date" and loc.absolute_date_context and re.search(loc.absolute_date_context, text) and not value[0].isdigit():
            value = rng.choice([d for d in loc.fillers["transaction_date"] if d[0].isdigit()])  # "el hoy" → "el 12/09/2026"
        slot: dict[str, Any] = {"type": part, "value": value, "start": len(text), "end": len(text) + len(value)}
        if part == "document_type":
            slot["normalized"] = values["document_type_normalized"]
        slots.append(slot)
        text += value
    for slot in slots:
        assert text[slot["start"] : slot["end"]] == slot["value"], slot
    return text, slots
