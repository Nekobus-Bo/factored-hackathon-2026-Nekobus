// The code field of the composer (CodeComposer) and what the chat does around it: the markup in each state, and the
// machine's side (cancel, resume, a new challenge, expiry, a code that fails, a session that locks). The pure
// decision is in chat-model.test.ts. The sixth digit sending by itself, the focus and the keyboard are manual
// checks: there is no DOM here.

import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { ChatDock } from "../src/app/chat/ChatDock";
import { CodeCells, CodeComposer, type CodeComposerProps } from "../src/app/chat/CodeComposer";
import { dictionaries } from "../src/i18n";
import { createAppMachine, type AppEnv } from "../src/machines/app.machine";
import { selectCodeMode } from "../src/machines/chat.machine";
import { CONVERSATION_ID, HANDOFF_BLOCK, inboxResponse, OTP_SEND_RECEIPT, OTP_VERIFY_RECEIPT, TEXT_BLOCK } from "./fixtures";
import { getScript } from "@pattern-blue/contracts";
import { requestNewCode } from "../src/app/chat/code-actions";
import { createWorld, json } from "./world";

const count = (html: string, pattern: RegExp) => html.match(pattern)?.length ?? 0;

const composer = (props: Partial<CodeComposerProps> = {}, dict = dictionaries.es) =>
  renderToStaticMarkup(
    <CodeComposer dict={dict} mode={{ kind: "entry", failed: false }} sendDisabled={false} onSend={() => {}} onCancel={() => {}} onRequestNew={() => {}} {...props} />,
  );

describe("the code field", () => {
  const cells = (html: string) => [...html.matchAll(/<span class="pb-code__d pb-t-code pb-code-entry__cell"([^>]*)>([^<]*)<\/span>/g)].map((match) => ({ attrs: match[1]!, digit: match[2]! }));
  /** The markup with some digits typed: the component keeps them in its state, so it is rendered through the cells' props only. */
  test("six boxes in a row, the system's digit cell in its code type, none of them the input", () => {
    const html = composer();
    expect(html).toContain('<form class="pb-chat__composer pb-code-entry">');
    expect(cells(html)).toHaveLength(6);
    expect(count(html, /pb-code__d/g)).toBe(6);
    // the code type is on every box, and the input has none of its own: the boxes show the digits
    expect(count(html, /pb-t-code/g)).toBe(6);
    expect(html).toMatch(/<div class="pb-code pb-code-entry__cells">/);
    expect(cells(html).every((cell) => cell.attrs.includes('aria-hidden="true"'))).toBe(true);
  });

  test("empty, the boxes are empty and the first is the one to type in", () => {
    const boxes = cells(composer());
    expect(boxes.map((cell) => cell.digit)).toEqual(["", "", "", "", "", ""]);
    expect(boxes.map((cell) => cell.attrs.includes('data-active="true"'))).toEqual([true, false, false, false, false, false]);
  });

  test("each box shows the digit of its place, and the box to type in is the next one; six digits leave none", () => {
    const render = (digits: string) => cells(renderToStaticMarkup(<CodeCells digits={digits} disabled={false} />));
    expect(render("58").map((cell) => cell.digit)).toEqual(["5", "8", "", "", "", ""]);
    expect(render("58").map((cell) => cell.attrs.includes('data-active="true"'))).toEqual([false, false, true, false, false, false]);
    expect(render("588820").map((cell) => cell.digit)).toEqual(["5", "8", "8", "8", "2", "0"]);
    expect(render("588820").some((cell) => cell.attrs.includes("data-active"))).toBe(false);
    // the digits are text of the box: nothing masks them in the field itself
    expect(renderToStaticMarkup(<CodeCells digits="0123" disabled />)).toContain(">0</span>");
  });

  test("one real input over the boxes: digits only, six at most, the numeric keyboard and the one-time-code hint", () => {
    const html = composer();
    expect(count(html, /<input/g)).toBe(1);
    expect(html).toContain('type="text"');
    expect(html).toContain('inputMode="numeric"');
    expect(html).toContain('autoComplete="one-time-code"');
    expect(html).toContain('pattern="[0-9]*"');
    // no maxLength: a pasted "588 820" is seven characters, and the filter (sanitizeCode) keeps the digits
    expect(html).not.toContain("maxLength");
    expect(html).toContain('class="pb-code-entry__input"');
    // the input comes after the boxes (it lies over them) and holds the value
    expect(html.indexOf("<input")).toBeGreaterThan(html.lastIndexOf("pb-code-entry__cell"));
    expect(html).not.toContain("<textarea");
    expect(html).not.toContain('type="submit"');
  });

  test("the label is visible, in the system's label style, and bound to the input", () => {
    const html = composer();
    const id = /<label class="pb-t-label" for="([^"]+)">Código de 6 dígitos<\/label>/.exec(html)?.[1];
    expect(id).toBeDefined();
    expect(html).toContain(`id="${id}"`);
    // not only for screen readers
    expect(html).not.toContain("pb-sr");
    expect(composer({}, dictionaries.en)).toContain(">6-digit code</label>");
    expect(composer({}, dictionaries.pt)).toContain(">Código de 6 dígitos</label>");
  });

  test("'Cancelar' sits after the boxes, a ghost button, and there is no send button", () => {
    const html = composer();
    expect(html).toContain('<button class="pb-btn pb-btn--ghost pb-code-entry__cancel" type="button">Cancelar</button>');
    expect(html.indexOf("pb-code-entry__cancel")).toBeGreaterThan(html.indexOf("<input"));
    expect(html).not.toContain("pb-code-entry__error");
    expect(html).not.toContain('role="alert"');
  });

  test("while the turn is in flight the input is off, the boxes dim and none is the one to type in", () => {
    const off = composer({ sendDisabled: true });
    expect(off).toMatch(/<input[^>]* disabled=""/);
    expect(off).toContain('<div class="pb-code pb-code-entry__cells" data-disabled="">');
    expect(cells(off).some((cell) => cell.attrs.includes("data-active"))).toBe(false);
    const on = composer();
    expect(on).not.toMatch(/<input[^>]* disabled=""/);
    expect(on).not.toContain("data-disabled");
  });

  test("a code that was not accepted gets one line under the field, and only when the mode says the turn proved it", () => {
    const failed = composer({ mode: { kind: "entry", failed: true } });
    expect(failed).toContain('role="alert"');
    // the input points at the line and says it is invalid
    expect(failed).toMatch(/aria-invalid="true" aria-describedby="([^"]+)-error"/);
    expect(failed).toContain("No se pudo verificar el código.");
    // no attempts counter: the client has none to show
    expect(failed).not.toMatch(/intento|\d\s*\/\s*3|restantes/i);
    expect(composer()).not.toContain("No se pudo verificar");
  });

  test("an expired code: the line, 'Pedir otro código' and 'Cancelar', and no field", () => {
    const html = composer({ mode: { kind: "expired" } });
    expect(html).toContain('<p class="pb-code-entry__note" role="status">El código venció.</p>');
    expect(html).toContain("Pedir otro código");
    expect(html).toContain("Cancelar");
    expect(html).not.toContain("<input");
    expect(html).not.toContain("pb-code__d");
    expect(composer({ mode: { kind: "expired" }, sendDisabled: true })).toMatch(/<button[^>]* disabled=""[^>]*data-code-new/);
  });

  test("hidden while the detective view takes the chat's place, mounted", () => {
    expect(composer({ hidden: true })).toMatch(/^<form class="pb-chat__composer pb-code-entry" hidden="">/);
  });

  test("the words are in each language", () => {
    const pt = composer({ mode: { kind: "entry", failed: true } }, dictionaries.pt);
    expect(pt).toContain(">Código de 6 dígitos</label>");
    expect(pt).toContain("Cancelar");
    expect(pt).toContain("Não foi possível verificar o código.");
    const en = composer({ mode: { kind: "expired" } }, dictionaries.en);
    expect(en).toContain("The code expired.");
    expect(en).toContain("Ask for another code");
    expect(en).toContain("Cancel");
  });

  test("the fixed message that asks for a code is the dictionary's, per language", () => {
    expect(dictionaries.es.chat.code.requestMessage).toBe("Envíame un código nuevo.");
    expect(dictionaries.pt.chat.code.requestMessage).toBe("Me envie um novo código.");
    expect(dictionaries.en.chat.code.requestMessage).toBe("Send me a new code.");
  });
});

describe("the chat around the code field", () => {
  let world = createWorld();
  afterEach(() => world.stop());
  const fresh = () => {
    world.stop();
    world = createWorld();
    return world;
  };
  const pending = (w: ReturnType<typeof createWorld>) => {
    w.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT] }));
    w.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z")));
  };
  const mode = () => selectCodeMode(world.snapshot);

  const dock = () => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es-CO" };
    return renderToStaticMarkup(
      <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world.actor }}>
        <ChatDock open onOpenChange={() => {}} />
      </ActorsProvider>,
    );
  };

  test("a code is pending: the field takes the composer's place, and the normal composer stays mounted, hidden, with its draft", async () => {
    fresh();
    pending(world);
    world.send("perdí mi tarjeta");
    await world.settle();
    expect(mode()).toEqual({ kind: "entry", failed: false });
    const html = dock();
    expect(html).toContain("data-code-field");
    expect(html).toMatch(/<form class="pb-chat__composer" hidden="">/);
    expect(html).toContain("<textarea");
    // the notice stays where it was
    expect(html).toContain("Abrir bandeja");
    expect(html).not.toContain("data-code-write");
  });

  test("with no challenge the composer is the normal one, with no field", async () => {
    fresh();
    world.send("hola");
    await world.settle();
    const html = dock();
    expect(mode()).toEqual({ kind: "off" });
    expect(html).not.toContain("data-code-field");
    expect(html).toMatch(/<form class="pb-chat__composer">/);
  });

  test("cancel leaves the field for that challenge, sends nothing, and the notice offers the way back", async () => {
    fresh();
    pending(world);
    world.send("perdí mi tarjeta");
    await world.settle();
    const sends = world.callsTo("sendMessage").length;
    world.actor.send({ type: "CODE.DISMISS" });
    expect(mode()).toEqual({ kind: "dismissed", resumable: true });
    expect(world.callsTo("sendMessage")).toHaveLength(sends);
    const html = dock();
    expect(html).not.toContain("data-code-field");
    expect(html).toMatch(/<form class="pb-chat__composer">/);
    expect(html).toContain('data-code-write="true"');
    expect(html).toContain("Escribir el código");
    // "Escribir el código" is the way back
    world.actor.send({ type: "CODE.RESUME" });
    expect(mode()).toEqual({ kind: "entry", failed: false });
    expect(dock()).not.toContain("data-code-write");
  });

  test("a new challenge after cancelling is the field again", async () => {
    fresh();
    pending(world);
    world.send("perdí mi tarjeta");
    await world.settle();
    world.actor.send({ type: "CODE.DISMISS" });
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT] }));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:49:02Z", "2026-09-29T15:44:02Z")));
    world.send("envíame otro");
    await world.settle();
    expect(mode()).toEqual({ kind: "entry", failed: false });
  });

  test("a code that fails stays in the field, with the line only because the turn carries a verification receipt that did not verify", async () => {
    fresh();
    pending(world);
    world.send("perdí mi tarjeta");
    await world.settle();
    // an answer in words only: no line
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK] }));
    world.send("000000");
    await world.settle();
    expect(mode()).toEqual({ kind: "entry", failed: false });
    // a receipt that did not verify: the line
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, { type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: "OTP_PENDING" } }] }));
    world.send("111111");
    await world.settle();
    expect(mode()).toEqual({ kind: "entry", failed: true });
    expect(dock()).toContain("No se pudo verificar el código.");
  });

  test("the code is typed through the chat's own send: the bubble reads 'Código: ••••••' and the six digits go as typed", async () => {
    fresh();
    pending(world);
    world.send("perdí mi tarjeta");
    await world.settle();
    world.send("588820");
    await world.settle();
    const last = world.snapshot.context.entries.filter((entry) => entry.kind === "customer").at(-1);
    expect(last).toMatchObject({ text: "Código: ••••••" });
    expect((world.callsTo("sendMessage").at(-1)!.body as { text: string }).text).toBe("588820");
  });

  test("a session that locks, a verification and a handoff end the mode", async () => {
    for (const final of [
      { type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: "LOCKED" } },
      OTP_VERIFY_RECEIPT,
      HANDOFF_BLOCK,
    ]) {
      fresh();
      pending(world);
      world.send("perdí mi tarjeta");
      await world.settle();
      expect(mode().kind).toBe("entry");
      world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, final] }));
      world.send("000000");
      await world.settle();
      expect(mode(), JSON.stringify(final).slice(0, 80)).toEqual({ kind: "off" });
      expect(dock()).not.toContain("data-code-field");
    }
  });

  test("when the code expires the field gives way to 'Pedir otro código'; the request is a fixed message in the language of the conversation, and the script stays at its code step", async () => {
    fresh();
    pending(world);
    world.actor.send({ type: "SCRIPT.START", scriptId: "stolenCard" });
    await world.settle();
    world.send(getScript("stolenCard").steps[1]!.kind === "message" ? (getScript("stolenCard").steps[1] as { text: string }).text : "", "pt");
    await world.settle();
    expect(world.snapshot.context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
    expect(mode().kind).toBe("entry");
    world.advance(5 * 60 * 1000 + 3000);
    await world.tick();
    expect(mode()).toEqual({ kind: "expired" });
    const html = dock();
    expect(html).not.toContain("data-code-field");
    expect(html).toContain("data-code-new");
    expect(html).toContain("El código venció.");
    expect(html).toMatch(/<form class="pb-chat__composer" hidden="">/);

    // the button's own path, with the page in Spanish and the conversation in Portuguese: the message is the Portuguese one
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT] }));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:50:00Z", "2026-09-29T15:45:30Z")));
    requestNewCode({ chat: world.actor }, world.snapshot.context.entries, "es", "es-CO");
    await world.settle();
    expect(world.callsTo("sendMessage").at(-1)!.body).toMatchObject({ text: "Me envie um novo código.", lang: "pt" });
    // it did not stop the demo script, and the new receipt is a new challenge: the field again
    expect(world.snapshot.context.script).toEqual({ scriptId: "stolenCard", step: 2, status: "running" });
    expect(mode()).toEqual({ kind: "entry", failed: false });
  });

  test("the request is in the page's language when the conversation has no message of its own, and in English for English", async () => {
    fresh();
    const entries = world.snapshot.context.entries;
    requestNewCode({ chat: world.actor }, entries, "en", "en-US");
    await world.settle();
    expect(world.callsTo("sendMessage")[0]!.body).toMatchObject({ text: "Send me a new code.", lang: "en" });
  });
});
