"""Markets the system serves (ADR-0014).

A locale names a market: its language and its country. The language drives replies
and the per-language fallbacks; the locale lets thresholds, metrics and masking rules
differ by market. The set is closed: a new market is a reviewed change here.
"""

from typing import Literal, get_args

Locale = Literal["pt-BR", "es-MX", "es-AR", "es-CO", "en-US"]
LOCALES: tuple[str, ...] = get_args(Locale)


def lang_of(locale: str) -> str:
    """``"es-MX"`` -> ``"es"``."""
    if locale not in LOCALES:
        raise ValueError(f"unknown locale {locale!r}; expected one of {LOCALES}")
    return locale.split("-", 1)[0]


__all__ = ["LOCALES", "Locale", "lang_of"]
