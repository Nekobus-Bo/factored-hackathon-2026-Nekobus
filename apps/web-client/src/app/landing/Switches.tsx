// The language, market and theme tools of the Navbar. Each is a group of options as radios, drawn like the language
// switch (`pb-lang`): the language (ES, PT), the market (for a language served in more than one) and the theme (a
// sun and a moon), each drawn with no lines (`pb-lang--fill`: the options in the full ink, the one checked on a `violet-soft` block). The language and the market carry a visible label
// outside it (the `label` style of the system); the theme has none and is named for assistive technology ("Tema"). The groups are told apart by room, with no rule between them
// (`pb-navtool`, in the stylesheet of the design-tokens package).

import type { Lang, Locale } from "@pattern-blue/contracts";
import { useId, type ReactNode } from "react";
import { LANG_NAMES, LANGS, localesOf } from "../../i18n";
import { useI18n, useLocale, useTheme } from "../actors";
import { useSystemDark } from "../hooks";
import { Icon } from "../ui/Icon";

/** A header tool: the visible label, then the radio group it names. Without a label (the theme) the group names itself. */
function Tool({ label, children }: { label?: string; children: (name: { "aria-labelledby": string } | undefined) => ReactNode }) {
  const labelId = useId();
  return (
    <div className="pb-navtool">
      {label !== undefined && (
        <span className="pb-navtool__label" id={labelId}>
          {label}
        </span>
      )}
      {children(label !== undefined ? { "aria-labelledby": labelId } : undefined)}
    </div>
  );
}

export function LangSwitch() {
  const { lang, dict, setLang } = useI18n();
  return (
    <Tool label={dict.nav.languageLabel}>
      {(name) => (
        <div className="pb-lang pb-lang--fill" role="radiogroup" {...name}>
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
      )}
    </Tool>
  );
}

/**
 * The customer's market, for a language served in more than one (today Spanish: MX, AR, CO), under its own label,
 * "País": it is the country (the market), not the currency. It shows the country code and reads the country's name. One is always
 * checked: the one the browser names, else the language's default (CO for Spanish). The text is the same in every
 * Spanish market, only what the chat sends changes.
 */
export function MarketSwitch() {
  const { lang, dict } = useI18n();
  const { locale, setLocale } = useLocale();
  const markets = localesOf(lang);
  if (markets.length < 2) return null;
  return (
    <Tool label={dict.nav.marketLabel}>
      {(name) => (
        <div className="pb-lang pb-lang--fill" role="radiogroup" {...name}>
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
      )}
    </Tool>
  );
}

/**
 * The theme: two radios, a sun and a moon, named "Claro" and "Oscuro". The one checked is the theme in force: the
 * pinned choice, or what the system prefers until one is pinned. Choosing one pins it (the machine and where it is
 * remembered are the same as ever).
 */
export function ThemeSwitch() {
  const { dict } = useI18n();
  const { theme, setTheme } = useTheme();
  const systemDark = useSystemDark();
  const shown = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  const options = [
    { id: "light", icon: "sun", name: dict.nav.themeLight },
    { id: "dark", icon: "moon", name: dict.nav.themeDark },
  ] as const;
  return (
    <Tool>
      {() => (
        <div className="pb-lang pb-lang--fill" role="radiogroup" aria-label={dict.nav.themeLabel}>
          {options.map((option) => (
            <button
              key={option.id}
              className="pb-lang__btn"
              type="button"
              role="radio"
              aria-checked={shown === option.id}
              aria-label={option.name}
              title={option.name}
              data-theme-set={option.id}
              onClick={() => setTheme(option.id)}
            >
              <Icon name={option.icon} />
            </button>
          ))}
        </div>
      )}
    </Tool>
  );
}
