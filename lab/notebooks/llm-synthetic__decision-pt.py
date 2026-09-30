import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # llm-synthetic · decision-pt

    **Question:** Can an LLM, guided by style cards mined from real Brazilian bank complaints, write a pt-BR intent dataset (15 intents, with slots) that passes our automated quality checks?

    **Inputs:** `data/staging/decision_pt/style_cards.A.yaml` and `phrase_bank.parquet` (half A only), from `eda-text__complaints-br-banking.py` · **Taxonomy:** `data/eval/synthetic/schema.yaml` · **Writes:** `data/staging/decision_pt/decision.pt.{pilot,train,validation}.jsonl` (local, not versioned) · **Generated:** 2026-09-29, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type extends `llm-synthetic`). Step 2 of the plan for the pt intent dataset.

    **Process:** plan the calls (intent × length × persona, plus topic for `out_of_scope`) → ask the LLM for messages with `{slot}` placeholders → fill the placeholders locally with fictitious values → drop duplicates, near-duplicates, source leaks and stray PII → split into train and validation → report label consistency and authenticity.

    Synthetic rows are LLM-generated and have **not been reviewed by a human**.
    """)
    return


@app.cell
def _():
    import hashlib
    import json
    import os
    import random
    import re
    import sys

    import marimo as mo
    import numpy as np
    import polars as pl
    import yaml

    return hashlib, json, mo, np, os, pl, random, re, sys, yaml


@app.cell
def _(mo, os):
    # Settings: change these, the rest of the notebook follows
    REPO = mo.notebook_dir().parents[1]
    OUT_DIR = REPO / "data" / "staging" / "decision_pt"
    SCHEMA_PATH = REPO / "data" / "eval" / "synthetic" / "schema.yaml"
    RAW_FILE = REPO / "data" / "raw" / "complaints_br" / "db_reclamacoes_clean.parquet"
    CACHE_DIR = mo.notebook_dir().parent / ".cache" / "llm"
    ENV_FILE = REPO / ".env"  # LLM_API_KEY and LLM_BASE_URL fall back to this file
    LLM_MODEL = os.environ.get("SYNTH_LLM_MODEL", "openai/gpt-6.1-sol")  # LiteLLM provider/model
    PROMPT_VERSION = "v1"
    MODE = os.environ.get("SYNTH_MODE", "pilot")  # "pilot": 10 per intent · "full": train + validation
    TARGET = {"train": 100, "validation": 50}  # rows per intent kept in full mode
    PILOT_PER_INTENT = 10
    OVERGENERATE = 1.4  # extra rows asked for, to survive the filters
    BATCH = 20  # messages per call
    LONG_SHARE = 0.375  # for intents that can be long; overall this gives about 25% long rows
    N_PHRASES = 5  # masked real phrases shown per call
    NEAR_DUP = 0.85  # near-duplicate cosine; stricter than the 0.9 gate in tools/synthdata_pt/checks.py, whose IDF is fitted on other rows
    LEAK_NGRAM = 8  # a shared run of this many words with a real complaint is a leak
    SEED = 7
    return (
        BATCH,
        CACHE_DIR,
        ENV_FILE,
        LEAK_NGRAM,
        LLM_MODEL,
        LONG_SHARE,
        MODE,
        NEAR_DUP,
        N_PHRASES,
        OUT_DIR,
        OVERGENERATE,
        PILOT_PER_INTENT,
        PROMPT_VERSION,
        RAW_FILE,
        REPO,
        SCHEMA_PATH,
        SEED,
        TARGET,
    )


@app.cell
def _():
    # Generation spec. Boundaries follow docs/labeling-rubric.md §2; placeholders follow tools/synthdata/templates_pt.py
    BOUNDARIES = {
        "report_unrecognized_charge": "Reports a specific charge or purchase they do not recognise or did not authorise. It does NOT explicitly ask for a refund, dispute or chargeback (that is request_dispute), and it is not a general security alert without a charge (that is report_suspicious_activity).",
        "request_dispute": "Explicitly asks to open a dispute (contestação), get a refund (estorno, reembolso, devolução) or a chargeback for a transaction: unrecognised, duplicated, cancelled purchase, wrong amount or product not delivered.",
        "report_lost_card": "The physical card was lost or misplaced. No theft, and no explicit request to block it (that is request_card_block).",
        "report_stolen_card": "The card was stolen, robbed or snatched (assalto, furto, roubo). No explicit request to block it (that is request_card_block).",
        "report_suspicious_activity": "General security signals: a suspicious SMS, email or call, a phishing link, a login alert, someone trying to access the account, a cloned-card suspicion, WITHOUT citing a specific charge (that is report_unrecognized_charge).",
        "request_card_block": "Explicitly asks to block, freeze, lock or cancel their card now. It may mention loss, theft or fraud; the block request wins.",
        "request_human_agent": "Explicitly asks to talk to a human agent, attendant or person instead of the bot. Frustration alone is not enough.",
        "provide_identity_data": "Gives their own identification data (full name, CPF or RG number, birth date, email, phone) so the bank can verify them.",
        "provide_otp_code": "Gives the one-time code or token they received by SMS, email or app.",
        "confirm": "A short affirmative answer to the assistant's previous question (yes, go ahead, that's right, I confirm). No new request.",
        "deny": "A short negative answer, rejection or cancellation of the assistant's previous question. No new request.",
        "check_balance": "Asks for their current balance, available credit limit or available funds.",
        "check_recent_transactions": "Asks to see recent transactions, the statement (extrato) or the items on the card bill (fatura).",
        "greeting": "Only a greeting or pleasantry, with no banking request.",
        "out_of_scope": "A message the assistant does not handle. The topic of each call is given below; the message must NOT ask for a balance or statement, report an unknown charge, ask for a refund, block a card or report fraud.",
    }
    PLACEHOLDERS = {  # allowed per intent; "required" means every message must carry at least one of them
        "report_unrecognized_charge": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
        "request_dispute": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
        "report_lost_card": (["card_last4"], False), "report_stolen_card": (["card_last4"], False),
        "request_card_block": (["card_last4"], False),
        "report_suspicious_activity": (["card_last4", "transaction_date"], False),
        "provide_identity_data": (["full_name", "document_type", "document_number", "birth_date", "email", "phone"], True),
        "provide_otp_code": (["otp_code"], True),
        "check_balance": (["card_last4"], False), "check_recent_transactions": (["card_last4"], False),
    }
    SHORT_ONLY = {"greeting", "confirm", "deny", "provide_otp_code", "provide_identity_data"}
    OOS_TOPICS = {  # "general" appears three times so about a third of out_of_scope is not about banking
        "oos_app": "problems with the bank app: errors, crashes, updates, login or facial-recognition failures",
        "oos_pix_transfer": "a Pix or TED transfer or deposit that was not received or credited",
        "oos_credit": "loans, payroll loans (consignado), credit limit, installments, interest, debt renegotiation, Serasa",
        "oos_account": "an account blocked or closed by the bank, wanting to close an account, Registrato",
        "oos_machine": "card machines (maquininha) for small businesses, sales money not received",
        "oos_rewards": "cashback, points, miles and promotions not credited",
        "general": "topics unrelated to banking: weather, football, recipes, jokes, general knowledge, small talk",
    }
    OOS_ROTATION = ["oos_app", "general", "oos_pix_transfer", "oos_credit", "general", "oos_account", "oos_machine", "general", "oos_rewards"]
    PERSONAS = [
        "a young customer, very informal, abbreviations (vc, pq, q, tb), no final punctuation",
        "an older customer, formal and polite, complete sentences",
        "an angry customer, some words in CAPITALS, exclamation marks",
        "a customer in a hurry, very short sentences",
        "a polite customer who starts with a greeting",
        "a small-business owner (conta PJ, maquininha, vendas)",
        "a customer typing on the phone without accents (nao, voce, cartao) and with small typos",
        "a customer from the Northeast or the South of Brazil, with light regional expressions",
    ]
    LENGTH_RULES = {
        "short": "1 to 3 sentences, like a chat message (roughly 4 to 40 words).",
        "long": "a longer, complaint-style chat message of 3 to 6 sentences (roughly 40 to 110 words): some context and emotion, maybe a secondary detail, but the intent must stay clearly dominant.",
    }
    return BOUNDARIES, LENGTH_RULES, OOS_ROTATION, OOS_TOPICS, PERSONAS, PLACEHOLDERS, SHORT_ONLY


@app.cell
def _():
    # Brazilian values for the non-PII slots; PII slots keep the fictitious values from tools/synthdata/fillers.py
    BR_FILLERS = {
        "amount": ["15,90", "29,99", "47,50", "89,90", "120,00", "150,00", "237,45", "349,90", "500,00", "780,00", "1.200,00", "1.899,90", "2.450,00", "35", "60", "250"],
        "currency": ["R$"],
        "merchant": ["iFood", "Mercado Livre", "Magalu", "Americanas", "Shopee", "Amazon", "Uber", "Rappi", "Netflix", "Spotify", "Drogasil", "Carrefour", "Pão de Açúcar", "Renner", "Casas Bahia", "Posto Ipiranga", "Shell", "Riachuelo", "Centauro", "Kabum", "Steam", "Assaí", "Atacadão", "Smart Fit", "Cinemark"],
        "transaction_date": ["ontem", "hoje", "12/09/2026", "03/09/2026", "28/08/2026", "21/09/2026", "15/09/2026", "07/09/2026"],
        "birth_date": ["12/04/1985", "24/11/1992", "08/07/1978", "30/09/1983", "19/01/1995", "05/12/1980", "17/03/1990", "22/06/1975"],
    }
    return (BR_FILLERS,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats**

    - **Not reviewed by a human** (decided in the plan). Label noise is only estimated, by the out-of-fold consistency check below.
    - **Privacy:** only half-A style cards (aggregated terms and register shares) and at most `N_PHRASES` masked, safety-filtered sentences per call reach the provider (AGENTS.md rule 5). No full complaint is ever sent.
    - PII in the output is fictitious: names, documents, emails, phones, OTPs and card numbers come from `tools/synthdata/fillers.py`, imported from the repository on purpose so both generators share one fictitious-PII guarantee. Amounts, merchants and dates use the Brazilian lists in `BR_FILLERS`.
    - `greeting`, `confirm` and `deny` have no complaint evidence; they get the register card only. `provide_otp_code` and `provide_identity_data` are short-only.
    - The test split is **not** generated here: it comes from a different process and a different model, using half-B style cards.
    - `LLM_MODEL` defaults to `openai/gpt-6.1-sol`. The call sends no `temperature` (some current models reject it); the disk cache keyed on model and prompt is what makes reruns reproducible.
    """)
    return


@app.cell
def _(CACHE_DIR, ENV_FILE, LLM_MODEL, hashlib, json, mo, os):
    _dotenv = dict(_l.split("=", 1) for _l in (ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else []) if "=" in _l and not _l.startswith("#"))
    _api_key = os.environ.get("LLM_API_KEY") or _dotenv.get("LLM_API_KEY", "").strip()
    _base_url = os.environ.get("LLM_BASE_URL") or _dotenv.get("LLM_BASE_URL", "").strip() or None
    mo.stop(not _api_key, mo.md("**Set `LLM_API_KEY`** in the environment or `.env` to run this notebook."))

    import litellm

    def ask(prompt: str) -> dict:
        """One cached LLM call. Returns the stored record: model, prompt, text, tokens."""
        key = hashlib.sha256(f"{LLM_MODEL}\n{prompt}".encode()).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        response = litellm.completion(model=LLM_MODEL, messages=[{"role": "user", "content": prompt}],
                                      api_key=_api_key, base_url=_base_url)
        record = {"model": LLM_MODEL, "prompt": prompt, "text": response.choices[0].message.content,
                  "tokens": response.usage.prompt_tokens + response.usage.completion_tokens}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False))
        return record

    def parse(text: str) -> dict:
        try:
            return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        except json.JSONDecodeError:
            return {"raw": text}
    return ask, parse


@app.cell
def _(OUT_DIR, SCHEMA_PATH, mo, pl, yaml):
    mo.stop(not (OUT_DIR / "style_cards.A.yaml").exists(), mo.md("**Run `eda-text__complaints-br-banking.py` first** to write the style cards."))
    card = yaml.safe_load((OUT_DIR / "style_cards.A.yaml").read_text())
    phrases = pl.read_parquet(OUT_DIR / "phrase_bank.parquet").filter(pl.col("half") == "A")
    DEFINITIONS = {i["name"]: i["description"] for i in yaml.safe_load(SCHEMA_PATH.read_text())["intents"]}
    phrases.group_by("intent").len().sort("len", descending=True)
    return DEFINITIONS, card, phrases


@app.cell
def _(
    BATCH,
    DEFINITIONS,
    LONG_SHARE,
    MODE,
    OOS_ROTATION,
    OVERGENERATE,
    PERSONAS,
    PILOT_PER_INTENT,
    SHORT_ONLY,
    TARGET,
    pl,
):
    # One row per LLM call: which intent, length, persona and (for out_of_scope) topic
    _per_intent = PILOT_PER_INTENT if MODE == "pilot" else round(sum(TARGET.values()) * OVERGENERATE)
    _batch = 5 if MODE == "pilot" else BATCH
    _calls = []
    for _intent in DEFINITIONS:
        _long = 0 if _intent in SHORT_ONLY else round(_per_intent * LONG_SHARE)
        for _length, _n in (("short", _per_intent - _long), ("long", _long)):
            for _k in range(0, _n, _batch):
                _i = len(_calls)
                _calls.append({"call": _i, "intent": _intent, "length": _length, "n": min(_batch, _n - _k),
                               "persona": PERSONAS[_i % len(PERSONAS)],
                               "topic": OOS_ROTATION[_k // _batch % len(OOS_ROTATION)] if _intent == "out_of_scope" else ""})
    calls = pl.DataFrame(_calls)
    calls.group_by("intent", "length").agg(calls=pl.len(), messages=pl.col("n").sum()).sort("intent", "length")
    return (calls,)


@app.cell
def _():
    PROMPT = """You write realistic messages that customers of a Brazilian bank type into the bank's chat assistant. Write in Brazilian Portuguese as real Brazilians write, never European Portuguese or Spanish.

Intent: {intent}
Definition: {definition}
Boundary: {boundary}
{topic}
Length of each message: {length}
Customer profile for this batch: {persona}

Style evidence mined from real, masked complaints of Brazilian bank customers:
- Words and expressions typical of this topic: {terms}
- Real sentences, for vocabulary and tone only; do not copy them and do not reuse their situations literally:
{phrases}
- Common openers: {openers}
- Informal spellings some customers use: {informal}
- Money is written like: {money}. Dates are written like: {dates}.

Slots: {slots}
Never write real-looking names, CPF or RG numbers, emails, phone numbers, card numbers, codes or protocol numbers except through the placeholders.

Write {n} different messages. Vary the situation, wording, tone, length within the rule, punctuation and how formal they are. Each message must clearly express the intent above and nothing that belongs to another intent.
Request id: {call_id}
Reply with only a JSON object: {{"messages": ["...", "..."]}}"""
    return (PROMPT,)


@app.cell
def _(
    BOUNDARIES,
    DEFINITIONS,
    LENGTH_RULES,
    N_PHRASES,
    OOS_TOPICS,
    PLACEHOLDERS,
    PROMPT,
    SEED,
    ask,
    calls,
    card,
    parse,
    phrases,
    pl,
):
    _reg = card["register"]
    _informal = ", ".join(w for w, s in sorted(_reg["informal_spelling_share"].items(), key=lambda x: -x[1])[:10])
    _raw, _tokens = [], 0
    for _c in calls.iter_rows(named=True):
        _intent, _themes = _c["intent"], card["intents"][_c["intent"]]["themes"]
        if _c["topic"] and _c["topic"] != "general":
            _themes = [_c["topic"]]
        _terms = [t for th in _themes for t in card["intents"]["out_of_scope" if th.startswith("oos_") else _intent]["terms"].get(th, [])]
        _pool = phrases.filter(pl.col("theme").is_in(_themes))
        _sample = _pool.sample(min(N_PHRASES, _pool.height), seed=SEED + _c["call"])["sentence"].to_list() if _pool.height else []
        _allowed, _required = PLACEHOLDERS.get(_intent, ([], False))
        _slots = (f"when a message mentions one of these, write the placeholder instead of a value: {', '.join('{' + s + '}' for s in _allowed)}. "
                  + ("Every message must contain at least one of them." if _required else "Use them in about half of the messages.")) if _allowed else "this intent has no slots; do not use any placeholder or curly braces."
        _record = ask(PROMPT.format(
            intent=_intent, definition=DEFINITIONS[_intent], boundary=BOUNDARIES[_intent],
            topic=f"Topic for this batch: {OOS_TOPICS[_c['topic']]}" if _c["topic"] else "",
            length=LENGTH_RULES[_c["length"]], persona=_c["persona"],
            terms=", ".join(_terms[:20]) or "(none mined; rely on the register below)",
            phrases="\n".join(f"  · {s}" for s in _sample) or "  (none)",
            openers=", ".join(_reg["openers"][:10]), informal=_informal,
            money=", ".join(_reg["money_formats"][:4]), dates=", ".join(_reg["date_formats"][:5]),
            slots=_slots, n=_c["n"], call_id=f"{_c['call']}-{_intent}-{_c['length']}"))
        _tokens += _record["tokens"]
        _messages = parse(_record["text"]).get("messages", [])
        _raw += [{**_c, "template": m} for m in _messages if isinstance(m, str) and m.strip()]
    raw = pl.DataFrame(_raw)
    {"calls": calls.height, "messages": raw.height, "tokens": _tokens}
    return (raw,)


@app.cell
def _(BR_FILLERS, PLACEHOLDERS, REPO, SEED, pl, random, raw, re, sys):
    # Placeholders → fictitious values with exact offsets (same assembly as tools/synthdata render_template)
    sys.path.insert(0, str(REPO))
    from tools.synthdata.fillers import DOCUMENT_PROFILES, get_fillers

    _filled, _rejected = [], []
    for _row in raw.iter_rows(named=True):
        _parts = re.split(r"(\{\w+\})", _row["template"].strip())
        _allowed, _required = PLACEHOLDERS.get(_row["intent"], ([], False))
        _names = [p[1:-1] for p in _parts if re.fullmatch(r"\{\w+\}", p)]
        _reason = ("unknown or disallowed placeholder" if any(n not in _allowed for n in _names)
                   else "required placeholder missing" if _required and not _names
                   else "stray brace" if re.search(r"[{}]", "".join(p for p in _parts if not re.fullmatch(r"\{\w+\}", p)))
                   else "")
        if _reason:
            _rejected.append({**_row, "reason": _reason})
            continue
        _rng = random.Random(f"{SEED}-{_row['call']}-{_row['template']}")
        _values = {**get_fillers("pt", _rng), **{k: _rng.choice(v) for k, v in BR_FILLERS.items()}}
        if "document_number" in _names and "document_type" not in _names:
            # The text names the document itself ("cpf {document_number}"): the number must match that type
            _named = re.search(r"(?i)\b(cpf|rg|passaporte|cnpj|rne|crnm)\b", _row["template"])
            _surface = _named.group(1).lower() if _named else "cpf"
            _profile = _rng.choice([d for d in DOCUMENT_PROFILES["pt"] if d["surface"].lower() == _surface])
            _values["document_number"] = _profile["number"]
        _text, _slots = "", []
        for _p in _parts:
            if re.fullmatch(r"\{\w+\}", _p):
                _name = _p[1:-1]
                _slot = {"type": _name, "value": _values[_name], "start": len(_text), "end": len(_text) + len(_values[_name])}
                if _name == "document_type":
                    _slot["normalized"] = _values["document_type_normalized"]
                _slots.append(_slot)
                _text += _values[_name]
            else:
                _text += _p
        assert all(_text[s["start"]:s["end"]] == s["value"] for s in _slots)
        _filled.append({**_row, "text": _text, "slots": _slots})
    filled = pl.DataFrame(_filled)
    rejected = pl.DataFrame(_rejected) if _rejected else pl.DataFrame(schema={"reason": pl.String})
    {"filled": filled.height, "rejected": rejected.height, "reasons": rejected["reason"].value_counts().to_dicts()}
    return filled, rejected


@app.cell
def _(NEAR_DUP, filled, np, pl, re):
    # Exact and near-duplicates, on both the placeholder text (filled values must not hide repeats)
    # and the filled text (what tools/synthdata_pt/checks.py compares across splits)
    from sklearn.feature_extraction.text import TfidfVectorizer

    _norm = lambda col: filled[col].map_elements(lambda t: re.sub(r"\W+", " ", t.lower()).strip(), return_dtype=pl.String)
    _by_template = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(_norm("template"))
    _vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(_norm("text"))
    _keep, _kept_idx = [], []
    for _i in range(filled.height):
        _dup = bool(_kept_idx) and max(float((_by_template[_kept_idx] @ _by_template[_i].T).max()),
                                       float((_vectors[_kept_idx] @ _vectors[_i].T).max())) >= NEAR_DUP
        _keep.append(not _dup)
        if not _dup:
            _kept_idx.append(_i)
    unique = filled.filter(pl.Series(_keep))
    {"before": filled.height, "after": unique.height, "near_duplicate_rate": round(1 - unique.height / max(filled.height, 1), 3),
     "vector_dims": int(np.shape(_vectors)[1])}
    return (unique,)


@app.cell
def _(LEAK_NGRAM, RAW_FILE, pl, re, unique):
    # Source leakage: no generated row may share an 8-word run with any real bank complaint (both halves)
    _words = lambda t: re.findall(r"\w+", t.lower())
    _gen = {}
    for _i, _t in enumerate(unique["text"]):
        _w = _words(_t)
        for _k in range(len(_w) - LEAK_NGRAM + 1):
            _gen.setdefault(tuple(_w[_k:_k + LEAK_NGRAM]), set()).add(_i)
    _leaks = set()
    for _t in pl.read_parquet(RAW_FILE, columns=["source", "ask"]).filter(pl.col("source") == "reclame_aqui")["ask"]:
        _w = _words(_t)
        for _k in range(len(_w) - LEAK_NGRAM + 1):
            _leaks |= _gen.get(tuple(_w[_k:_k + LEAK_NGRAM]), set())
    no_leak = unique.filter(~pl.Series(range(unique.height)).is_in(list(_leaks)))
    {"rows": unique.height, "leaking rows dropped": len(_leaks)}
    return (no_leak,)


@app.cell
def _(no_leak, pl, re):
    # PII outside slots: anything that looks like a CPF, phone, email, card or long number must be a filled slot
    _pii = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\+?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}|[\w.+-]+@[\w-]+\.\w+|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|\d{6,}")
    _ok = []
    for _text, _slots in no_leak.select("text", "slots").iter_rows():
        _masked = list(_text)
        for _s in _slots:
            _masked[_s["start"]:_s["end"]] = ["_"] * (_s["end"] - _s["start"])
        _ok.append(not _pii.search("".join(_masked)))
    clean = no_leak.filter(pl.Series(_ok))
    {"rows": no_leak.height, "stray PII dropped": no_leak.height - clean.height}
    return (clean,)


@app.cell
def _(
    LLM_MODEL,
    MODE,
    OUT_DIR,
    PROMPT_VERSION,
    SEED,
    TARGET,
    clean,
    json,
    mo,
    pl,
):
    # Split per intent, keeping each intent's short/long mix in both splits
    _rows = []
    for (_intent,), _d in clean.sample(fraction=1.0, shuffle=True, seed=SEED).group_by("intent", maintain_order=True):
        _splits = {"pilot": _d} if MODE == "pilot" else {}
        if MODE != "pilot":
            _long_share = (_d["length"] == "long").mean()
            _parts = {_l: _g for (_l,), _g in _d.group_by("length")}
            for _split, _n in TARGET.items():
                _n_long = round(_n * _long_share)
                _take = [(_l, _n_long if _l == "long" else _n - _n_long) for _l in _parts]
                _splits[_split] = pl.concat([_parts[_l].head(_k) for _l, _k in _take])
                _parts = {_l: _parts[_l].slice(_k) for _l, _k in _take}
        for _split, _g in _splits.items():
            for _j, _r in enumerate(_g.iter_rows(named=True)):
                _rows.append({"id": f"synthpt_{_split}_{_intent}_{_j:03d}", "text": _r["text"], "lang": "pt", "intent": _intent,
                              "slots": _r["slots"], "split": _split, "source": "synthetic-llm", "generator": LLM_MODEL,
                              "prompt_version": PROMPT_VERSION, "length": _r["length"], "topic": _r["topic"]})
    dataset = pl.DataFrame(_rows)
    for (_split,), _g in dataset.group_by("split"):
        (OUT_DIR / f"decision.pt.{_split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _g.to_dicts()))
    mo.vstack([mo.md(f"Wrote {dataset.height} rows to `{OUT_DIR}`."),
               dataset.group_by("split", "intent").agg(rows=pl.len(), long=(pl.col("length") == "long").sum()).pivot("split", index="intent", values=["rows", "long"])])
    return (dataset,)


@app.cell
def _(dataset, pl):
    # Label consistency: 5-fold out-of-fold TF-IDF + LR; a row whose own label gets < 0.1 is flagged
    from sklearn.feature_extraction.text import TfidfVectorizer as _Tfidf
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict
    from sklearn.pipeline import make_pipeline

    _folds = int(min(5, dataset.group_by("intent").len()["len"].min()))
    _model = make_pipeline(_Tfidf(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True), LogisticRegression(max_iter=2000))
    _proba = cross_val_predict(_model, dataset["text"].to_list(), dataset["intent"].to_list(), cv=_folds, method="predict_proba")
    _classes = sorted(dataset["intent"].unique().to_list())
    consistency = dataset.with_columns(
        own_prob=pl.Series([_proba[i, _classes.index(l)] for i, l in enumerate(dataset["intent"])]),
        oof_pred=pl.Series([_classes[j] for j in _proba.argmax(1)]),
    )
    consistency.group_by("intent").agg(rows=pl.len(), oof_accuracy=(pl.col("oof_pred") == pl.col("intent")).mean().round(3),
                                       flagged=(pl.col("own_prob") < 0.1).sum()).sort("oof_accuracy")
    return (consistency,)


@app.cell
def _(card, dataset, pl):
    # Authenticity: mined-lexicon hits per intent, Brazilian markers, and markers that should stay near zero
    _br = r"(?i)\b(você|vc|vcs|a gente|pra|tá|cadê|fatura|pix|boleto|estorno|r\$|reais|beleza|valeu|obrigad[oa])\b"
    _foreign = r"(?i)\b(telemóvel|multibanco|estás|tens|vós|usted|tarjeta|cuenta|necesito|quiero|gracias|ahorita)\b"
    _lex = {i: [t for ts in v["terms"].values() for t in ts if " " not in t] for i, v in card["intents"].items()}
    dataset.with_columns(
        lexicon_hit=pl.struct("intent", "text").map_elements(lambda r: any(w in r["text"].lower() for w in _lex.get(r["intent"], [])), return_dtype=pl.Boolean),
        br_marker=pl.col("text").str.contains(_br), foreign_marker=pl.col("text").str.contains(_foreign),
        words=pl.col("text").str.count_matches(r"\S+"),
    ).group_by("intent").agg(
        rows=pl.len(), lexicon_hit=pl.col("lexicon_hit").mean().round(2), br_marker=pl.col("br_marker").mean().round(2),
        foreign_marker=pl.col("foreign_marker").sum(), median_words=pl.col("words").median(),
    ).sort("intent")
    return


@app.cell
def _(consistency, mo, pl):
    mo.ui.table(consistency.sort("own_prob").select("split", "intent", "length", "topic", "text", "own_prob", "oof_pred"))
    return


@app.cell
def _(mo, rejected):
    mo.ui.table(rejected.select([c for c in ("intent", "reason", "template") if c in rejected.columns]))
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
