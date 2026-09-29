// The global machine: theme, language and the agent session.
//
//   booting ── session found ──▶ authenticated ── LOGOUT ──▶ signingOut ──▶ anonymous
//      └─ no session ──▶ anonymous ── LOGIN ──▶ signingIn ── ok ──▶ authenticated
//                                                    └─ error ──▶ anonymous (with `loginError`)
//
// `SESSION.EXPIRED` (any 401 from the BFF, see `createApi`) sends the agent back to the login from
// anywhere. Theme and language are handled at the root, in every state.

import { isThemeId, themeAttribute, type ThemeId } from "@pattern-blue/design-tokens/tokens";
import type { Lang } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import { isApiError, type Api } from "../api/client";
import { categorize } from "../api/errors";
import { DEFAULT_LANG } from "../i18n";

export type ThemeChoice = ThemeId | "system";
export const THEME_STORAGE_KEY = "pb-backoffice-theme";

/** The slice of Web Storage the machine uses, so a test can pass a fake (or one that throws). */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** The slice of `<html>` the machine writes to: `data-theme` and `lang`. */
export interface RootLike {
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
}

/** `localStorage`, or null: reading the accessor itself can throw (blocked site data, private windows). */
export function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** A stored choice is untrusted input: anything that is not a theme id is "system". */
export function readStoredTheme(storage: StorageLike | null): ThemeChoice {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY);
    return isThemeId(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function persistTheme(storage: StorageLike | null, choice: ThemeChoice): void {
  try {
    if (choice === "system") storage?.removeItem(THEME_STORAGE_KEY);
    else storage?.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Storage is a convenience: the choice still applies to this page.
  }
}

export function applyTheme(choice: ThemeChoice, root: RootLike | null): void {
  if (!root) return;
  if (choice === "system") root.removeAttribute(themeAttribute);
  else root.setAttribute(themeAttribute, choice);
}

export type LoginError = "invalid" | "malformed" | "unavailable";

export interface AppInput {
  api: Api;
  storage?: StorageLike | null;
  root?: RootLike | null;
  lang?: Lang;
}

export interface AppContext {
  api: Api;
  storage: StorageLike | null;
  root: RootLike | null;
  theme: ThemeChoice;
  lang: Lang;
  /** The e-mail the session was opened with; null when nobody is logged in. */
  agent: string | null;
  loginError: LoginError | null;
}

export type AppEvent =
  | { type: "THEME.SET"; theme: ThemeChoice }
  | { type: "LANG.SET"; lang: Lang }
  | { type: "LOGIN"; email: string; password: string }
  | { type: "LOGOUT" }
  | { type: "SESSION.EXPIRED" };

function loginErrorOf(error: unknown): LoginError {
  const category = categorize(error);
  if (isApiError(error) && error.status === 401) return "invalid";
  if (category === "validation") return "malformed";
  return "unavailable";
}

export const appMachine = setup({
  types: {
    context: {} as AppContext,
    events: {} as AppEvent,
    input: {} as AppInput,
  },
  actors: {
    restoreSession: fromPromise(({ input }: { input: { api: Api } }) => input.api.getSession()),
    signIn: fromPromise(async ({ input }: { input: { api: Api; email: string; password: string } }) => {
      await input.api.login(input.email, input.password);
      return input.api.getSession();
    }),
    signOut: fromPromise(({ input }: { input: { api: Api } }) => input.api.logout()),
  },
  actions: {
    applyTheme: ({ context }) => applyTheme(context.theme, context.root),
    persistTheme: ({ context }) => persistTheme(context.storage, context.theme),
    applyLang: ({ context }) => context.root?.setAttribute("lang", context.lang),
    forgetAgent: assign({ agent: null }),
  },
}).createMachine({
  id: "app",
  context: ({ input }) => ({
    api: input.api,
    storage: input.storage ?? null,
    root: input.root ?? null,
    theme: readStoredTheme(input.storage ?? null),
    lang: input.lang ?? DEFAULT_LANG,
    agent: null,
    loginError: null,
  }),
  entry: ["applyTheme", "applyLang"],
  on: {
    "THEME.SET": { actions: [assign({ theme: ({ event }) => event.theme }), "applyTheme", "persistTheme"] },
    "LANG.SET": { actions: [assign({ lang: ({ event }) => event.lang }), "applyLang"] },
    "SESSION.EXPIRED": { target: ".anonymous", actions: "forgetAgent" },
  },
  initial: "booting",
  states: {
    booting: {
      invoke: {
        src: "restoreSession",
        input: ({ context }) => ({ api: context.api }),
        onDone: { target: "authenticated", actions: assign({ agent: ({ event }) => event.output.agent_ref }) },
        onError: { target: "anonymous" },
      },
    },
    anonymous: {
      on: { LOGIN: "signingIn" },
    },
    signingIn: {
      entry: assign({ loginError: null }),
      invoke: {
        src: "signIn",
        input: ({ context, event }) => ({
          api: context.api,
          email: event.type === "LOGIN" ? event.email : "",
          password: event.type === "LOGIN" ? event.password : "",
        }),
        onDone: { target: "authenticated", actions: assign({ agent: ({ event }) => event.output.agent_ref }) },
        onError: { target: "anonymous", actions: assign({ loginError: ({ event }) => loginErrorOf(event.error) }) },
      },
    },
    authenticated: {
      on: { LOGOUT: "signingOut" },
    },
    signingOut: {
      invoke: {
        src: "signOut",
        input: ({ context }) => ({ api: context.api }),
        // Whether or not the server heard it, this browser is done with the session.
        onDone: { target: "anonymous", actions: "forgetAgent" },
        onError: { target: "anonymous", actions: "forgetAgent" },
      },
    },
  },
});
