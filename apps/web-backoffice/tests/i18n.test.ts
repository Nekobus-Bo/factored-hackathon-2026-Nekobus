import { describe, expect, test } from "bun:test";
import {
  DepartmentSchema,
  HandoffOutcomeSchema,
  HandoffPrioritySchema,
  HandoffReasonSchema,
  HandoffStatusSchema,
  ReasonCodeSchema,
  RejectReasonSchema,
  VerificationStateSchema,
} from "@pattern-blue/contracts";
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
    expect(Object.keys(dictionary.outcome).sort()).toEqual([...HandoffOutcomeSchema.options].sort());
    expect(Object.keys(dictionary.rejectReason).sort()).toEqual([...RejectReasonSchema.options].sort());
    expect(Object.keys(dictionary.state).sort()).toEqual([...VerificationStateSchema.options].sort());
  });

  test.each(LANGUAGES)("%s has a note for every tool the code floor lists", (lang) => {
    for (const tool of Object.keys(toolPolicy().code_floor)) {
      expect(toolNote(lang, tool), `${lang}: ${tool}`).toBeDefined();
    }
    expect(toolNote(lang, "no.such.tool")).toBeUndefined();
  });

  test("the labels the review fixed are there", () => {
    expect(dictionaries.es.handoff.take).toBe("Tomar caso");
    expect(dictionaries.es.decide.approve).toBe("Aprobar");
    expect(dictionaries.es.decide.reject).toBe("Rechazar");
    expect(dictionaries.es.decide.escalate).toBe("Escalar");
    expect(dictionaries.es.handoff.footnote).toBe("El asistente no resuelve disputas. La decisión es tuya.");
    expect(dictionaries.es.guardrails.mode.flagLabel).toBe("Recomendar handoff");
    expect(dictionaries.es.guardrails.mode.blockLabel).toBe("Exigir handoff");
    expect(dictionaries.en.guardrails.mode.flagLabel).toBe("Recommend a handoff");
    expect(dictionaries.en.guardrails.mode.blockLabel).toBe("Require a handoff");
  });

  test("the composer tells the agent that the customer reads the text as written and the assistant does not see it", () => {
    const expected = {
      es: ["tal cual", "El asistente no lo ve"],
      pt: ["tal como está", "O assistente não o vê"],
      en: ["as you write it", "The assistant does not see it"],
    } as const;
    for (const lang of LANGUAGES) {
      const note = dictionaries[lang].handoff.composer.note;
      for (const part of expected[lang]) expect(note, lang).toContain(part);
      // The text is stored masked but shown as written: the note must not claim it is masked.
      expect(note, lang).not.toMatch(/mask|mascar|enmascar/i);
    }
  });

  test("the screens show no raw enum in running text: a word stands for it", () => {
    for (const lang of LANGUAGES) {
      for (const [key, text] of leaves(dictionaries[lang])) {
        if (key.startsWith("guardrails/reset")) continue; // names the environment variable to set
        if (key.startsWith("flows/")) continue; // draws the state machine: its states are the subject
        expect(text, `${lang}: ${key}`).not.toMatch(/\b(QUEUED|ASSIGNED|VERIFIED|ANONYMOUS|model_unverified|amount_mode|thresholds_minor|ops\.audit_log)\b/);
      }
    }
  });
});

describe("translator", () => {
  test("fills {placeholders} and leaves an unknown one visible", () => {
    expect(fill("Hola {name}, {count} casos", { name: "Ana", count: 3 })).toBe("Hola Ana, 3 casos");
    expect(fill("Hola {name}")).toBe("Hola {name}");
  });

  test("translates by dotted key in the language asked", () => {
    expect(translator("es")("queue.title")).toBe("Cola");
    expect(translator("pt")("queue.title")).toBe("Fila");
    expect(translator("en")("queue.title")).toBe("Queue");
    expect(translator("en")("queue.waiting", { position: 2 })).toBe("Queued · #2");
  });
});
