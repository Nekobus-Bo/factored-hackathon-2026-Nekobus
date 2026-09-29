// The language and theme controls, in the Navbar and repeated in the Footer. Both are radio groups.

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
