// Three dictionaries with the same keys; `t("some.key", { name })` fills {name}.

import { LangSchema, type Lang } from "@pattern-blue/contracts";
import { en } from "./en";
import { es, type Dictionary } from "./es";
import { pt } from "./pt";

export const LANGUAGES = LangSchema.options;
export const DEFAULT_LANG: Lang = "es";

export const dictionaries: Record<Lang, Dictionary> = { es, pt, en };

/** Dotted paths to the string leaves of the dictionary, except the tool notes (their keys contain dots). */
type Path<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${Prefix}${K}` : K extends "notes" ? never : Path<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

export type MessageKey = Path<Dictionary>;
export type Params = Record<string, string | number>;

export type Translate = (key: MessageKey, params?: Params) => string;

function lookup(dictionary: Dictionary, key: string): string {
  let node: unknown = dictionary;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null) return key;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : key;
}

export function fill(template: string, params: Params = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function translator(lang: Lang): Translate {
  const dictionary = dictionaries[lang];
  return (key, params) => fill(lookup(dictionary, key), params);
}

/** What the matrix says about a tool, or undefined for a tool it has no note for. */
export function toolNote(lang: Lang, tool: string): string | undefined {
  const notes: Record<string, string> = dictionaries[lang].guardrails.tools.notes;
  return notes[tool];
}
