// The back office's header tools, on the markup: the theme as two radios under a visible label, and the agent's
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

  test("the button is a button of the system with the user icon, the e-mail in the data type, and the chevron", () => {
    expect(html).toContain('<button type="button" class="pb-btn pb-btn--ghost pb-btn--sm pb-menu__btn" aria-expanded="false" aria-controls="bo-agent-menu">');
    expect(html).toContain('<i class="pb-ico pb-ico--user" aria-hidden="true"></i>');
    expect(html).toContain(`<span class="pb-menu__agent" title="${AGENT_EMAIL}">${AGENT_EMAIL}</span>`);
    expect(html.indexOf("pb-ico--chev1")).toBeGreaterThan(html.indexOf("pb-menu__agent"));
  });

  test("the panel has labelled sections: Sesión with the e-mail in the data type, Idioma with ES, PT and EN, then a rule and Salir as a secondary button", () => {
    const panel = html.slice(html.indexOf('<div class="pb-cut pb-menu__panel"'));
    expect(panel).toMatch(/<span class="pb-t-label" id="[^"]+">Sesión<\/span><p class="pb-menu__email pb-t-mono">/);
    expect(panel).toContain(`>${AGENT_EMAIL}</p>`);
    expect(panel).toMatch(/<span class="pb-t-label" id="([^"]+)">Idioma<\/span><div class="pb-lang pb-lang--fill" role="radiogroup" aria-labelledby="\1">/);
    expect([...panel.matchAll(/data-lang="(\w+)"/g)].map((match) => match[1])).toEqual(["es", "pt", "en"]);
    expect(panel.indexOf("<hr")).toBeGreaterThan(panel.indexOf("data-lang"));
    expect(panel).toMatch(/<hr\/><button type="button" class="pb-btn pb-btn--secondary pb-btn--sm">Salir<\/button>/);
    // closed until the button opens it
    expect(panel).toMatch(/id="bo-agent-menu" hidden=""/);
  });

  test("in each language", () => {
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "pt")).toContain(">Sessão</span>");
    expect(render(<AgentMenu agent={AGENT_EMAIL} />, "en")).toContain(">Session</span>");
    for (const lang of ["es", "pt", "en"] as const) expect(dictionaries[lang].nav.session.length).toBeGreaterThan(0);
  });
});

describe("the bar", () => {
  test("before a session the tools are the theme (named, with no visible label) and the language (with its label), and the wordmark and section tag stay", () => {
    const html = render(
      <Shell route={{ name: "queue" }} authenticated={false}>
        {null}
      </Shell>,
    );
    expect([...html.matchAll(/<span class="pb-navtool__label" id="[^"]+">([^<]*)<\/span>/g)].map((match) => match[1])).toEqual(["Idioma"]);
    expect(html).toContain('role="radiogroup" aria-label="Tema"');
    expect(html).toContain('<span class="pb-t-label bo-section-tag">Back office</span>');
    // the brand: two parts, the text unchanged, the accessible name unchanged
    expect(html).toContain('<span class="pb-wordmark__ink">Pattern</span> <span class="pb-wordmark__blue">Blue</span>');
    expect(html).toContain('aria-label="Pattern Blue, Back office"');
    expect(html).not.toContain("PATTERN BLUE");
    expect(html).not.toContain("pb-theme");
  });
});
