import { describe, expect, test } from "bun:test";
import {
  DEFAULT_LANG,
  detectLang,
  detectLocale,
  dictionaries,
  format,
  formatWait,
  LANGS,
  langOf,
  LOCALES,
  localesOf,
} from "../src/i18n";

/** `a.b[0].c` for every string in the dictionary. */
function flatten(value: unknown, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  if (typeof value === "string") {
    out.set(prefix, value);
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => {
      for (const [key, text] of flatten(item, `${prefix}[${index}]`)) out.set(key, text);
    });
  } else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      for (const [path, text] of flatten(child, prefix ? `${prefix}.${key}` : key)) out.set(path, text);
    }
  }
  return out;
}

const flat = {
  es: flatten(dictionaries.es),
  pt: flatten(dictionaries.pt),
  en: flatten(dictionaries.en),
};

describe("dictionaries", () => {
  test("es, pt and en have the same keys", () => {
    const es = [...flat.es.keys()].sort();
    expect([...flat.pt.keys()].sort()).toEqual(es);
    expect([...flat.en.keys()].sort()).toEqual(es);
    expect(es.length).toBeGreaterThan(140);
  });

  test("no string is empty", () => {
    for (const lang of LANGS) {
      for (const [key, text] of flat[lang]) expect(text.trim(), `${lang}:${key}`).not.toBe("");
    }
  });

  test("a placeholder appears in every language or in none", () => {
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const [key, text] of flat.es) {
      expect(placeholders(flat.pt.get(key) ?? ""), `pt:${key}`).toEqual(placeholders(text));
      expect(placeholders(flat.en.get(key) ?? ""), `en:${key}`).toEqual(placeholders(text));
    }
  });

  test("pt and en are translated, not copied from es", () => {
    // Where the same string is the right translation: names, symbols, and words Spanish and Portuguese
    // share. Anything else equal to the Spanish is a string somebody forgot to translate.
    const sameInBoth = ["nav.s2", "s2.label", "s2.ticker", "chat.inbox.demoTag", "nav.markets.es-AR"];
    const sameInPt = [
      ...sameInBoth,
      "meta.documentTitle",
      "hero.kicker",
      "hero.title[1]",
      "nav.openChat",
      "chat.handoff.caseLabel",
      "nav.linksLabel",
      "nav.languageLabel",
      "nav.marketLabel",
      "nav.markets.es-MX",
      "nav.markets.pt-BR",
      "nav.markets.en-US",
      "card.holder",
      "flow.steps[0].chip",
      "flow.steps[1].chip",
      "s2.top",
      "s2.title[0]",
      "chat.roles.agent",
      "chat.codePrefix",
      "chat.chip.identified",
      "chat.chip.verified",
      "chat.rateLimited.minutesOne",
      "chat.rateLimited.minutesOther",
      "chat.states.VERIFIED",
      "chat.states.EXPIRED",
      "chat.states.LOCKED",
      "chat.states.IDENTIFIED",
      "chat.handoff.departments.DISPUTES",
      "chat.inbox.codeAria",
      "chat.inbox.codeHiddenAria",
      "chat.inbox.reveal",
      "chat.inbox.hide",
    ];
    const sameInEn = [...sameInBoth, "nav.markets.es-CO", "chat.feedback.no"];
    for (const [lang, allowed] of [
      ["pt", sameInPt],
      ["en", sameInEn],
    ] as const) {
      const copied = [...flat.es].filter(([key, text]) => flat[lang].get(key) === text).map(([key]) => key);
      expect(copied.sort(), lang).toEqual([...allowed].filter((key) => copied.includes(key)).sort());
      // and the list does not hide a string that has since been translated
      expect(allowed.filter((key) => !copied.includes(key)), `${lang}: stale entries`).toEqual([]);
    }
  });
});

describe("landing rules hold in every language", () => {
  const landingKeys = (key: string) => /^(nav|hero|card|products|flow|s2|faq|footer)\b/.test(key);

  test("every number is a product fact: 6 digits, 5 minutes, S2, the year of the hackathon", () => {
    const allowed = new Set(["6", "5", "2", "2026"]);
    for (const lang of LANGS) {
      for (const [key, text] of flat[lang]) {
        if (!landingKeys(key)) continue;
        for (const run of text.match(/\d+/g) ?? []) {
          expect(allowed.has(run), `${lang}:${key} has the number ${run}`).toBe(true);
        }
      }
    }
  });

  test("no claim about users, ratings, uptime or speed", () => {
    const banned = /(usuarios|utilizadores|users|customers|clientes|rating|estrellas|stars|estrelas|uptime|99|%|instant|inmediat|imediat|ahora mismo|agora mesmo)/i;
    for (const lang of LANGS) {
      for (const [key, text] of flat[lang]) {
        if (!landingKeys(key)) continue;
        expect(banned.test(text), `${lang}:${key}: ${text}`).toBe(false);
      }
    }
  });

  test("the demo note and the S2 small print are in every language", () => {
    for (const lang of LANGS) {
      const dict = dictionaries[lang];
      expect(dict.footer.demoNote).toContain("Factored AI & Data Hackathon 2026");
      expect(dict.footer.demoNote.toLowerCase()).toContain("demo");
      expect(dict.footer.legal).toContain("© 2026 Pattern Blue (demo)");
      expect(dict.s2.demo.toLowerCase()).toContain("demo");
      expect(dict.s2.legal.length).toBeGreaterThan(20);
    }
  });

  test("the hero headline is three lines, as the design system fixes", () => {
    for (const lang of LANGS) expect(dictionaries[lang].hero.title).toHaveLength(3);
    expect(dictionaries.pt.hero.title).toEqual(["Seu banco", "responde", "no chat"]);
    expect(dictionaries.en.hero.title).toEqual(["Your bank", "answers", "in the chat"]);
  });

  test("the FAQ has the five questions, the lost-card section the four steps, and the bank its three products", () => {
    for (const lang of LANGS) {
      expect(dictionaries[lang].faq.items).toHaveLength(5);
      expect(dictionaries[lang].flow.steps).toHaveLength(4);
      expect(dictionaries[lang].products.items).toHaveLength(3);
    }
  });

  test("the landing describes the bank, not the system behind it", () => {
    const system = /(base de datos|banco de dados|database|releído|relido|re-read)/i;
    const ai = /\b(IA|AI)\b/;
    for (const lang of LANGS) {
      for (const [key, text] of flat[lang]) {
        if (!landingKeys(key)) continue;
        // The hackathon's own name is not a claim about the bank.
        const claim = text.replace("Factored AI & Data Hackathon", "");
        expect(system.test(claim) || ai.test(claim), `${lang}:${key}: ${text}`).toBe(false);
      }
    }
  });

  test("plain copy: no colon used to join two clauses, no em dash, no curly quotes", () => {
    for (const lang of LANGS) {
      for (const [key, text] of flat[lang]) {
        expect(/[—“”‘’]/.test(text), `${lang}:${key}: ${text}`).toBe(false);
        if (landingKeys(key)) expect(/[a-záéíóúãõç]: [a-záéíóúãõç]/i.test(text), `${lang}:${key}: ${text}`).toBe(false);
      }
    }
  });
});

describe("helpers", () => {
  test("detectLang", () => {
    expect(detectLang("es-CO")).toBe("es");
    expect(detectLang("pt-BR")).toBe("pt");
    expect(detectLang("pt")).toBe("pt");
    expect(detectLang("en-US")).toBe("en");
    expect(detectLang("EN_gb")).toBe("en");
    expect(detectLang("fr-FR")).toBe(DEFAULT_LANG);
    expect(detectLang("")).toBe("es");
    expect(detectLang(undefined)).toBe("es");
    expect(detectLang(null)).toBe("es");
  });

  test("detectLocale names a market only on an exact match", () => {
    expect(detectLocale("es-CO")).toBe("es-CO");
    expect(detectLocale("ES-mx")).toBe("es-MX");
    expect(detectLocale(" es_AR ")).toBe("es-AR");
    expect(detectLocale("pt-BR")).toBe("pt-BR");
    expect(detectLocale("en-US")).toBe("en-US");
    for (const none of ["es", "es-ES", "es-CL", "pt", "pt-PT", "en-GB", "fr-FR", "", undefined, null]) {
      expect(detectLocale(none), String(none)).toBeNull();
    }
  });

  test("every market belongs to a supported language, and Spanish has three", () => {
    for (const locale of LOCALES) expect(LANGS).toContain(langOf(locale));
    expect(localesOf("es")).toEqual(["es-MX", "es-AR", "es-CO"]);
    expect(localesOf("pt")).toEqual(["pt-BR"]);
    expect(localesOf("en")).toEqual(["en-US"]);
  });

  test("format fills placeholders and leaves an unknown one visible", () => {
    expect(format("{n} en la fila", { n: 2 })).toBe("2 en la fila");
    expect(format("hola {name}", {})).toBe("hola {name}");
  });

  test("formatWait rounds up to whole minutes", () => {
    const es = dictionaries.es;
    expect(formatWait(es, 30)).toBe("menos de un minuto");
    expect(formatWait(es, 60)).toBe("1 minuto");
    expect(formatWait(es, 61)).toBe("2 minutos");
    expect(formatWait(es, 287)).toBe("5 minutos");
    expect(formatWait(dictionaries.en, 300)).toBe("5 minutes");
    expect(formatWait(dictionaries.pt, 1)).toBe("menos de um minuto");
  });
});
