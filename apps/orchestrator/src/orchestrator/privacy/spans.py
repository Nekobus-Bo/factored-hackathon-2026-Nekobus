"""Union of the regex masker and the encoder's PII spans (AGENTS rule 5).

The regexes see patterns (an email, a card number, "me llamo ..."); the encoder
sees context (a name with no intro phrase, a written date). Each catches what
the other misses, so the text that leaves for the provider masks both.

The regex masker rewrites text with sequential substring replacement, so its
matches carry no offsets. Instead of rewriting it, this module runs *after* it
and works on raw-text coordinates: the masked text is aligned back to the raw
text through the session mapping (each placeholder stands for a known raw
value), which yields the exact range every placeholder covers. Encoder spans
are then merged with those ranges:

- an encoder span whose characters are all inside placeholders already is
  ignored: the text is byte-identical to regex-only masking;
- an encoder span that reaches characters the regexes left in clear replaces
  everything it overlaps by ONE placeholder over the hull of the overlapping
  ranges, of the kind of the largest member (a tie keeps the regex kind). The
  hull, never the larger member alone, so no fragment of either survives.

The result can only mask more than regex-only masking. If the pieces cannot be
put back together exactly, or the masker still reports residual PII, the call
raises MaskingError and nothing goes out.
"""

import logging
import unicodedata
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from contracts import PiiSpan, PiiType

from orchestrator.privacy.masking import PLACEHOLDER_RE, Masker, MaskingError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpanUnion:
    """Masked text after the union, and how many encoder spans changed it."""

    masked_text: str
    spans_added: int


@dataclass(frozen=True)
class _Range:
    """A masked range of the raw text: a regex placeholder or an encoder span."""

    start: int
    end: int
    kind: str
    token: str = ""  # the regex placeholder; empty for an encoder span

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def from_regex(self) -> bool:
        return bool(self.token)


def union_mask(
    masker: Masker,
    raw_text: str,
    masked_text: str,
    mapping: dict[str, str],
    previous: Collection[str],
    spans: Sequence[PiiSpan],
) -> SpanUnion:
    """Widen `masked_text` (the regex masking of `raw_text`) with encoder `spans`.

    `mapping` is the session's placeholder -> raw value map, updated in place:
    new placeholders are added, and placeholders created this turn that no
    longer appear are dropped. Those in `previous` (from earlier turns) are
    never dropped: the stored history may still cite them.

    Raises MaskingError when the encoder spans cannot be placed exactly or the
    result is not safe. Callers must then send nothing.
    """
    encoder = [r for r in (_encoder_range(s, raw_text) for s in spans) if r]
    if not encoder:
        return SpanUnion(masked_text, 0)

    baseline = _align(raw_text, masked_text, mapping)
    if baseline is None:
        logger.warning("Encoder PII spans could not be aligned with the masked text")
        raise MaskingError("cannot place encoder PII spans on the masked text")

    plan = [
        (group, _needs_merge(group))
        for group in _overlap_groups([*baseline, *encoder])
    ]
    # Placeholders that only stood inside a merged range leave the map before
    # new ones are allocated, so their numbers are reused. Tokens cited elsewhere
    # in this text, or by an earlier turn's history, always stay.
    kept = {r.token for group, merge in plan if not merge for r in group}
    replaced = {r.token for group, merge in plan if merge for r in group}
    for token in (replaced - kept - set(previous)) - {""}:
        mapping.pop(token, None)

    allocator = _Allocator(mapping)
    pieces: list[str] = []
    cursor = 0
    added = 0
    for group, merge in plan:
        if not merge:
            for r in group:
                if r.from_regex:
                    pieces.append(raw_text[cursor : r.start])
                    pieces.append(r.token)
                    cursor = r.end
            continue
        start = min(r.start for r in group)
        end = max(r.end for r in group)
        winner = max(group, key=lambda r: (r.length, r.from_regex))
        pieces.append(raw_text[cursor:start])
        pieces.append(allocator.token(winner.kind, raw_text[start:end]))
        cursor = end
        added += sum(1 for r in group if not r.from_regex)
    pieces.append(raw_text[cursor:])
    result = "".join(pieces)

    if masker.unmask(result, mapping) != raw_text:
        raise MaskingError("masked text does not rehydrate to the customer text")
    if not masker.verify_safe(result):
        raise MaskingError("residual PII after joining encoder spans")
    return SpanUnion(result, added)


def _is_word_char(char: str) -> bool:
    """Letters, digits, underscore and combining marks (NFD accents)."""
    return char == "_" or unicodedata.category(char)[0] in "LNM"


def _encoder_range(span: PiiSpan, raw_text: str) -> _Range | None:
    """The span as a range of `raw_text`, or None if it masks nothing.

    Offsets are trimmed of whitespace and widened to whole words, so an offset
    that is off by a character cannot leave the tail of a name or a digit in
    clear. Out-of-range and empty spans are dropped: the union only adds.
    """
    start, end = span.start, min(span.end, len(raw_text))
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    while (
        start > 0
        and _is_word_char(raw_text[start - 1])
        and _is_word_char(raw_text[start])
    ):
        start -= 1
    while (
        end < len(raw_text)
        and _is_word_char(raw_text[end - 1])
        and _is_word_char(raw_text[end])
    ):
        end += 1
    return _Range(start, end, PiiType(span.type).value)


def _align(
    raw_text: str, masked_text: str, mapping: dict[str, str]
) -> list[_Range] | None:
    """Raw-text range of every placeholder of `masked_text`, or None if it disagrees.

    Each placeholder stands for its mapped raw value; the text between them is
    literal. Rehydrating must reproduce `raw_text` exactly, character by
    character, or the alignment is refused (for instance when the customer
    typed something that looks like a placeholder already in the session).
    """
    ranges: list[_Range] = []
    raw_pos = 0
    masked_pos = 0
    for match in PLACEHOLDER_RE.finditer(masked_text):
        token = match.group(0)
        value = mapping.get(token)
        if value is None:
            continue  # looks like a placeholder but is literal text
        literal = masked_text[masked_pos : match.start()]
        if not raw_text.startswith(literal, raw_pos):
            return None
        raw_pos += len(literal)
        if not value or not raw_text.startswith(value, raw_pos):
            return None
        ranges.append(_Range(raw_pos, raw_pos + len(value), match.group(1), token))
        raw_pos += len(value)
        masked_pos = match.end()
    if raw_text[raw_pos:] != masked_text[masked_pos:]:
        return None
    return ranges


def _overlap_groups(ranges: Iterable[_Range]) -> list[list[_Range]]:
    """Ranges grouped by overlap (touching ranges stay apart), in text order."""
    groups: list[list[_Range]] = []
    group_end = -1
    for current in sorted(ranges, key=lambda r: (r.start, -r.end)):
        if groups and current.start < group_end:
            groups[-1].append(current)
            group_end = max(group_end, current.end)
        else:
            groups.append([current])
            group_end = current.end
    return groups


def _needs_merge(group: list[_Range]) -> bool:
    """True if an encoder span in `group` reaches characters no regex masked."""
    regex = [r for r in group if r.from_regex]
    return any(not _is_covered(r, regex) for r in group if not r.from_regex)


def _is_covered(member: _Range, regex: list[_Range]) -> bool:
    """True if every character of `member` is inside some regex placeholder."""
    position = member.start
    for r in sorted(regex, key=lambda r: r.start):
        if r.end <= position:
            continue
        if r.start > position:
            return False
        position = r.end
        if position >= member.end:
            return True
    return position >= member.end


class _Allocator:
    """Placeholder allocation with the masker's rules: one token per value."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self._by_value = {value: token for token, value in mapping.items()}
        self._counters = {kind.value: 0 for kind in PiiType}
        for token in mapping:
            match = PLACEHOLDER_RE.fullmatch(token)
            if match:
                kind, index = match.group(1), int(match.group(2))
                self._counters[kind] = max(self._counters[kind], index)

    def token(self, kind: str, value: str) -> str:
        existing = self._by_value.get(value)
        if existing is not None:
            return existing
        self._counters[kind] += 1
        token = f"[{kind}_{self._counters[kind]}]"
        self._mapping[token] = value
        self._by_value[value] = token
        return token
