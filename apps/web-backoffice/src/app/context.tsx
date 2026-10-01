// What every screen needs from the global machine: the language (as a translator), the theme, the
// session and the API. The default context is Spanish with no session, which is also what a server
// render in a test gets without a provider.

import type { Lang } from "@pattern-blue/contracts";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useSelector } from "@xstate/react";
import type { ActorRefFrom } from "xstate";
import type { Api } from "../api/client";
import { DEFAULT_LANG, toolNote, translator, type Translate } from "../i18n";
import type { appMachine, ThemeChoice } from "../machines/app";

export interface I18n {
  lang: Lang;
  t: Translate;
  /** The matrix's one-line note for a tool, if the dictionaries have one. */
  note: (tool: string) => string | undefined;
}

export function makeI18n(lang: Lang): I18n {
  return { lang, t: translator(lang), note: (tool) => toolNote(lang, tool) };
}

const I18nContext = createContext<I18n>(makeI18n(DEFAULT_LANG));

export const I18nProvider = ({ lang, children }: { lang: Lang; children: ReactNode }) => (
  <I18nContext.Provider value={makeI18n(lang)}>{children}</I18nContext.Provider>
);

export const useI18n = (): I18n => useContext(I18nContext);
export const useT = (): Translate => useContext(I18nContext).t;

export type AppActor = ActorRefFrom<typeof appMachine>;

interface AppServices {
  actor: AppActor;
  api: Api;
}

const AppContext = createContext<AppServices | null>(null);

export const AppServicesProvider = ({ actor, api, children }: AppServices & { children: ReactNode }) => (
  <AppContext.Provider value={{ actor, api }}>{children}</AppContext.Provider>
);

export function useAppServices(): AppServices {
  const services = useContext(AppContext);
  if (!services) throw new Error("useAppServices needs an AppServicesProvider");
  return services;
}

export function useLang(): Lang {
  const { actor } = useAppServices();
  return useSelector(actor, (snapshot) => snapshot.context.lang);
}

export function useTheme(): ThemeChoice {
  const { actor } = useAppServices();
  return useSelector(actor, (snapshot) => snapshot.context.theme);
}

/**
 * Tell a machine whether the tab is visible: its polling pauses while it is hidden and resumes, with an
 * immediate refresh, when it is back.
 */
export function useVisibility(send: (event: { type: "VISIBILITY"; visible: boolean }) => void): void {
  useEffect(() => {
    const report = () => send({ type: "VISIBILITY", visible: document.visibilityState !== "hidden" });
    document.addEventListener("visibilitychange", report);
    // The tab may already be hidden when the screen mounts (opened in the background).
    if (document.visibilityState === "hidden") report();
    return () => document.removeEventListener("visibilitychange", report);
  }, [send]);
}

/** A clock that re-renders its component every `intervalMs`, for waiting times that tick. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs, setNow]);
  return now;
}
