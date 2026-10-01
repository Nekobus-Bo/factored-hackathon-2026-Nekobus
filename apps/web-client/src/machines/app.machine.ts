// The global machine: the theme and the language of the page.
//
//   theme  system | light | dark. `system` leaves `data-theme` off `<html>` and the page follows the
//          browser; the other two pin it. The choice is remembered in localStorage (every access is
//          wrapped: the storage can be missing, blocked or throw, and the page works without it).
//   lang   es | pt | en, from `navigator.language`, Spanish when it is none of them. It is not
//          remembered: the page follows the browser on load, and the switch changes it for this visit.
//
// The effects (the attribute on `<html>`, the storage) go through the `env` the factory receives, so a
// test runs the same machine with fakes.

import type { Lang } from "@pattern-blue/contracts";
import { isThemeId, themeAttribute } from "@pattern-blue/design-tokens/tokens";
import { assign, createMachine } from "xstate";
import { detectLang } from "../i18n";

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "pb-theme";

export interface AppContext {
  theme: ThemeChoice;
  lang: Lang;
}

export type AppEvent = { type: "THEME.SET"; theme: ThemeChoice } | { type: "LANG.SET"; lang: Lang };

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

  return createMachine({
    types: {} as { context: AppContext; events: AppEvent },
    id: "app",
    context: (): AppContext => ({
      theme: readStoredTheme(env.storage),
      lang: detectLang(env.navigatorLanguage),
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
              assign({ lang: ({ event }) => event.lang }),
              ({ event }) => env.root?.setAttribute("lang", event.lang),
            ],
          },
        },
      },
    },
  });
}

export type AppMachine = ReturnType<typeof createAppMachine>;
