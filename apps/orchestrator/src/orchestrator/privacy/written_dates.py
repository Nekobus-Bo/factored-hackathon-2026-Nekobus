"""Written-out calendar dates in Spanish, Portuguese and English.

One grammar, two users: the masker hides these dates before text leaves for the
LLM provider, and the date normalizer turns the rehydrated text into the ISO
form banking-core requires. Sharing it keeps the two from drifting: whatever the
masker hides, the normalizer can read.

Recognized (case-insensitive, accents optional, with or without "de"/"of"/"del",
optional ordinal suffix, full or abbreviated month, optional trailing period):

    4 de marzo de 1988    4 de março de 1988    4 de marco del 1988
    March 4, 1988         4 March 1988          4th of March 1988
    4 mar 1988            Mar. 4 1988           4-mar-1988

A date needs a four-digit year (1800-2099). "mayo" alone, "March madness",
"March 1988" and "4 de marzo" are not dates for this module: without a year the
text is a month, a period or a day of the year, not a value that identifies
anyone. That gap is declared in docs/limitations.md.

Month names of the three languages never collide on a different month number,
so the session language is not needed to read a written date: the position of
the month token (before or after the day) already says which order was typed.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# Month number -> every accepted spelling, lowercase. Accents are optional in
# the text; the one accented month is listed with and without its cedilla.
_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("enero", "janeiro", "january", "ene", "jan"),
    2: ("febrero", "fevereiro", "february", "feb", "fev"),
    3: ("marzo", "março", "marco", "march", "mar"),
    4: ("abril", "april", "abr", "apr"),
    5: ("mayo", "maio", "may", "mai"),
    6: ("junio", "junho", "june", "jun"),
    7: ("julio", "julho", "july", "jul"),
    8: ("agosto", "august", "ago", "aug"),
    9: (
        "septiembre",
        "setiembre",
        "setembro",
        "september",
        "sept",
        "sep",
        "set",
    ),
    10: ("octubre", "outubro", "october", "oct", "out"),
    11: ("noviembre", "novembro", "november", "nov"),
    12: ("diciembre", "dezembro", "december", "dic", "dez", "dec"),
}


def _month_key(token: str) -> str:
    """Normal form of a month token used as the lookup key."""
    return unicodedata.normalize("NFC", token).casefold().rstrip(".")


_MONTH_NUMBER: dict[str, int] = {
    _month_key(name): number
    for number, names in _MONTH_NAMES.items()
    for name in names
}

# Text may carry the cedilla as a combining mark (NFD); accept it too.
_MONTH_SPELLINGS = sorted(
    {*_MONTH_NUMBER, unicodedata.normalize("NFD", "março")}, key=len, reverse=True
)
_MONTH = "(?:" + "|".join(re.escape(name) for name in _MONTH_SPELLINGS) + r")\.?"
# A month is a whole word: "mark" and "marzipan" are not "mar".
_MONTH_END = r"(?![^\W\d_])"
_ORDINAL = r"(?:st|nd|rd|th|º|°|ª|ro|er|o)?"
_LINK = r"(?:de|of|del)"
_DAY = r"(?P<day>\d{1,2})(?!\d)"
_MONTH_GROUP = rf"(?P<month>{_MONTH}){_MONTH_END}"
_YEAR = r"(?P<year>1[89]\d{2}|20\d{2})(?!\d)"
_DAY_TO_MONTH = rf"(?:\s+{_LINK}\s+|\s+|\s*[-/]\s*)"
_MONTH_TO_DAY = r"(?:\s+(?:the\s+)?|\s*[-/]\s*)"
_TO_YEAR = rf"(?:\s*,\s*|\s+(?:{_LINK}\s+)?|\s*[-/]\s*)"

_DAY_FIRST_RE = re.compile(
    rf"(?<!\w){_DAY}{_ORDINAL}{_DAY_TO_MONTH}{_MONTH_GROUP}{_TO_YEAR}{_YEAR}",
    re.IGNORECASE,
)
_MONTH_FIRST_RE = re.compile(
    rf"(?<!\w){_MONTH_GROUP}{_MONTH_TO_DAY}{_DAY}{_ORDINAL}{_TO_YEAR}{_YEAR}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WrittenDate:
    """A written date found in a text, as typed (not validated as a calendar day)."""

    start: int
    end: int
    day: int
    month: int
    year: int

    def to_date(self) -> date | None:
        """The calendar date, or None when the day does not exist in that month."""
        try:
            return date(self.year, self.month, self.day)
        except ValueError:
            return None


def _from_match(match: re.Match[str]) -> WrittenDate:
    return WrittenDate(
        start=match.start(),
        end=match.end(),
        day=int(match["day"]),
        month=_MONTH_NUMBER[_month_key(match["month"])],
        year=int(match["year"]),
    )


def find_written_dates(text: str) -> list[WrittenDate]:
    """Written dates in `text`, in order, without overlaps (leftmost, longest).

    Impossible days ("31 de febrero de 1990") are still found: masking is about
    what the customer typed, not about whether the calendar agrees.
    """
    candidates = [
        _from_match(match)
        for pattern in (_DAY_FIRST_RE, _MONTH_FIRST_RE)
        for match in pattern.finditer(text)
    ]
    candidates.sort(key=lambda found: (found.start, found.start - found.end))
    kept: list[WrittenDate] = []
    for found in candidates:
        if kept and found.start < kept[-1].end:
            continue
        kept.append(found)
    return kept


def parse_written_date(value: str) -> date | None:
    """The date `value` spells out when it is exactly one written date, else None."""
    text = value.strip()
    for pattern in (_DAY_FIRST_RE, _MONTH_FIRST_RE):
        match = pattern.fullmatch(text)
        if match is not None:
            return _from_match(match).to_date()
    return None
