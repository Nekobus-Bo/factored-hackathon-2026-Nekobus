"""Mine real customer text into style cards and a phrase bank (local only; nothing leaves the machine).

mask personal data → split into sentences → keep sentences that pass a safety filter → tag a theme
per sentence → rank distinctive terms per theme (log-odds with an informative Dirichlet prior,
Monroe et al. 2008) → measure register → write one style card per company half. Half A feeds
train and validation; half B feeds the test. Where a second country of the same language is
configured, the card also lists the words that set this country apart (the same log-odds, one
country against the other), and how its customers type (tools/synthdata_regional/register.py).

Usage: python -m tools.synthdata_regional.mine --locale es-MX
"""

import argparse
from pathlib import Path

import polars as pl
import yaml

from tools.synthdata_regional import register
from tools.synthdata_regional.locales import LOCALES, Locale, get_locale

MIN_WORDS, MAX_WORDS = 4, 25  # sentence length kept in the phrase bank
MAX_MASKS = 1  # sentences with more masked spans are dropped
TOP_TERMS = 25  # distinctive terms per theme in each style card
MIN_TERM_COUNT = 5  # a term must appear this often in a theme to be ranked
TOP_REGIONAL, MIN_REGIONAL_COUNT, MIN_REGIONAL_RATIO = 40, 15, 8


def load_source(loc: Locale, raw_file: Path | None = None) -> pl.DataFrame:
    """Real customer texts with a company half: A → train/validation, B → test."""
    texts = pl.read_parquet(raw_file or loc.raw_file, columns=["company", "source", "ask"]).filter(
        pl.col("source") == loc.raw_source).drop("source")
    if loc.dedup_raw:
        texts = texts.unique(subset="ask", keep="first", maintain_order=True)
    texts = texts.with_row_index("complaint_id")
    # Alternating by size so both halves are balanced
    order = texts.group_by("company").len().sort(["len", "company"], descending=[True, False])["company"].to_list()
    half = {c: "A" if i % 2 == 0 else "B" for i, c in enumerate(order)}
    return texts.with_columns(half=pl.col("company").replace_strict(half))


def mask(loc: Locale, column: str = "ask") -> pl.Expr:
    """Regex masks, in order, before anything else touches the text (AGENTS.md rule 5). Best effort."""
    expr = pl.col(column)
    for pattern, replacement in loc.masks:
        expr = expr.str.replace_all(pattern, replacement)
    return expr


def safe_sentences(loc: Locale, texts: pl.DataFrame) -> pl.DataFrame:
    sentences = (
        texts.with_columns(masked=mask(loc))
        .select("complaint_id", "company", "half", pl.col("masked").str.extract_all(r"[^.!?;\n]+[.!?]*").alias("sentence"))
        .explode("sentence", empty_as_null=True).with_columns(pl.col("sentence").str.strip_chars())
        .with_columns(words=pl.col("sentence").str.count_matches(r"\S+"))
        .filter(pl.col("words").is_between(MIN_WORDS, MAX_WORDS))
    )
    # Safety filter: only these sentences may later be shown to an LLM. A capitalised word that is
    # not a known brand, month or weekday may be a name, so the sentence is dropped.
    caps = pl.col("sentence").str.extract_all(r"\s(\p{Lu}\p{Ll}+)").list.eval(pl.element().str.strip_chars().str.to_lowercase())
    checked = sentences.with_columns(
        masks=pl.col("sentence").str.count_matches(rf"\[({loc.mask_labels})\]"),
        unknown_caps=caps.list.eval(pl.element().filter(~pl.element().is_in(list(loc.allowed_caps)))).list.len(),
    )
    ok = (~pl.col("sentence").str.contains(rf"\d{{4,}}|\[({loc.drop_if_masked})\]")) & (pl.col("masks") <= MAX_MASKS) & (pl.col("unknown_caps") == 0)
    return checked.filter(ok).drop("unknown_caps")


def tag(loc: Locale, safe: pl.DataFrame) -> pl.DataFrame:
    theme = pl.lit(None, dtype=pl.String)
    for name, rx in reversed(loc.themes.items()):  # first match wins
        theme = pl.when(pl.col("sentence").str.to_lowercase().str.contains(rx)).then(pl.lit(name)).otherwise(theme)
    intent_of = {t: i for i, ts in loc.intent_themes.items() for t in ts}
    return safe.with_columns(theme=theme).with_columns(intent=pl.col("theme").replace_strict(intent_of, default=None))


def _terms(loc: Locale, frame: pl.DataFrame, text: str, group: list[str]) -> pl.DataFrame:
    tokens = frame.select(*group, pl.col(text).str.to_lowercase().str.extract_all(rf"[{loc.word_class}]{{2,}}").alias("w"))
    bigrams = tokens.with_columns(pl.col("w").list.eval(pl.concat_str([pl.element(), pl.element().shift(-1)], separator=" ").drop_nulls()))
    return pl.concat([tokens, bigrams]).explode("w", empty_as_null=True).drop_nulls().filter(
        ~pl.col("w").str.split(" ").list.eval(pl.element().is_in(list(loc.stopwords))).list.all())


def _log_odds(counts: pl.DataFrame, outer: list[str], inner: str) -> pl.DataFrame:
    """z-scores of each term in its `inner` group against the rest of its `outer` group."""
    n = counts.with_columns(n_all=pl.col("n").sum().over(*outer, "w"), n_theme=pl.col("n").sum().over(*outer, inner),
                            N=pl.col("n").sum().over(*outer) if outer else pl.col("n").sum())
    n = n.with_columns(prior=0.01 * pl.col("n_all"), rest=pl.col("n_all") - pl.col("n"), rest_total=pl.col("N") - pl.col("n_theme"))
    return n.with_columns(z=(
        ((pl.col("n") + pl.col("prior")) / (pl.col("n_theme") - pl.col("n"))).log()
        - ((pl.col("rest") + pl.col("prior")) / (pl.col("rest_total") - pl.col("rest"))).log()
    ) / (1 / (pl.col("n") + pl.col("prior")) + 1 / (pl.col("rest") + pl.col("prior"))).sqrt())


def theme_terms(loc: Locale, tagged: pl.DataFrame) -> pl.DataFrame:
    """Distinctive terms per theme and half."""
    terms = _terms(loc, tagged.filter(pl.col("theme").is_not_null()), "sentence", ["half", "theme"])
    return _log_odds(terms.group_by("half", "theme", "w").len("n"), ["half"], "theme").filter(
        pl.col("n") >= MIN_TERM_COUNT).sort(["z", "w"], descending=[True, False]).group_by("half", "theme", maintain_order=True).head(TOP_TERMS)


def regional_terms(loc: Locale, texts: pl.DataFrame) -> list[str]:
    """Words and bigrams that set this country's customers apart from the other country's."""
    other = load_source(loc, loc.contrast_raw_file)
    both = pl.concat([texts.select("ask", country=pl.lit("own")), other.select("ask", country=pl.lit("other"))]).with_columns(masked=mask(loc))
    terms = _terms(loc, both, "masked", ["country"]).filter(
        ~pl.col("w").str.split(" ").list.eval(pl.element().is_in(list(loc.allowed_caps))).list.any())
    scored = _log_odds(terms.group_by("country", "w").len("n"), [], "country")
    # Log-odds alone favours frequent topic words that are only somewhat more common here (the two
    # corpora complain about different app features); a variety word must also be rare over there
    rate = scored.with_columns(rate=pl.col("n") / pl.col("n_theme"),
                               other_rate=(pl.col("rest") + 1) / pl.col("rest_total"))
    return rate.filter((pl.col("country") == "own") & (pl.col("n") >= MIN_REGIONAL_COUNT)
                       & (pl.col("rate") >= MIN_REGIONAL_RATIO * pl.col("other_rate"))).sort(
        ["z", "w"], descending=[True, False]).head(TOP_REGIONAL)["w"].to_list()


def register_stats(loc: Locale, texts: pl.DataFrame) -> dict[str, dict]:
    """Register per half on whole texts; only shapes and shares are kept, never values."""
    low = texts.with_columns(t=pl.col("ask").str.to_lowercase())
    wc = loc.word_class
    stats = {}
    for (half,), d in low.group_by("half", maintain_order=True):
        words = d["t"].str.extract_all(rf"[{wc}]+")
        stats[half] = {
            "openers": d["t"].str.extract(rf"^\W*((?:[{wc}]+[ ,]+){{2}}[{wc}]+)").str.replace_all(r"[ ,]+", " ").value_counts().drop_nulls().sort(["count", "t"], descending=[True, False]).head(20)["t"].to_list(),
            "informal_spelling_share": {w: round(float(words.list.contains(w).mean()), 4) for w in loc.informal},
            "money_formats": d["t"].str.extract_all(loc.money_rx).explode(empty_as_null=True).drop_nulls().str.replace_all(r"\d", "9").value_counts().sort(["count", "t"], descending=[True, False]).head(8)["t"].to_list(),
            "date_formats": d["t"].str.extract_all(loc.date_rx).explode(empty_as_null=True).drop_nulls().str.replace_all(r"\d", "9").value_counts().sort(["count", "t"], descending=[True, False]).head(8)["t"].to_list(),
            "all_caps_share": round(float(d["ask"].str.contains(r"\b[A-ZÀ-Ú]{4,}(?:\s+[A-ZÀ-Ú]{4,}){3,}").mean()), 4),
            loc.no_accent_key: round(float(d["t"].str.contains(loc.no_accent_rx).mean()), 4),
        }
        if loc.bad_source:
            stats[half]["typing"] = register.profile(d["ask"].to_list(), loc)
    return stats


def mine(loc: Locale, out_dir: Path) -> pl.DataFrame:
    texts = load_source(loc)
    tagged = tag(loc, safe_sentences(loc, texts))
    terms = theme_terms(loc, tagged)
    reg = register_stats(loc, texts)
    regional = regional_terms(loc, texts) if loc.contrast_raw_file is not None else None

    out_dir.mkdir(parents=True, exist_ok=True)
    phrase_bank = tagged.filter(pl.col("theme").is_not_null()).select("complaint_id", "company", "half", "theme", "intent", "sentence", "words")
    phrase_bank.write_parquet(out_dir / "phrase_bank.parquet")
    for half in ("A", "B"):
        t, p = terms.filter(pl.col("half") == half), phrase_bank.filter(pl.col("half") == half)
        card = {"half": half, "companies": sorted(texts.filter(pl.col("half") == half)["company"].unique().to_list()),
                "register": reg[half], "service_expressions": t.filter(pl.col("theme") == "oos_service")["w"].to_list(),
                "intents": {i: {"themes": ts, "sentences": p.filter(pl.col("theme").is_in(ts)).height,
                                "terms": {th: t.filter(pl.col("theme") == th)["w"].to_list() for th in ts}}
                            for i, ts in loc.intent_themes.items()}}
        if regional is not None:
            card["regional_terms"] = regional
        (out_dir / f"style_cards.{half}.yaml").write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False))
    return phrase_bank


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locale", required=True, choices=list(LOCALES))
    parser.add_argument("--out-dir", type=Path, help="defaults to the locale's staging directory")
    args = parser.parse_args()
    loc = get_locale(args.locale)
    out_dir = args.out_dir or loc.out_dir
    bank = mine(loc, out_dir)
    counts = bank.group_by("intent", "half").len().pivot("half", index="intent", values="len").fill_null(0).sort("A", descending=True)
    with pl.Config(tbl_rows=30):
        print(f"Wrote {out_dir}/phrase_bank.parquet ({bank.height} sentences) and style_cards.{{A,B}}.yaml\n{counts}")


if __name__ == "__main__":
    main()
