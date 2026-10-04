// The two machines of the page, created once outside React (so StrictMode cannot start them twice) and
// handed to the tree through context.

import { useSelector } from "@xstate/react";
import { createContext, useContext, type ReactNode } from "react";
import type { ActorRefFrom } from "xstate";
import type { Lang, Locale } from "@pattern-blue/contracts";
import { dictionaries, type Dictionary } from "../i18n";
import type { AppMachine, ThemeChoice } from "../machines/app.machine";
import type { ChatMachine } from "../machines/chat.machine";

export interface Actors {
  app: ActorRefFrom<AppMachine>;
  chat: ActorRefFrom<ChatMachine>;
}

const ActorsContext = createContext<Actors | null>(null);

export function ActorsProvider({ actors, children }: { actors: Actors; children: ReactNode }) {
  return <ActorsContext.Provider value={actors}>{children}</ActorsContext.Provider>;
}

export function useActors(): Actors {
  const actors = useContext(ActorsContext);
  if (!actors) throw new Error("useActors needs an <ActorsProvider>");
  return actors;
}

export function useI18n(): { lang: Lang; dict: Dictionary; setLang: (lang: Lang) => void } {
  const { app } = useActors();
  const lang = useSelector(app, (snapshot) => snapshot.context.lang);
  return { lang, dict: dictionaries[lang], setLang: (next) => app.send({ type: "LANG.SET", lang: next }) };
}

/** The customer's market, or null. Picking one also sets its language. */
export function useLocale(): { locale: Locale | null; setLocale: (locale: Locale) => void } {
  const { app } = useActors();
  const locale = useSelector(app, (snapshot) => snapshot.context.locale);
  return { locale, setLocale: (next) => app.send({ type: "LOCALE.SET", locale: next }) };
}

/** The viewer's detective switch (ADR-0019): shown only where detective mode is on. */
export function useDetective(): { on: boolean; setOn: (on: boolean) => void } {
  const { app } = useActors();
  const on = useSelector(app, (snapshot) => snapshot.context.detective);
  return { on, setOn: (next) => app.send({ type: "DETECTIVE.SET", on: next }) };
}

export function useTheme(): { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void } {
  const { app } = useActors();
  const theme = useSelector(app, (snapshot) => snapshot.context.theme);
  return { theme, setTheme: (next) => app.send({ type: "THEME.SET", theme: next }) };
}
