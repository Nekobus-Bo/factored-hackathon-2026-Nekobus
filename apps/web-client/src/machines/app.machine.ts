// The global machine: the theme, the language and the market of the page.
//
//   theme  system | light | dark. `system` leaves `data-theme` off `<html>` and the page follows the
//          browser; the other two pin it. The choice is remembered in localStorage (every access is
//          wrapped: the storage can be missing, blocked or throw, and the page works without it).
//   lang   es | pt | en, from `navigator.language`, Spanish when it is none of them. It is not
//          remembered: the page follows the browser on load, and the switch changes it for this visit.
//   locale the customer's market (ADR-0014): es-CO | es-MX | es-AR | pt-BR | en-US.
//          From `navigator.language` when it names a market exactly, else the default market of `lang`
//          (es-CO for Spanish), or the market switch. It always belongs to `lang`: picking a market sets
//          its language, and switching to another language moves to that language's default market. The page text does not change with it (one Spanish for every Spanish market); the
//          chat sends it when it creates the conversation, so the encoder uses that market's thresholds.
//          Not remembered, like `lang`.
//   detective the viewer's switch for detective mode (ADR-0019): show each turn's trace. Remembered like
//          the theme, off by default; the chat offers it only where the orchestrator says the mode is on.
//
// The effects (the attribute on `<html>`, the storage) go through the `env` the factory receives, so a
// test runs the same machine with fakes.

import type { Lang, Locale } from "@pattern-blue/contracts";
import { isThemeId, themeAttribute } from "@pattern-blue/design-tokens/tokens";
import { assign, createMachine } from "xstate";
import { DEFAULT_LOCALES, langOf, startLocale } from "../i18n";

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "pb-theme";
/** The viewer's detective switch (ADR-0019): "on" or absent. A convenience, not a setting. */
export const DETECTIVE_STORAGE_KEY = "pb-detective";

export interface AppContext {
  theme: ThemeChoice;
  lang: Lang;
  locale: Locale | null;
  /** The viewer wants each turn's trace shown, where detective mode is on. Remembered, off by default. */
  detective: boolean;
}

export type AppEvent =
  | { type: "THEME.SET"; theme: ThemeChoice }
  | { type: "LANG.SET"; lang: Lang }
  | { type: "LOCALE.SET"; locale: Locale }
  | { type: "DETECTIVE.SET"; on: boolean };

export interface AppEnv {
  /** `localStorage`, or null when the browser has none. Any call may throw. */
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  /** `document.documentElement`, or null on the server. */
  root: Pick<HTMLElement, "setAttribute" | "removeAttribute"> | null;
  navigatorLanguage: string | undefined;
}

/** The environment of a browser tab. Reading `localStorage` itself can throw, hence the try. */
export function browserEnv(): AppEnv {
  let storage: AppEnv["storage"] = null;
  try {
    storage = window.localStorage;
  } catch {
    storage = null;
  }
  return {
    storage,
    root: document.documentElement,
    navigatorLanguage: navigator.language,
  };
}

/** A remembered choice is untrusted input: check it. */
export function readStoredTheme(storage: AppEnv["storage"]): ThemeChoice {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY) ?? null;
    return isThemeId(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function readStoredDetective(storage: AppEnv["storage"]): boolean {
  try {
    return storage?.getItem(DETECTIVE_STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

export function createAppMachine(env: AppEnv) {
  const applyTheme = (theme: ThemeChoice) => {
    if (theme === "system") env.root?.removeAttribute(themeAttribute);
    else env.root?.setAttribute(themeAttribute, theme);
  };

  const persistTheme = (theme: ThemeChoice) => {
    try {
      if (theme === "system") env.storage?.removeItem(THEME_STORAGE_KEY);
      else env.storage?.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // The choice holds for this visit; it is just not remembered.
    }
  };

  const persistDetective = (on: boolean) => {
    try {
      if (on) env.storage?.setItem(DETECTIVE_STORAGE_KEY, "on");
      else env.storage?.removeItem(DETECTIVE_STORAGE_KEY);
    } catch {
      // As for the theme: it holds for this visit.
    }
  };

  return createMachine({
    types: {} as { context: AppContext; events: AppEvent },
    id: "app",
    context: (): AppContext => ({
      theme: readStoredTheme(env.storage),
      lang: langOf(startLocale(env.navigatorLanguage)),
      locale: startLocale(env.navigatorLanguage),
      detective: readStoredDetective(env.storage),
    }),
    initial: "ready",
    // What the page starts with reaches <html> once, so the attributes never depend on a component mounting.
    entry: ({ context }) => {
      applyTheme(context.theme);
      env.root?.setAttribute("lang", context.lang);
    },
    states: {
      ready: {
        on: {
          "THEME.SET": {
            actions: [
              assign({ theme: ({ event }) => event.theme }),
              ({ event }) => {
                applyTheme(event.theme);
                persistTheme(event.theme);
              },
            ],
          },
          "LANG.SET": {
            actions: [
              assign({
                lang: ({ event }) => event.lang,
                locale: ({ context, event }) =>
                  context.locale && langOf(context.locale) === event.lang ? context.locale : DEFAULT_LOCALES[event.lang],
              }),
              ({ event }) => env.root?.setAttribute("lang", event.lang),
            ],
          },
          "DETECTIVE.SET": {
            actions: [assign({ detective: ({ event }) => event.on }), ({ event }) => persistDetective(event.on)],
          },
          "LOCALE.SET": {
            actions: [
              assign({ locale: ({ event }) => event.locale, lang: ({ event }) => langOf(event.locale) }),
              ({ event }) => env.root?.setAttribute("lang", langOf(event.locale)),
            ],
          },
        },
      },
    },
  });
}

export type AppMachine = ReturnType<typeof createAppMachine>;
