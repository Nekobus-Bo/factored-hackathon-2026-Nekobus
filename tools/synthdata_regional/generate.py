"""Generate a locale's train and validation splits with an LLM guided by the half-A style cards.

plan the calls (intent × length × persona, plus topic for out_of_scope) → ask the LLM for messages
with `{slot}` placeholders → fill them locally with fictitious values → drop duplicates,
near-duplicates, source leaks and stray PII → split into train and validation.

Privacy (AGENTS.md rule 5): only half-A style cards (aggregated terms and shares), at most
N_PHRASES masked, safety-filtered sentences per call and, for es, a few rejected synthetic rows
(no real customer text) reach the provider. Every call is cached on disk by model and prompt, so
reruns are reproducible and free. Rows are LLM-generated and not reviewed by a human.

Usage: python -m tools.synthdata_regional.generate --locale es-MX --mode pilot|full
Environment: SYNTH_LLM_MODEL (default openai/gpt-6.1-sol), LLM_API_KEY, LLM_BASE_URL (or .env).
"""

import argparse
import hashlib
import json
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl
import yaml

from tools.synthdata_regional.checks import check_pii, source_texts
from tools.synthdata_regional.fill import fill, placeholder_problem
from tools.synthdata_regional.locales import LENGTH_RULES, LOCALES, PLACEHOLDERS, REPO, SHORT_ONLY, Locale, get_locale

SCHEMA_PATH = REPO / "data" / "eval" / "synthetic" / "schema.yaml"
CACHE_DIR = REPO / "lab" / ".cache" / "llm"  # shared with the lab notebooks, so their calls are reused
ENV_FILE = REPO / ".env"
PROMPT_VERSION = "v1"
TARGET = {"train": 100, "validation": 50}  # rows per intent kept in full mode
PILOT_PER_INTENT = 10
OVERGENERATE = 1.4  # extra rows asked for, to survive the filters
BATCH = 20  # messages per call
LONG_SHARE = 0.375  # for intents that can be long; overall this gives about 25% long rows
N_PHRASES = 5  # masked real phrases shown per call
N_ANTI = 3  # rejected synthetic rows shown per call as what not to write
NEAR_DUP = 0.85  # stricter than the 0.9 gate in checks.py, whose IDF is fitted on other rows
LEAK_NGRAM = 8
SEED = 7
WORKERS = 8


def _llm_settings() -> tuple[str, str, str | None]:
    dotenv = dict(line.split("=", 1) for line in (ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else [])
                  if "=" in line and not line.startswith("#"))
    model = os.environ.get("SYNTH_LLM_MODEL", "openai/gpt-6.1-sol")
    api_key = os.environ.get("LLM_API_KEY") or dotenv.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL") or dotenv.get("LLM_BASE_URL", "").strip()
    return model, api_key, base_url if "://" in base_url else None


def ask(prompt: str, model: str, api_key: str, base_url: str | None) -> dict:
    """One cached LLM call. Returns the stored record: model, prompt, text, tokens."""
    key = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    if not api_key:
        raise SystemExit("Set LLM_API_KEY in the environment or .env (the call is not cached yet).")
    import litellm

    response = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}], api_key=api_key, base_url=base_url)
    record = {"model": model, "prompt": prompt, "text": response.choices[0].message.content,
              "tokens": response.usage.prompt_tokens + response.usage.completion_tokens}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False))
    return record


def parse(text: str) -> dict:
    try:
        return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except json.JSONDecodeError:
        return {"raw": text}


def plan_calls(loc: Locale, intents: list[str], mode: str) -> pl.DataFrame:
    """One row per LLM call: which intent, length, persona and (for out_of_scope) topic."""
    per_intent = PILOT_PER_INTENT if mode == "pilot" else round(sum(TARGET.values()) * OVERGENERATE)
    batch = 5 if mode == "pilot" else BATCH
    calls = []
    for intent in intents:
        n_long = 0 if intent in SHORT_ONLY else round(per_intent * LONG_SHARE)
        for length, n in (("short", per_intent - n_long), ("long", n_long)):
            for k in range(0, n, batch):
                i = len(calls)
                calls.append({"call": i, "intent": intent, "length": length, "n": min(batch, n - k),
                              "persona": loc.personas[i % len(loc.personas)],
                              "topic": loc.oos_rotation[k // batch % len(loc.oos_rotation)] if intent == "out_of_scope" else ""})
    return pl.DataFrame(calls)


def _typing(card: dict) -> str:
    t = card["register"].get("typing")
    if not t:
        return ""
    return (f"about {t['no_final_punct']:.0%} of messages have no final punctuation, {t['missing_accent']:.0%} skip accents "
            f"(aplicacion, tambien), {t['abbreviation']:.0%} use abbreviations, {t['repeated_punct']:.0%} use '!!' or '??', "
            f"{t['emoji']:.0%} use an emoji, {t['shouting']:.0%} shout in CAPITALS, {t['lowercase_start']:.0%} start in lowercase, "
            f"and only {t['slang']:.1%} use any slang")


def build_prompts(loc: Locale, calls: pl.DataFrame, card: dict, phrases: pl.DataFrame, definitions: dict[str, str],
                  rejected: list[str]) -> list[str]:
    reg = card["register"]
    informal = ", ".join(w for w, s in sorted(reg["informal_spelling_share"].items(), key=lambda x: -x[1])[:10])
    prompts = []
    for c in calls.iter_rows(named=True):
        intent, themes = c["intent"], card["intents"][c["intent"]]["themes"]
        if c["topic"] and c["topic"] != "general":
            themes = [c["topic"]]
        terms = [t for th in themes for t in card["intents"]["out_of_scope" if th.startswith("oos_") else intent]["terms"].get(th, [])]
        pool = phrases.filter(pl.col("theme").is_in(themes))
        sample = pool.sample(min(N_PHRASES, pool.height), seed=SEED + c["call"])["sentence"].to_list() if pool.height else []
        allowed, required = PLACEHOLDERS.get(intent, ([], False))
        slots = (f"when a message mentions one of these, write the placeholder instead of a value: {', '.join('{' + s + '}' for s in allowed)}. "
                 + ("Every message must contain at least one of them." if required else "Use them in about half of the messages.")) if allowed else "this intent has no slots; do not use any placeholder or curly braces."
        anti = random.Random(f"{SEED}-{c['call']}").sample(rejected, min(N_ANTI, len(rejected))) if rejected else []
        # str.format ignores fields a prompt does not use, so the pt-BR prompt stays byte-identical
        prompts.append(loc.prompt.format(
            intent=intent, definition=definitions[intent], boundary=loc.boundaries[intent],
            topic=f"Topic for this batch: {loc.oos_topics[c['topic']]}" if c["topic"] else "",
            length=loc.long_rules[c["call"] % len(loc.long_rules)] if c["length"] == "long" and loc.long_rules else LENGTH_RULES[c["length"]],
            persona=c["persona"],
            terms=", ".join(terms[:20]) or "(none mined; rely on the register below)",
            phrases="\n".join(f"  · {s}" for s in sample) or "  (none)",
            openers=", ".join(reg["openers"][:10]), informal=informal,
            money=", ".join(reg["money_formats"][:4]), dates=", ".join(reg["date_formats"][:5]),
            slots=slots, n=c["n"], call_id=f"{c['call']}-{intent}-{c['length']}",
            variety_rule=loc.variety_rule, bank_country=loc.bank_country, people=loc.people,
            account_numbers=loc.account_numbers, regional=", ".join(card.get("regional_terms", [])[:25]),
            register=_typing(card), anti_examples="\n".join(f"  ✗ {a}" for a in anti)))
    return prompts


def fill_rows(loc: Locale, raw: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Placeholders → fictitious values with exact offsets."""
    filled, rejected = [], []
    for row in raw.iter_rows(named=True):
        reason = placeholder_problem(row["template"].strip(), row["intent"])
        if reason:
            rejected.append({**row, "reason": reason})
            continue
        text, slots = fill(loc, row["template"], row["intent"], random.Random(f"{SEED}-{row['call']}-{row['template']}"))
        filled.append({**row, "text": text, "slots": slots})
    return pl.DataFrame(filled), pl.DataFrame(rejected) if rejected else pl.DataFrame(schema={"reason": pl.String})


def dedup(filled: pl.DataFrame) -> pl.DataFrame:
    """Exact and near-duplicates, on both the placeholder text (filled values must not hide repeats)
    and the filled text (what checks.py compares across splits)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    def norm(col: str) -> list[str]:
        return [re.sub(r"\W+", " ", t.lower()).strip() for t in filled[col]]

    by_template = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(norm("template"))
    vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(norm("text"))
    keep, kept = [], []
    for i in range(filled.height):
        dup = bool(kept) and max(float((by_template[kept] @ by_template[i].T).max()),
                                 float((vectors[kept] @ vectors[i].T).max())) >= NEAR_DUP
        keep.append(not dup)
        if not dup:
            kept.append(i)
    return filled.filter(pl.Series(keep))


def drop_leaks(loc: Locale, unique: pl.DataFrame) -> pl.DataFrame:
    """No generated row may share an 8-word run with any source text (both halves)."""
    def words(t: str) -> list[str]:
        return re.findall(r"\w+", t.lower())

    grams: dict[tuple, set[int]] = {}
    for i, t in enumerate(unique["text"]):
        w = words(t)
        for k in range(len(w) - LEAK_NGRAM + 1):
            grams.setdefault(tuple(w[k:k + LEAK_NGRAM]), set()).add(i)
    leaks: set[int] = set()
    for t in source_texts(loc, loc.raw_file, all_sources=loc.leak_all_sources):
        w = words(t)
        for k in range(len(w) - LEAK_NGRAM + 1):
            leaks |= grams.get(tuple(w[k:k + LEAK_NGRAM]), set())
    return unique.filter(~pl.Series(range(unique.height)).is_in(list(leaks)))


def drop_pii(loc: Locale, frame: pl.DataFrame) -> pl.DataFrame:
    """Anything PII-like outside a filled slot drops the row."""
    indexed = frame.with_row_index("_i").with_columns(id=pl.col("_i").cast(pl.String))
    bad = {e.split(":")[0] for e in check_pii(indexed, loc)}
    return indexed.filter(~pl.col("id").is_in(list(bad))).drop("_i", "id")


def drop_foreign(loc: Locale, frame: pl.DataFrame) -> pl.DataFrame:
    """Rows with markers of another variety never enter the dataset (checks.py gates the rate).
    pt-BR predates this filter; applying it there would reshuffle its splits."""
    if loc.code == "pt-BR":
        return frame
    return frame.filter(~pl.col("text").str.contains(loc.foreign_markers))


def split_rows(loc: Locale, clean: pl.DataFrame, mode: str, model: str) -> pl.DataFrame:
    """Split per intent, keeping each intent's short/long mix in both splits."""
    rows = []
    for (intent,), d in clean.sample(fraction=1.0, shuffle=True, seed=SEED).group_by("intent", maintain_order=True):
        splits = {"pilot": d} if mode == "pilot" else {}
        if mode != "pilot":
            long_share = (d["length"] == "long").mean()
            parts = {length: g for (length,), g in d.group_by("length", maintain_order=True)}
            for split, n in TARGET.items():
                n_long = round(n * long_share)
                take = [(length, n_long if length == "long" else n - n_long) for length in parts]
                splits[split] = pl.concat([parts[length].head(k) for length, k in take])
                parts = {length: parts[length].slice(k) for length, k in take}
        for split, g in splits.items():
            for j, r in enumerate(g.iter_rows(named=True)):
                rows.append({"id": f"{loc.id_prefix}_{split}_{intent}_{j:03d}", "text": r["text"], "lang": loc.lang,
                             **({"locale": loc.code} if loc.record_locale else {}), "intent": intent,
                             "slots": r["slots"], "split": split, "source": "synthetic-llm", "generator": model,
                             "prompt_version": PROMPT_VERSION, "length": r["length"], "topic": r["topic"]})
    return pl.DataFrame(rows)


def generate(loc: Locale, mode: str, out_dir: Path) -> pl.DataFrame:
    model, api_key, base_url = _llm_settings()
    card = yaml.safe_load((out_dir / "style_cards.A.yaml").read_text())
    phrases = pl.read_parquet(out_dir / "phrase_bank.parquet").filter(pl.col("half") == "A")
    definitions = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    rejected = []
    if loc.bad_source:
        rejected = pl.read_parquet(loc.raw_file, columns=["source", "ask"]).filter(pl.col("source") == loc.bad_source)["ask"].sort().to_list()

    calls = plan_calls(loc, list(definitions), mode)
    prompts = build_prompts(loc, calls, card, phrases, definitions, rejected)
    with ThreadPoolExecutor(WORKERS) as pool:
        records = list(pool.map(lambda p: ask(p, model, api_key, base_url), prompts))
    raw = []
    for c, record in zip(calls.iter_rows(named=True), records):
        messages = parse(record["text"]).get("messages", [])
        raw += [{**c, "template": m} for m in messages if isinstance(m, str) and m.strip()]
    raw = pl.DataFrame(raw)
    filled, rejected_rows = fill_rows(loc, raw)
    unique = dedup(filled)
    no_leak = drop_leaks(loc, unique)
    clean = drop_foreign(loc, drop_pii(loc, no_leak))
    print(f"calls {calls.height} · tokens {sum(r['tokens'] for r in records):,} · messages {raw.height} · "
          f"placeholder rejects {rejected_rows.height} · after dedup {unique.height} · after leaks {no_leak.height} · "
          f"after PII and foreign markers {clean.height}")
    short = clean.group_by("intent").len().filter(pl.col("len") < (PILOT_PER_INTENT // 2 if mode == "pilot" else sum(TARGET.values())))
    if short.height:
        print(f"WARNING: intents below target:\n{short}")

    dataset = split_rows(loc, clean, mode, model)
    for (split,), g in dataset.group_by("split"):
        (out_dir / f"{loc.stem}.{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in g.to_dicts()))
    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locale", required=True, choices=list(LOCALES))
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--out-dir", type=Path, help="defaults to the locale's staging directory")
    args = parser.parse_args()
    loc = get_locale(args.locale)
    dataset = generate(loc, args.mode, args.out_dir or loc.out_dir)
    print(dataset.group_by("split", "intent").len().pivot("split", index="intent", values="len").sort("intent"))


if __name__ == "__main__":
    main()
