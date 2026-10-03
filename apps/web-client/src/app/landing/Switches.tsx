// The language, market and theme controls, in the Navbar and repeated in the Footer. All are radio groups.

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
 * country code and reads the country's name. None is checked until the browser names one or the customer
 * picks one: the text is the same in every Spanish market, only what the chat sends changes.
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

export function ThemeSwitch() {
  const { dict } = useI18n();
  const { theme, setTheme } = useTheme();
  const systemDark = useSystemDark();
  // `system` has no button of its own: the one that matches what the browser prefers shows as checked.
  const effective = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  return (
    <div className="pb-theme" role="radiogroup" aria-label={dict.nav.themeLabel}>
      <button
        className="pb-theme__btn"
        type="button"
        role="radio"
        aria-checked={effective === "light"}
        data-theme-set="light"
        aria-label={dict.nav.themeLight}
        onClick={() => setTheme("light")}
      >
        <Icon name="sun" />
      </button>
      <button
        className="pb-theme__btn"
        type="button"
        role="radio"
        aria-checked={effective === "dark"}
        data-theme-set="dark"
        aria-label={dict.nav.themeDark}
        onClick={() => setTheme("dark")}
      >
        <Icon name="moon" />
      </button>
    </div>
  );
}
