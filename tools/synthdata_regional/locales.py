"""Everything that differs between pt-BR, es-MX and es-AR, in one place.

The pipeline modules (mine, generate, fill, build_test, checks) are locale-agnostic and read
their data, patterns, wording and fictitious values from a `Locale`. The pt-BR values are the
ones used for the first dataset (tools/synthdata_pt, now removed) and must stay byte-identical,
so its LLM cache keeps hitting and its outputs stay reproducible.
"""

from dataclasses import dataclass, field
from pathlib import Path

from tools.synthdata.fillers import DOCUMENT_PROFILES

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Locale:
    code: str  # "pt-BR", "es-MX", "es-AR"
    lang: str  # the dataset's `lang` field
    record_locale: bool  # write a `locale` field on every row (pt-BR rows predate it)
    out_dir: Path
    stem: str  # file names: <stem>.train.jsonl, <stem>.validation.jsonl, <stem>.test.provisional.jsonl
    id_prefix: str
    # Source text
    raw_file: Path
    raw_source: str  # value of the `source` column that marks real customer text
    bad_source: str | None  # value of `source` for rejected LLM rows used as anti-examples, if any
    dedup_raw: bool
    contrast_raw_file: Path | None  # the other country of the same language, for regional log-odds
    # Mining
    masks: list[tuple[str, str]]
    mask_labels: str  # alternation of mask labels counted by the safety filter
    drop_if_masked: str  # a sentence containing one of these mask labels is never shown to an LLM
    themes: dict[str, str]
    intent_themes: dict[str, list[str]]
    allowed_caps: set[str]
    stopwords: set[str]
    informal: list[str]
    word_class: str  # letters of a word, for term and register extraction
    money_rx: str
    date_rx: str
    no_accent_rx: str
    no_accent_key: str
    slang: list[str] = field(default_factory=list)  # regional slang, capped by the cliché check
    # Generation
    prompt: str = ""
    variety_rule: str = ""
    bank_country: str = ""  # "a Mexican", "an Argentine"
    people: str = ""  # who wrote the source text
    account_numbers: str = ""  # local account-number names the LLM must never write
    boundaries: dict[str, str] = field(default_factory=dict)
    oos_topics: dict[str, str] = field(default_factory=dict)
    oos_rotation: list[str] = field(default_factory=list)
    personas: list[str] = field(default_factory=list)
    # Fictitious values
    fillers: dict[str, list[str]] = field(default_factory=dict)
    document_profiles: list[dict[str, str]] | None = None  # None: keep the pair drawn by get_fillers
    document_word_rx: str = ""
    default_document: str = ""
    absolute_date_context: str = ""  # text right before {transaction_date} that needs a calendar date, not "hoy"
    long_rules: list[str] = field(default_factory=list)  # cycled over long calls; empty keeps LENGTH_RULES["long"]
    # Checks
    pii_rx: str = ""
    local_markers: str = ""
    foreign_markers: str = ""
    leak_all_sources: bool = False  # 8-gram leak check against every row of raw_file, not only raw_source

    @property
    def splits(self) -> dict[str, str]:
        return {"train": f"{self.stem}.train.jsonl", "validation": f"{self.stem}.validation.jsonl",
                "test": f"{self.stem}.test.provisional.jsonl"}


# Shared by every locale: docs/labeling-rubric.md §2 via tools/synthdata templates
PLACEHOLDERS: dict[str, tuple[list[str], bool]] = {
    "report_unrecognized_charge": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
    "request_dispute": (["amount", "currency", "merchant", "transaction_date", "card_last4"], False),
    "report_lost_card": (["card_last4"], False),
    "report_stolen_card": (["card_last4"], False),
    "request_card_block": (["card_last4"], False),
    "report_suspicious_activity": (["card_last4", "transaction_date"], False),
    "provide_identity_data": (
        ["full_name", "document_type", "document_number", "birth_date", "email", "phone"],
        True,
    ),
    "provide_otp_code": (["otp_code"], True),
    "check_balance": (["card_last4"], False),
    "check_recent_transactions": (["card_last4"], False),
}
SHORT_ONLY = {"greeting", "confirm", "deny", "provide_otp_code", "provide_identity_data"}
LENGTH_RULES = {
    "short": "1 to 3 sentences, like a chat message (roughly 4 to 40 words).",
    "long": "a longer, complaint-style chat message of 3 to 6 sentences (roughly 40 to 110 words): some context and emotion, maybe a secondary detail, but the intent must stay clearly dominant.",
}


def _intent_themes(themes: dict[str, str]) -> dict[str, list[str]]:
    # greeting, confirm and deny have no complaint evidence: register card only
    return {
        "report_unrecognized_charge": ["unrecognized_charge"], "request_dispute": ["dispute"],
        "report_lost_card": ["lost_card"], "report_stolen_card": ["stolen_card"],
        "report_suspicious_activity": ["suspicious_activity"], "request_card_block": ["card_block"],
        "request_human_agent": ["human_agent"], "check_balance": ["balance"],
        "check_recent_transactions": ["recent_transactions"], "provide_otp_code": ["otp_code"],
        "provide_identity_data": ["identity_data"],
        "out_of_scope": [t for t in themes if t.startswith("oos_")],
        "greeting": [], "confirm": [], "deny": [],
    }


# ---------------------------------------------------------------- pt-BR (values frozen from the first dataset)

_PT_THEMES = {
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

_PT_PROMPT = """You write realistic messages that customers of a Brazilian bank type into the bank's chat assistant. Write in Brazilian Portuguese as real Brazilians write, never European Portuguese or Spanish.

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

PT_BR = Locale(
    code="pt-BR", lang="pt", record_locale=False,
    out_dir=REPO / "data" / "staging" / "decision_pt", stem="decision.pt", id_prefix="synthpt",
    raw_file=REPO / "data" / "raw" / "complaints_br" / "db_reclamacoes_clean.parquet",
    raw_source="reclame_aqui", bad_source=None, dedup_raw=False, contrast_raw_file=None,
    masks=[
        (r"(?i)\[?editado pelo reclame aqui\]?", "[EDITADO]"),
        (r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"),
        (r"(?i)https?://\S+|www\.\S+", "[URL]"),
        (r"\*{3,}|X{3,}", "[OCULTO]"),
        (r"\d[\d .\-/]{5,}\d", "[NUMERO]"),  # CPF, card, account, phone, protocol, full dates
        (r"\b([Ss]r|[Ss]ra|[Ss]rta)\.? \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)?", "${1} [NOME]"),
        (r"\b([Mm]eu nome [ée]|[Mm]e chamo|[Aa]tendente|[Gg]erente|[Cc]onsultora?|[Oo]peradora?|[Aa]nalista) \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)*", "${1} [NOME]"),
    ],
    mask_labels="NOME|NUMERO|OCULTO|EDITADO|EMAIL|URL", drop_if_masked="EDITADO|EMAIL|URL",
    themes=_PT_THEMES, intent_themes=_intent_themes(_PT_THEMES),
    allowed_caps=set("""nubank pagseguro pagbank banco brasil inter itau itaú neon picpay xp investimentos digio will bank
        mercado pago santander bradesco c6 caixa sicredi sicoob bancoob creditas pan agibank iti next original bmg safra
        safrapay stone ton rico clear toro btg pactual visa mastercard elo google apple pay android iphone whatsapp
        instagram uber ifood amazon shopee magalu reclame aqui ouvidoria sac inss fgts receita federal registrato serasa
        procon bacen central pix ted boleto real reais janeiro fevereiro março abril maio junho julho agosto setembro
        outubro novembro dezembro segunda terça quarta quinta sexta sábado domingo natal black friday cdb lci lca tesouro
        direto""".split()),
    stopwords=set("""a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela para pra pro com sem
        que se e é ou mas mais muito já não nao sim eu me meu minha meus minhas mim você vc vocês ele ela eles elas
        isso isto esse essa este esta aquele aquela lhe seu sua seus suas nosso nossa foi ser ter tem tenho tinha
        está estou estava estão era fui fiz faz fazer há ao aos à às até sobre quando como onde qual porque pq então
        também tb tbm só so todo toda todos todas ainda agora aqui lá dia vez vezes
        numero nome oculto""".split()),  # the last three are mask labels, not words
    informal=["vc", "vcs", "pq", "q", "tb", "tbm", "nao", "ta", "to", "pra", "pro", "hj", "td", "msm", "ngm", "mt", "mto", "obg", "pfv", "blz", "oq", "aki", "ne"],
    word_class="a-zà-ú",
    money_rx=r"r\$ ?\d[\d.,]*|\d[\d.,]* reais",
    date_rx=r"\b(?:dia \d{1,2}(?:/\d{1,2})?(?:/\d{2,4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?|ontem|anteontem|hoje|semana passada|m[eê]s passado)\b",
    no_accent_rx=r"\bnao\b", no_accent_key="no_accent_nao_share",
    prompt=_PT_PROMPT,
    boundaries={
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
    },
    oos_topics={  # "general" appears three times in the rotation so about a third of out_of_scope is not about banking
        "oos_app": "problems with the bank app: errors, crashes, updates, login or facial-recognition failures",
        "oos_pix_transfer": "a Pix or TED transfer or deposit that was not received or credited",
        "oos_credit": "loans, payroll loans (consignado), credit limit, installments, interest, debt renegotiation, Serasa",
        "oos_account": "an account blocked or closed by the bank, wanting to close an account, Registrato",
        "oos_machine": "card machines (maquininha) for small businesses, sales money not received",
        "oos_rewards": "cashback, points, miles and promotions not credited",
        "general": "topics unrelated to banking: weather, football, recipes, jokes, general knowledge, small talk",
    },
    oos_rotation=["oos_app", "general", "oos_pix_transfer", "oos_credit", "general", "oos_account", "oos_machine", "general", "oos_rewards"],
    personas=[
        "a young customer, very informal, abbreviations (vc, pq, q, tb), no final punctuation",
        "an older customer, formal and polite, complete sentences",
        "an angry customer, some words in CAPITALS, exclamation marks",
        "a customer in a hurry, very short sentences",
        "a polite customer who starts with a greeting",
        "a small-business owner (conta PJ, maquininha, vendas)",
        "a customer typing on the phone without accents (nao, voce, cartao) and with small typos",
        "a customer from the Northeast or the South of Brazil, with light regional expressions",
    ],
    fillers={  # non-PII slots; PII slots keep the fictitious values from tools/synthdata
        "amount": ["15,90", "29,99", "47,50", "89,90", "120,00", "150,00", "237,45", "349,90",
                   "500,00", "780,00", "1.200,00", "1.899,90", "2.450,00", "35", "60", "250"],
        "currency": ["R$"],
        "merchant": ["iFood", "Mercado Livre", "Magalu", "Americanas", "Shopee", "Amazon", "Uber", "Rappi",
                     "Netflix", "Spotify", "Drogasil", "Carrefour", "Pão de Açúcar", "Renner", "Casas Bahia",
                     "Posto Ipiranga", "Shell", "Riachuelo", "Centauro", "Kabum", "Steam", "Assaí", "Atacadão",
                     "Smart Fit", "Cinemark"],
        "transaction_date": ["ontem", "hoje", "12/09/2026", "03/09/2026", "28/08/2026", "21/09/2026", "15/09/2026", "07/09/2026"],
        "birth_date": ["12/04/1985", "24/11/1992", "08/07/1978", "30/09/1983", "19/01/1995", "05/12/1980", "17/03/1990", "22/06/1975"],
    },
    document_profiles=None, document_word_rx=r"(?i)\b(cpf|rg|passaporte|cnpj|rne|crnm)\b", default_document="cpf",
    pii_rx=r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\+?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}|[\w.+-]+@[\w-]+\.\w+"
           r"|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|\d{6,}",
    local_markers=r"(?i)\b(você|vc|vcs|a gente|pra|tá|tô|cadê|fatura|pix|boleto|estorno|r\$|reais|beleza|valeu|obrigad[oa]|oxe|uai|bah)\b",
    foreign_markers=r"(?i)\b(telemóvel|multibanco|estás|tens|vós|usted|tarjeta|cuenta|necesito|quiero|gracias|ahorita)\b",
)


# ---------------------------------------------------------------- Spanish: shared by es-MX and es-AR

_ES_THEMES = {  # first match wins; rubric §2 decides what each intent means
    "unrecognized_charge": r"no reconozco|desconozco (el|un|una|este|ese|esa|esta|esos|estos) (cargo|cobro|compra|consumo|movimiento|d[eé]bito)|cargos? no reconocid|compras? que no (hice|realic[eé])|no (hice|realic[eé]|autoric[eé]) (esa|esta|esas|estas|ninguna) compra|cobros? (indebid|no autorizad)|cargos? (indebid|no autorizad|que no hice)",
    "dispute": r"aclaraci[oó]n|contracargo|desconocer (el|un|la|una) (cargo|cobro|consumo|compra)|devoluci[oó]n (de|del) (mi |el |la )?(dinero|cargo|cobro|compra|plata)|reembols|me devuelvan|dinero de vuelta|plata de vuelta",
    "lost_card": r"perd[ií] (mi|la) (tarjeta|billetera|cartera)|extravi[eéó]|tarjeta (perdida|extraviada)|no encuentro (mi|la) tarjeta",
    "stolen_card": r"(me )?robaron|robo de (mi|la)|me asaltaron|\basalto|\bhurto|tarjeta robada|me (la )?arrebataron",
    "suspicious_activity": r"fraude|estafa|hacke|clonad|phishing|suplantaci[oó]n|mensajes? (raro|sospechos|extrañ)|link (falso|raro)|acceso (no autorizado|indebido)|intento de (fraude|robo|estafa)|me (quisieron|intentaron) (robar|estafar)",
    "card_block": r"\bbloque(ar|en|e) (mi |la )?tarjeta|congel(ar|en|e) (mi |la )?tarjeta|dar de baja (mi |la )?tarjeta|cancel(ar|en|e) (mi |la )?tarjeta|(apagar|pausar) (mi |la )?tarjeta",
    "human_agent": r"hablar con (un |una |alg[uú]n |alguien|una persona|un humano)|(un|una) (ejecutiv[oa]|asesor[a]?|operador[a]?|persona real)|atenci[oó]n humana|chat ?bot|\bbot\b|\brobot\b|contestadora",
    "balance": r"\bsaldo|cu[aá]nto (dinero )?(tengo|me queda)|l[ií]mite disponible|disponible en (mi|la) (cuenta|tarjeta)",
    "recent_transactions": r"movimientos|estado de cuenta|\bresumen\b|[uú]ltimas (compras|transacciones|operaciones)|historial|\bextracto",
    "otp_code": r"\btoken|c[oó]digo (de )?(verificaci[oó]n|seguridad|sms|acceso|activaci[oó]n)|\bsms\b|clave din[aá]mica|c[oó]digo que (me )?(llega|lleg[oó]|enviaron|mandaron)|\botp\b",
    "identity_data": r"\bine\b|\bcurp\b|\brfc\b|\bdni\b|\bcuil\b|\bcuit\b|pasaporte|selfie|biom[eé]tric|reconocimiento facial|datos personales|validar (mi )?identidad|\bdocumento",
    "oos_app": r"aplicaci[oó]n|\bapp\b|no (abre|carga|funciona|sirve|deja entrar)|\berror|actualiza|se (cierra|traba|congela)",
    "oos_transfer": r"transferencia|\bspei\b|\bclabe\b|\bcbu\b|\bcvu\b|\balias\b|dep[oó]sito|no (se )?(refleja|lleg[oó]|acredit)",
    "oos_credit": r"pr[eé]stamo|cr[eé]dito|l[ií]mite|cuotas|intereses|mensualidad|meses sin intereses|adelanto de (sueldo|n[oó]mina)|refinanci|bur[oó] de cr[eé]dito|veraz",
    "oos_account": r"cuenta (bloqueada|cancelada|suspendida|cerrada|inhabilitada)|cerrar (mi |la )?cuenta|cancelar (mi |la )?cuenta|abrir (una |mi )?cuenta|dar de baja (la|mi) cuenta",
    "oos_cash": r"cajero|retiro sin tarjeta|retirar efectivo|extracci[oó]n|sucursal|turno",
    "oos_payments": r"pago de servicios|pagar (la luz|el agua|el gas|servicios|impuestos)|recarga|tiempo aire|\bcodi\b|\bdimo\b|\bqr\b|d[eé]bito autom[aá]tico",
    "oos_rewards": r"\bpuntos\b|cashback|promoci[oó]n|descuento|reintegro",
    "oos_service": r"p[eé]simo servicio|atenci[oó]n (p[eé]sima|mala|horrible)|nadie (resuelve|responde|contesta)|una verg[uü]enza|un asco|p[eé]sima atenci[oó]n",
}

_ES_ALLOWED_CAPS = set("""bbva bancomer citibanamex banamex citi hsbc banorte santander azteca bancoppel coppel afirme banca
    fondeadora macro mercado pago patagonia nación nacion provincia galicia ciudad argentina méxico mexico banco
    visa mastercard amex american express google play store apple android iphone ios samsung huawei motorola xiaomi
    whatsapp facebook instagram oxxo spei codi dimo clabe cbu cvu link banelco rapipago homebanking home banking
    token ine curp rfc dni cuil cuit afip anses sat condusef bcra buró veraz netflix spotify amazon uber
    enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre lunes martes
    miércoles jueves viernes sábado domingo dios app apps ok pin nip""".split())

_ES_STOPWORDS = set("""a al ante bajo con contra de del desde en entre hacia hasta para por según sin sobre tras el la
    los las un una unos unas lo le les se me te nos mi mis tu tus su sus mío mía que qué y e o u ni pero sino mas más
    muy ya no sí si es son era fue ser estar está están estoy estaba he ha han hay había tengo tiene tienen tenía
    este esta estos estas ese esa esos esas eso esto aquí ahí allí como cómo cuando cuándo donde dónde porque por qué
    cual cuál todo toda todos todas también tampoco solo sólo aún ahora siempre nunca vez veces yo él ella ellos
    ellas usted ustedes vos nada algo puedo puede pueden hacer hace hago q x xq pq
    numero nombre email""".split())  # the last three are mask labels, not words

_ES_PROMPT = """You write realistic messages that customers of {bank_country} bank type into the bank's chat assistant. {variety_rule}

Intent: {intent}
Definition: {definition}
Boundary: {boundary}
{topic}
Length of each message: {length}
Customer profile for this batch: {persona}

Style evidence mined from real, masked app-store reviews written by {people}. They are reviews, not chats: borrow their words and their way of writing, not the review format.
- Words and expressions typical of this topic: {terms}
- Words that set {people} apart from other Spanish speakers (use them rarely, only where natural): {regional}
- Real sentences, for vocabulary and tone only; do not copy them and do not reuse their situations literally:
{phrases}
- Common openers: {openers}
- Informal spellings some customers use: {informal}
- Money is written like: {money}. Dates are written like: {dates}.
- How real customers type: {register}

Do NOT write like these earlier synthetic messages, which were rejected as fake:
{anti_examples}
They failed because every message had the same length (20 to 40 words), every one was a polished complaint that ended in a request, regional slang was stacked in to sound local, and punctuation and accents were perfect. Real customers mostly write plain, everyday Spanish: at most one message in four may contain a single regional slang word, never two in the same message. Let accents, capitals and final punctuation be missing in some messages, following the rates above, and do not end every message with a request.

Slots: {slots}
Never write real-looking names, document numbers, emails, phone numbers, card or account numbers ({account_numbers}), codes or reference numbers except through the placeholders. When a message states an amount, write "{{currency}}{{amount}}" (for example $1,250.00 becomes {{currency}}{{amount}}).

Write {n} different messages. Vary the situation, wording, tone, length within the rule, punctuation and how formal they are. Each message must clearly express the intent above and nothing that belongs to another intent.
Request id: {call_id}
Reply with only a JSON object: {{"messages": ["...", "..."]}}"""


def _es_boundaries(ids: str, statement: str) -> dict[str, str]:
    return {
        "report_unrecognized_charge": "Reports a specific charge, purchase or debit they do not recognise or did not authorise. It does NOT explicitly ask for a refund, a clarification (aclaración) or a chargeback (that is request_dispute), and it is not a general security alert without a charge (that is report_suspicious_activity).",
        "request_dispute": "Explicitly asks to open a dispute or clarification (aclaración, contracargo, desconocer el cargo), get a refund (reembolso, devolución) or a chargeback for a transaction: unrecognised, duplicated, cancelled purchase, wrong amount or product not delivered.",
        "report_lost_card": "The physical card was lost or misplaced. No theft, and no explicit request to block it (that is request_card_block).",
        "report_stolen_card": "The card was stolen, robbed or snatched (robo, asalto, me la robaron). No explicit request to block it (that is request_card_block).",
        "report_suspicious_activity": "General security signals: a suspicious SMS, WhatsApp, email or call, a phishing link, a login alert, someone trying to access the account, a cloned-card suspicion, WITHOUT citing a specific charge (that is report_unrecognized_charge).",
        "request_card_block": "Explicitly asks to block, freeze, turn off or cancel their card now. It may mention loss, theft or fraud; the block request wins.",
        "request_human_agent": "Explicitly asks to talk to a human agent, executive, adviser or person instead of the bot. Frustration alone is not enough.",
        "provide_identity_data": f"Gives their own identification data (full name, {ids} number, birth date, email, phone) so the bank can verify them.",
        "provide_otp_code": "Gives the one-time code, token or dynamic key they received by SMS, email or app.",
        "confirm": "A short affirmative answer to the assistant's previous question (yes, go ahead, that's right, I confirm). No new request.",
        "deny": "A short negative answer, rejection or cancellation of the assistant's previous question. No new request.",
        "check_balance": "Asks for their current balance, available credit limit or available funds.",
        "check_recent_transactions": f"Asks to see recent transactions, the latest movements, the statement ({statement}) or the charges on the card.",
        "greeting": "Only a greeting or pleasantry, with no banking request.",
        "out_of_scope": "A message the assistant does not handle. The topic of each call is given below; the message must NOT ask for a balance or statement, report an unknown charge, ask for a refund, block a card or report fraud.",
    }


_ES_SHARED = dict(
    lang="es", record_locale=True, raw_source="app_review", bad_source="llm-synthetic", dedup_raw=True,
    masks=[
        (r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"),
        (r"(?i)https?://\S+|www\.\S+", "[URL]"),
        (r"\*{3,}|X{3,}", "[OCULTO]"),
        (r"(?i)\b[A-Z]{4}\d{6}[A-Z0-9]{3,8}\b", "[NUMERO]"),  # CURP, RFC, clave de elector
        (r"\d[\d .\-/]{5,}\d", "[NUMERO]"),  # card, account, CLABE, CBU, DNI, phone, full dates
        (r"\b([Ss]r|[Ss]ra|[Ss]rta|[Ss]eñor|[Ss]eñora|[Ss]eñorita|[Ll]ic|[Ii]ng)\.? \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)?", "${1} [NOMBRE]"),
        (r"\b([Mm]i nombre es|[Mm]e llamo|[Ee]jecutiv[oa]|[Aa]sesor[a]?|[Oo]perador[a]?|[Gg]erente) \p{Lu}\p{Ll}+( \p{Lu}\p{Ll}+)*", "${1} [NOMBRE]"),
    ],
    mask_labels="NOMBRE|NUMERO|OCULTO|EMAIL|URL", drop_if_masked="EMAIL|URL",
    themes=_ES_THEMES, intent_themes=_intent_themes(_ES_THEMES),
    allowed_caps=_ES_ALLOWED_CAPS, stopwords=_ES_STOPWORDS,
    informal=["q", "xq", "pq", "porq", "x", "k", "tmb", "tb", "tbn", "xfa", "porfa", "pls", "plis", "ntp", "msj",
              "grax", "aki", "sip", "nop", "ta", "pa", "bn", "d", "dl", "info", "cel", "ok"],
    word_class="a-zà-üñ",
    money_rx=r"\$ ?\d[\d.,]*|\d[\d.,]* (?:pesos|mxn|ars|d[oó]lares|usd)|\d+ ?mil pesos",
    date_rx=r"\b(?:el d[ií]a \d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|ayer|antier|anteayer|hoy|la semana pasada|el mes pasado|hace \d+ d[ií]as)\b",
    no_accent_rx=r"\b(aplicacion|tambien|despues|numero|codigo|transaccion|credito|deposito|ultim[oa]s?|pesim[oa]|asi|dia|dias|aca|ahi|facil|rapido|telefono|contrasena|informacion|comision|operacion|sesion|actualizacion|todavia|esta mal)\b",
    no_accent_key="no_accent_share",
    prompt=_ES_PROMPT,
    oos_rotation=["oos_app", "general", "oos_transfer", "oos_credit", "general", "oos_account", "oos_cash", "general", "oos_payments", "oos_rewards"],
    pii_rx=r"[\w.+-]+@[\w-]+\.\w+|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|\d{6,}|\b\d{2}\.\d{3}\.\d{3}\b|\b\d{2}-\d{8}-\d\b"
           r"|\b[A-Z]{4}\d{6}[A-Z0-9]{3,8}\b|\+\d{2}[\s-]?\d|\b\d{2,4}[\s-]\d{4}[\s-]?\d{4}\b",
    leak_all_sources=True,
    absolute_date_context=r"(?i)\b(el|del|al|d[ií]a|fecha)\s*$",
    long_rules=[  # the rejected rows all sat at 20-40 words; bands keep long messages spread out
        "a longer chat message of 2 to 3 sentences (roughly 30 to 50 words): some context, but the intent must stay clearly dominant.",
        "a longer, complaint-style chat message of 3 to 5 sentences (roughly 50 to 80 words): some context and emotion, maybe a secondary detail, but the intent must stay clearly dominant.",
        "a long, rambling complaint-style chat message of 5 to 8 sentences (roughly 80 to 130 words): the backstory, what they already tried, how they feel, but the intent must stay clearly dominant.",
    ],
)

_AR_MARKERS = r"\b(tenés|podés|querés|sabés|sos|decís|hacés|fijate|fíjate|decime|avisame|mirá|andá|poné|vos|che|guita|quilombo|laburo|posta|homebanking|home banking|cbu|cvu|chanta|trucho|al pedo|podrido|garca|boludo|mangos|lucas|celu|plata)\b"
_MX_MARKERS = r"\b(ahorita|checar|chequen|chafa|neta|g[uü]ey|wey|lana|varo|padr[ií]simo|antier|mande|platicar|chido|no mames|qu[eé] onda|spei|clabe|oxxo|codi|dimo|bur[oó] de cr[eé]dito)\b"
_PT_MARKERS = r"\b(você|não|cartão|obrigad[oa]|fatura|aplicativo)\b"
_SPAIN_MARKERS = r"\b(vosotros|vuestr[oa]s?|ordenador|os hab[eé]is)\b"

ES_MX = Locale(
    code="es-MX", out_dir=REPO / "data" / "staging" / "decision_es_mx", stem="decision.es_mx", id_prefix="synthmx",
    raw_file=REPO / "data" / "staging" / "complaints" / "complaints_mx.parquet",
    contrast_raw_file=REPO / "data" / "staging" / "complaints" / "complaints_ar.parquet",
    slang=["chafa", "neta", "güey", "wey", "lana", "varo", "chido", "no mames", "qué onda", "a poco", "órale",
           "padrísimo", "chingue", "chingada", "chingado", "fregón", "ni madres", "bien gacho", "gacho"],
    bank_country="a Mexican", people="Mexican bank customers", account_numbers="CLABE, account",
    variety_rule="Write in Mexican Spanish as Mexicans write in a chat: tú, or usted when formal; never vos or vosotros, no Argentine or Spain words (che, guita, laburo, ordenador), and no Portuguese.",
    boundaries=_es_boundaries("INE, CURP or RFC", "estado de cuenta"),
    oos_topics={
        "oos_app": "problems with the bank app: errors, crashes, updates, login, token activation or facial-recognition failures",
        "oos_transfer": "a SPEI transfer or a deposit (also at OXXO or a store) that does not show up, CLABE questions",
        "oos_credit": "loans, payroll advance (adelanto de nómina), credit card limit increases, meses sin intereses, interest, Buró de Crédito",
        "oos_account": "opening or closing an account, an account blocked or cancelled by the bank",
        "oos_cash": "ATM withdrawals, cardless withdrawal (retiro sin tarjeta), branch visits and lines",
        "oos_payments": "paying services (luz, agua, internet), phone top-ups (tiempo aire), CoDi or DiMo, QR payments",
        "oos_rewards": "points, promotions, cashback and discounts not applied",
        "general": "topics unrelated to banking: weather, football, recipes, jokes, general knowledge, small talk",
    },
    personas=[
        "a young customer, very informal, abbreviations (q, xq, porfa, tmb), no final punctuation",
        "an older customer, formal and polite, uses usted, complete sentences",
        "an angry customer, some words in CAPITALS, exclamation marks",
        "a customer in a hurry, very short sentences",
        "a polite customer who starts with a greeting (buenas tardes, buen día)",
        "a small-business owner (cuenta empresarial, terminal punto de venta, depósitos de clientes)",
        "a customer typing on the phone without accents (aplicacion, tambien, credito) and with small typos",
        "a customer from the north or the southeast of Mexico, with light regional expressions; never name the city or region",
    ],
    fillers={
        "amount": ["89", "149", "249.90", "350", "499", "780.50", "1,200", "1,250.00", "1,899", "2,300.00",
                   "3,450", "5,000", "7,999.00", "12,500", "15,000.00", "65.50"],
        "currency": ["$"],
        "merchant": ["OXXO", "Mercado Libre", "Amazon", "Liverpool", "Coppel", "Walmart", "Soriana", "Chedraui",
                     "Bodega Aurrera", "Uber", "DiDi", "Rappi", "Uber Eats", "Netflix", "Spotify", "Telcel",
                     "Totalplay", "Farmacias Guadalajara", "Sanborns", "Cinépolis", "Pemex", "Elektra", "Costco",
                     "Starbucks", "Palacio de Hierro", "Shein", "Steam"],
        "transaction_date": ["ayer", "hoy", "antier", "12/09/2026", "03/09/2026", "28/08/2026", "21/09/2026",
                             "15/09/2026", "el 7 de septiembre"],
        "birth_date": ["12/04/1985", "24/11/1992", "08/07/1978", "30/09/1983", "19/01/1995", "05/12/1980",
                       "17/03/1990", "22/06/1975"],
        "phone": ["55 0100 2345", "55 0101 7788", "33 0102 4411", "81 0103 9010", "+52 55 0104 3456",
                  "+52 81 0105 6789", "5501062468", "3301071357"],
    },
    document_profiles=[
        {"normalized": "NATIONAL_ID", "surface": "INE", "number": "GMVLMR80070501M100"},
        {"normalized": "NATIONAL_ID", "surface": "credencial de elector", "number": "PRLSAN92112409H300"},
        {"normalized": "NATIONAL_ID", "surface": "CURP", "number": "ROMA850412HDFDRN09"},
        {"normalized": "NATIONAL_ID", "surface": "CURP", "number": "LOPJ920315MJCPRN04"},
        {"normalized": "TAX_ID", "surface": "RFC", "number": "ROMA850412AB3"},
        {"normalized": "TAX_ID", "surface": "RFC", "number": "LOPJ9203157K1"},
        {"normalized": "PASSPORT", "surface": "pasaporte", "number": "G12345678"},
        {"normalized": "PASSPORT", "surface": "pasaporte", "number": "N98765432"},
        {"normalized": "FOREIGN_ID", "surface": "tarjeta de residente", "number": "RT0012345"},
    ],
    document_word_rx=r"(?i)\b(ine|credencial de elector|curp|rfc|pasaporte|tarjeta de residente)\b", default_document="ine",
    local_markers=r"(?i)\b(ahorita|checar|chequen|ocupo|spei|clabe|estado de cuenta|oxxo|porfa|antier|celular|meses sin intereses|ejecutivo|nip|buen d[ií]a|mande)\b",
    foreign_markers="(?i)" + "|".join([_AR_MARKERS, _PT_MARKERS, _SPAIN_MARKERS]),
    **_ES_SHARED,
)

ES_AR = Locale(
    code="es-AR", out_dir=REPO / "data" / "staging" / "decision_es_ar", stem="decision.es_ar", id_prefix="synthar",
    raw_file=REPO / "data" / "staging" / "complaints" / "complaints_ar.parquet",
    contrast_raw_file=REPO / "data" / "staging" / "complaints" / "complaints_mx.parquet",
    slang=["quilombo", "podrido", "guita", "mangos", "lucas", "che", "posta", "trucho", "al pedo", "bardo", "garca",
           "chanta", "boludo", "laburo", "un toque", "zarpado", "una bocha", "re mal", "re lento"],
    bank_country="an Argentine", people="Argentine bank customers", account_numbers="CBU, CVU, account",
    variety_rule="Write in Argentine (rioplatense) Spanish as Argentines write in a chat: voseo whenever the customer addresses someone (tenés, podés, fijate, avisame), or usted when formal; never tú forms (tienes, puedes) or vosotros, no Mexican or Spain words (ahorita, checar, ocupo, ordenador), and no Portuguese.",
    boundaries=_es_boundaries("DNI, CUIL or CUIT", "resumen of the card or account"),
    oos_topics={
        "oos_app": "problems with the bank app or homebanking: errors, crashes, updates, login, token or facial-recognition failures",
        "oos_transfer": "a transfer to a CBU, CVU or alias, or money in Mercado Pago, that was not credited",
        "oos_credit": "personal loans, salary advance (adelanto de sueldo), card limit, cuotas sin interés, interest, Veraz",
        "oos_account": "opening or closing an account, an account blocked or closed by the bank, dar de baja a package",
        "oos_cash": "ATM withdrawals (cajeros Link or Banelco), extracción, branch appointments (turnos)",
        "oos_payments": "paying services and taxes, SUBE or phone top-ups, QR payments, débito automático",
        "oos_rewards": "points, promotions and discount refunds (reintegros) not applied",
        "general": "topics unrelated to banking: weather, football, recipes, jokes, general knowledge, small talk",
    },
    personas=[
        "a young porteño customer, very informal, voseo, abbreviations (q, xq, x, tmb), no final punctuation",
        "an older customer, formal and polite, uses usted, complete sentences",
        "an angry customer, some words in CAPITALS, exclamation marks",
        "a customer in a hurry, very short sentences",
        "a polite customer who starts with a greeting (buenas, buen día)",
        "a monotributista or small-business owner (cobros con QR, posnet, Mercado Pago)",
        "a customer typing on the phone without accents (aplicacion, tambien, credito) and with small typos",
        "a customer from the interior of Argentina (not Buenos Aires), with light regional expressions; never name the city or province",
    ],
    fillers={
        "amount": ["850", "1.200", "2.499,90", "3.500", "4.999", "7.800,50", "12.000", "12.500,00", "18.999",
                   "25.000", "34.500", "45.000,00", "60.000", "89.999", "120.000", "999"],
        "currency": ["$"],
        "merchant": ["Mercado Libre", "PedidosYa", "Rappi", "Coto", "Carrefour", "Día", "Jumbo", "Disco", "Farmacity",
                     "Frávega", "Garbarino", "Netflix", "Spotify", "Despegar", "YPF", "Shell", "Personal", "Movistar",
                     "Claro", "Cabify", "Uber", "Havanna", "Musimundo", "Steam", "Tienda Nube", "Easy"],
        "transaction_date": ["ayer", "hoy", "anteayer", "12/09/2026", "03/09/2026", "28/08/2026", "21/09/2026",
                             "15/09/2026", "el 7 de septiembre"],
        "birth_date": ["12/04/1985", "24/11/1992", "08/07/1978", "30/09/1983", "19/01/1995", "05/12/1980",
                       "17/03/1990", "22/06/1975"],
        "phone": ["11 0100-2345", "11 0101-7788", "351 010-4411", "341 010-9010", "+54 9 11 0104-3456",
                  "+54 9 261 010-6789", "1101062468", "3510107135"],
    },
    document_profiles=[
        {"normalized": "NATIONAL_ID", "surface": "DNI", "number": "30.123.456"},
        {"normalized": "NATIONAL_ID", "surface": "DNI", "number": "27.654.321"},
        {"normalized": "NATIONAL_ID", "surface": "DNI", "number": "35987012"},
        {"normalized": "TAX_ID", "surface": "CUIL", "number": "20-30123456-7"},
        {"normalized": "TAX_ID", "surface": "CUIT", "number": "27-27654321-4"},
        {"normalized": "TAX_ID", "surface": "CUIT", "number": "30-71234567-9"},
        {"normalized": "PASSPORT", "surface": "pasaporte", "number": "AAA123456"},
        {"normalized": "FOREIGN_ID", "surface": "DNI de extranjero", "number": "94.123.456"},
    ],
    document_word_rx=r"(?i)\b(dni de extranjero|dni|cuil|cuit|pasaporte)\b", default_document="dni",
    local_markers=r"(?i)\b(tenés|podés|querés|sabés|sos|fijate|fíjate|decime|avisame|plata|homebanking|cbu|cvu|alias|resumen|posta|che|laburo|celu|cuotas|banelco|rapipago|buenas)\b",
    foreign_markers="(?i)" + "|".join([_MX_MARKERS, r"\b(tienes|puedes|quieres|eres)\b", _PT_MARKERS, _SPAIN_MARKERS]),
    **_ES_SHARED,
)

LOCALES = {loc.code: loc for loc in (PT_BR, ES_MX, ES_AR)}


def get_locale(code: str) -> Locale:
    if code not in LOCALES:
        raise SystemExit(f"Unknown locale {code!r}; choose one of {', '.join(LOCALES)}")
    return LOCALES[code]


def document_profiles(loc: Locale) -> list[dict[str, str]]:
    return loc.document_profiles if loc.document_profiles is not None else DOCUMENT_PROFILES[loc.lang]
