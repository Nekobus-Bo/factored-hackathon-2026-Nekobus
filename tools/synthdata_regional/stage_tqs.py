"""Stage tuquejasuma.com complaint threads as es-CO mining sources (local only; nothing leaves the machine).

Reads data/raw/apple_store_reviews/snapshot_<cc>_1000/tqs_<cc>_dataset.parquet and writes, in
data/staging/complaints/:

- complaints_co.parquet: consumer turns (opening complaints and consumer comments) of Colombian banks;
- complaints_mx_tqs.parquet: the same for Mexican banks, the contrast country for es-CO's regional terms
  (same site, genre and sector; the Argentine snapshot has no banks);
- complaints_co_sample_150.parquet: the real-world check set, drawn from company half B only, so it never
  overlaps the half-A text that mining shows the LLM. Same columns and draw as the MX and AR samples
  (lab/complaints-labeling-notes.md).

Cleaning: the site's vote counter ("2 ¡Sumados!", sometimes after the company name) is removed, HTML
entities are unescaped, and names typed in lowercase after "soy", "me llamo", "mi nombre", "asesora"…
become the site's own [nombre] mask, which the capitalised-name masks of mining would miss. Mining
masks the rest (locales.py). The `author` column is never read.

Usage: python -m tools.synthdata_regional.stage_tqs
"""

import argparse
import html
import re
from pathlib import Path

import polars as pl

from tools.synthdata_regional.locales import REPO, get_locale
from tools.synthdata_regional.mine import load_source, mask

RAW_DIR = REPO / "data" / "raw" / "apple_store_reviews"
OUT_DIR = REPO / "data" / "staging" / "complaints"
SOURCE = "tqs_thread"
BANKS = {"co": r"^banc|davivienda|daviplata", "mx": r"^banc|banamex|bbva|azteca"}
OUTPUTS = {"co": "complaints_co.parquet", "mx": "complaints_mx_tqs.parquet"}
SAMPLE_FILE = "complaints_co_sample_150.parquet"
SAMPLE_SIZE, SAMPLE_THEMED, PER_THEME, MAX_SAMPLE_WORDS, SEED = 150, 60, 6, 120, 11
MIN_WORDS = 3

COUNTER = re.compile(r"^[^\n]{0,60}?\b\d+ ¡Sumados?!\s*")
NAME_INTRO = re.compile(r"(?i)\b(soy|me llamo|mi nombre es|mi nombre|asesora?|ejecutiva?|funcionaria?|operadora?|señora?|sra?\.?)\s+")
NAME_TOKEN = re.compile(r"[^\W\d_]+")
# A word right after the introducer that shows it is not a name; any other word starts a masked run
NOT_A_NAME = set("""a al el la los las lo un una de del en y o que se me mi no ni yo es muy ya con por para su
    sus le les nos cliente clienta usuario usuaria titular persona personas joven mayor estafador víctima victima
    madre padre mamá papá estudiante pensionado pensionada afiliado afiliada propietario propietaria comerciante
    independiente cuentahabiente venezolano venezolana colombiano colombiana extranjero extranjera asesor asesora
    nuevo nueva quien aparece y""".split())
STOP_RUN = NOT_A_NAME | set("""tengo tiene tenía fui fue me dijo dice dijeron informó indicó aparece pertenece""".split())
MAX_NAME_TOKENS = 4


def scrub_names(text: str) -> str:
    """Replace up to MAX_NAME_TOKENS words after a self-introduction or a staff title with [nombre]."""
    out, pos = [], 0
    for intro in NAME_INTRO.finditer(text):
        if intro.start() < pos:
            continue
        end = cursor = intro.end()
        n = 0
        while n < MAX_NAME_TOKENS:
            token = NAME_TOKEN.match(text, cursor)
            if not token or token.group(0).lower() in (NOT_A_NAME if n == 0 else STOP_RUN):
                break
            end, n = token.end(), n + 1
            gap = re.match(r"[ \t]+", text[end:])  # a name continues across spaces only, never punctuation
            if not gap:
                break
            cursor = end + gap.end()
        if n:
            out += [text[pos:intro.end()], "[nombre]"]
            pos = end
    return "".join(out) + text[pos:]


def clean(text: str) -> str:
    return scrub_names(COUNTER.sub("", html.unescape(text))).strip()


def consumer_turns(country: str, raw_dir: Path = RAW_DIR) -> pl.DataFrame:
    path = raw_dir / f"snapshot_{country}_1000" / f"tqs_{country}_dataset.parquet"
    if not path.is_file():
        raise SystemExit(f"{path} is missing: unzip snapshot_{country}_1000.zip into {raw_dir}")
    turns = pl.read_parquet(path, columns=["thread_id", "turn", "role", "text", "company_name"]).filter(
        pl.col("company_name").str.to_lowercase().str.contains(BANKS[country]), pl.col("role") == "consumer")
    return turns.select(
        pl.col("company_name").alias("company"), pl.lit(SOURCE).alias("source"),
        pl.col("text").map_elements(clean, return_dtype=pl.String).alias("ask"), "thread_id", "turn",
    ).filter(pl.col("ask").str.count_matches(r"\S+") >= MIN_WORDS).sort("thread_id", "turn")


def sample(out_dir: Path) -> pl.DataFrame:
    """150 half-B texts: up to PER_THEME per in-scope theme (SAMPLE_THEMED in all), the rest random."""
    loc = get_locale("es-CO")
    texts = load_source(loc, out_dir / OUTPUTS["co"]).filter(pl.col("half") == "B").with_columns(masked=mask(loc)).filter(
        pl.col("ask").str.count_matches(r"\S+") <= MAX_SAMPLE_WORDS)
    theme = pl.lit(None, dtype=pl.String)
    for name, rx in reversed(loc.themes.items()):  # first match wins, as in mining
        theme = pl.when(pl.col("masked").str.to_lowercase().str.contains(rx)).then(pl.lit(name)).otherwise(theme)
    texts = texts.with_columns(theme=theme)
    themed = texts.filter(pl.col("theme").is_not_null() & ~pl.col("theme").str.starts_with("oos_")).sample(
        fraction=1.0, shuffle=True, seed=SEED).group_by("theme", maintain_order=True).head(PER_THEME).head(SAMPLE_THEMED)
    rest = texts.join(themed.select("complaint_id"), on="complaint_id", how="anti")
    drawn = pl.concat([themed.select(texts.columns).with_columns(stratum=pl.lit("theme")),
                       rest.sample(min(SAMPLE_SIZE - themed.height, rest.height), seed=SEED).with_columns(stratum=pl.lit("random"))])
    return drawn.sort("complaint_id").with_row_index("id").select(
        "id", "company", "half", "stratum", "theme", pl.col("ask").alias("original"), "masked")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for country, name in OUTPUTS.items():
        frame = consumer_turns(country, args.raw_dir)
        frame.write_parquet(args.out_dir / name)
        print(f"{name}: {frame.height} texts from {frame['company'].n_unique()} banks")
    drawn = sample(args.out_dir)
    drawn.write_parquet(args.out_dir / SAMPLE_FILE)
    print(f"{SAMPLE_FILE}: {drawn.height} half-B texts {dict(drawn.group_by('stratum').len().iter_rows())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
