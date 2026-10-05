// The demo guide (ScriptChoice), on the markup with react-dom/server: no DOM library. The machine's side of it
// (what choosing a script does to the conversation) is in chat.machine.test.ts; here: the panel, the dock around
// it, and what a click does to the two machines (guide-actions).

import { afterEach, describe, expect, test } from "bun:test";
import { DEMO_SCRIPTS, getScript, startScript, type DemoScriptId, type ScriptState } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { ChatDock } from "../src/app/chat/ChatDock";
import { sendGuideLine, sendTyped, startGuideScript } from "../src/app/chat/guide-actions";
import { GuidePanel, type GuidePanelProps } from "../src/app/chat/GuidePanel";
import { SidePanel, type SidePanelProps } from "../src/app/chat/SidePanel";
import { dictionaries } from "../src/i18n";
import { createAppMachine, type AppEnv } from "../src/machines/app.machine";
import { NextBand } from "../src/app/chat/NextLine";
import { CONVERSATION_ID, INBOX_CODE, inboxResponse, OTP_SEND_RECEIPT, TEXT_BLOCK } from "./fixtures";
import { createWorld, json } from "./world";

const OPTION = /class="pb-cut pb-say__opt"/g;
/** The next line's card (text, not a button) and its two icon buttons, send then copy. */
const CARD = /class="pb-cut pb-say__card"/g;
const SEND = /<button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__send"[^>]*>/g;
const count = (html: string, pattern: RegExp) => html.match(pattern)?.length ?? 0;

const panel = (props: Partial<GuidePanelProps> = {}) =>
  renderToStaticMarkup(
    <GuidePanel dict={dictionaries.es} script={null} disabled={false} onPick={() => {}} onSend={() => {}} onCopy={() => {}} onReset={() => {}} {...props} />,
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
  test("case 7: one card, the next line, with its send button; the earlier one as sent; the code step as what comes after", () => {
    const html = panel({ script: at("stolenCard", 1) });
    expect(count(html, CARD)).toBe(1);
    expect(count(html, SEND)).toBe(1);
    expect(count(html, OPTION)).toBe(0);
    expect(html).toContain('data-state="done"');
    expect(count(html, /data-state="done"/g)).toBe(1);
    expect(html).toContain(`<span class="pb-guide__label"><i class="pb-ico pb-ico--check" aria-hidden="true"></i>Enviado</span><p class="pb-guide__sent" lang="pt-BR">${lineOf("stolenCard", 0)}</p>`);
    expect(html).toContain(`data-say="${lineOf("stolenCard", 1)}"`);
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--hex" aria-hidden="true"></i>Ahora</span>');
    expect(html).toContain('<span class="pb-guide__label"><i class="pb-ico pb-ico--mail" aria-hidden="true"></i>Sigue</span>');
    // the title says which script and its market; the hint says the rule
    expect(html).toContain("Tarjeta robada, portugués informal");
    expect(html).toContain("Envía el mensaje tal como está, o cópialo al chat para editarlo");
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

  test("only the current step has the card and its two buttons (send, copy), whatever the state of the script", () => {
    for (const script of [startScript("chargeAboveThreshold"), at("chargeAboveThreshold", 1), at("chargeAboveThreshold", 2), at("chargeAboveThreshold", 3), at("chargeAboveThreshold", 4, "complete"), at("chargeAboveThreshold", 2, "stopped")]) {
      const html = panel({ script });
      const buttons = count(html.slice(0, html.indexOf("pb-guide__foot")), /<button/g);
      // the send and the copy buttons, only on a running message step; the card is text and the six options are not there
      const on = script.status === "running" && script.step !== 2;
      expect(buttons, JSON.stringify(script)).toBe(on ? 2 : 0);
      expect(count(html, CARD), JSON.stringify(script)).toBe(on ? 1 : 0);
      expect(count(html, OPTION), JSON.stringify(script)).toBe(0);
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
    expect(count(html, CARD)).toBe(1);
    expect(count(html, OPTION)).toBe(0);
    expect(html).toContain(`data-say="${lineOf("chargeAboveThreshold", 0)}"`);
    expect(count(html, /data-state="done"/g)).toBe(0);
    // what comes after is told, and none of it is an option
    expect(html).toContain(lineOf("chargeAboveThreshold", 1));
    expect(html).toContain(lineOf("chargeAboveThreshold", 3));
  });

  test("case 8: the card carries the line, in its language and not a button; the send button sends it as written; both are the guide's, not the log's", () => {
    const html = panel({ script: at("stolenCard", 1) });
    expect(html).toContain('<p class="pb-cut pb-say__card"><span class="pb-say__text" lang="pt-BR">Meu CPF é 123.456.789-00 e meu nome é Mariana Silva.</span></p>');
    expect(html).toMatch(/<button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__send" type="button" data-say="Meu CPF é 123.456.789-00 e meu nome é Mariana Silva\."[^>]*>/);
    // send first, then copy, with their glyphs and no visible text
    expect(html).toContain('title="Enviar este mensaje"><i class="pb-ico pb-ico--send" aria-hidden="true"></i></button><button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy"');
    expect(html).not.toContain(">Enviar este mensaje<");
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
    expect(count(after, CARD)).toBe(1);
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
    expect(html).toContain("Saliste del guion: esta guía ya no sugiere los pasos siguientes.");
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
    expect(panel({ script, disabled: true })).toMatch(/<button class="pb-btn[^"]*pb-guide__send"[^>]* disabled=""/);
    expect(panel({ script, awaitingRetry: true })).toMatch(/<button class="pb-btn[^"]*pb-guide__send"[^>]* disabled=""/);
    // "Cambiar de guion" stays: the way out is never disabled
    expect(panel({ script, disabled: true })).toMatch(/<button class="pb-action" type="button">Cambiar de guion/);
  });
});

describe("copying the next line into the composer ('Copiar al chat')", () => {
  const COPY = /<button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy"[^>]*>/g;
  const copyTag = (html: string) => html.match(COPY)?.[0] ?? "";

  test("a secondary icon button beside the current card, after the send button, with the line it copies", () => {
    const html = panel({ script: at("stolenCard", 1) });
    expect(count(html, COPY)).toBe(1);
    expect(copyTag(html)).toContain(`data-copy="${lineOf("stolenCard", 1)}"`);
    expect(html).toContain("</button><button class=\"pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy\"");
    // the card is text: the line is in it, and it is not a button
    expect(html).toContain(`<p class="pb-cut pb-say__card"><span class="pb-say__text" lang="pt-BR">${lineOf("stolenCard", 1)}</span></p>`);
    // icon only: the glyph, no visible text, the name in aria-label and title
    expect(html).toContain(`<button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy" type="button" data-copy="${lineOf("stolenCard", 1)}" aria-label="Copiar al chat" title="Copiar al chat"><i class="pb-ico pb-ico--copy" aria-hidden="true"></i></button>`);
    expect(html).not.toContain(">Copiar al chat<");
    // it is not an option (the options are counted by that class) and has no animation class
    expect(copyTag(html)).not.toContain("pb-say__opt");
    expect(count(html, OPTION)).toBe(0);
    // in the current step's block, not in a done or next one
    const now = html.slice(html.indexOf('data-state="current"'), html.indexOf('data-state="next"'));
    expect(now).toContain("pb-guide__copy");
  });

  test("only on the next line of a running script: not on the six, not at the code step, not complete, not stopped", () => {
    expect(count(panel(), COPY)).toBe(0);
    expect(count(panel({ script: startScript("stolenCard") }), COPY)).toBe(1);
    expect(count(panel({ script: at("chargeBelowThreshold", 3) }), COPY)).toBe(1);
    expect(count(panel({ script: at("stolenCard", 2) }), COPY)).toBe(0); // the code step
    expect(count(panel({ script: at("stolenCard", 3, "complete") }), COPY)).toBe(0);
    expect(count(panel({ script: at("fakeAdmin", 1, "complete") }), COPY)).toBe(0);
    expect(count(panel({ script: at("stolenCard", 1, "stopped") }), COPY)).toBe(0);
    expect(count(panel({ script: at("chargeBelowThreshold", 2) }), COPY)).toBe(0);
  });

  test("off like the card: a message in flight, a rate limit, a gone conversation (disabled) and one waiting for its retry", () => {
    const script = at("stolenCard", 1);
    expect(copyTag(panel({ script }))).not.toContain("disabled");
    // in flight, rate limited and gone are the same flag for the guide: `disabled`
    expect(copyTag(panel({ script, disabled: true }))).toContain('disabled=""');
    expect(copyTag(panel({ script, awaitingRetry: true }))).toContain('disabled=""');
    expect(copyTag(panel({ script, disabled: true, chooseDisabled: false }))).toContain('disabled=""');
  });

  test("off while the code field is the composer in sight, and 'Cambiar de guion' stays on", () => {
    const script = at("stolenCard", 1);
    const html = panel({ script, codeFieldShown: true });
    expect(copyTag(html)).toContain('disabled=""');
    // the send button is not off for that: a line can still be sent
    expect(html).not.toMatch(/<button class="pb-btn[^"]*pb-guide__send"[^>]* disabled=""/);
    expect(html).toMatch(/<button class="pb-action" type="button">Cambiar de guion/);
    expect(panel({ script, codeFieldShown: true, disabled: true })).toMatch(/<button class="pb-action" type="button">Cambiar de guion/);
  });

  test("the label and the hints are in each language; the line itself is never translated", () => {
    const script = at("stolenCard", 1);
    for (const [lang, label, sendLabel, running, stopped] of [
      ["es", "Copiar al chat", "Enviar este mensaje", "cópialo al chat para editarlo", "Saliste del guion"],
      ["pt", "Copiar para o chat", "Enviar esta mensagem", "copie-a para o chat para editá-la", "Você saiu do roteiro"],
      ["en", "Copy to chat", "Send this message", "copy it to the chat to edit it", "You left the script"],
    ] as const) {
      const dict = dictionaries[lang];
      const html = panel({ dict, script });
      // the send button has a name of its own, not the composer's ("Enviar mensaje"), so a screen reader can tell them apart
      expect(html, lang).toContain(`aria-label="${sendLabel}" title="${sendLabel}"><i class="pb-ico pb-ico--send" aria-hidden="true"></i></button>`);
      expect(html, lang).not.toContain(`>${sendLabel}<`);
      expect(sendLabel, lang).not.toBe(dict.chat.send);
      expect(html, lang).toContain(`aria-label="${label}" title="${label}"><i class="pb-ico pb-ico--copy" aria-hidden="true"></i></button>`);
      expect(html, lang).not.toContain(`>${label}<`);
      expect(html, lang).toContain(running);
      expect(html, lang).toContain(`data-copy="${lineOf("stolenCard", 1)}"`);
      expect(panel({ dict, script: at("stolenCard", 1, "stopped") }), lang).toContain(stopped);
    }
  });

  test("the stopped hint is true for any cause: it blames neither a message nor the script's lines", () => {
    for (const lang of ["es", "pt", "en"] as const) {
      const hint = dictionaries[lang].chat.guide.stoppedHint;
      expect(hint, lang).not.toMatch(/enviou|enviado|envi[óo]|sent/i);
    }
  });

  test("the dock shows the copy button with the panel beside the chat on a running script, and sends nothing by itself", async () => {
    const world = createWorld();
    try {
      const actors = { app: createActor(createAppMachine({ storage: null, root: null, navigatorLanguage: "es-CO" })).start(), chat: world.actor };
      startGuideScript(actors, "stolenCard");
      await world.settle();
      const sent = world.callsTo("sendMessage").length;
      const html = renderToStaticMarkup(
        <ActorsProvider actors={actors}>
          <ChatDock open onOpenChange={() => {}} startWithGuide wide />
        </ActorsProvider>,
      );
      expect(count(html, COPY)).toBe(1);
      expect(copyTag(html)).not.toContain("disabled");
      expect(world.callsTo("sendMessage")).toHaveLength(sent);
    } finally {
      world.stop();
    }
  });
});

describe("the panel around the guide (SidePanel)", () => {
  const side = (props: Partial<SidePanelProps> = {}) =>
    renderToStaticMarkup(
      <SidePanel dict={dictionaries.es} hidden={false} tab="script" detectiveOffered={false} onTab={() => {}} {...props}>
        <GuidePanel dict={dictionaries.es} script={null} disabled={false} onPick={() => {}} onSend={() => {}} onCopy={() => {}} onReset={() => {}} />
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

  test("with no room beside the chat the guide takes the chat's place: the title, the way back, the guide alone with its tag, the log and the composer kept but hidden", () => {
    const html = dock({ startWithGuide: true, wide: false });
    const section = html.slice(html.indexOf("<section"), html.indexOf("</section>"));
    // the chat's panel is named by the demo menu, and its header has the way back instead of the toggle
    expect(section).toContain('aria-label="Menú demo"');
    expect(section).toContain('<i class="pb-ico pb-ico--menu" aria-hidden="true"></i> Menú demo</span>');
    const back = /<button[^>]*pb-demo-toggle[^>]*>/.exec(html)![0];
    expect(back).toContain('aria-label="Volver al chat"');
    expect(back).not.toContain("aria-pressed");
    expect(back).not.toContain("aria-controls");
    // the same panel, inside the chat's panel (one instance: its ids are fixed), as the guide alone: no tabs
    expect(count(html, /<aside/g)).toBe(1);
    expect(section).toContain('<aside class="pb-side pb-side--inplace" id="side-panel" aria-labelledby="side-title"');
    expect(section).not.toContain("pb-dock__side");
    expect(section).toContain("Guion de demo");
    expect(section).toContain('<span class="pb-tag">Solo demo</span>');
    expect(section).not.toContain("tablist");
    expect(count(section, /data-script="/g)).toBe(6);
    // the log and the composer are still there, hidden: the scroll and the draft survive
    expect(section).toMatch(/<div class="pb-chat__body" hidden="">/);
    expect(section).toMatch(/<form class="pb-chat__composer" hidden="">/);
    expect(section).toContain('role="log"');
    expect(section).toContain("<textarea");
    // the panel comes before the body, as a conditional sibling: the composer is not remounted when it appears
    expect(section.indexOf("<aside")).toBeLessThan(section.indexOf('class="pb-chat__body"'));
  });

  test("with no room and the panel closed there is the button, the chat, and a hidden aside beside it; the button opens nothing yet", () => {
    const html = dock({ wide: false });
    expect(html).toContain("data-demo-toggle");
    expect(html).toContain('aria-pressed="false" data-demo-toggle');
    expect(html).toMatch(/<div class="pb-chat__body">/);
    expect(html).toMatch(/<form class="pb-chat__composer">/);
    expect(sideTag(html)).toMatch(/ hidden=""/);
    expect(html).not.toContain("data-script=");
  });

  test("a closed chat has no panel anywhere: beside the chat the aside is hidden, in place of it the section that holds it is", () => {
    const wide = dock({ open: false, startWithGuide: true, wide: true });
    expect(sideTag(wide)).toMatch(/ hidden=""/);
    const narrow = dock({ open: false, startWithGuide: true, wide: false });
    expect(narrow).toMatch(/<section class="pb-chat pb-dock__panel" id="dock-panel"[^>]*hidden="">/);
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
    expect(count(html, CARD)).toBe(1);
    // the same dock rendered on the detective tab does not lose it: the machine's context is the same
    expect(world.actor.getSnapshot().context.script).toEqual({ scriptId: "stolenCard", step: 1, status: "running" });
    dock({ startInDetective: true });
    expect(world.actor.getSnapshot().context.script).toEqual({ scriptId: "stolenCard", step: 1, status: "running" });
  });
});

describe("the suggested next line over the composer (NextBand)", () => {
  let world: ReturnType<typeof createWorld> | undefined;
  afterEach(() => world?.stop());

  const appFor = (navigatorLanguage = "es-CO") => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage };
    return createActor(createAppMachine(env)).start();
  };
  const dock = (props: { open?: boolean; startWithGuide?: boolean; wide?: boolean; lang?: string } = {}) =>
    renderToStaticMarkup(
      <ActorsProvider actors={{ app: appFor(props.lang), chat: world!.actor }}>
        <ChatDock open={props.open ?? true} onOpenChange={() => {}} startWithGuide={props.startWithGuide} wide={props.wide} />
      </ActorsProvider>,
    );
  const band = (html: string) => html.slice(html.indexOf("<div class=\"pb-say pb-say--next\""), html.indexOf("</form>", html.indexOf("pb-say--next")));
  const BAND = /data-script-band/g;
  const running = async (id: DemoScriptId = "stolenCard") => {
    world = createWorld();
    startGuideScript({ app: appFor(), chat: world.actor }, id);
    await world.settle();
    return world;
  };

  test("a running script on a message step with no panel showing: the band over the composer, with its label, the line as written and the two actions", async () => {
    await running();
    for (const wide of [false, true]) {
      const html = dock({ wide });
      expect(count(html, BAND), `wide=${wide}`).toBe(1);
      const text = band(html);
      expect(text).toContain("Siguiente mensaje del guion");
      expect(text).toContain(`<p class="pb-cut pb-say__card pb-say__card--compact" title="${lineOf("stolenCard", 1)}"><span class="pb-say__text" lang="pt-BR">${lineOf("stolenCard", 1)}</span></p>`);
      // send, then copy, two icon buttons of the same kind
      expect(text).toContain(`data-say="${lineOf("stolenCard", 1)}" aria-label="Enviar este mensaje" title="Enviar este mensaje"><i class="pb-ico pb-ico--send" aria-hidden="true"></i></button><button class="pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy"`);
      expect(text).not.toContain("pb-say__opt");
      expect(text).toContain(`data-copy="${lineOf("stolenCard", 1)}"`);
      expect(text).toContain('aria-label="Copiar al chat" title="Copiar al chat"><i class="pb-ico pb-ico--copy" aria-hidden="true"></i></button>');
      expect(text).not.toContain(">Copiar al chat<");
      // not a message, not announced: between the log and the composer, never inside the log
      expect(html.indexOf("data-script-band")).toBeGreaterThan(html.indexOf('role="log"'));
      expect(html.indexOf("data-script-band")).toBeLessThan(html.indexOf('<form class="pb-chat__composer"'));
    }
  });

  test("the log's own element does not contain it", async () => {
    await running();
    const html = dock({ wide: false });
    const start = html.indexOf('role="log"');
    // the log's div closes before the body's div does, and the band comes after the body
    const body = html.slice(html.lastIndexOf('<div class="pb-chat__body"', start), html.indexOf("data-script-band"));
    expect(body).not.toBe("");
    expect(html.slice(start, html.indexOf("data-script-band"))).toContain("</div></div>");
    expect(/<div[^>]*role="log"[^>]*>(?:(?!<\/div>).)*data-script-band/s.test(html)).toBe(false);
  });

  test("in none of the other cases: no script, complete, stopped, the code step, the panel beside the chat or in place of it, a closed chat", async () => {
    world = createWorld();
    expect(count(dock({ wide: false }), BAND), "no script").toBe(0);
    // complete: a one-line script
    startGuideScript({ app: appFor(), chat: world.actor }, "fakeAdmin");
    await world.settle();
    expect(world.snapshot.context.script?.status).toBe("complete");
    expect(count(dock({ wide: false }), BAND), "complete").toBe(0);
    // stopped: a line that is not the script's
    startGuideScript({ app: appFor(), chat: world.actor }, "stolenCard");
    await world.settle();
    expect(count(dock({ wide: false }), BAND), "running").toBe(1);
    world.send("otra cosa");
    await world.settle();
    expect(world.snapshot.context.script?.status).toBe("stopped");
    expect(count(dock({ wide: false }), BAND), "stopped").toBe(0);
    // the code step: the line before it was sent
    startGuideScript({ app: appFor(), chat: world.actor }, "stolenCard");
    await world.settle();
    sendGuideLine({ chat: world.actor }, world.snapshot.context.script!, lineOf("stolenCard", 1));
    await world.settle();
    expect(world.snapshot.context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
    expect(count(dock({ wide: false }), BAND), "code step").toBe(0);
    // a running script, but the panel is showing, beside the chat or in place of it, or the chat is closed
    startGuideScript({ app: appFor(), chat: world.actor }, "stolenCard");
    await world.settle();
    expect(count(dock({ wide: false }), BAND)).toBe(1);
    expect(count(dock({ wide: true, startWithGuide: true }), BAND), "panel beside the chat").toBe(0);
    expect(count(dock({ wide: false, startWithGuide: true }), BAND), "panel in place of the chat").toBe(0);
    expect(count(dock({ open: false, wide: false }), BAND), "closed chat").toBe(0);
  });

  test("not while the code field is the composer", async () => {
    world = createWorld();
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT] }));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z")));
    startGuideScript({ app: appFor(), chat: world.actor }, "stolenCard");
    await world.settle();
    expect(world.snapshot.context.script?.status).toBe("running");
    const html = dock({ wide: false });
    expect(html).toContain("data-code-field");
    expect(count(html, BAND)).toBe(0);
  });

  test("the same disabled states as the card: in flight, awaiting its retry; the code field case is the dock's (no band)", () => {
    const render = (props: Partial<Parameters<typeof NextBand>[0]> = {}) =>
      renderToStaticMarkup(<NextBand dict={dictionaries.es} script={at("stolenCard", 1)} disabled={false} awaitingRetry={false} onSend={() => {}} onCopy={() => {}} {...props} />);
    const opt = (html: string) => /<button class="pb-btn[^"]*pb-guide__send"[^>]*>/.exec(html)![0];
    const copy = (html: string) => /<button class="pb-btn[^"]*pb-guide__copy"[^>]*>/.exec(html)![0];
    expect(opt(render())).not.toContain("disabled");
    expect(copy(render())).not.toContain("disabled");
    for (const props of [{ disabled: true }, { awaitingRetry: true }]) {
      expect(opt(render(props))).toContain('disabled=""');
      expect(copy(render(props))).toContain('disabled=""');
    }
    // the same markup as the guide's card, so one component serves both
    const guide = panel({ script: at("stolenCard", 1) });
    expect(copy(render())).toBe(copy(guide));
    // nothing for a script that is not running on a message step
    for (const script of [null, at("stolenCard", 2), at("stolenCard", 3, "complete"), at("stolenCard", 1, "stopped")]) {
      expect(render({ script })).toBe("");
    }
  });

  test("the label is in each language and the line is never translated", async () => {
    await running();
    for (const [lang, label] of [["es-CO", "Siguiente mensaje del guion"], ["pt-BR", "Próxima mensagem do roteiro"]] as const) {
      const html = dock({ wide: false, lang });
      expect(band(html), lang).toContain(label);
      expect(band(html), lang).toContain(`lang="pt-BR">${lineOf("stolenCard", 1)}</span>`);
    }
    // English is not offered on the page (it falls back to Spanish): the band itself, in English
    const en = renderToStaticMarkup(<NextBand dict={dictionaries.en} script={at("stolenCard", 1)} disabled={false} awaitingRetry={false} onSend={() => {}} onCopy={() => {}} />);
    expect(en).toContain("Next script message");
    expect(en).toContain('aria-label="Copy to chat" title="Copy to chat"><i class="pb-ico pb-ico--copy"');
    expect(en).not.toContain(">Copy to chat<");
    const pt = renderToStaticMarkup(<NextBand dict={dictionaries.pt} script={at("stolenCard", 1)} disabled={false} awaitingRetry={false} onSend={() => {}} onCopy={() => {}} />);
    expect(pt).toContain('aria-label="Copiar para o chat" title="Copiar para o chat"');
    expect(pt).not.toContain(">Copiar para o chat<");
    expect(en).toContain(`lang="pt-BR">${lineOf("stolenCard", 1)}</span>`);
  });

  test("the action behind a send is the guide's: sendGuideLine advances the script (the dock gives the band and the guide the same handler; the click itself is a manual check)", async () => {
    await running();
    sendGuideLine({ chat: world!.actor }, world!.snapshot.context.script!, lineOf("stolenCard", 1));
    await world!.settle();
    expect(world!.snapshot.context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
  });
});

describe("what the composer's send does with the script's line (sendTyped)", () => {
  let world: ReturnType<typeof createWorld> | undefined;
  afterEach(() => world?.stop());

  const started = async () => {
    world = createWorld();
    const app = createActor(createAppMachine({ storage: null, root: null, navigatorLanguage: "es-CO" })).start();
    startGuideScript({ app, chat: world.actor }, "stolenCard");
    await world.settle();
    return world;
  };
  const page = { lang: "es", locale: "es-CO" } as const;

  test("a copied line sent unchanged goes in the script's language and market, as the card's click does, and the script advances", async () => {
    const w = await started();
    const before = w.callsTo("sendMessage").length;
    sendTyped({ chat: w.actor }, w.snapshot.context.script, lineOf("stolenCard", 1), page);
    await w.settle();
    expect(w.callsTo("sendMessage")[before]!.body).toMatchObject({ text: lineOf("stolenCard", 1), lang: "pt" });
    expect(w.snapshot.context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
  });

  test("the match is the machine's own (equal after trim): surrounding spaces still count as the line, and the text goes out as typed", async () => {
    const w = await started();
    const before = w.callsTo("sendMessage").length;
    sendTyped({ chat: w.actor }, w.snapshot.context.script, `  ${lineOf("stolenCard", 1)}\n`, page);
    await w.settle();
    expect(w.callsTo("sendMessage")[before]!.body).toMatchObject({ lang: "pt" });
    expect(w.snapshot.context.script?.step).toBe(2);
  });

  test("any other text goes with the page's language and stops the script, as before", async () => {
    const w = await started();
    const before = w.callsTo("sendMessage").length;
    sendTyped({ chat: w.actor }, w.snapshot.context.script, `${lineOf("stolenCard", 1)} editado`, page);
    await w.settle();
    expect(w.callsTo("sendMessage")[before]!.body).toMatchObject({ lang: "es" });
    expect(w.snapshot.context.script?.status).toBe("stopped");
  });

  test("with no script, a complete or stopped one, or at the code step, the text goes with the page's language", async () => {
    const w = await started();
    const line = lineOf("stolenCard", 1);
    for (const script of [null, { scriptId: "stolenCard", step: 1, status: "stopped" }, { scriptId: "stolenCard", step: 3, status: "complete" }] as const) {
      const before = w.callsTo("sendMessage").length;
      sendTyped({ chat: w.actor }, script, line, page);
      await w.settle();
      expect(w.callsTo("sendMessage"), JSON.stringify(script)).toHaveLength(before + 1);
      expect(w.callsTo("sendMessage")[before]!.body, JSON.stringify(script)).toMatchObject({ lang: "es" });
    }
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
      <GuidePanel dict={dictionaries[both.app.getSnapshot().context.lang]} script={script} disabled={false} onPick={() => {}} onSend={() => {}} onCopy={() => {}} onReset={() => {}} />,
    );
    expect(html).toContain("Agora</span>");
    expect(count(html, CARD)).toBe(1);
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
