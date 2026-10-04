// The language, market and theme controls of the Navbar: the language and the market are radio groups, the
// theme one toggle button.

import type { Lang, Locale } from "@pattern-blue/contracts";
import { LANG_NAMES, LANGS, localesOf } from "../../i18n";
import { useI18n, useLocale, useTheme } from "../actors";
import { useSystemDark } from "../hooks";
import { Icon } from "../ui/Icon";

export function LangSwitch() {
  const { lang, dict, setLang } = useI18n();
  return (
    <div className="pb-lang" role="radiogroup" aria-label={dict.nav.languageLabel}>
      {LANGS.map((code: Lang) => (
        <button
          key={code}
          className="pb-lang__btn"
          type="button"
          role="radio"
          aria-checked={lang === code}
          data-lang={code}
          lang={code}
          aria-label={LANG_NAMES[code]}
          onClick={() => setLang(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

/**
 * The customer's market, for a language served in more than one (today Spanish: MX, AR, CO). It shows the
 * country code and reads the country's name. One is always checked: the one the browser names, else the
 * language's default (CO for Spanish). The text is the same in every Spanish market, only what the chat
 * sends changes.
 */
export function MarketSwitch() {
  const { lang, dict } = useI18n();
  const { locale, setLocale } = useLocale();
  const markets = localesOf(lang);
  if (markets.length < 2) return null;
  return (
    <div className="pb-lang" role="radiogroup" aria-label={dict.nav.marketLabel}>
      {markets.map((code: Locale) => (
        <button
          key={code}
          className="pb-lang__btn"
          type="button"
          role="radio"
          aria-checked={locale === code}
          data-locale={code}
          aria-label={dict.nav.markets[code]}
          onClick={() => setLocale(code)}
        >
          {code.split("-")[1]}
        </button>
      ))}
    </div>
  );
}

/** One button that switches to the other theme; its label says which. Follows the system until it is pressed. */
export function ThemeToggle() {
  const { dict } = useI18n();
  const { theme, setTheme } = useTheme();
  const systemDark = useSystemDark();
  const dark = (theme === "system" ? (systemDark ? "dark" : "light") : theme) === "dark";
  return (
    <div className="pb-theme pb-theme--single">
      <button
        className="pb-theme__btn"
        type="button"
        data-theme-set={dark ? "light" : "dark"}
        aria-label={dark ? dict.nav.themeToLight : dict.nav.themeToDark}
        onClick={() => setTheme(dark ? "light" : "dark")}
      >
        <Icon name={dark ? "sun" : "moon"} />
      </button>
    </div>
  );
}
