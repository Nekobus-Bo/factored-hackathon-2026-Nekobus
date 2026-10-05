// The demo guide (ScriptChoice), on the markup with react-dom/server: no DOM library. The machine's side of it
// (what choosing a script does to the conversation) is in chat.machine.test.ts; here: the panel, the dock around
// it, and what a click does to the two machines (guide-actions).

import { afterEach, describe, expect, test } from "bun:test";
import { DEMO_SCRIPTS, getScript, startScript, type DemoScriptId, type ScriptState } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { ChatDock } from "../src/app/chat/ChatDock";
import { sendGuideLine, startGuideScript } from "../src/app/chat/guide-actions";
import { GuidePanel, type GuidePanelProps } from "../src/app/chat/GuidePanel";
import { SidePanel, type SidePanelProps } from "../src/app/chat/SidePanel";
import { dictionaries } from "../src/i18n";
import { createAppMachine, type AppEnv } from "../src/machines/app.machine";
import { INBOX_CODE } from "./fixtures";
import { createWorld } from "./world";

const OPTION = /class="pb-cut pb-say__opt"/g;
const count = (html: string, pattern: RegExp) => html.match(pattern)?.length ?? 0;

const panel = (props: Partial<GuidePanelProps> = {}) =>
  renderToStaticMarkup(
    <GuidePanel dict={dictionaries.es} script={null} disabled={false} onPick={() => {}} onSend={() => {}} onReset={() => {}} {...props} />,
  );

/** A script after `step` steps, still running. */
const at = (scriptId: DemoScriptId, step: number, status: ScriptState["status"] = "running"): ScriptState => ({ scriptId, step, status });

const lineOf = (id: DemoScriptId, index: number): string => {
  const step = getScript(id).steps[index];
  if (step?.kind !== "message") throw new Error("not a message");
  return step.text;
};

describe("case 3: with no script, the panel offers the six", () => {
  const html = panel();

  test("six options, each with its label, its first line as written and its market", () => {
    expect(count(html, OPTION)).toBe(6);
    expect(html).toContain('<span class="pb-say__label">Tarjeta robada, portugués informal</span>');
    for (const script of DEMO_SCRIPTS) {
      expect(html).toContain(`data-script="${script.id}"`);
      expect(html).toContain(`lang="${script.locale}" title="${lineOf(script.id, 0)}">${lineOf(script.id, 0)}</span>`);
    }
    expect(count(html, /class="pb-tag"><span class="pb-sr">Mercado <\/span>pt-BR/g)).toBe(2);
    expect(count(html, /class="pb-tag"><span class="pb-sr">Mercado <\/span>es-CO/g)).toBe(3);
    expect(count(html, /class="pb-tag"><span class="pb-sr">Mercado <\/span>es-MX/g)).toBe(1);
  });

  test("the guardrail note is on scripts 2 and 3 only, with the amount in mono", () => {
    expect(count(html, /pb-say__note/g)).toBe(2);
    expect(html).toContain('Guardrail: umbral <span class="pb-t-mono">COP 2.000.000</span>, handoff recomendado');
    expect(html).toContain('Guardrail: umbral <span class="pb-t-mono">COP 200.000</span>, handoff requerido');
  });

  test("it is the content of the script tab: the title, the hint and the six; the panel around it (tabs, 'Solo demo') is SidePanel's", () => {
    expect(html).toMatch(/^<div class="pb-guide__body">/);
    expect(html).toContain("Elige un guion");
    expect(html).not.toContain("<aside");
    expect(html).not.toContain("Solo demo");
    expect(html).not.toContain("pb-guide__steps");
    expect(html).not.toContain("pb-guide__foot");
  });

  test("no placeholder is left unfilled", () => {
    expect(html).not.toContain("{");
    expect(html).not.toContain("undefined");
  });

  test("the six are off while a message is in flight, a rate limit runs or the conversation is gone", () => {
    expect(count(panel({ disabled: true }), /<button class="pb-cut pb-say__opt"[^>]* disabled=""/g)).toBe(6);
    expect(count(panel({ awaitingRetry: true }), /disabled=""/g)).toBe(0);
  });

});

describe("a script in the page's language: the lines are never translated", () => {
  test("case 4: in Portuguese the panel speaks Portuguese and the lines stay as the script wrote them", () => {
    const html = panel({ dict: dictionaries.pt });
    expect(html).toContain("Escolha um roteiro");
    expect(html).toContain("Cobrança não reconhecida, abaixo do limite");
    expect(html).toContain("Guardrail: limite <span");
    expect(html).not.toContain("Elige un guion");
    // the Spanish lines under a Portuguese interface are the same Spanish lines
    expect(html).toContain(">Me salió un cobro en la tarjeta de crédito que no hice.</span>");
    expect(html).toContain(">oye tengo un pedo con lo de la tarjeta y no sé qué onda</span>");
  });

  test("no line of any script is in any dictionary", () => {
    const dictionaryText = JSON.stringify(dictionaries);
    for (const script of DEMO_SCRIPTS) {
      for (const step of script.steps) {
        if (step.kind === "message") expect(dictionaryText, script.id).not.toContain(JSON.stringify(step.text).slice(1, -1));
      }
    }
    expect(dictionaryText).not.toContain("Global Electronics Megastore");
  });

  test("every script has a label in every language; the note and its amount exist for 2 and 3 only", () => {
    for (const lang of ["es", "pt", "en"] as const) {
      const scripts: Record<string, { label: string; note?: string; amount?: string }> = dictionaries[lang].chat.guide.scripts;
      expect(Object.keys(scripts).sort(), lang).toEqual(DEMO_SCRIPTS.map((script) => script.id).sort());
      for (const script of DEMO_SCRIPTS) {
        const entry = scripts[script.id]!;
        expect(entry.label.trim(), `${lang}:${script.id}`).not.toBe("");
        const hasNote = script.id === "chargeBelowThreshold" || script.id === "chargeAboveThreshold";
        expect(entry.note !== undefined, `${lang}:${script.id}`).toBe(hasNote);
        expect(entry.amount !== undefined, `${lang}:${script.id}`).toBe(hasNote);
        if (hasNote) expect(entry.note, `${lang}:${script.id}`).toContain("{amount}");
      }
    }
  });
});

describe("a script in progress", () => {
  test("case 7: one option, the next line; the earlier one as sent; the code step as what comes after", () => {
    const html = panel({ script: at("stolenCard", 1) });
    expect(count(html, OPTION)).toBe(1);
    expect(html).toContain('data-state="done"');
    expect(count(html, /data-state="done"/g)).toBe(1);
    expect(html).toContain(`<span class="pb-guide__label"><i class="pb-ico pb-ico--check" aria-hidden="true"></i>Enviado</span><p class="pb-guide__sent" lang="pt-BR">${lineOf("stolenCard", 0)}</p>`);
    expect(html).toContain(`data-say="${lineOf("stolenCard", 1)}"`);
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--hex" aria-hidden="true"></i>Ahora</span>');
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--mail" aria-hidden="true"></i>Sigue</span>');
    // the title says which script and its market; the hint says the rule
    expect(html).toContain("Tarjeta robada, portugués informal");
    expect(html).toContain("Cada mensaje se envía tal como está");
    // not the six any more
    expect(html).not.toContain("Elige un guion");
    expect(html).not.toContain("data-script=");
  });

  test("a track: the steps are a numbered list, the heading says the step, and the states are three different things", () => {
    const html = panel({ script: at("chargeBelowThreshold", 1) });
    // heading with the advance, next to the script's name and market
    expect(html).toContain('<span class="pb-guide__progress">Paso 2 de 4</span>');
    expect(html.indexOf("Cargo no reconocido, bajo el umbral")).toBeLessThan(html.indexOf("Paso 2 de 4"));
    // four steps in an ordered list (the numerals and the rail are the stylesheet's counter): done, now, next (the code), next
    expect(count(html, /<li class="pb-guide__step"/g)).toBe(4);
    expect(html).toContain('<ol class="pb-guide__steps">');
    expect([...html.matchAll(/<li class="pb-guide__step" data-state="(\w+)"/g)].map((match) => match[1])).toEqual(["done", "current", "next", "next"]);
    // done: a check, "Enviado", the text in a dimmed paragraph and no button
    const done = html.slice(html.indexOf('data-state="done"'), html.indexOf('data-state="current"'));
    expect(done).toContain("pb-ico--check");
    expect(done).toContain("Enviado");
    expect(done).toContain('class="pb-guide__sent"');
    expect(done).not.toContain("<button");
    // now: the label and the one option
    const now = html.slice(html.indexOf('data-state="current"'), html.indexOf('data-state="next"'));
    expect(now).toContain("Ahora");
    expect(now).toContain("<button");
    // next: the label "Sigue", the code step with its pointer in a card, the line in a card, no button
    const next = html.slice(html.indexOf('data-state="next"'), html.indexOf("pb-guide__foot"));
    expect(count(next, /Sigue/g)).toBe(2);
    expect(count(next, /class="pb-guide__card"/g)).toBe(2);
    expect(next).not.toContain("<button");
    expect(next).toContain("<b>Abrir bandeja</b>");
  });

  test("the progress: step n of the total while running, all of them when complete, where it stopped when stopped; in each language", () => {
    expect(panel({ script: startScript("stolenCard") })).toContain("Paso 1 de 3");
    expect(panel({ script: at("stolenCard", 2) })).toContain("Paso 3 de 3");
    expect(panel({ script: at("stolenCard", 3, "complete") })).toContain("Paso 3 de 3");
    expect(panel({ script: at("fakeAdmin", 1, "complete") })).toContain("Paso 1 de 1");
    expect(panel({ script: at("chargeBelowThreshold", 1, "stopped") })).toContain("Paso 2 de 4");
    expect(panel({ dict: dictionaries.pt, script: at("stolenCard", 1) })).toContain("Passo 2 de 3");
    expect(panel({ dict: dictionaries.en, script: at("stolenCard", 1) })).toContain("Step 2 of 3");
    expect(panel({ script: null })).not.toContain("pb-guide__progress");
  });

  test("only the current step is a button, whatever the state of the script", () => {
    for (const script of [startScript("chargeAboveThreshold"), at("chargeAboveThreshold", 1), at("chargeAboveThreshold", 2), at("chargeAboveThreshold", 3), at("chargeAboveThreshold", 4, "complete"), at("chargeAboveThreshold", 2, "stopped")]) {
      const html = panel({ script });
      const buttons = count(html.slice(0, html.indexOf("pb-guide__foot")), /<button/g);
      expect(buttons, JSON.stringify(script)).toBe(script.status === "running" && script.step !== 2 ? 1 : 0);
    }
  });

  test("complete shows every step done and no option; stopped shows what was sent and ends there", () => {
    const complete = panel({ script: at("chargeAboveThreshold", 4, "complete") });
    expect([...complete.matchAll(/data-state="(\w+)"/g)].map((match) => match[1])).toEqual(["done", "done", "done", "done"]);
    const stopped = panel({ script: at("chargeAboveThreshold", 2, "stopped") });
    expect([...stopped.matchAll(/data-state="(\w+)"/g)].map((match) => match[1])).toEqual(["done", "done"]);
  });

  test("the first line of the chosen script is the one offered, before anything was sent", () => {
    const html = panel({ script: startScript("chargeAboveThreshold") });
    expect(count(html, OPTION)).toBe(1);
    expect(html).toContain(`data-say="${lineOf("chargeAboveThreshold", 0)}"`);
    expect(count(html, /data-state="done"/g)).toBe(0);
    // what comes after is told, and none of it is an option
    expect(html).toContain(lineOf("chargeAboveThreshold", 1));
    expect(html).toContain(lineOf("chargeAboveThreshold", 3));
  });

  test("case 8: the option sends the line as written; it is a button of the guide, not of the log", () => {
    const html = panel({ script: at("stolenCard", 1) });
    expect(html).toMatch(/<button class="pb-cut pb-say__opt" type="button" data-say="Meu CPF é 123.456.789-00 e meu nome é Mariana Silva\.">/);
  });

  test("case 10: at the code step there is no option, a pointer to the inbox and the code, and never the code", () => {
    const html = panel({ script: at("stolenCard", 2) });
    expect(count(html, OPTION)).toBe(0);
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--mail" aria-hidden="true"></i>Ahora</span>');
    expect(html).toContain("El código es real. Usa <b>Abrir bandeja</b> y <b>Mostrar código</b>, y escríbelo en el chat.");
    expect(html).toContain('data-state="current"');
    expect(html).not.toContain(INBOX_CODE);
    // the names of the two actions are the chat's own, in each language
    const pt = panel({ dict: dictionaries.pt, script: at("stolenCard", 2) });
    expect(pt).toContain("<b>Abrir caixa de entrada</b>");
    expect(pt).toContain("<b>Mostrar código</b>");
  });

  test("case 10: at the code step of script 2 the line that follows is told, not offered", () => {
    const html = panel({ script: at("chargeBelowThreshold", 2) });
    expect(count(html, OPTION)).toBe(0);
    expect(html).toContain(lineOf("chargeBelowThreshold", 3));
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--chat" aria-hidden="true"></i>Sigue</span>');
    // what follows is a card with its message in the normal ink, and it is not a button
    expect(html).toContain(`<p class="pb-guide__card" lang="es-CO">${lineOf("chargeBelowThreshold", 3)}</p>`);
  });

  test("case 11: once the code is verified the script offers the line that follows (2 and 3), or is complete (1)", () => {
    const after = panel({ script: at("chargeBelowThreshold", 3) });
    expect(count(after, OPTION)).toBe(1);
    expect(after).toContain(`data-say="${lineOf("chargeBelowThreshold", 3)}"`);
    expect(after).toContain('<i class="pb-ico pb-ico--check" aria-hidden="true"></i>Código verificado</span>');
    const complete = panel({ script: at("stolenCard", 3, "complete") });
    expect(count(complete, OPTION)).toBe(0);
    expect(count(complete, /data-state="done"/g)).toBe(3);
    expect(complete).toContain("Ya se enviaron todos los mensajes del guion.");
  });

  test("case 13: a one-line script is complete with its line and no option", () => {
    for (const id of ["fakeAdmin", "ambiguousSlang", "mixedLanguages"] as const) {
      const html = panel({ script: at(id, 1, "complete") });
      expect(count(html, OPTION), id).toBe(0);
      expect(html, id).toContain(lineOf(id, 0));
      expect(html, id).toContain("Ya se enviaron todos los mensajes del guion.");
    }
  });

  test("case 9: a stopped script offers nothing, keeps what was sent, and says why", () => {
    const html = panel({ script: at("stolenCard", 1, "stopped") });
    expect(count(html, OPTION)).toBe(0);
    expect(count(html, /data-state="done"/g)).toBe(1);
    expect(html).not.toContain('data-state="next"');
    expect(html).not.toContain('data-state="current"');
    expect(html).toContain("el guion se detuvo");
    expect(html).toContain("pb-guide__foot");
  });

  test("case 17: 'Cambiar de guion' is in the foot of every state with a script, and in none without one", () => {
    for (const status of ["running", "complete", "stopped"] as const) {
      const html = panel({ script: at("stolenCard", 1, status) });
      expect(html, status).toContain('<div class="pb-guide__foot"><button class="pb-action" type="button">Cambiar de guion<i class="pb-ico pb-ico--arrow"');
    }
    expect(panel()).not.toContain("Cambiar de guion");
  });

  test("case 14: the next line is off while a message is in flight, and while one waits for its retry", () => {
    const script = at("stolenCard", 1);
    expect(panel({ script })).not.toMatch(/disabled=""/);
    expect(panel({ script, disabled: true })).toMatch(/<button class="pb-cut pb-say__opt"[^>]* disabled=""/);
    expect(panel({ script, awaitingRetry: true })).toMatch(/<button class="pb-cut pb-say__opt"[^>]* disabled=""/);
    // "Cambiar de guion" stays: the way out is never disabled
    expect(panel({ script, disabled: true })).toMatch(/<button class="pb-action" type="button">Cambiar de guion/);
  });
});

describe("the panel around the guide (SidePanel)", () => {
  const side = (props: Partial<SidePanelProps> = {}) =>
    renderToStaticMarkup(
      <SidePanel dict={dictionaries.es} hidden={false} tab="script" detectiveOffered={false} onTab={() => {}} {...props}>
        <GuidePanel dict={dictionaries.es} script={null} disabled={false} onPick={() => {}} onSend={() => {}} onReset={() => {}} />
      </SidePanel>,
    );

  test("with no detective tab the panel is the guide alone: its title, the 'Solo demo' tag, no tabs", () => {
    const html = side();
    expect(html).toMatch(/^<aside class="pb-cut pb-side pb-dock__side" id="side-panel" aria-labelledby="side-title"/);
    expect(html).toContain('<span class="pb-tag">Solo demo</span>');
    expect(html).toContain('id="side-title"><i class="pb-ico pb-ico--menu" aria-hidden="true"></i> Guion de demo');
    expect(html).not.toContain("tablist");
    expect(html).not.toContain('role="tabpanel"');
    expect(count(html, OPTION)).toBe(6);
  });

  test("with the detective tab there are two tabs, the 'Solo demo' tag belongs to the guide's, and the panel has a name of its own", () => {
    const withTabs = side({ detectiveOffered: true });
    expect(withTabs).toContain('aria-label="Panel de demo"');
    expect(withTabs).toContain('role="tablist"');
    expect(count(withTabs, /role="tab"/g)).toBe(2);
    expect(withTabs).toContain("Solo demo");
    // on the detective tab the tag is gone
    expect(side({ detectiveOffered: true, tab: "detective" })).not.toContain("Solo demo");
  });

  test("the panel's words are in each language", () => {
    const pt = renderToStaticMarkup(
      <SidePanel dict={dictionaries.pt} hidden={false} tab="script" detectiveOffered onTab={() => {}}>
        {null}
      </SidePanel>,
    );
    expect(pt).toContain("Painel de demo");
    expect(pt).toContain(">Roteiro</button>");
    expect(pt).toContain(">Detetive</button>");
    expect(pt).toContain("Só demo");
  });

  test("hidden is the attribute on the aside", () => {
    expect(side({ hidden: true })).toMatch(/^<aside[^>]* hidden=""/);
    expect(side()).not.toMatch(/^<aside[^>]* hidden=""/);
  });
});

describe("the dock around the panel", () => {
  let world: ReturnType<typeof createWorld> | undefined;
  afterEach(() => world?.stop());

  const appFor = (navigatorLanguage: string) => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage };
    return createActor(createAppMachine(env)).start();
  };

  const dock = (props: { open?: boolean; startWithGuide?: boolean; startInDetective?: boolean; wide?: boolean } = {}) => {
    world ??= createWorld();
    return renderToStaticMarkup(
      <ActorsProvider actors={{ app: appFor("es-CO"), chat: world.actor }}>
        <ChatDock
          open={props.open ?? true}
          onOpenChange={() => {}}
          startWithGuide={props.startWithGuide}
          startInDetective={props.startInDetective}
          wide={props.wide}
        />
      </ActorsProvider>,
    );
  };
  const sideTag = (html: string) => /<aside[^>]*>/.exec(html)?.[0] ?? "";

  test("case 2: the chat is open and the panel is closed: the button says so, the panel is hidden, and nothing was requested", () => {
    const html = dock();
    expect(sideTag(html)).toMatch(/ hidden=""/);
    expect(html).toContain("pb-btn pb-btn--secondary pb-btn--sm pb-demo-toggle");
    expect(html).toContain('aria-label="Menú demo" title="Menú demo" aria-pressed="false" aria-controls="side-panel" data-demo-toggle');
    expect(html).not.toContain("data-script=");
    expect(world!.calls).toHaveLength(0);
  });

  test("the demo menu button shows the panel, on the guide the first time: pressed, filled, the panel in sight and offering the six", () => {
    const html = dock({ startWithGuide: true });
    expect(html).toContain("pb-btn pb-btn--primary pb-btn--sm pb-demo-toggle");
    expect(html).toContain('aria-pressed="true" aria-controls="side-panel"');
    expect(sideTag(html)).not.toMatch(/ hidden=""/);
    expect(count(html, /data-script="/g)).toBe(6);
    expect(world!.calls).toHaveLength(0);
  });

  test("a closed chat takes the panel with it", () => {
    const html = dock({ open: false, startWithGuide: true });
    expect(sideTag(html)).toMatch(/ hidden=""/);
    expect(html).not.toContain("data-script=");
  });

  test("with no room beside the chat the guide is not drawn (the dock draws no guide, whatever the state, and the stylesheet hides the panel)", () => {
    const html = dock({ startWithGuide: true, wide: false });
    expect(html).not.toContain("data-script=");
    // the button is there only for the detective view, which this dock does not offer: with no mode, no button
    expect(html).not.toContain("data-demo-toggle");
  });

  test("the demo menu button is in the header before the close one, and the panel sits beside the chat, not in it", () => {
    const html = dock({ startWithGuide: true });
    expect(html.indexOf("pb-demo-toggle")).toBeGreaterThan(html.indexOf("pb-chat__title"));
    expect(html.indexOf("data-close-chat")).toBeGreaterThan(html.indexOf("pb-demo-toggle"));
    const section = html.slice(html.indexOf("<section"), html.indexOf("</section>"));
    expect(section).not.toContain("pb-side ");
    expect(section).not.toContain("pb-say__opt");
    expect(html.indexOf("<aside")).toBeGreaterThan(html.indexOf("</section>"));
  });

  test("case 18: with the panel beside the chat the chat is never hidden, so a click in the guide needs no way back", () => {
    for (const html of [dock({ startWithGuide: true }), dock({ startInDetective: true })]) {
      expect(html).toMatch(/<div class="pb-chat__body">/);
      expect(html).toMatch(/<form class="pb-chat__composer">/);
    }
  });

  test("a script in progress shows in the guide whichever tab was open before: the script lives in the chat machine, not in the panel", async () => {
    world = createWorld();
    startGuideScript({ app: appFor("es-CO"), chat: world.actor }, "stolenCard");
    await world.settle();
    const html = dock({ startWithGuide: true });
    expect(html).toContain("Ahora</span>");
    expect(count(html, /class="pb-cut pb-say__opt"/g)).toBe(1);
    // the same dock rendered on the detective tab does not lose it: the machine's context is the same
    expect(world.actor.getSnapshot().context.script).toEqual({ scriptId: "stolenCard", step: 1, status: "running" });
    dock({ startInDetective: true });
    expect(world.actor.getSnapshot().context.script).toEqual({ scriptId: "stolenCard", step: 1, status: "running" });
  });
});

describe("what a click in the guide does to the two machines (cases 4 and 5)", () => {
  let world: ReturnType<typeof createWorld> | undefined;
  afterEach(() => world?.stop());

  const actors = (navigatorLanguage: string) => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage };
    world = createWorld();
    return { app: createActor(createAppMachine(env)).start(), chat: world.actor };
  };

  test("case 4: a Portuguese script from a Spanish page: the page moves to pt-BR, and the conversation is created in it with the line as written", async () => {
    const both = actors("es-CO");
    expect(both.app.getSnapshot().context).toMatchObject({ lang: "es", locale: "es-CO" });
    startGuideScript(both, "stolenCard");
    expect(both.app.getSnapshot().context).toMatchObject({ lang: "pt", locale: "pt-BR" });
    await world!.settle();
    expect(world!.callsTo("createConversation").map((call) => call.body)).toEqual([{ lang: "pt", locale: "pt-BR" }]);
    expect(world!.callsTo("sendMessage")[0]!.body).toMatchObject({ text: lineOf("stolenCard", 0), lang: "pt" });
    // and from here the panel offers one line, in Portuguese
    const script = both.chat.getSnapshot().context.script!;
    const html = renderToStaticMarkup(
      <GuidePanel dict={dictionaries[both.app.getSnapshot().context.lang]} script={script} disabled={false} onPick={() => {}} onSend={() => {}} onReset={() => {}} />,
    );
    expect(html).toContain("Agora</span>");
    expect(count(html, OPTION)).toBe(1);
    expect(html).toContain(`data-say="${lineOf("stolenCard", 1)}"`);
  });

  test("case 5: a Mexican script from a Colombian page: es-MX, still Spanish", async () => {
    const both = actors("es-CO");
    startGuideScript(both, "ambiguousSlang");
    expect(both.app.getSnapshot().context).toMatchObject({ lang: "es", locale: "es-MX" });
    await world!.settle();
    expect(world!.callsTo("createConversation").map((call) => call.body)).toEqual([{ lang: "es", locale: "es-MX" }]);
  });

  test("the next line goes in the script's language, whatever the page was switched to meanwhile", async () => {
    const both = actors("es-CO");
    startGuideScript(both, "stolenCard");
    await world!.settle();
    both.app.send({ type: "LANG.SET", lang: "es" });
    sendGuideLine(both, both.chat.getSnapshot().context.script!, lineOf("stolenCard", 1));
    await world!.settle();
    expect(world!.callsTo("sendMessage")[1]!.body).toMatchObject({ text: lineOf("stolenCard", 1), lang: "pt" });
    expect(both.chat.getSnapshot().context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
  });
});
