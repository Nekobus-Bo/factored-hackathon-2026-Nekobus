// The frame of every screen: the wordmark, the sections, the theme tool and the agent's menu (the
// declutter review of 2026-10-02). There is no app-shell component in the design system, so this is the
// Navbar's parts put to work in the back office, plus a count on "Cola" and the menu (local.css).

import { LangSchema, type Lang } from "@pattern-blue/contracts";
import { useSelector } from "@xstate/react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { ThemeChoice } from "../machines/app";
import { useAppServices, useI18n, useLang, useTheme } from "./context";
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

/**
 * The brand's name in two parts, "Pattern" in the main text colour and the last word in the brand's blue. The text is
 * unchanged ("Pattern Blue"); capitals are the stylesheet's.
 */
function BrandName({ name }: { name: string }) {
  const at = name.lastIndexOf(" ");
  if (at < 0) return <>{name}</>;
  return (
    <>
      <span className="pb-wordmark__ink">{name.slice(0, at)}</span> <span className="pb-wordmark__blue">{name.slice(at + 1)}</span>
    </>
  );
}

/** A header tool: the visible label (the `label` style), then the radio group it names. */
function Tool({ label, children }: { label: string; children: (labelId: string) => ReactNode }) {
  const labelId = useId();
  return (
    <div className="pb-navtool">
      <span className="pb-navtool__label" id={labelId}>
        {label}
      </span>
      {children(labelId)}
    </div>
  );
}

/** The language: ES, PT, EN as radios, the one in force checked. */
export function LanguageRadios({ labelId }: { labelId: string }) {
  const { actor } = useAppServices();
  const lang = useLang();
  return (
    <div className="pb-lang pb-lang--fill" role="radiogroup" aria-labelledby={labelId}>
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
  );
}

/**
 * The theme: a sun and a moon as radios, named "Claro" and "Oscuro"; the one checked is the theme in force (the
 * system's until one is pinned). It has no visible label: the group is named "Tema" for assistive technology.
 */
export function ThemeTool() {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const shown = effectiveTheme(useTheme());
  const options = [
    { id: "light", icon: "sun", name: t("nav.themeLight") },
    { id: "dark", icon: "moon", name: t("nav.themeDark") },
  ] as const;
  return (
    <div className="pb-navtool">
      <div className="pb-lang pb-lang--fill" role="radiogroup" aria-label={t("nav.theme")}>
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className="pb-lang__btn"
            role="radio"
            aria-checked={shown === option.id}
            aria-label={option.name}
            title={option.name}
            data-theme-set={option.id}
            onClick={() => actor.send({ type: "THEME.SET", theme: option.id })}
          >
            <Icon name={option.icon} />
          </button>
        ))}
      </div>
    </div>
  );
}

/** The agent's menu: a button of the system with the e-mail, and a panel in sections: Sesión, Idioma, and Salir. */
export function AgentMenu({ agent }: { agent: string }) {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const languageId = useId();

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
      <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm pb-menu__btn" aria-expanded={open} aria-controls="bo-agent-menu" onClick={() => setOpen(!open)}>
        <Icon name="user" />
        <span className="pb-menu__agent" title={agent}>
          {agent}
        </span>
        <Icon name="chev1" />
      </button>
      <div className="pb-cut pb-menu__panel" id="bo-agent-menu" hidden={!open}>
        <div className="pb-menu__section">
          <span className="pb-t-label">{t("nav.session")}</span>
          <p className="pb-menu__email pb-t-mono">{agent}</p>
        </div>
        <div className="pb-menu__section">
          <span className="pb-t-label" id={languageId}>
            {t("nav.language")}
          </span>
          <LanguageRadios labelId={languageId} />
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
  const agent = useSelector(actor, (snapshot) => snapshot.context.agent);
  const [open, setOpen] = useState(false);
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
            <BrandName name={t("app.name")} />
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
                {link("#/flows", t("nav.flows"), route.name === "flows")}
              </nav>
            )}
            <div className="pb-nav__tools">
              <ThemeTool />
              {authenticated && agent ? (
                <AgentMenu agent={agent} />
              ) : (
                <Tool label={t("nav.language")}>{(labelId) => <LanguageRadios labelId={labelId} />}</Tool>
              )}
            </div>
          </div>
        </div>
      </header>
      <div className="bo-main">{children}</div>
    </>
  );
}
