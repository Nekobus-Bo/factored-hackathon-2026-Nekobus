import { describe, expect, test } from "bun:test";
import { DEFAULT_LANG, detectLang, dictionaries, format, formatWait, LANGS } from "../src/i18n";

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
    expect(es.length).toBeGreaterThan(150);
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
    const sameInBoth = [
      "nav.s2",
      "s2.label",
      "s2.ticker",
      "features.items[3].fact",
      "footer.legalGroup",
      "chat.handoff.priorities.NORMAL",
      "chat.inbox.demoTag",
    ];
    const sameInPt = [
      ...sameInBoth,
      "nav.linksLabel",
      "nav.languageLabel",
      "nav.themeLabel",
      "nav.themeLight",
      "card.holder",
      "flow.title[1]",
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
      "chat.receipt.destination",
      "chat.states.VERIFIED",
      "chat.states.EXPIRED",
      "chat.states.LOCKED",
      "chat.states.IDENTIFIED",
      "chat.handoff.departments.DISPUTES",
      "chat.handoff.priorities.URGENT",
      "chat.handoff.priorities.HIGH",
      "chat.inbox.from",
      "chat.inbox.to",
      "chat.inbox.codeAria",
      "chat.inbox.codeHiddenAria",
      "chat.inbox.reveal",
      "chat.inbox.hide",
    ];
    for (const [lang, allowed] of [
      ["pt", sameInPt],
      ["en", sameInBoth],
    ] as const) {
      const copied = [...flat.es].filter(([key, text]) => flat[lang].get(key) === text).map(([key]) => key);
      expect(copied.sort(), lang).toEqual([...allowed].filter((key) => copied.includes(key)).sort());
      // and the list does not hide a string that has since been translated
      expect(allowed.filter((key) => !copied.includes(key)), `${lang}: stale entries`).toEqual([]);
    }
  });
});

describe("landing rules hold in every language", () => {
  const landingKeys = (key: string) => /^(nav|hero|card|features|flow|s2|faq|footer)\b/.test(key);

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
    expect(dictionaries.pt.hero.title).toEqual(["Seu cartão", "bloqueado", "com comprovante"]);
    expect(dictionaries.en.hero.title).toEqual(["Your card", "blocked", "with a receipt"]);
  });

  test("the FAQ has the five questions and the flow the four steps, in the same order", () => {
    for (const lang of LANGS) {
      expect(dictionaries[lang].faq.items).toHaveLength(5);
      expect(dictionaries[lang].flow.steps).toHaveLength(4);
      expect(dictionaries[lang].features.items).toHaveLength(4);
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
