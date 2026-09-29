// One dictionary per language (es, pt, en), all with the shape of the Spanish one: the `Dictionary`
// type is derived from `es`, so a key missing from `pt` or `en` does not compile, and
// tests/i18n.test.ts checks the same at run time.

import type { Lang } from "@pattern-blue/contracts";
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
