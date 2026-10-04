import { describe, expect, test } from "bun:test";
import { createActor } from "xstate";
import { createAppMachine, DETECTIVE_STORAGE_KEY, readStoredTheme, THEME_STORAGE_KEY, type AppEnv } from "../src/machines/app.machine";

function fakeEnv(overrides: Partial<AppEnv> & { stored?: Record<string, string> } = {}) {
  const store = new Map<string, string>(Object.entries(overrides.stored ?? {}));
  const attributes = new Map<string, string>();
  const env: AppEnv = {
    storage: {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => void store.set(key, value),
      removeItem: (key) => void store.delete(key),
    },
    root: {
      setAttribute: (name, value) => void attributes.set(name, value),
      removeAttribute: (name) => void attributes.delete(name),
    },
    navigatorLanguage: "es-CO",
    ...overrides,
  };
  return { env, store, attributes };
}

const start = (env: AppEnv) => {
  const actor = createActor(createAppMachine(env));
  actor.start();
  return actor;
};

describe("theme", () => {
  test("starts on system: no data-theme on <html>, nothing stored", () => {
    const { env, attributes, store } = fakeEnv();
    const actor = start(env);
    expect(actor.getSnapshot().context.theme).toBe("system");
    expect(attributes.has("data-theme")).toBe(false);
    expect(store.size).toBe(0);
  });

  test("a remembered light or dark is applied on start", () => {
    for (const theme of ["light", "dark"] as const) {
      const { env, attributes } = fakeEnv({ stored: { [THEME_STORAGE_KEY]: theme } });
      const actor = start(env);
      expect(actor.getSnapshot().context.theme).toBe(theme);
      expect(attributes.get("data-theme")).toBe(theme);
    }
  });

  test("a stored value that is not a theme is ignored", () => {
    for (const junk of ["", "blue", "<script>", "DARK", "system"]) {
      const { env, attributes } = fakeEnv({ stored: { [THEME_STORAGE_KEY]: junk } });
      const actor = start(env);
      expect(actor.getSnapshot().context.theme).toBe("system");
      expect(attributes.has("data-theme")).toBe(false);
    }
  });

  test("THEME.SET pins the attribute and remembers the choice", () => {
    const { env, attributes, store } = fakeEnv();
    const actor = start(env);
    actor.send({ type: "THEME.SET", theme: "dark" });
    expect(actor.getSnapshot().context.theme).toBe("dark");
    expect(attributes.get("data-theme")).toBe("dark");
    expect(store.get(THEME_STORAGE_KEY)).toBe("dark");
    actor.send({ type: "THEME.SET", theme: "light" });
    expect(attributes.get("data-theme")).toBe("light");
    expect(store.get(THEME_STORAGE_KEY)).toBe("light");
  });

  test("back to system removes the attribute and forgets the choice", () => {
    const { env, attributes, store } = fakeEnv({ stored: { [THEME_STORAGE_KEY]: "dark" } });
    const actor = start(env);
    actor.send({ type: "THEME.SET", theme: "system" });
    expect(actor.getSnapshot().context.theme).toBe("system");
    expect(attributes.has("data-theme")).toBe(false);
    expect(store.has(THEME_STORAGE_KEY)).toBe(false);
  });

  test("a storage that throws on every access leaves the page working", () => {
    const boom = () => {
      throw new Error("SecurityError");
    };
    const { env, attributes } = fakeEnv({ storage: { getItem: boom, setItem: boom, removeItem: boom } });
    const actor = start(env);
    expect(actor.getSnapshot().context.theme).toBe("system");
    actor.send({ type: "THEME.SET", theme: "dark" });
    expect(actor.getSnapshot().context.theme).toBe("dark");
    expect(attributes.get("data-theme")).toBe("dark");
    actor.send({ type: "THEME.SET", theme: "system" });
    expect(actor.getSnapshot().context.theme).toBe("system");
  });

  test("no storage at all", () => {
    const { env } = fakeEnv({ storage: null });
    const actor = start(env);
    actor.send({ type: "THEME.SET", theme: "light" });
    expect(actor.getSnapshot().context.theme).toBe("light");
    expect(readStoredTheme(null)).toBe("system");
  });

  test("no root (server): the machine still runs", () => {
    const { env } = fakeEnv({ root: null });
    const actor = start(env);
    actor.send({ type: "THEME.SET", theme: "dark" });
    expect(actor.getSnapshot().context.theme).toBe("dark");
  });
});

describe("language", () => {
  test("starts from navigator.language and is set on <html>", () => {
    for (const [nav, lang] of [
      ["es-CO", "es"],
      ["pt-BR", "pt"],
      ["en-US", "en"],
      ["fr-FR", "es"],
      [undefined, "es"],
    ] as const) {
      const { env, attributes } = fakeEnv({ navigatorLanguage: nav });
      const actor = start(env);
      expect(actor.getSnapshot().context.lang).toBe(lang);
      expect(attributes.get("lang")).toBe(lang);
    }
  });

  test("LANG.SET changes the language and <html lang>, and does not touch the theme", () => {
    const { env, attributes, store } = fakeEnv();
    const actor = start(env);
    actor.send({ type: "LANG.SET", lang: "pt" });
    expect(actor.getSnapshot().context).toEqual({ theme: "system", lang: "pt", locale: "pt-BR", detective: false });
    expect(attributes.get("lang")).toBe("pt");
    expect(store.size).toBe(0);
    actor.send({ type: "LANG.SET", lang: "en" });
    expect(actor.getSnapshot().context.lang).toBe("en");
  });
});

describe("market", () => {
  test("starts from navigator.language when it names a market, else its language's default market", () => {
    for (const [nav, locale] of [
      ["es-CO", "es-CO"],
      ["es-mx", "es-MX"],
      ["es_AR", "es-AR"],
      ["pt-BR", "pt-BR"],
      ["en-US", "en-US"],
      ["es", "es-CO"],
      ["es-ES", "es-CO"],
      ["pt-PT", "pt-BR"],
      ["en-GB", "en-US"],
      ["fr-FR", "es-CO"],
      [undefined, "es-CO"],
    ] as const) {
      const { env } = fakeEnv({ navigatorLanguage: nav });
      expect(start(env).getSnapshot().context.locale).toBe(locale);
    }
  });

  test("LOCALE.SET picks the market and its language, and <html lang> follows the language", () => {
    const { env, attributes } = fakeEnv({ navigatorLanguage: "en-US" });
    const actor = start(env);
    actor.send({ type: "LOCALE.SET", locale: "es-MX" });
    expect(actor.getSnapshot().context).toEqual({ theme: "system", lang: "es", locale: "es-MX", detective: false });
    expect(attributes.get("lang")).toBe("es");
    actor.send({ type: "LOCALE.SET", locale: "es-AR" });
    expect(actor.getSnapshot().context.locale).toBe("es-AR");
  });

  test("LANG.SET keeps a market of the same language and moves to the default market of another", () => {
    const { env } = fakeEnv({ navigatorLanguage: "es-CO" });
    const actor = start(env);
    actor.send({ type: "LANG.SET", lang: "es" });
    expect(actor.getSnapshot().context.locale).toBe("es-CO");
    actor.send({ type: "LOCALE.SET", locale: "es-MX" });
    actor.send({ type: "LANG.SET", lang: "pt" });
    expect(actor.getSnapshot().context.locale).toBe("pt-BR");
    actor.send({ type: "LANG.SET", lang: "es" });
    expect(actor.getSnapshot().context.locale).toBe("es-CO");
  });
});

describe("detective switch (ADR-0019)", () => {
  test("off by default; DETECTIVE.SET turns it on and off and remembers it", () => {
    const { env, store } = fakeEnv();
    const actor = start(env);
    expect(actor.getSnapshot().context.detective).toBe(false);
    actor.send({ type: "DETECTIVE.SET", on: true });
    expect(actor.getSnapshot().context.detective).toBe(true);
    expect(store.get(DETECTIVE_STORAGE_KEY)).toBe("on");
    actor.send({ type: "DETECTIVE.SET", on: false });
    expect(actor.getSnapshot().context.detective).toBe(false);
    expect(store.has(DETECTIVE_STORAGE_KEY)).toBe(false);
  });

  test("a remembered choice is read back, and anything but \"on\" is off", () => {
    expect(start(fakeEnv({ stored: { [DETECTIVE_STORAGE_KEY]: "on" } }).env).getSnapshot().context.detective).toBe(true);
    expect(start(fakeEnv({ stored: { [DETECTIVE_STORAGE_KEY]: "yes" } }).env).getSnapshot().context.detective).toBe(false);
  });

  test("a storage that throws: off, and the switch still works for the visit", () => {
    const boom = () => {
      throw new Error("SecurityError");
    };
    const actor = start(fakeEnv({ storage: { getItem: boom, setItem: boom, removeItem: boom } }).env);
    expect(actor.getSnapshot().context.detective).toBe(false);
    actor.send({ type: "DETECTIVE.SET", on: true });
    expect(actor.getSnapshot().context.detective).toBe(true);
  });
});
