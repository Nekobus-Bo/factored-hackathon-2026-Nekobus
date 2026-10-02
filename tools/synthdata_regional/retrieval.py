"""Generate a locale's kb.search test questions with an LLM guided by the half-B style cards.

For every knowledge-base topic, ask the LLM for customer messages whose best answer is that
topic's snippet, written the way this locale's real customers type (register, regional terms,
masked real phrases from the companies held out of the decision training data). Add messages
the KB does not cover: banking products outside the assistant's scope (gold: the scope snippet)
and off-topic chat (gold: none). Filter duplicates, source leaks, PII, foreign-variety markers
and copies of the gold snippet's wording. Then ask the orchestrator's own LLM, with its real
system prompt and tool schemas, which query it would send to kb_search for each message.

Privacy (AGENTS.md rule 5): only half-B style cards (aggregated terms and shares), at most
N_PHRASES masked, safety-filtered sentences per call and the public KB text reach the provider;
the rewrite step sends each generated message masked by the orchestrator's RegexMasker. Every
call is cached on disk (lab/.cache/llm/), so reruns are reproducible and free. Rows are
LLM-generated and not reviewed by a human: the split is a provisional test.

Usage:
  python -m tools.synthdata_regional.retrieval --locale es-MX   # generate + rewrite one locale
  python -m tools.synthdata_regional.retrieval --pool          # pool the locales and write checks.md
Environment: SYNTH_LLM_MODEL (default openai/gpt-6.1-sol), LLM_MODEL (the orchestrator's model,
used for the rewrite), LLM_REASONING_EFFORT, LLM_API_KEY, LLM_BASE_URL (or .env).
"""

import argparse
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl
import yaml

from tools.synthdata_regional.generate import (
    CACHE_DIR,
    ENV_FILE,
    _llm_settings,
    _typing,
    ask,
    dedup,
    drop_leaks,
    drop_pii,
    parse,
)
from tools.synthdata_regional.locales import LOCALES, REPO, Locale, get_locale

KB_PATH = REPO / "packages" / "retrieval" / "kb" / "snippets.jsonl"
RETRIEVAL_DIR = REPO / "data" / "eval" / "synthetic" / "retrieval"
OUT_DIR = RETRIEVAL_DIR / "regional"
POOLED = RETRIEVAL_DIR / "queries_regional.jsonl"
# The same recipe with two generators: GPT Sol through the API, and Claude Opus 5.5 writing
# by hand in a coding session from the same briefs (`--brief`), read from `written/<locale>.jsonl`.
GENERATORS = {
    "gpt-sol": {"out_dir": OUT_DIR, "pooled": POOLED, "id": "rq", "written": None},
    "claude": {"out_dir": RETRIEVAL_DIR / "regional_claude", "pooled": RETRIEVAL_DIR / "queries_regional_claude.jsonl",
               "id": "rqc", "written": RETRIEVAL_DIR / "regional_claude" / "written", "model": "claude-opus-5-5"},
}
OLD_QUERIES = REPO / "data" / "eval" / "synthetic" / "retrieval" / "queries.jsonl"
PROMPT_VERSION = "retrieval-v1"
SPLIT = "test"
SOURCE = "synthetic"

PER_TOPIC = 3  # kept per KB topic: 2 short and 1 long when the filters leave them
ASK_SHORT, ASK_LONG = 3, 2  # asked per topic call, to survive the filters
NOT_COVERED = 15  # kept per kind of not-covered message
NOT_COVERED_CALLS = 2  # calls per kind, 10 messages each (7 short, 3 long)
N_PHRASES = 5  # masked real phrases shown per call (as generate.py)
COPY_NGRAM = 4  # a message sharing a 4-word run with its gold snippet copies the KB's wording
QUERY_MAX_CHARS = 200  # KbSearchInput.query
SEED = 11
WORKERS = 8
REWRITE_WORKERS, REWRITE_RETRIES = 3, 8  # each rewrite carries the whole tool catalog: stay under the TPM limit
SCOPE_TOPIC = "security_privacy.03"  # "Service scope and out-of-scope operations"

ID_PREFIX = {"es-MX": "mx", "es-AR": "ar", "es-CO": "co", "pt-BR": "br"}
# Real phrases are picked by theme; a KB family borrows the themes of the intents it answers.
FAMILY_THEMES = {
    "card_security": ["card_block", "lost_card", "stolen_card"],
    "fraud_reporting": ["unrecognized_charge", "suspicious_activity"],
    "disputes": ["dispute"],
    "auth_identity": ["otp_code", "identity_data"],
    "support_handoff": ["human_agent"],
    "account_inquiry": ["balance", "recent_transactions"],
    "security_privacy": ["suspicious_activity", "identity_data"],
}
# pt-BR's Locale keeps the first dataset's frozen prompt and leaves these empty.
PT_WORDING = {
    "bank_country": "a Brazilian",
    "people": "Brazilian bank customers",
    "variety_rule": "Write in Brazilian Portuguese as real Brazilians write in a chat, never European Portuguese or Spanish.",
    "account_numbers": "Pix key, agência, conta",
}
OUT_OF_SCOPE_PRODUCTS = (
    "a banking product this chat assistant does not handle: loans or credit, a higher credit limit, "
    "mortgages, insurance, investments, or opening a new account"
)

PROMPT = """You write realistic messages that customers of {bank_country} bank type into the bank's chat assistant. {variety_rule}

{task}

Style evidence mined from real, masked texts written by {people}. They are reviews or complaints, not chats: borrow their words and their way of writing, not the format.
- Words and expressions typical of this topic: {terms}
- Words that set {people} apart from other speakers of the language (use them rarely, only where natural): {regional}
- Real sentences, for vocabulary and tone only; do not copy them and do not reuse their situations literally:
{phrases}
- Common openers: {openers}
- Informal spellings some customers use: {informal}
- Money is written like: {money}. Dates are written like: {dates}.
- How real customers type: {register}
Most real customers write plain, everyday language: at most one message in four may contain a single regional slang word. Let accents, capitals and final punctuation be missing in some messages, following the rates above.
Customer profile for this batch: {persona}

Never write names, document numbers, emails, phone numbers, card or account numbers ({account_numbers}), codes or reference numbers: say {generic} or similar instead.

Write {n_short} short messages (one line, 4 to 25 words, as typed in a chat) and {n_long} longer ones (2 to 4 sentences, 25 to 70 words, with some context). Vary the situation, wording, tone and formality.
Request id: {call_id}
Reply with only a JSON object: {{"short": ["..."], "long": ["..."]}}"""

TASK_IN_SCOPE = """The bank's chat assistant answers this customer with the policy below. The customer has NOT read it; they only know their situation or question.
Policy ({title}): {text}

Write messages whose best answer is exactly this policy, not another one. Describe the situation or ask the question in the customer's own words: do not reuse the policy's distinctive words or phrases, do not name the policy, and do not quote its numbers or rules."""

TASK_OUT_OF_SCOPE = """The customer asks about {topic}. The bank's chat assistant only handles compromised cards, fraud reports, disputes and basic balance or transaction questions, so this is outside its scope, but the customer does not know that.

Write messages asking for that product or service, in the customer's own words."""

TASK_OFF_TOPIC = """The customer writes to the bank's chat assistant about {topic}, with no banking content at all (people do this: small talk, tests, curiosity, the wrong chat).

Write such messages."""


def kb_snippets() -> pl.DataFrame:
    return pl.read_ndjson(KB_PATH)


def theme_terms(card: dict) -> dict[str, list[str]]:
    """Mined log-odds terms per theme, whichever intent they were mined under."""
    terms: dict[str, list[str]] = {}
    for intent in card["intents"].values():
        for theme, words in intent.get("terms", {}).items():
            terms.setdefault(theme, [])
            terms[theme] += [w for w in words if w not in terms[theme]]
    return terms


def wording(loc: Locale) -> dict[str, str]:
    if loc.code == "pt-BR":
        return PT_WORDING
    return {"bank_country": loc.bank_country, "people": loc.people, "variety_rule": loc.variety_rule,
            "account_numbers": loc.account_numbers}


def plan_calls(loc: Locale, kb: pl.DataFrame) -> pl.DataFrame:
    """One row per LLM call: what the messages are about, and the gold snippet ids."""
    calls = []
    for row in kb.filter(pl.col("lang") == loc.lang).sort("topic_id").iter_rows(named=True):
        calls.append({"kind": "in_scope", "topic_id": row["topic_id"], "relevant_ids": [row["id"]],
                      "themes": FAMILY_THEMES[row["topic_id"].split(".")[0]],
                      "task": TASK_IN_SCOPE.format(title=row["title"], text=row["text"]),
                      "n_short": ASK_SHORT, "n_long": ASK_LONG})
    scope_id = f"{SCOPE_TOPIC}.{loc.lang}"
    credit = loc.oos_topics.get("oos_credit", "")
    for _ in range(NOT_COVERED_CALLS):
        calls.append({"kind": "out_of_scope_banking", "topic_id": SCOPE_TOPIC, "relevant_ids": [scope_id],
                      "themes": ["oos_credit"],
                      "task": TASK_OUT_OF_SCOPE.format(topic=f"{OUT_OF_SCOPE_PRODUCTS} (locally: {credit})"),
                      "n_short": 7, "n_long": 3})
        calls.append({"kind": "off_topic", "topic_id": "", "relevant_ids": [],
                      "themes": [], "task": TASK_OFF_TOPIC.format(topic=loc.oos_topics["general"]),
                      "n_short": 7, "n_long": 3})
    for i, c in enumerate(calls):
        c["call"] = i
        c["persona"] = loc.personas[i % len(loc.personas)]
    return pl.DataFrame(calls)


def build_prompts(loc: Locale, calls: pl.DataFrame, card: dict, phrases: pl.DataFrame, round_: int = 0) -> list[str]:
    reg = card["register"]
    informal = ", ".join(w for w, s in sorted(reg["informal_spelling_share"].items(), key=lambda x: -x[1])[:10])
    terms_by_theme = theme_terms(card)
    words = wording(loc)
    prompts = []
    for c in calls.iter_rows(named=True):
        terms = [t for th in c["themes"] for t in terms_by_theme.get(th, [])]
        pool = phrases.filter(pl.col("theme").is_in(c["themes"]))
        sample = pool.sample(min(N_PHRASES, pool.height), seed=SEED + c["call"])["sentence"].to_list() if pool.height else []
        persona = c["persona"] + (f". Retry {round_}: earlier messages were too alike or reused the policy's wording; "
                                  "write clearly different situations in plainer customer words" if round_ else "")
        prompts.append(PROMPT.format(
            task=c["task"], persona=persona,
            terms=", ".join(terms[:20]) or "(none mined; rely on the register below)",
            regional=", ".join(card.get("regional_terms", [])[:25]) or "(none)",
            phrases="\n".join(f"  · {s}" for s in sample) or "  (none)",
            openers=", ".join(reg["openers"][:10]), informal=informal,
            money=", ".join(reg["money_formats"][:4]), dates=", ".join(reg["date_formats"][:5]),
            register=_typing(card) or "(no typing profile mined)",
            generic='"meu cartão", "minha conta"' if loc.lang == "pt" else '"mi tarjeta", "mi cuenta"',
            n_short=c["n_short"], n_long=c["n_long"], call_id=f"{loc.code}-{c['call']}-{c['kind']}-r{round_}",
            **words))
    return prompts


def collect(calls: pl.DataFrame, records: list[dict]) -> list[dict]:
    rows = []
    for c, record in zip(calls.iter_rows(named=True), records, strict=True):
        reply = parse(record["text"])
        for length in ("short", "long"):
            for m in reply.get(length, []) if isinstance(reply.get(length), list) else []:
                if isinstance(m, str) and m.strip():
                    rows.append({**{k: c[k] for k in ("call", "kind", "topic_id", "relevant_ids")},
                                 "length": length, "text": m.strip()})
    return rows


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def copies_snippet(text: str, snippet: str) -> bool:
    """True when the message shares a COPY_NGRAM-word run with its gold snippet."""
    w, s = words(text), words(snippet)
    grams = {tuple(s[k:k + COPY_NGRAM]) for k in range(len(s) - COPY_NGRAM + 1)}
    return any(tuple(w[k:k + COPY_NGRAM]) in grams for k in range(len(w) - COPY_NGRAM + 1))


def clean(loc: Locale, rows: list[dict], kb: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Duplicates, source leaks, PII, foreign-variety markers and copies of the gold snippet."""
    raw = pl.DataFrame(rows).with_columns(template=pl.col("text"))
    counts = {"messages": raw.height}
    unique = dedup(raw)
    counts["after dedup"] = unique.height
    no_leak = drop_leaks(loc, unique)
    counts["after source leaks"] = no_leak.height
    # drop_pii masks filled slots; these messages have none
    no_pii = drop_pii(loc, no_leak.with_columns(slots=pl.Series([[] for _ in range(no_leak.height)],
                                                                 dtype=pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64})))))
    counts["after PII"] = no_pii.height
    no_foreign = no_pii.filter(~pl.col("text").str.contains(loc.foreign_markers)) if loc.foreign_markers else no_pii
    counts["after foreign markers"] = no_foreign.height
    text_of = dict(zip(kb["id"], kb["text"], strict=True))
    copied = [any(copies_snippet(t, text_of[g]) for g in gold)
              for t, gold in zip(no_foreign["text"], no_foreign["relevant_ids"], strict=True)]
    out = no_foreign.filter(~pl.Series(copied, dtype=pl.Boolean))
    counts["after snippet copies"] = out.height
    return out.drop("template", "slots"), counts


def select(clean_rows: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Keep PER_TOPIC per topic (2 short + 1 long when available) and NOT_COVERED per kind."""
    keep, deficit = [], {}
    for (kind, topic), g in clean_rows.sort("call").group_by("kind", "topic_id", maintain_order=True):
        target = PER_TOPIC if kind == "in_scope" else NOT_COVERED
        n_long = 1 if kind == "in_scope" else NOT_COVERED // 3
        longs, shorts = g.filter(pl.col("length") == "long"), g.filter(pl.col("length") == "short")
        take_long = longs.head(min(n_long, longs.height))
        chosen = pl.concat([shorts.head(target - take_long.height), take_long])
        if chosen.height < target:
            chosen = pl.concat([chosen, longs.slice(take_long.height, target - chosen.height)])
        keep.append(chosen)
        if chosen.height < target:
            deficit[f"{kind}:{topic}"] = target - chosen.height
    return pl.concat(keep), deficit


def rewrite(messages: list[str]) -> list[dict]:
    """The query the orchestrator's LLM sends to kb_search for each message (forced tool call)."""
    from orchestrator.conversation.prompt import SYSTEM_PROMPT
    from orchestrator.conversation.tools import build_llm_tools
    from orchestrator.privacy.masking import RegexMasker

    dotenv = dict(line.split("=", 1) for line in (ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else [])
                  if "=" in line and not line.startswith("#"))
    env = lambda k: (os.environ.get(k) or dotenv.get(k, "")).split("#")[0].strip()  # noqa: E731
    model, api_key, effort = env("LLM_MODEL"), env("LLM_API_KEY"), env("LLM_REASONING_EFFORT")
    base_url = env("LLM_BASE_URL") if "://" in env("LLM_BASE_URL") else None
    if not model:
        raise SystemExit("Set LLM_MODEL (the orchestrator's model) for the rewrite step.")
    tools, _ = build_llm_tools()
    choice = {"type": "function", "function": {"name": "kb_search"}}
    masker = RegexMasker()

    def one(message: str) -> dict:
        masked = masker.mask(message).masked_text
        chat = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": masked}]
        key = hashlib.sha256(json.dumps({"model": model, "messages": chat, "tools": tools, "tool_choice": choice,
                                         "reasoning_effort": effort}, sort_keys=True).encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        if not api_key:
            raise SystemExit("Set LLM_API_KEY in the environment or .env (the call is not cached yet).")
        import litellm

        kwargs = {"model": model, "messages": chat, "tools": tools, "tool_choice": choice, "temperature": 0.0,
                  "api_key": api_key, "base_url": base_url, "num_retries": REWRITE_RETRIES}
        if effort:
            kwargs["reasoning_effort"] = effort
        response = litellm.completion(**kwargs)
        calls = response.choices[0].message.tool_calls or []
        args = json.loads(calls[0].function.arguments) if calls else {}
        record = {"model": model, "masked_message": masked, "query": args.get("query", ""), "locale": args.get("locale"),
                  "tokens": response.usage.prompt_tokens + response.usage.completion_tokens}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False))
        return record

    with ThreadPoolExecutor(REWRITE_WORKERS) as pool:
        return list(pool.map(one, messages))


def read_written(loc: Locale, path: Path) -> list[dict]:
    """Hand-written messages ({kind, topic_id, length, text} per line), in the shape collect() returns."""
    rows = []
    for i, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        r = json.loads(line)
        kind, topic = r["kind"], r.get("topic_id", "")
        gold = {"in_scope": [f"{topic}.{loc.lang}"], "out_of_scope_banking": [f"{SCOPE_TOPIC}.{loc.lang}"],
                "off_topic": []}[kind]
        rows.append({"call": i, "kind": kind, "topic_id": SCOPE_TOPIC if kind == "out_of_scope_banking" else topic,
                     "relevant_ids": gold, "length": r["length"], "text": r["text"].strip()})
    return rows


def brief(loc: Locale) -> str:
    """What each GPT Sol call is given, compacted, for a person or a coding agent writing by hand."""
    card = yaml.safe_load((loc.out_dir / "style_cards.B.yaml").read_text())
    phrases = pl.read_parquet(loc.out_dir / "phrase_bank.parquet").filter(pl.col("half") == "B")
    prompts = build_prompts(loc, plan_calls(loc, kb_snippets()), card, phrases)
    head = prompts[0].split("The bank's chat assistant answers")[0]
    style = prompts[0].split("Style evidence")[1].split("Customer profile")[0]
    out = [head.strip(), "", "Style evidence" + style.strip(), ""]
    for c, prompt in zip(plan_calls(loc, kb_snippets()).iter_rows(named=True), prompts, strict=True):
        task = prompt.split("\n\n", 1)[1].split("\n\nStyle evidence")[0]
        real = prompt.split("do not reuse their situations literally:\n")[1].split("\n- Common openers")[0]
        persona = prompt.split("Customer profile for this batch: ")[1].split("\n")[0]
        terms = prompt.split("- Words and expressions typical of this topic: ")[1].split("\n")[0]
        out += [f"### {c['kind']} {c['topic_id']} (call {c['call']})", task, f"Topic terms: {terms}", "Real phrases:", real,
                f"Persona: {persona}", ""]
    return "\n".join(out)


def generate(loc: Locale, generator: str = "gpt-sol") -> pl.DataFrame:
    spec = GENERATORS[generator]
    kb = kb_snippets()
    if spec["written"] is not None:
        model = spec["model"]
        rows = read_written(loc, spec["written"] / f"{loc.code}.jsonl")
        cleaned, counts = clean(loc, rows, kb)
        kept, deficit = select(cleaned)
        print(f"{loc.code} ({generator}): written {len(rows)} · " + " · ".join(f"{k} {v}" for k, v in counts.items()))
        if deficit:
            print(f"WARNING: below target, write more for: {deficit}")
    else:
        model, kept = _generate_llm(loc, kb)
    return _finish(loc, kept, model, spec)


def _generate_llm(loc: Locale, kb: pl.DataFrame) -> tuple[str, pl.DataFrame]:
    model, api_key, base_url = _llm_settings()
    stage = loc.out_dir
    card = yaml.safe_load((stage / "style_cards.B.yaml").read_text())
    phrases = pl.read_parquet(stage / "phrase_bank.parquet").filter(pl.col("half") == "B")

    def run(batch: pl.DataFrame, round_: int) -> tuple[list[dict], int]:
        prompts = build_prompts(loc, batch, card, phrases, round_)
        with ThreadPoolExecutor(WORKERS) as pool:
            records = list(pool.map(lambda p: ask(p, model, api_key, base_url), prompts))
        return collect(batch, records), sum(r["tokens"] for r in records)

    calls = plan_calls(loc, kb)
    rows, tokens = run(calls, 0)
    cleaned, counts = clean(loc, rows, kb)
    kept, deficit = select(cleaned)
    if deficit:  # one top-up round: ask again for the topics the filters left short
        short = calls.filter((pl.col("kind") + ":" + pl.col("topic_id")).is_in(list(deficit)))
        retry = short.with_columns(call=pl.col("call") + calls.height)
        print(f"top-up: {deficit} → {retry.height} extra calls")
        more, more_tokens = run(retry, 1)
        rows, tokens = rows + more, tokens + more_tokens
        cleaned, counts = clean(loc, rows, kb)
        kept, deficit = select(cleaned)
    print(f"{loc.code}: calls {calls.height} · tokens {tokens:,} · " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    if deficit:
        print(f"WARNING: below target after top-up: {deficit}")
    return model, kept


def _finish(loc: Locale, kept: pl.DataFrame, model: str, spec: dict) -> pl.DataFrame:
    """The rewrite step, ids and provenance, and the locale file."""
    rewrites = rewrite(kept["text"].to_list())
    prefix = ID_PREFIX[loc.code]
    out = kept.with_columns(
        id=pl.Series([f"{spec['id']}-{prefix}-{i:03d}" for i in range(1, kept.height + 1)]),
        kb_query=pl.Series([r["query"][:QUERY_MAX_CHARS] for r in rewrites]),
        lang=pl.lit(loc.lang), locale=pl.lit(loc.code), split=pl.lit(SPLIT), source=pl.lit(SOURCE),
        model=pl.lit(model), rewrite_model=pl.lit(rewrites[0]["model"] if rewrites else ""),
        prompt_version=pl.lit(PROMPT_VERSION),
    ).select("id", "text", "kb_query", "lang", "locale", "relevant_ids", "split", "source", "kind", "topic_id",
             "length", "model", "rewrite_model", "prompt_version")
    empty = sum(1 for r in rewrites if not r["query"])
    if empty:
        print(f"WARNING: {empty} rewrites returned no query")
    spec["out_dir"].mkdir(parents=True, exist_ok=True)
    (spec["out_dir"] / f"{loc.code}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out.to_dicts()))
    return out


def pool(generator: str = "gpt-sol") -> pl.DataFrame:
    spec = GENERATORS[generator]
    out_dir = spec["out_dir"]
    frames = [pl.read_ndjson(out_dir / f"{code}.jsonl") for code in LOCALES if (out_dir / f"{code}.jsonl").exists()]
    if not frames:
        raise SystemExit(f"No locale files in {out_dir}: generate them first.")
    pooled = pl.concat(frames, how="diagonal_relaxed")
    spec["pooled"].write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pooled.to_dicts()))
    return pooled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--locale", choices=list(LOCALES))
    parser.add_argument("--generator", choices=list(GENERATORS), default="gpt-sol",
                        help="gpt-sol calls the API; claude reads hand-written messages from written/<locale>.jsonl")
    parser.add_argument("--pool", action="store_true", help="pool the locale files and write checks.md")
    parser.add_argument("--brief", action="store_true", help="print what each call is given, for writing by hand")
    args = parser.parse_args()
    if args.brief:
        if not args.locale:
            parser.error("--brief needs --locale")
        print(brief(get_locale(args.locale)))
        return
    if not args.locale and not args.pool:
        parser.error("set --locale, --pool or both")
    if args.locale:
        out = generate(get_locale(args.locale), args.generator)
        print(out.group_by("kind", "length").len().sort("kind", "length"))
    if args.pool:
        from tools.synthdata_regional.retrieval_checks import write_checks

        spec = GENERATORS[args.generator]
        pooled = pool(args.generator)
        print(f"pooled {pooled.height} rows → {spec['pooled'].relative_to(REPO)}")
        write_checks(pooled, spec["out_dir"])


if __name__ == "__main__":
    main()
