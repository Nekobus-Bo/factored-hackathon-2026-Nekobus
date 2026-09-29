"""Union of regex masking and encoder PII spans (AGENTS rule 5).

The union may only ever mask more than the regex masker alone. The tests pin
that from both ends: concrete cases (a name only the encoder finds, an encoder
span inside or wider than a regex match, overlapping spans, unicode offsets)
and a seeded random check of the invariants.
"""

import random
import unicodedata

import pytest
from contracts import PiiSpan, PiiType
from orchestrator.privacy.masking import (
    PLACEHOLDER_RE,
    Masker,
    MaskingError,
    MaskResult,
    RegexMasker,
)
from orchestrator.privacy.spans import SpanUnion, union_mask


def span(kind: str, start: int, end: int) -> PiiSpan:
    return PiiSpan(type=PiiType(kind), start=start, end=end)


def span_of(kind: str, raw: str, needle: str, occurrence: int = 0) -> PiiSpan:
    start = -1
    for _ in range(occurrence + 1):
        start = raw.index(needle, start + 1)
    return span(kind, start, start + len(needle))


def run(
    raw: str,
    spans: list[PiiSpan],
    state: dict[str, str] | None = None,
) -> tuple[SpanUnion, dict[str, str], MaskResult]:
    """Regex-mask `raw` as the engine does, then apply the union."""
    masker = RegexMasker()
    mapping = dict(state or {})
    previous = set(mapping)
    baseline = masker.mask(raw, state=mapping)
    mapping.update(baseline.mapping)
    union = union_mask(masker, raw, baseline.masked_text, mapping, previous, spans)
    return union, mapping, baseline


def craft(
    raw: str,
    masked: str,
    mapping: dict[str, str],
    spans: list[PiiSpan],
    previous: set[str] | None = None,
) -> tuple[SpanUnion, dict[str, str]]:
    """Union over a hand-written regex baseline (independent of the regexes)."""
    state = dict(mapping)
    kept = set(mapping) if previous is None else previous
    union = union_mask(RegexMasker(), raw, masked, state, kept, spans)
    return union, state


# ------------------------------------------------------- what the encoder adds


def test_a_name_only_the_encoder_finds_is_masked() -> None:
    raw = "hola, Carlos Gómez aquí, perdí la tarjeta"
    baseline = RegexMasker().mask(raw)
    assert "Carlos" in baseline.masked_text  # the regexes miss it: no intro phrase

    union, mapping, _ = run(raw, [span_of("NAME", raw, "Carlos Gómez")])

    assert union.masked_text == "hola, [NAME_1] aquí, perdí la tarjeta"
    assert union.spans_added == 1
    assert mapping == {"[NAME_1]": "Carlos Gómez"}
    assert RegexMasker().unmask(union.masked_text, mapping) == raw


def test_without_spans_the_text_is_the_regex_text_and_nothing_is_aligned() -> None:
    raw = "mi correo es ana@bank.com"
    union, mapping, baseline = run(raw, [])

    assert union.masked_text == baseline.masked_text == "mi correo es [EMAIL_1]"
    assert union.spans_added == 0
    assert mapping == baseline.mapping


def test_spans_that_mask_nothing_never_fail_the_alignment() -> None:
    """Empty, blank and out-of-range spans are dropped before anything else."""
    union, _ = craft(
        raw="[NAME_1] hola  ",  # the customer typed a placeholder-shaped text
        masked="[NAME_1] hola  ",
        mapping={"[NAME_1]": "Ana"},
        spans=[span("NAME", 9, 9), span("NAME", 13, 15), span("NAME", 40, 50)],
    )

    assert union.masked_text == "[NAME_1] hola  "
    assert union.spans_added == 0


# ------------------------------------------- an encoder span the regexes cover


def test_span_equal_to_a_regex_match_changes_nothing() -> None:
    raw = "mi correo es ana@bank.com, gracias"
    union, mapping, baseline = run(raw, [span_of("EMAIL", raw, "ana@bank.com")])

    assert union.masked_text == baseline.masked_text
    assert union.spans_added == 0
    assert mapping == baseline.mapping


def test_span_inside_a_regex_match_keeps_the_regex_placeholder() -> None:
    raw = "mi tarjeta es 4532 1234 5678 9012, gracias"
    union, mapping, baseline = run(raw, [span_of("DOC", raw, "1234 5678")])

    assert baseline.masked_text == "mi tarjeta es [CARD_1], gracias"
    assert union.masked_text == baseline.masked_text
    assert mapping == baseline.mapping
    assert union.spans_added == 0


def test_a_span_across_two_regex_matches_that_adds_nothing_keeps_both() -> None:
    union, mapping = craft(
        raw="ana@bank.com3001234567",
        masked="[EMAIL_1][PHONE_1]",
        mapping={"[EMAIL_1]": "ana@bank.com", "[PHONE_1]": "3001234567"},
        spans=[span("NAME", 5, 16)],  # covers the seam, every character masked
    )

    assert union.masked_text == "[EMAIL_1][PHONE_1]"
    assert union.spans_added == 0
    assert set(mapping) == {"[EMAIL_1]", "[PHONE_1]"}


# ------------------------------------------------ an encoder span wider than it


def test_a_wider_encoder_span_replaces_the_regex_placeholder() -> None:
    raw = "mi cédula es CC 1020304050 gracias"
    baseline = RegexMasker().mask(raw)
    assert baseline.masked_text == "mi cédula es CC [DOC_1] gracias"

    union, mapping, _ = run(raw, [span_of("DOC", raw, "CC 1020304050")])

    assert union.masked_text == "mi cédula es [DOC_1] gracias"
    assert mapping == {"[DOC_1]": "CC 1020304050"}  # the number is reused
    assert union.spans_added == 1
    assert "1020304050" not in union.masked_text


def test_a_span_extending_a_regex_match_leaves_no_fragment() -> None:
    raw = "Hola Carlos Andrés Gómez"
    union, mapping = craft(
        raw,
        masked="Hola [NAME_1] Andrés Gómez",
        mapping={"[NAME_1]": "Carlos"},
        spans=[span("NAME", 5, 24)],
        previous=set(),
    )

    assert union.masked_text == "Hola [NAME_1]"
    assert mapping == {"[NAME_1]": "Carlos Andrés Gómez"}


def test_a_span_starting_before_a_regex_match_extends_it_leftwards() -> None:
    raw = "Sra. Ana Pérez"
    union, mapping = craft(
        raw,
        masked="Sra. [NAME_1]",
        mapping={"[NAME_1]": "Ana Pérez"},
        spans=[span("NAME", 0, 14)],
        previous=set(),
    )

    assert union.masked_text == "[NAME_1]"
    assert mapping == {"[NAME_1]": "Sra. Ana Pérez"}


def test_the_larger_member_decides_the_kind_and_a_tie_keeps_the_regex_kind() -> None:
    larger, _ = craft(
        raw="ab cd ef",
        masked="[NAME_1] ef",
        mapping={"[NAME_1]": "ab cd"},
        spans=[span("DOC", 3, 8)],  # same length as the regex range
        previous=set(),
    )
    assert larger.masked_text == "[NAME_1]"  # tie: NAME (regex) wins over DOC

    encoder_wins, mapping = craft(
        raw="ab cd ef gh",
        masked="[NAME_1] ef gh",
        mapping={"[NAME_1]": "ab cd"},
        spans=[span("DOC", 3, 11)],  # longer than the regex range
        previous=set(),
    )
    assert encoder_wins.masked_text == "[DOC_1]"
    assert mapping == {"[DOC_1]": "ab cd ef gh"}


def test_overlapping_encoder_spans_become_one_placeholder_over_their_hull() -> None:
    raw = "hola Ana María Pérez ok"
    union, mapping, _ = run(
        raw,
        [span_of("NAME", raw, "Ana María"), span_of("NAME", raw, "María Pérez")],
    )

    assert union.masked_text == "hola [NAME_1] ok"
    assert mapping == {"[NAME_1]": "Ana María Pérez"}
    assert union.spans_added == 2


def test_touching_encoder_spans_stay_separate() -> None:
    raw = "Ana,Pérez"
    union, mapping, _ = run(
        raw, [span_of("NAME", raw, "Ana"), span_of("NAME", raw, "Pérez")]
    )

    assert union.masked_text == "[NAME_1],[NAME_2]"
    assert set(mapping.values()) == {"Ana", "Pérez"}


# -------------------------------------------------- placeholders and the mapping


def test_same_value_shares_a_token_and_numbering_continues_the_session() -> None:
    raw = "Ana Pérez llamó. Ana Pérez insiste"
    union, mapping, _ = run(
        raw,
        [span_of("NAME", raw, "Ana Pérez", 0), span_of("NAME", raw, "Ana Pérez", 1)],
        state={"[NAME_1]": "Luis"},
    )

    assert union.masked_text == "[NAME_2] llamó. [NAME_2] insiste"
    assert mapping == {"[NAME_1]": "Luis", "[NAME_2]": "Ana Pérez"}


def test_a_placeholder_from_an_earlier_turn_is_never_dropped() -> None:
    raw = "Carlos Andrés Gómez"
    union, mapping = craft(
        raw,
        masked="[NAME_1] Andrés Gómez",
        mapping={"[NAME_1]": "Carlos"},
        spans=[span("NAME", 0, 19)],
        previous={"[NAME_1]"},  # cited by the stored history
    )

    assert union.masked_text == "[NAME_2]"
    assert mapping == {"[NAME_1]": "Carlos", "[NAME_2]": "Carlos Andrés Gómez"}


def test_a_token_still_cited_elsewhere_in_the_text_is_kept() -> None:
    raw = "Carlos y Carlos Andrés"
    union, mapping = craft(
        raw,
        masked="[NAME_1] y [NAME_1] Andrés",
        mapping={"[NAME_1]": "Carlos"},
        spans=[span("NAME", 10, 22)],
        previous=set(),
    )

    assert union.masked_text == "[NAME_1] y [NAME_2]"
    assert mapping == {"[NAME_1]": "Carlos", "[NAME_2]": "Carlos Andrés"}


# ------------------------------------------------------------ offsets and text


def test_offsets_are_trimmed_of_whitespace_and_widened_to_whole_words() -> None:
    raw = "hola Carlos Gómez aquí"
    padded = span_of("NAME", raw, " Carlos Gómez ")  # blanks around the name
    off_by_two = span("NAME", raw.index("Carlos") + 2, raw.index("Gómez") + 3)

    for candidate in (padded, off_by_two):
        union, mapping, _ = run(raw, [candidate])
        assert union.masked_text == "hola [NAME_1] aquí"
        assert mapping == {"[NAME_1]": "Carlos Gómez"}


def test_offsets_count_characters_not_bytes_or_utf16_units() -> None:
    raw = "¡Hola! 😀🎉 Señora Ñandú Gómez, ¿me ayudas? ✓"
    union, mapping, _ = run(raw, [span_of("NAME", raw, "Ñandú Gómez")])

    assert union.masked_text == "¡Hola! 😀🎉 Señora [NAME_1], ¿me ayudas? ✓"
    assert mapping == {"[NAME_1]": "Ñandú Gómez"}


@pytest.mark.parametrize("form", ["NFC", "NFD"])
def test_accents_as_combining_marks_do_not_shift_or_split_a_span(form: str) -> None:
    raw = unicodedata.normalize(form, "hola José Ángel Gómez aquí")
    name = unicodedata.normalize(form, "Ángel Gómez")
    start = raw.index(name)
    # end lands between "o" and its combining accent when the text is NFD
    short = span("NAME", start, start + len(name) - (2 if form == "NFD" else 1))

    union, mapping, _ = run(raw, [short])

    assert union.masked_text == unicodedata.normalize(form, "hola José [NAME_1] aquí")
    assert mapping == {"[NAME_1]": name}
    assert RegexMasker().unmask(union.masked_text, mapping) == raw


def test_a_placeholder_shaped_text_the_customer_typed_fails_closed() -> None:
    """The alignment cannot tell the typed text from the stored placeholder."""
    masker = RegexMasker()
    raw = "[NAME_1] y Pedro"
    state = {"[NAME_1]": "Ana"}

    with pytest.raises(MaskingError):
        union_mask(
            masker, raw, raw, state, {"[NAME_1]"}, [span_of("NAME", raw, "Pedro")]
        )
    assert state == {"[NAME_1]": "Ana"}


class _UnsafeMasker(RegexMasker):
    def verify_safe(self, text: str) -> bool:
        return False


class _LossyMasker(RegexMasker):
    def unmask(self, text: str, mapping: dict[str, str]) -> str:
        return text


@pytest.mark.parametrize("masker_type", [_UnsafeMasker, _LossyMasker])
def test_a_result_that_is_not_safe_or_not_faithful_is_refused(
    masker_type: type[Masker],
) -> None:
    raw = "hola Carlos"
    with pytest.raises(MaskingError):
        union_mask(masker_type(), raw, raw, {}, set(), [span("NAME", 5, 11)])


# ------------------------------------------------------------ random invariants

_WORDS = ["kor", "mel", "tav", "ni", "zu", "qe", "Ana", "Óscar", "ñu"]
_TOKENS = ["NAME", "DOC", "PHONE", "EMAIL", "DATE", "CARD", "OTP"]


def _random_case(
    rng: random.Random,
) -> tuple[str, str, dict[str, str], list[PiiSpan], list[tuple[int, int]]]:
    """A raw text, a hand-made regex baseline over it, and random encoder spans."""
    words = [rng.choice(_WORDS) for _ in range(rng.randint(3, 12))]
    raw = ""
    word_ranges: list[tuple[int, int]] = []
    for word in words:
        if raw:
            raw += rng.choice([" ", " ", ",", " - "])
        word_ranges.append((len(raw), len(raw) + len(word)))
        raw += word

    mapping: dict[str, str] = {}
    counters = dict.fromkeys(_TOKENS, 0)
    pieces: list[str] = []
    cursor = 0
    baseline_ranges: list[tuple[int, int]] = []
    for start, end in word_ranges:
        if start < cursor or rng.random() > 0.35:
            continue
        kind = rng.choice(_TOKENS)
        counters[kind] += 1
        token = f"[{kind}_{counters[kind]}]"
        mapping[token] = raw[start:end]
        pieces.append(raw[cursor:start])
        pieces.append(token)
        cursor = end
        baseline_ranges.append((start, end))
    pieces.append(raw[cursor:])

    spans: list[PiiSpan] = []
    for _ in range(rng.randint(1, 4)):
        start = rng.randint(0, len(raw) + 3)
        end = start + rng.randint(0, 14)
        spans.append(span(rng.choice(_TOKENS), start, end))
    return raw, "".join(pieces), mapping, spans, baseline_ranges


def _masked_positions(masked: str, mapping: dict[str, str], length: int) -> set[int]:
    """Raw-text positions hidden behind a placeholder of `masked`."""
    hidden: set[int] = set()
    raw_pos = 0
    cursor = 0
    for match in PLACEHOLDER_RE.finditer(masked):
        raw_pos += match.start() - cursor
        value = mapping[match.group(0)]
        hidden.update(range(raw_pos, raw_pos + len(value)))
        raw_pos += len(value)
        cursor = match.end()
    assert raw_pos + len(masked) - cursor == length
    return hidden


def test_random_spans_never_unmask_anything_and_always_round_trip() -> None:
    rng = random.Random(20260929)
    masker = RegexMasker()
    for _ in range(400):
        raw, masked, mapping, spans, baseline_ranges = _random_case(rng)
        before = set(mapping)
        state = dict(mapping)

        union = union_mask(masker, raw, masked, state, before, spans)

        # nothing is lost or invented: rehydrating gives back the typed text
        assert masker.unmask(union.masked_text, state) == raw
        hidden = _masked_positions(union.masked_text, state, len(raw))
        # every character the regexes hid is still hidden
        for start, end in baseline_ranges:
            assert set(range(start, end)) <= hidden
        # every character an encoder span names is hidden too
        for s in spans:
            stripped = raw[s.start : s.end].strip()
            if stripped:
                first = s.start + raw[s.start : s.end].index(stripped[0])
                assert set(range(first, first + len(stripped))) <= hidden
        # earlier turns' placeholders survive, with their values
        assert all(state[token] == mapping[token] for token in before)
        # deterministic
        again = union_mask(masker, raw, masked, dict(mapping), before, spans)
        assert again == union


_REAL_TURNS = [
    "Hola, mi correo es ana.perez@bank.com y mi tarjeta 4532 1234 5678 9012",
    "Me llamo Carlos Andrés Gómez, cédula 1020304050, nací el 4 de marzo de 1988",
    "Meu CPF é 123.456.789-01, nasci em 4 de março de 1988, +55 11 91234-5678",
    "My name is John Doe, born on March 4, 1988. Call me at +1 415 555 0132",
    "El código de verificación es 654321 y soy Sra. Ñandú Pérez",
    "cobro de $1,988.00 en mayo, terminada en 1234, hoy 12/09/2026",
    "hola, María José Rodríguez aquí; 300 123 4567; ID: AB1234567",
    "😀 Señor Óscar Núñez, DNI 12.345.678, mi email: o.nunez@x.org, código 8842",
    "4 de marzo de 1988 y 14 de marzo de 1988 y 5 mar 1990",
    "Nada sensible aquí, solo perdí mi tarjeta ayer",
]


def test_random_spans_over_the_real_regex_masking_never_unmask_anything() -> None:
    """Same invariants, with the regexes' own output as the baseline."""
    rng = random.Random(29092026)
    masker = RegexMasker()
    for _ in range(600):
        raw = rng.choice(_REAL_TURNS)
        earlier = {"[NAME_1]": "Luis", "[DOC_1]": "999888777"}
        if rng.random() > 0.3:
            earlier = {}
        baseline = masker.mask(raw, state=dict(earlier))
        mapping = {**earlier, **baseline.mapping}
        spans = []
        for _ in range(rng.randint(1, 4)):
            start = rng.randint(0, len(raw) + 2)
            spans.append(span(rng.choice(_TOKENS), start, start + rng.randint(0, 25)))

        state = dict(mapping)
        union = union_mask(
            masker, raw, baseline.masked_text, state, set(earlier), spans
        )

        assert masker.unmask(union.masked_text, state) == raw
        assert masker.verify_safe(union.masked_text)
        before = _masked_positions(baseline.masked_text, mapping, len(raw))
        after = _masked_positions(union.masked_text, state, len(raw))
        assert before <= after
        assert all(state[token] == mapping[token] for token in earlier)
        for s in spans:
            named = raw[s.start : s.end].strip()
            if named:
                first = s.start + raw[s.start : s.end].index(named[0])
                assert set(range(first, first + len(named))) <= after
