"""Customer-typed dates to the ISO form tool contracts require.

The masker turns "15/03/1985" into `[DATE_1]` and the engine rehydrates it raw
for banking-core, whose `date` arguments accept only ISO (`YYYY-MM-DD`). The
conversion happens here, at rehydration, from the session language: the model
never sees or reasons about the raw date.
"""

import re
from datetime import date
from functools import cache
from typing import Any, get_args

from contracts import TOOL_CATALOG

from orchestrator.conversation.models import Lang

_ISO_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# One separator, used twice: "15/03-1985" is not a date anyone meant to type.
_YEAR_FIRST_RE = re.compile(r"([0-9]{4})([/.-])([0-9]{1,2})\2([0-9]{1,2})")
_YEAR_LAST_RE = re.compile(r"([0-9]{1,2})([/.-])([0-9]{1,2})\2([0-9]{4})")


def normalize_date(value: str, lang: Lang) -> str:
    """Return `value` as ISO `YYYY-MM-DD` when it is an unambiguous numeric date.

    Accepts `/`, `-` and `.` separators and 4-digit years. Year-first is always
    year-month-day. Year-last is day-first for `es` and `pt`; for `en` it is
    month-first (US) unless the first part is above 12, which can only be a day.
    ISO input, two-digit years and anything that is not a real calendar date
    come back unchanged, so the contract's own validation still rejects them.
    """
    text = value.strip()
    if _ISO_RE.fullmatch(text):
        return value
    if match := _YEAR_FIRST_RE.fullmatch(text):
        year, month, day = int(match[1]), int(match[3]), int(match[4])
    elif match := _YEAR_LAST_RE.fullmatch(text):
        first, second, year = int(match[1]), int(match[3]), int(match[4])
        month, day = (first, second) if _month_first(first, lang) else (second, first)
    else:
        return value
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return value


def _month_first(first: int, lang: Lang) -> bool:
    return lang == "en" and first <= 12


@cache
def date_arguments(tool: str) -> tuple[str, ...]:
    """Names of the `date`-typed input arguments of a catalog tool."""
    model = TOOL_CATALOG[tool].input_model
    return tuple(
        name
        for name, info in model.model_fields.items()
        if info.annotation is date or date in get_args(info.annotation)
    )


def normalize_date_arguments(tool: str, args: dict[str, Any], lang: Lang) -> None:
    """Normalize, in place, every `date`-typed string argument of `tool`."""
    for name in date_arguments(tool):
        value = args.get(name)
        if isinstance(value, str):
            args[name] = normalize_date(value, lang)
