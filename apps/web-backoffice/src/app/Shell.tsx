// The frame of every screen: the wordmark, the sections, one theme button and the agent's menu (the
// declutter review of 2026-10-02). There is no app-shell component in the design system, so this is the
// Navbar's parts put to work in the back office, plus a count on "Cola" and the menu (local.css).

import { LangSchema, type Lang } from "@pattern-blue/contracts";
import { useSelector } from "@xstate/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ThemeChoice } from "../machines/app";
import { useAppServices, useI18n, useLang } from "./context";
import type { Route } from "./router";
import { Icon } from "./ui";

const LANGUAGE_NAME: Record<Lang, string> = { es: "Español", pt: "Português", en: "English" };

/** How often the navigation counts the cases nobody took. */
export const QUEUE_COUNT_MS = 15000;

/** The theme in force: the pinned choice, or what the system prefers when nothing is pinned. */
function effectiveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The number of queued cases, read every 15 s while the tab is visible; null until the first answer. */
function useQueuedCount(enabled: boolean): number | null {
  const { api } = useAppServices();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const read = () => {
      if (document.visibilityState === "hidden") return;
      api.listHandoffs(["QUEUED"]).then(
        (answer) => live && setCount(answer.items.length),
        () => undefined,
      );
    };
    read();
    const timer = setInterval(read, QUEUE_COUNT_MS);
    document.addEventListener("visibilitychange", read);
    return () => {
      live = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", read);
    };
  }, [api, enabled]);
  return count;
}

function AgentMenu({ agent }: { agent: string }) {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="pb-menu" ref={root}>
      <button type="button" className="pb-menu__btn" aria-expanded={open} aria-controls="bo-agent-menu" onClick={() => setOpen(!open)}>
        <Icon name="user" />
        {agent}
        <Icon name="chev1" />
      </button>
      <div className="pb-cut pb-menu__panel" id="bo-agent-menu" hidden={!open}>
        <p>{t("nav.signedInAs", { agent })}</p>
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
        <hr />
        <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => actor.send({ type: "LOGOUT" })}>
          {t("nav.logout")}
        </button>
      </div>
    </div>
  );
}

export function Shell({ route, authenticated, children }: { route: Route; authenticated: boolean; children: ReactNode }) {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const lang = useLang();
  const theme = useSelector(actor, (snapshot) => snapshot.context.theme);
  const agent = useSelector(actor, (snapshot) => snapshot.context.agent);
  const [open, setOpen] = useState(false);
  const shownTheme = effectiveTheme(theme);
  const queued = useQueuedCount(authenticated);

  const link = (href: string, label: string, current: boolean, extra?: ReactNode) => (
    <a className="pb-nav__link" href={href} aria-current={current ? "page" : undefined} onClick={() => setOpen(false)}>
      {label}
      {extra}
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
                {link(
                  "#/",
                  t("nav.queue"),
                  route.name === "queue" || route.name === "handoff",
                  queued !== null && queued > 0 ? (
                    <span className="pb-nav__count" title={t("nav.queueCount", { count: queued })}>
                      {queued}
                    </span>
                  ) : null,
                )}
                {link("#/guardrails", t("nav.guardrails"), route.name === "guardrails")}
                {link("#/metrics", t("nav.metrics"), route.name === "metrics")}
              </nav>
            )}
            <div className="pb-nav__tools">
              <div className="pb-theme pb-theme--single">
                <button
                  type="button"
                  className="pb-theme__btn"
                  aria-label={shownTheme === "dark" ? t("nav.themeToLight") : t("nav.themeToDark")}
                  onClick={() => actor.send({ type: "THEME.SET", theme: shownTheme === "dark" ? "light" : "dark" })}
                >
                  <Icon name={shownTheme === "dark" ? "sun" : "moon"} />
                </button>
              </div>
              {authenticated && agent ? (
                <AgentMenu agent={agent} />
              ) : (
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
              )}
            </div>
          </div>
        </div>
      </header>
      <div className="bo-main">{children}</div>
    </>
  );
}
