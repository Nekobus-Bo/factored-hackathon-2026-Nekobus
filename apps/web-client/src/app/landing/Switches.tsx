// The language and theme controls of the Navbar: the language is a radio group, the theme one toggle button.

import type { Lang } from "@pattern-blue/contracts";
import { LANG_NAMES, LANGS } from "../../i18n";
import { useI18n, useTheme } from "../actors";
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
