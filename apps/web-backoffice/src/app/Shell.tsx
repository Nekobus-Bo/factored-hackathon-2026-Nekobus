// The frame of every screen: the wordmark, the sections, the language and theme switches and the session.
// There is no app-shell component in the design system, so this is the Navbar's parts (pb-nav, pb-lang,
// pb-theme) put to work in the back office: sentence-case headings, no title cards.

import { LangSchema, type Lang } from "@pattern-blue/contracts";
import { useSelector } from "@xstate/react";
import { useState, type ReactNode } from "react";
import type { ThemeChoice } from "../machines/app";
import { useAppServices, useI18n, useLang } from "./context";
import type { Route } from "./router";
import { Icon } from "./ui";

const LANGUAGE_NAME: Record<Lang, string> = { es: "Español", pt: "Português", en: "English" };

/** The theme in force: the pinned choice, or what the system prefers when nothing is pinned. */
function effectiveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function Shell({ route, authenticated, children }: { route: Route; authenticated: boolean; children: ReactNode }) {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const lang = useLang();
  const theme = useSelector(actor, (snapshot) => snapshot.context.theme);
  const agent = useSelector(actor, (snapshot) => snapshot.context.agent);
  const [open, setOpen] = useState(false);
  const shownTheme = effectiveTheme(theme);

  const link = (href: string, label: string, current: boolean) => (
    <a className="pb-nav__link" href={href} aria-current={current ? "page" : undefined} onClick={() => setOpen(false)}>
      {label}
    </a>
  );

  return (
    <>
      <header className="pb-nav" data-open={open ? "true" : "false"}>
        <div className="pb-nav__bar">
          <a className="pb-nav__brand" href="#/" aria-label={`${t("app.name")}, ${t("app.section")}`}>
            {t("app.name")}
          </a>
          <span className="pb-t-label bo-section-tag">{t("app.section")}</span>
          <button type="button" className="pb-nav__menu" aria-expanded={open} aria-controls="bo-menu" onClick={() => setOpen(!open)}>
            <Icon name={open ? "x" : "menu"} />
            {t("nav.menu")}
          </button>
          <div className="pb-nav__collapse" id="bo-menu">
            {authenticated && (
              <nav className="pb-nav__links" aria-label={t("nav.label")}>
                {link("#/", t("nav.queue"), route.name === "queue" || route.name === "handoff")}
                {link("#/guardrails", t("nav.guardrails"), route.name === "guardrails")}
                {link("#/metrics", t("nav.metrics"), route.name === "metrics")}
              </nav>
            )}
            <div className="pb-nav__tools">
              <div className="pb-lang" role="radiogroup" aria-label={t("nav.language")}>
                {LangSchema.options.map((code) => (
                  <button
                    key={code}
                    type="button"
                    className="pb-lang__btn"
                    role="radio"
                    aria-checked={lang === code}
                    data-lang={code}
                    lang={code}
                    aria-label={LANGUAGE_NAME[code]}
                    onClick={() => actor.send({ type: "LANG.SET", lang: code })}
                  >
                    {code.toUpperCase()}
                  </button>
                ))}
              </div>
              <div className="pb-theme" role="radiogroup" aria-label={t("nav.theme")}>
                <button type="button" className="pb-theme__btn" role="radio" aria-checked={shownTheme === "light"} data-theme-set="light" aria-label={t("nav.themeLight")} onClick={() => actor.send({ type: "THEME.SET", theme: "light" })}>
                  <Icon name="sun" />
                </button>
                <button type="button" className="pb-theme__btn" role="radio" aria-checked={shownTheme === "dark"} data-theme-set="dark" aria-label={t("nav.themeDark")} onClick={() => actor.send({ type: "THEME.SET", theme: "dark" })}>
                  <Icon name="moon" />
                </button>
              </div>
              {authenticated && (
                <span className="bo-session">
                  {agent && <span className="pb-t-small" title={t("nav.signedInAs", { agent })}>{agent}</span>}
                  <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => actor.send({ type: "LOGOUT" })}>
                    {t("nav.logout")}
                  </button>
                </span>
              )}
            </div>
          </div>
        </div>
      </header>
      <div className="bo-main">{children}</div>
    </>
  );
}
