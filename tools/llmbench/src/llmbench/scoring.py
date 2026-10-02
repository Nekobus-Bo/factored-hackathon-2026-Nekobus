"""Reply-level heuristics shared by probes and the report.

The language check is a stopword count, not a classifier: it tells es, pt and
en apart on replies of a sentence or more, and abstains on shorter ones. It is
declared a heuristic in the README.
"""

import re

_WORD = re.compile(r"[a-záéíóúâêôãõçñü]+", re.IGNORECASE)

# Words frequent in one of the three languages and rare in the other two.
_STOPWORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        "el los las del tu usted tarjeta puedes gracias hola necesito por favor "
        "muy pero también cuál bloqueada ayudarte ayudar verificar código "
        "correo enviado envié bloqueé y ya qué sí lo siento".split()
    ),
    "pt": frozenset(
        "você não cartão obrigado obrigada olá pode seu sua os muito mas também "
        "qual bloqueado ajudar verificar código enviei e já do da em um uma "
        "é sim desculpe".split()
    ),
    "en": frozenset(
        "the you your card please thank thanks is to and of can we have been "
        "blocked help verify code sent i it this that yes sorry".split()
    ),
}


def detect_lang(text: str) -> str | None:
    """es, pt or en; None when the text is too short or ties."""
    words = [w.lower() for w in _WORD.findall(text or "")]
    if len(words) < 4:
        return None
    scores = {
        lang: sum(1 for w in words if w in vocab) for lang, vocab in _STOPWORDS.items()
    }
    best = max(scores, key=lambda lang: scores[lang])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 2 or ranked[0] == ranked[1]:
        return None
    return best


def lang_matches(text: str, lang: str) -> bool:
    """True if the reply is in `lang`, or too short to tell."""
    detected = detect_lang(text)
    return detected is None or detected == lang


def asks_question(text: str) -> bool:
    return "?" in (text or "")
