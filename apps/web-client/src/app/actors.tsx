// The two machines of the page, created once outside React (so StrictMode cannot start them twice) and
// handed to the tree through context.

import { useSelector } from "@xstate/react";
import { createContext, useContext, type ReactNode } from "react";
import type { ActorRefFrom } from "xstate";
import type { Lang } from "@pattern-blue/contracts";
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

export function useTheme(): { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void } {
  const { app } = useActors();
  const theme = useSelector(app, (snapshot) => snapshot.context.theme);
  return { theme, setTheme: (next) => app.send({ type: "THEME.SET", theme: next }) };
}
