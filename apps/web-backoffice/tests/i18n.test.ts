import { describe, expect, test } from "bun:test";
import { DepartmentSchema, HandoffPrioritySchema, HandoffReasonSchema, HandoffStatusSchema, ReasonCodeSchema } from "@pattern-blue/contracts";
import { LANGUAGES, dictionaries, fill, toolNote, translator } from "../src/i18n";
import { es } from "../src/i18n/es";
import { toolPolicy } from "./support/fixtures";

/** Every leaf of a dictionary as `path/to/leaf` (the tool notes' keys contain dots, so the separator is a slash). */
function leaves(node: unknown, prefix = ""): Map<string, string> {
  const result = new Map<string, string>();
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix === "" ? key : `${prefix}/${key}`;
    if (typeof value === "string") result.set(path, value);
    else for (const [nested, text] of leaves(value, path)) result.set(nested, text);
  }
  return result;
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1] as string).sort();

const spanish = leaves(dictionaries.es);

describe("dictionaries", () => {
  test("there are three, es first", () => {
    expect(LANGUAGES).toEqual(["es", "pt", "en"]);
    expect(Object.keys(dictionaries).sort()).toEqual(["en", "es", "pt"]);
    expect(dictionaries.es).toBe(es);
  });

  test.each(["pt", "en"] as const)("%s has exactly the keys of es", (lang) => {
    const other = leaves(dictionaries[lang]);
    expect([...other.keys()].sort()).toEqual([...spanish.keys()].sort());
  });

  test.each(["pt", "en"] as const)("%s fills the same {placeholders} as es, key by key", (lang) => {
    const other = leaves(dictionaries[lang]);
    for (const [key, text] of spanish) {
      expect(placeholders(other.get(key) as string), key).toEqual(placeholders(text));
    }
  });

  test.each(LANGUAGES)("%s has no empty text", (lang) => {
    for (const [key, text] of leaves(dictionaries[lang])) {
      // "—" is the one deliberate placeholder for "no value".
      expect(text.trim().length, `${lang}: ${key}`).toBeGreaterThan(0);
    }
  });

  test.each(["pt", "en"] as const)("%s is actually translated: no sentence is left in Spanish", (lang) => {
    const other = leaves(dictionaries[lang]);
    // Short labels (Guardrails, Normal, Urgente, Total...) may coincide; a sentence may not.
    const untranslated = [...spanish].filter(([key, text]) => text.length > 40 && other.get(key) === text).map(([key]) => key);
    expect(untranslated).toEqual([]);
  });

  test("no language uses an exclamation mark or an emoji (voice: calm, precise)", () => {
    for (const lang of LANGUAGES) {
      for (const [key, text] of leaves(dictionaries[lang])) {
        expect(text, `${lang}: ${key}`).not.toMatch(/!|¡|\p{Extended_Pictographic}/u);
      }
    }
  });

  test.each(LANGUAGES)("%s has a word for every value of every enum the screens show", (lang) => {
    const dictionary = dictionaries[lang].enums;
    expect(Object.keys(dictionary.priority).sort()).toEqual([...HandoffPrioritySchema.options].sort());
    expect(Object.keys(dictionary.department).sort()).toEqual([...DepartmentSchema.options].sort());
    expect(Object.keys(dictionary.status).sort()).toEqual([...HandoffStatusSchema.options].sort());
    expect(Object.keys(dictionary.reason).sort()).toEqual([...HandoffReasonSchema.options].sort());
    expect(Object.keys(dictionary.reasonCode).sort()).toEqual([...ReasonCodeSchema.options].sort());
    expect(Object.keys(dictionary.decision).sort()).toEqual(["allowed", "error", "refused"]);
  });

  test.each(LANGUAGES)("%s has a note for every tool the code floor lists", (lang) => {
    for (const tool of Object.keys(toolPolicy().code_floor)) {
      expect(toolNote(lang, tool), `${lang}: ${tool}`).toBeDefined();
    }
    expect(toolNote(lang, "no.such.tool")).toBeUndefined();
  });

  test("the labels the spec fixes are there", () => {
    expect(dictionaries.es.handoff.take).toBe("Tomar caso");
    expect(dictionaries.es.handoff.heldByOther).toBe("Otro agente ya tomó este caso");
    expect(dictionaries.es.guardrails.mode.flagLabel).toBe("handoff recomendado");
    expect(dictionaries.es.guardrails.mode.blockLabel).toBe("handoff requerido");
    expect(dictionaries.en.guardrails.mode.flagLabel).toBe("handoff recommended");
    expect(dictionaries.en.guardrails.mode.blockLabel).toBe("handoff required");
  });

  test("the composer tells the agent that the customer reads masked text, the agent's own name included", () => {
    for (const lang of LANGUAGES) {
      const note = dictionaries[lang].handoff.composer.note;
      expect(note.length).toBeGreaterThan(60);
    }
    expect(dictionaries.es.handoff.composer.note).toContain("tampoco tu nombre");
    expect(dictionaries.en.handoff.composer.note).toContain("not even your own name");
  });
});

describe("translator", () => {
  test("fills {placeholders} and leaves an unknown one visible", () => {
    expect(fill("Hola {name}, {count} casos", { name: "Ana", count: 3 })).toBe("Hola Ana, 3 casos");
    expect(fill("Hola {name}")).toBe("Hola {name}");
  });

  test("translates by dotted key in the language asked", () => {
    expect(translator("es")("queue.title")).toBe("Cola de handoff");
    expect(translator("pt")("queue.title")).toBe("Fila de handoff");
    expect(translator("en")("queue.title")).toBe("Handoff queue");
    expect(translator("en")("queue.position", { position: 2 })).toBe("Position 2");
  });
});
