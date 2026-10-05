// The back office's header tools, on the markup: the theme as two radios with no visible label, and the agent's
// menu as a button of the system with a panel in labelled sections.

import { describe, expect, test } from "bun:test";
import type { Lang } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { createApi } from "../src/api/client";
import { AppServicesProvider, I18nProvider } from "../src/app/context";
import { AgentMenu, Shell, ThemeTool } from "../src/app/Shell";
import { appMachine } from "../src/machines/app";
import { dictionaries } from "../src/i18n";
import { AGENT_EMAIL } from "./support/fixtures";
import { fakeFetch } from "./support/fake-fetch";

function render(element: React.ReactElement, lang: Lang = "es") {
  const actor = createActor(appMachine, { input: { api: createApi(fakeFetch({}).fetch), storage: null, root: null, lang } }).start();
  const markup = renderToStaticMarkup(
    <I18nProvider lang={lang}>
      <AppServicesProvider actor={actor} api={createApi(fakeFetch({}).fetch)}>
        {element}
      </AppServicesProvider>
    </I18nProvider>,
  );
  actor.stop();
  return markup;
}

describe("the theme tool", () => {
  test("no visible label: a group named Tema for assistive technology and two radios with an icon, named Claro and Oscuro, one checked", () => {
    const html = render(<ThemeTool />);
    expect(html).toContain('<div class="pb-navtool"><div class="pb-lang pb-lang--fill" role="radiogroup" aria-label="Tema">');
    expect(html).not.toContain("pb-navtool__label");
    expect(html).toContain('aria-label="Claro" title="Claro" data-theme-set="light"');
    expect(html).toContain('aria-label="Oscuro" title="Oscuro" data-theme-set="dark"');
    expect(html).toContain("pb-ico--sun");
    expect(html).toContain("pb-ico--moon");
    expect(html.match(/role="radio"/g)).toHaveLength(2);
    expect(html.match(/aria-checked="true"/g)).toHaveLength(1);
    // no square toggle of the old bar
    expect(html).not.toContain("pb-theme");
  });

  test("in each language", () => {
    for (const [lang, theme, light, dark] of [["pt", "Tema", "Claro", "Escuro"], ["en", "Theme", "Light", "Dark"]] as const) {
      const html = render(<ThemeTool />, lang);
      expect(html).toContain(`aria-label="${theme}"`);
      expect(html).toContain(`aria-label="${light}"`);
      expect(html).toContain(`aria-label="${dark}"`);
    }
  });
});

describe("the agent's menu", () => {
  const html = render(<AgentMenu agent={AGENT_EMAIL} />);

  test("the button is a button of the system with the user glyph and the chevron and no e-mail in the bar: the e-mail is its name and its tooltip", () => {
    const button = html.slice(0, html.indexOf("</button>"));
    expect(button).toContain('<button type="button" class="pb-btn pb-btn--ghost pb-btn--sm pb-menu__btn" aria-expanded="false" aria-controls="bo-agent-menu"');
    expect(button).toContain(`aria-label="Menú del agente, ${AGENT_EMAIL}" title="${AGENT_EMAIL}"`);
    expect(button).toContain('<i class="pb-ico pb-ico--user" aria-hidden="true"></i>');
    expect(button.indexOf("pb-ico--chev1")).toBeGreaterThan(button.indexOf("pb-ico--user"));
    // no text in the button, only its two glyphs
    expect(button.replace(/<[^>]*>/g, "").length).toBe(0);
    expect(button).not.toContain("pb-menu__agent");
  });

  test("where there is room (the folded panel) the e-mail shows next to the glyph, still named the same", () => {
    const wide = render(<AgentMenu agent={AGENT_EMAIL} showEmail />);
    expect(wide).toContain(`<span class="pb-menu__agent">${AGENT_EMAIL}</span>`);
    expect(wide).toContain(`aria-label="Menú del agente, ${AGENT_EMAIL}"`);
  });

  test("the panel has Sesión with the e-mail in the data type, then a rule and Salir as a secondary button, and no language", () => {
    const panel = html.slice(html.indexOf('<div class="pb-cut pb-menu__panel"'));
    expect(panel).toMatch(/<span class="pb-t-label">Sesión<\/span><p class="pb-menu__email pb-t-mono">/);
    expect(panel).toContain(`>${AGENT_EMAIL}</p>`);
    expect(panel).not.toContain("data-lang");
    expect(panel).not.toContain("Idioma");
    expect(panel).not.toContain("pb-lang");
    expect(panel).toMatch(/<hr\/><button type="button" class="pb-btn pb-btn--secondary pb-btn--sm">Salir<\/button>/);
    // closed until the button opens it
    expect(panel).toMatch(/id="bo-agent-menu" hidden=""/);
  });

  test("in each language", () => {
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "pt")).toContain(">Sessão</span>");
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "en")).toContain(">Session</span>");
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "pt")).toContain(`aria-label="Menu do agente, ${AGENT_EMAIL}"`);
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "en")).toContain(`aria-label="Agent menu, ${AGENT_EMAIL}"`);
    for (const lang of ["es", "pt", "en"] as const) expect(dictionaries[lang].nav.session.length).toBeGreaterThan(0);
  });
});

describe("the bar", () => {
  const bar = (authenticated: boolean, lang: Lang = "es") =>
    render(
      <Shell route={{ name: "queue" }} authenticated={authenticated}>
        {null}
      </Shell>,
      lang,
    );

  test("before a session the bar holds the wordmark, the tag, the language with its label and the theme (named, with no visible label)", () => {
    const html = bar(false);
    expect([...html.matchAll(/<span class="pb-navtool__label" id="[^"]+">([^<]*)<\/span>/g)].map((match) => match[1])).toEqual(["Idioma"]);
    expect(html).toContain('role="radiogroup" aria-label="Tema"');
    expect(html).toContain('<span class="pb-t-label bo-section-tag">Back office</span>');
    // the brand: two parts, the text unchanged, the accessible name unchanged
    expect(html).toContain('<span class="pb-wordmark__ink">Pattern</span> <span class="pb-wordmark__blue">Blue</span>');
    expect(html).toContain('aria-label="Pattern Blue, Back office"');
    expect(html).not.toContain("PATTERN BLUE");
    expect(html).not.toContain("pb-theme");
  });

  test.each([false, true])("the language group is a child of the bar, after the folded panel and outside it, and the same one with a session (%p)", (authenticated) => {
    const html = bar(authenticated);
    const panelStart = html.indexOf('<div class="pb-nav__collapse" id="bo-menu">');
    const language = html.indexOf('<div class="pb-navtool bo-lang">');
    expect(panelStart).toBeGreaterThan(-1);
    expect(language).toBeGreaterThan(panelStart);
    // the panel closes right before the language group: nothing of the language is inside it
    const panel = html.slice(panelStart, language);
    expect(panel).not.toContain("data-lang");
    expect(panel).not.toContain("Idioma");
    // and the group is the one of the system, named by its label, with ES, PT and EN
    const group = html.slice(language, html.indexOf('<div class="bo-bartools">', language));
    expect(group).toMatch(/<span class="pb-navtool__label" id="([^"]+)">Idioma<\/span><div class="pb-lang pb-lang--fill" role="radiogroup" aria-labelledby="\1">/);
    expect([...group.matchAll(/data-lang="(\w+)"/g)].map((match) => match[1])).toEqual(["es", "pt", "en"]);
    // the theme sits after it, in the bar's own group, and the menu button closes the bar
    expect(html.indexOf('aria-label="Tema"')).toBeGreaterThan(language);
    expect(html.indexOf('class="pb-nav__menu"')).toBeGreaterThan(html.indexOf('aria-label="Tema"'));
  });

  test("the button of the folded bar has a name of its own and keeps the word apart from it, so a phone can show only the icon", () => {
    const html = bar(true);
    expect(html).toContain('<button type="button" class="pb-nav__menu" aria-expanded="false" aria-controls="bo-menu" aria-label="Menú">');
    expect(html).toContain('<span class="bo-menu-word">Menú</span>');
    expect(bar(true, "en")).toContain('aria-label="Menu"');
  });

  test("the sections are in the folded panel and the agent's menu has no e-mail text in the bar", () => {
    const html = bar(true);
    const panel = html.slice(html.indexOf('<div class="pb-nav__collapse" id="bo-menu">'), html.indexOf('<div class="pb-navtool bo-lang">'));
    for (const word of ["Cola", "Guardrails", "Métricas", "Flujos"]) expect(panel).toContain(word);
    expect(html).not.toContain("pb-menu__agent");
  });
});

describe("the header's stylesheet", () => {
  const read = (path: string) => Bun.file(new URL(path, import.meta.url)).text();

  test("the language is not folded away at the fold: its label hides, the group keeps its name, and nothing hides the group itself", async () => {
    const css = await read("../src/app/app.css");
    expect(css).toMatch(/@media \(max-width: 1140px\) \{\s*\.bo-lang \.pb-navtool__label \{ display: none; \}/);
    expect(css).not.toMatch(/\.bo-lang \{[^}]*display: none/);
    expect(css).not.toMatch(/\.bo-lang[^{]*\{[^}]*order:/);
  });

  test("the theme and the agent go into the panel on a phone: the component asks the browser at the width the stylesheet's comment names", async () => {
    const css = await read("../src/app/app.css");
    const shell = await read("../src/app/Shell.tsx");
    expect(shell).toContain('const COMPACT_BAR = "(max-width: 759px)";');
    expect(css).toContain("`COMPACT_BAR` in Shell.tsx has the same width");
    // the tag goes below 600px, with room for the wordmark, the language and the button beside it above
    expect(css).toMatch(/@media \(max-width: 599px\) \{\s*\.bo-section-tag \{ display: none; \}/);
  });

  test("the small phones keep 32px targets, a smaller wordmark and a button with only its icon", async () => {
    const css = await read("../src/app/app.css");
    const block = /@media \(max-width: 480px\) \{([^@]*?)\n\}/.exec(css)?.[1] ?? "";
    expect(block).toContain(".bo-lang .pb-lang__btn { min-width: 32px; min-height: 32px;");
    expect(block).toContain(".pb-nav__menu { min-width: 32px; min-height: 32px; }");
    expect(block).toContain(".bo-menu-word { display: none; }");
    expect(block).toContain("clamp(20px, 6.6vw, 30px)");
  });
});
