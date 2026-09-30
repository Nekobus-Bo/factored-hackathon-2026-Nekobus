"""How a set of messages is typed: length spread, casing, punctuation, accents, abbreviations, slang.

Computed the same way for real reviews, for the rejected LLM rows and for a generated dataset,
so the checks can ask whether the dataset looks more like real customers than like the rejects.
"""

import polars as pl

from tools.synthdata_regional.locales import Locale

# Share features compared between datasets (means of per-message booleans)
SHARE_FEATURES = ["lowercase_start", "no_final_punct", "missing_accent", "abbreviation", "emoji",
                  "repeated_punct", "shouting", "slang"]
_REQUEST = (r"(?i)(ayud|resuelv|soluci|revis|devuelv|indiq|expliq|inform|arregl|necesito|quiero|pueden|podr[ií]an|"
            r"agradecer|chequ|fij|avis|den de baja|mand|reembols|devolu|reintegr|por favor|porfa|x favor)")


def _word_rx(words: list[str]) -> str:
    return r"(?i)\b(" + "|".join(sorted(words, key=len, reverse=True)) + r")\b" if words else r"$^"


def per_message(texts: list[str], loc: Locale) -> pl.DataFrame:
    t = pl.col("text")
    return pl.DataFrame({"text": texts}, schema={"text": pl.String}).with_columns(
        words=t.str.count_matches(r"\S+"),
        lowercase_start=t.str.contains(r"^\W*\p{Ll}"),
        no_final_punct=~t.str.contains(r"[.!?…)]\s*$"),
        missing_accent=t.str.to_lowercase().str.contains(loc.no_accent_rx),
        abbreviation=t.str.contains(_word_rx(loc.informal)),
        emoji=t.str.contains(r"[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]"),
        repeated_punct=t.str.contains(r"[!?]{2,}"),
        shouting=t.str.contains(r"\b\p{Lu}{3,}\s+\p{Lu}{3,}\b"),
        slang=t.str.contains(_word_rx(loc.slang)),
        ends_request=t.str.extract(r"([^.!?\n]+)[.!?\s]*$").fill_null("").str.contains(_REQUEST),
    )


def profile(texts: list[str], loc: Locale) -> dict[str, float]:
    """Summary of a set of messages: length spread plus the mean of every share feature."""
    m = per_message(texts, loc)
    words = m["words"].cast(pl.Float64)
    out = {"messages": float(m.height), "median_words": float(words.median()),
           "words_cv": round(float(words.std() / words.mean()), 3)}
    out.update({f: round(float(m[f].mean()), 4) for f in SHARE_FEATURES + ["ends_request"]})
    return out


def slang_shares(texts: list[str], loc: Locale) -> dict[str, float]:
    """Share of messages containing each slang term, most frequent first."""
    low = pl.Series(texts, dtype=pl.String).str.to_lowercase()
    shares = {w: round(float(low.str.contains(rf"\b{w}\b").mean()), 4) for w in loc.slang}
    return dict(sorted(shares.items(), key=lambda kv: -kv[1]))


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    """L1 distance over the share features."""
    return round(sum(abs(a[f] - b[f]) for f in SHARE_FEATURES), 4)
