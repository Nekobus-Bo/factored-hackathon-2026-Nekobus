import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # eda-text · complaints-br-banking

    **Question:** Which words, expressions and writing habits do Brazilian bank customers use for each of our 15 intents, and how can we capture them safely as style cards for generating a pt-BR intent dataset?

    **Data:** `data/raw/complaints_br/db_reclamacoes_clean.parquet`, `source = 'reclame_aqui'` only (bank and fintech complaints) · **Writes:** `data/staging/decision_pt/phrase_bank.parquet` and `style_cards.{A,B}.yaml` (local, not versioned) · **Generated:** 2026-09-29, following the style rules in `lab/NOTEBOOK_GUIDE.md` (this type is not in its menu yet). Step 1 of the plan for the pt intent dataset.

    **Process:** mask personal data → split into sentences → keep only sentences that pass a safety filter → tag each sentence with a theme → rank the most distinctive terms per theme → measure register (openers, informal spelling, money and date formats) → write one style card per company half. Half **A** feeds train and validation; half **B** feeds the test.
    """)
    return


@app.cell
def _():
    import marimo as mo
    import polars as pl
    import yaml

    return mo, pl, yaml


@app.cell
def _(mo):
    # Settings: change these, the rest of the notebook follows
    RAW_FILE = mo.notebook_dir().parents[1] / "data" / "raw" / "complaints_br" / "db_reclamacoes_clean.parquet"
    OUT_DIR = mo.notebook_dir().parents[1] / "data" / "staging" / "decision_pt"
    MIN_WORDS, MAX_WORDS = 4, 25  # sentence length kept in the phrase bank
    MAX_MASKS = 1  # sentences with more masked spans are dropped
    TOP_TERMS = 25  # distinctive terms per theme in each style card
    MIN_TERM_COUNT = 5  # a term must appear this often in a theme to be ranked
    INFORMAL = ["vc", "vcs", "pq", "q", "tb", "tbm", "nao", "ta", "to", "pra", "pro", "hj", "td", "msm", "ngm", "mt", "mto", "obg", "pfv", "blz", "oq", "aki", "ne"]
    return (
        INFORMAL,
        MAX_MASKS,
        MAX_WORDS,
        MIN_TERM_COUNT,
        MIN_WORDS,
        OUT_DIR,
        RAW_FILE,
        TOP_TERMS,
    )


@app.cell
def _():
    # Patterns: masks run in order, before anything else touches the text (AGENTS.md rule 5). Best effort.
    MASKS = [
        (r"(?i)\[?editado pelo reclame aqui\]?", "[EDITADO]"),
        (r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"),
        (r"(?i)https?://\S+|www\.\S+", "[URL]"),
        (r"\*{3,}|X{3,}", "[OCULTO]"),
        (r"\d[\d .\-/]{5,}\d", "[NUMERO]"),  # CPF, card, account, phone, protocol, full dates
        (r"\b([Ss]r|[Ss]ra|[Ss]rta)\.? \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)?", "${1} [NOME]"),
        (r"\b([Mm]eu nome [ée]|[Mm]e chamo|[Aa]tendente|[Gg]erente|[Cc]onsultora?|[Oo]peradora?|[Aa]nalista) \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)*", "${1} [NOME]"),
    ]
    # Theme per sentence, first match wins; rubric §2 decides what each intent means
    THEMES = {
        "unrecognized_charge": r"n[aã]o reconhe[cç]o|n[aã]o fiz (essa|esta|a|nenhuma) compra|n[aã]o autorizei|compras? que n[aã]o fiz|desconhe[cç]o (a|essa|esta|o|esse)|n[aã]o reconhecid",
        "dispute": r"contesta[cç][aã]o|contestar|\bestorn|reembols|chargeback|devolu[cç][aã]o d[oa] (valor|dinheiro)|ressarc|quero (meu|o) dinheiro de volta",
        "lost_card": r"perdi (o |meu |minha )?(cart[aã]o|carteira)|cart[aã]o (foi )?perdido|n[aã]o (acho|encontro) (o |meu )?cart[aã]o",
        "stolen_card": r"cart[aã]o (foi )?(roubado|furtado)|roubaram (o |meu |minha )|furtaram|fui (assaltad|roubad|furtad)|assalto",
        "suspicious_activity": r"golpe|fraude|hacke|invadi|clonad|link (falso|estranho)|acesso (suspeito|indevido|n[aã]o autorizado)|mensagem estranha|sms estranho",
        "card_block": r"\bbloque(ar|iem|ie|em) (o |meu |minha )?cart[aã]o|\bbloqueio (do|de) (meu )?cart[aã]o|cancel(ar|em|e) (o |meu )?cart[aã]o",
        "human_agent": r"falar com (um |uma |algum |alguma )?(atendente|pessoa|humano|ser humano)|atendimento humano|atendente humano|s[oó] (rob[oô]|bot)|\bbot\b|\brob[oô]\b",
        "balance": r"\bsaldo\b|limite dispon[ií]vel|quanto (eu )?tenho",
        "recent_transactions": r"\bextrato|movimenta[cç][oõ]es|lan[cç]amentos|[uú]ltimas (compras|transa[cç][oõ]es)",
        "otp_code": r"c[oó]digo (de |do )?(verifica[cç][aã]o|seguran[cç]a|sms|acesso)|\btoken|\botp\b|c[oó]digo que (chegou|recebi)",
        "identity_data": r"\bcpf\b|\brg\b|documento|selfie|biometria|reconhecimento facial|dados pessoais",
        "oos_app": r"aplicativo|\bapp\b|n[aã]o abre|n[aã]o carrega|erro|atualiza[cç][aã]o",
        "oos_pix_transfer": r"\bpix\b|\bted\b|transfer[eê]ncia|n[aã]o caiu|n[aã]o foi creditad",
        "oos_credit": r"empr[eé]stimo|consignado|financiamento|\blimite|parcela|juros|renegocia|acordo|serasa",
        "oos_account": r"conta (foi )?(bloqueada|encerrada|suspensa|cancelada)|encerrar (a |minha )?conta|cancelar (a |minha )?conta|registrato",
        "oos_machine": r"maquininha|m[aá]quina (de cart[aã]o)?|\bpos\b",
        "oos_rewards": r"cashback|pontos|milhas|promo[cç][aã]o|cupom",
        "oos_service": r"atendimento (p[eé]ssimo|horr[ií]vel|ruim)|descaso|falta de respeito|ningu[eé]m (resolve|responde)",
    }
    INTENT_THEMES = {  # greeting, confirm and deny have no complaint evidence: register card only
        "report_unrecognized_charge": ["unrecognized_charge"], "request_dispute": ["dispute"],
        "report_lost_card": ["lost_card"], "report_stolen_card": ["stolen_card"],
        "report_suspicious_activity": ["suspicious_activity"], "request_card_block": ["card_block"],
        "request_human_agent": ["human_agent"], "check_balance": ["balance"],
        "check_recent_transactions": ["recent_transactions"], "provide_otp_code": ["otp_code"],
        "provide_identity_data": ["identity_data"],
        "out_of_scope": [t for t in THEMES if t.startswith("oos_")],
        "greeting": [], "confirm": [], "deny": [],
    }
    return INTENT_THEMES, MASKS, THEMES


@app.cell
def _():
    # Capitalised words allowed mid-sentence; any other capitalised word may be a name, so the sentence is dropped
    ALLOWED_CAPS = set("""nubank pagseguro pagbank banco brasil inter itau itaú neon picpay xp investimentos digio will bank
        mercado pago santander bradesco c6 caixa sicredi sicoob bancoob creditas pan agibank iti next original bmg safra
        safrapay stone ton rico clear toro btg pactual visa mastercard elo google apple pay android iphone whatsapp
        instagram uber ifood amazon shopee magalu reclame aqui ouvidoria sac inss fgts receita federal registrato serasa
        procon bacen central pix ted boleto real reais janeiro fevereiro março abril maio junho julho agosto setembro
        outubro novembro dezembro segunda terça quarta quinta sexta sábado domingo natal black friday cdb lci lca tesouro
        direto""".split())
    STOPWORDS = set("""a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela para pra pro com sem
        que se e é ou mas mais muito já não nao sim eu me meu minha meus minhas mim você vc vocês ele ela eles elas
        isso isto esse essa este esta aquele aquela lhe seu sua seus suas nosso nossa foi ser ter tem tenho tinha
        está estou estava estão era fui fiz faz fazer há ao aos à às até sobre quando como onde qual porque pq então
        também tb tbm só so todo toda todos todas ainda agora aqui lá dia vez vezes
        numero nome oculto""".split())  # the last three are mask labels, not words
    return ALLOWED_CAPS, STOPWORDS


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Known caveats** (from `lab/notebooks/eda-table__complaints-br.py`)

    - Only `reclame_aqui` rows are used: 59.5k complaints across 29 banks and fintechs. `consumidor_gov` is telecom only.
    - The texts are **only partly masked at source**. Masking here is regex-based and best effort, so the safety filter also drops any sentence with a digit run of 4+, more than `MAX_MASKS` masked spans, or a capitalised word that is not a known brand, month or weekday. Nothing leaves the machine in this notebook.
    - These are complaints, not chat turns: long, emotional and often about topics outside the 15 intents. Themes are keyword seeds, so they measure vocabulary, not intent. A sentence tagged `dispute` can be a story about a refund, not a request.
    - `lost_card` and `stolen_card` are rare (about 40–50 sentences each after filtering). Stolen-card sentences often concern stolen phones.
    - Sentence splitting is rule-based on `. ! ? ;` and line breaks. Run-on complaints stay long and are dropped by `MAX_WORDS`.
    """)
    return


@app.cell
def _(RAW_FILE, mo, pl):
    mo.stop(not RAW_FILE.exists(), mo.md(f"**Complaints file not found at `{RAW_FILE}`.**"))
    complaints = pl.read_parquet(RAW_FILE, columns=["company", "source", "ask"]).filter(
        pl.col("source") == "reclame_aqui"
    ).drop("source").with_row_index("complaint_id")
    # Company halves, alternating by size so both halves are balanced: A → train/validation, B → test
    _order = complaints.group_by("company").len().sort("len", descending=True)["company"].to_list()
    HALF = {c: "A" if i % 2 == 0 else "B" for i, c in enumerate(_order)}
    complaints = complaints.with_columns(half=pl.col("company").replace_strict(HALF))
    complaints.group_by("half").agg(companies=pl.col("company").n_unique(), complaints=pl.len()).sort("half")
    return (complaints,)


@app.cell
def _(MASKS, MAX_WORDS, MIN_WORDS, complaints, pl):
    _masked = pl.col("ask")
    for _pattern, _replacement in MASKS:
        _masked = _masked.str.replace_all(_pattern, _replacement)
    sentences = (
        complaints.with_columns(masked=_masked)
        .select("complaint_id", "company", "half", pl.col("masked").str.extract_all(r"[^.!?;\n]+[.!?]*").alias("sentence"))
        .explode("sentence", empty_as_null=True).with_columns(pl.col("sentence").str.strip_chars())
        .with_columns(words=pl.col("sentence").str.count_matches(r"\S+"))
        .filter(pl.col("words").is_between(MIN_WORDS, MAX_WORDS))
    )
    {"complaints": complaints.height, "sentences in length range": sentences.height}
    return (sentences,)


@app.cell
def _(ALLOWED_CAPS, MAX_MASKS, mo, pl, sentences):
    # Safety filter: only these sentences may later be shown to an LLM (plan, Privacy)
    _caps = pl.col("sentence").str.extract_all(r"\s(\p{Lu}\p{Ll}+)").list.eval(pl.element().str.strip_chars().str.to_lowercase())
    _checked = sentences.with_columns(
        masks=pl.col("sentence").str.count_matches(r"\[(NOME|NUMERO|OCULTO|EDITADO|EMAIL|URL)\]"),
        unknown_caps=_caps.list.eval(pl.element().filter(~pl.element().is_in(list(ALLOWED_CAPS)))).list.len(),
    )
    _ok = (~pl.col("sentence").str.contains(r"\d{4,}|\[(EDITADO|EMAIL|URL)\]")) & (pl.col("masks") <= MAX_MASKS) & (pl.col("unknown_caps") == 0)
    safe = _checked.filter(_ok).drop("unknown_caps")
    mo.vstack([
        mo.md(f"**{safe.height:,}** of {sentences.height:,} sentences pass the safety filter ({safe.height / sentences.height:.0%}). Dropped sample:"),
        mo.ui.table(_checked.filter(~_ok).sample(20, seed=0).select("sentence", "masks", "unknown_caps")),
    ])
    return (safe,)


@app.cell
def _(INTENT_THEMES, THEMES, pl, safe):
    _theme = pl.lit(None, dtype=pl.String)
    for _name, _rx in reversed(THEMES.items()):
        _theme = pl.when(pl.col("sentence").str.to_lowercase().str.contains(_rx)).then(pl.lit(_name)).otherwise(_theme)
    _intent_of = {t: i for i, ts in INTENT_THEMES.items() for t in ts}
    tagged = safe.with_columns(theme=_theme).with_columns(intent=pl.col("theme").replace_strict(_intent_of, default=None))
    tagged.group_by("theme", "intent", "half").len().pivot("half", index=["theme", "intent"], values="len").fill_null(0).sort("A", descending=True)
    return (tagged,)


@app.cell
def _(MIN_TERM_COUNT, STOPWORDS, TOP_TERMS, pl, tagged):
    # Distinctive terms per theme and half: log-odds with an informative Dirichlet prior (Monroe et al. 2008)
    _tokens = tagged.filter(pl.col("theme").is_not_null()).select(
        "half", "theme", pl.col("sentence").str.to_lowercase().str.extract_all(r"[a-zà-ú]{2,}").alias("w"))
    _bigrams = _tokens.with_columns(pl.col("w").list.eval(pl.concat_str([pl.element(), pl.element().shift(-1)], separator=" ").drop_nulls()))
    _terms = pl.concat([_tokens, _bigrams]).explode("w", empty_as_null=True).drop_nulls().filter(
        ~pl.col("w").str.split(" ").list.eval(pl.element().is_in(list(STOPWORDS))).list.all())
    _n = _terms.group_by("half", "theme", "w").len("n").with_columns(
        n_all=pl.col("n").sum().over("half", "w"), n_theme=pl.col("n").sum().over("half", "theme"), N=pl.col("n").sum().over("half"))
    _n = _n.with_columns(prior=0.01 * pl.col("n_all"), rest=pl.col("n_all") - pl.col("n"), rest_total=pl.col("N") - pl.col("n_theme"))
    terms = _n.with_columns(z=(
        ((pl.col("n") + pl.col("prior")) / (pl.col("n_theme") - pl.col("n"))).log()
        - ((pl.col("rest") + pl.col("prior")) / (pl.col("rest_total") - pl.col("rest"))).log()
    ) / (1 / (pl.col("n") + pl.col("prior")) + 1 / (pl.col("rest") + pl.col("prior"))).sqrt()).filter(
        pl.col("n") >= MIN_TERM_COUNT).sort("z", descending=True).group_by("half", "theme", maintain_order=True).head(TOP_TERMS)
    terms.filter(pl.col("half") == "A").group_by("theme", maintain_order=True).agg(pl.col("w").str.join(", ").alias("top terms (half A)"))
    return (terms,)


@app.cell
def _(INFORMAL, complaints, pl):
    # Register, measured per half on whole complaints; only shapes and shares are kept, never values
    _low = complaints.with_columns(t=pl.col("ask").str.to_lowercase())
    register = {}
    for (_half,), _d in _low.group_by("half", maintain_order=True):
        _words = _d["t"].str.extract_all(r"[a-zà-ú]+")
        register[_half] = {
            "openers": _d["t"].str.extract(r"^\W*((?:[a-zà-ú]+[ ,]+){2}[a-zà-ú]+)").str.replace_all(r"[ ,]+", " ").value_counts().drop_nulls().sort("count", descending=True).head(20)["t"].to_list(),
            "informal_spelling_share": {w: round(float(_words.list.contains(w).mean()), 4) for w in INFORMAL},
            "money_formats": _d["t"].str.extract_all(r"r\$ ?\d[\d.,]*|\d[\d.,]* reais").explode().drop_nulls().str.replace_all(r"\d", "9").value_counts().sort("count", descending=True).head(8)["t"].to_list(),
            "date_formats": _d["t"].str.extract_all(r"\b(?:dia \d{1,2}(?:/\d{1,2})?(?:/\d{2,4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?|ontem|anteontem|hoje|semana passada|m[eê]s passado)\b").explode().drop_nulls().str.replace_all(r"\d", "9").value_counts().sort("count", descending=True).head(8)["t"].to_list(),
            "all_caps_share": round(float(_d["ask"].str.contains(r"\b[A-ZÀ-Ú]{4,}(?:\s+[A-ZÀ-Ú]{4,}){3,}").mean()), 4),
            "no_accent_nao_share": round(float(_d["t"].str.contains(r"\bnao\b").mean()), 4),
        }
    register["A"]
    return (register,)


@app.cell
def _(INTENT_THEMES, OUT_DIR, complaints, pl, register, tagged, terms, yaml):
    # One style card per half; the phrase bank keeps every tagged, filtered sentence with its half
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    phrase_bank = tagged.filter(pl.col("theme").is_not_null()).select("complaint_id", "company", "half", "theme", "intent", "sentence", "words")
    phrase_bank.write_parquet(OUT_DIR / "phrase_bank.parquet")
    for _half in ("A", "B"):
        _t, _p = terms.filter(pl.col("half") == _half), phrase_bank.filter(pl.col("half") == _half)
        _card = {"half": _half, "companies": sorted(complaints.filter(pl.col("half") == _half)["company"].unique().to_list()),
                 "register": register[_half], "service_expressions": _t.filter(pl.col("theme") == "oos_service")["w"].to_list(),
                 "intents": {_i: {"themes": _ts, "sentences": _p.filter(pl.col("theme").is_in(_ts)).height,
                                  "terms": {_th: _t.filter(pl.col("theme") == _th)["w"].to_list() for _th in _ts}}
                             for _i, _ts in INTENT_THEMES.items()}}
        (OUT_DIR / f"style_cards.{_half}.yaml").write_text(yaml.safe_dump(_card, allow_unicode=True, sort_keys=False))
    phrase_bank.group_by("intent", "half").len().pivot("half", index="intent", values="len").sort("A", descending=True)
    return (phrase_bank,)


@app.cell
def _(mo, phrase_bank):
    mo.ui.table(phrase_bank.sample(200, seed=0).select("half", "theme", "intent", "sentence"))
    return


@app.cell
def _():
    # next:
    return


if __name__ == "__main__":
    app.run()
