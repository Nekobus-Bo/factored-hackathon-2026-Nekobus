// One dictionary per language (es, pt, en), all with the shape of the Spanish one: the `Dictionary`
// type is derived from `es`, so a key missing from `pt` or `en` does not compile, and
// tests/i18n.test.ts checks the same at run time.

import { LocaleSchema, type Lang, type Locale } from "@pattern-blue/contracts";
import { en } from "./en";
import { es } from "./es";
import { pt } from "./pt";

/** Every string becomes `string`, every tuple keeps its length: the shape without the Spanish words. */
type Widen<T> = T extends string
  ? string
  : T extends readonly unknown[]
    ? { [K in keyof T]: Widen<T[K]> }
    : T extends object
      ? { [K in keyof T]: Widen<T[K]> }
      : T;

export type Dictionary = Widen<typeof es>;

export const DEFAULT_LANG: Lang = "es";
export const LANGS: readonly Lang[] = ["es", "pt", "en"];

export const dictionaries: Record<Lang, Dictionary> = { es, pt, en };

/** `navigator.language` -> a supported language, else Spanish. `pt-BR` -> `pt`, `EN_us` -> `en`. */
export function detectLang(navigatorLanguage: string | null | undefined): Lang {
  const primary = navigatorLanguage?.trim().toLowerCase().split(/[-_]/)[0];
  return LANGS.find((lang) => lang === primary) ?? DEFAULT_LANG;
}

/** The markets the system serves (ADR-0014), in the contract's order. The page text stays one per language. */
export const LOCALES: readonly Locale[] = LocaleSchema.options;

/** `es-MX` -> `es`: a market's language is the part before "-". */
export function langOf(locale: Locale): Lang {
  return locale.split("-")[0] as Lang;
}

/** The markets of one language: three for Spanish, one each for Portuguese and English. */
export function localesOf(lang: Lang): Locale[] {
  return LOCALES.filter((locale) => langOf(locale) === lang);
}

/** The market a language starts in when nothing names one: Colombia for Spanish, the only one for the others. */
export const DEFAULT_LOCALES: Record<Lang, Locale> = { es: "es-CO", pt: "pt-BR", en: "en-US" };

/**
 * `navigator.language` -> a market only when it names one exactly (`es-co` -> `es-CO`). `es`, `es-ES` or
 * `pt-PT` say nothing about a market we serve: null, and the language alone decides.
 */
export function detectLocale(navigatorLanguage: string | null | undefined): Locale | null {
  const tag = navigatorLanguage?.trim().replace("_", "-").toLowerCase();
  return LOCALES.find((locale) => locale.toLowerCase() === tag) ?? null;
}

/** `navigator.language` -> the market it names, else the default market of its language: `es-CO` for none. */
export function startLocale(navigatorLanguage: string | null | undefined): Locale {
  return detectLocale(navigatorLanguage) ?? DEFAULT_LOCALES[detectLang(navigatorLanguage)];
}

/** Fill `{name}` placeholders. A placeholder with no value stays visible, which a test would catch. */
export function format(template: string, values: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = values[name];
    return value === undefined ? whole : String(value);
  });
}

/** "5 minutos", "1 minuto", "menos de un minuto": the wait a 429 asks for, in whole minutes rounded up. */
export function formatWait(dict: Dictionary, seconds: number): string {
  const rl = dict.chat.rateLimited;
  if (seconds < 60) return rl.lessThanMinute;
  const minutes = Math.ceil(seconds / 60);
  return format(minutes === 1 ? rl.minutesOne : rl.minutesOther, { n: minutes });
}

/** Each language written in itself: the names on the switch are not translated. */
export const LANG_NAMES: Record<Lang, string> = { es: "Español", pt: "Português", en: "English" };
