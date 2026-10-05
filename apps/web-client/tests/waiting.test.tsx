// The waiting clock: the three send buttons (the composer's, the guide's next line and the band's) swap the arrow for the
// system's clock while a message is in flight or a rate limit runs, and only then. The animation itself is CSS (tokens.test.ts).

import { afterEach, describe, expect, test } from "bun:test";
import { startScript, type ScriptState } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { ChatDock } from "../src/app/chat/ChatDock";
import { Composer } from "../src/app/chat/Composer";
import { startGuideScript } from "../src/app/chat/guide-actions";
import { NextBand, NextLine } from "../src/app/chat/NextLine";
import { dictionaries } from "../src/i18n";
import { createAppMachine, type AppEnv } from "../src/machines/app.machine";
import { createWorld, json } from "./world";

const composerSend = (html: string) => /<button class="pb-btn pb-btn--primary pb-btn--icon" type="submit"[^>]*>.*?<\/button>/.exec(html)![0];
const render = (props: { sendDisabled?: boolean; waiting?: boolean }) =>
  renderToStaticMarkup(<Composer dict={dictionaries.es} sendDisabled={props.sendDisabled ?? false} waiting={props.waiting} onSend={() => {}} />);

describe("the composer's send button", () => {
  test("ready: the arrow, no waiting marks (disabled only because the draft is empty)", () => {
    const html = composerSend(render({}));
    expect(html).toContain('<i class="pb-ico pb-ico--send" aria-hidden="true"></i>');
    expect(html).toContain('disabled=""');
    expect(html).not.toContain("data-waiting");
    expect(html).not.toContain("aria-busy");
  });

  test("waiting: the clock, data-waiting and aria-busy, still disabled and still named", () => {
    const html = composerSend(render({ sendDisabled: true, waiting: true }));
    expect(html).toContain('<i class="pb-ico pb-ico--clock" aria-hidden="true"></i>');
    expect(html).not.toContain("pb-ico--send");
    expect(html).toContain('data-waiting="true"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('aria-label="Enviar mensaje"');
  });

  test("off for another reason (a conversation that is gone): the arrow, disabled, no waiting marks", () => {
    const html = composerSend(render({ sendDisabled: true, waiting: false }));
    expect(html).toContain("pb-ico--send");
    expect(html).toContain('disabled=""');
    expect(html).not.toContain("data-waiting");
    expect(html).not.toContain("aria-busy");
  });
});

describe("the machine's states in the dock", () => {
  let world: ReturnType<typeof createWorld> | undefined;
  afterEach(() => world?.stop());
  const dock = () => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es-CO" };
    return renderToStaticMarkup(
      <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world!.actor }}>
        <ChatDock open onOpenChange={() => {}} wide />
      </ActorsProvider>,
    );
  };
  const clockCount = (html: string) => (html.match(/data-waiting="true"/g) ?? []).length;

  test("creating and sending: the clock; ready, rate limited (a 429 on the turn after the wait), gone and awaiting retry: see each", async () => {
    world = createWorld();
    // creating: the first message is in flight
    world.send("uno");
    expect(world.state).toBe("creating");
    expect(composerSend(dock())).toContain("pb-ico--clock");
    expect(clockCount(dock())).toBe(1);
    await world.settle();
    // ready: the arrow
    expect(composerSend(dock())).toContain("pb-ico--send");
    expect(clockCount(dock())).toBe(0);
    // a 429: the wait runs, the clock shows
    world.script("sendMessage", json({ detail: "slow" }, 429, { "Retry-After": "60" }));
    world.send("dos");
    await world.settle();
    expect(world.state).toBe("rateLimited");
    expect(composerSend(dock())).toContain("pb-ico--clock");
    expect(composerSend(dock())).toContain('aria-busy="true"');
  });

  test("gone and a message waiting for its retry keep the arrow", async () => {
    world = createWorld();
    world.send("uno");
    await world.settle();
    world.script("sendMessage", json({ detail: "Conversation not found" }, 404));
    world.send("dos");
    await world.settle();
    expect(world.state).toBe("gone");
    expect(composerSend(dock())).toContain("pb-ico--send");
    expect(clockCount(dock())).toBe(0);
    world.stop();
    world = createWorld();
    world.script("sendMessage", json({ detail: "replay_miss" }, 503));
    world.send("uno");
    await world.settle();
    expect(world.state).toBe("unavailable");
    expect(clockCount(dock())).toBe(0);
  });

  test("the guide's card and the band follow the same rule as the composer", async () => {
    world = createWorld();
    const app = createActor(createAppMachine({ storage: null, root: null, navigatorLanguage: "es-CO" })).start();
    startGuideScript({ app, chat: world.actor }, "stolenCard");
    expect(world.state).toBe("creating");
    // in flight: the band (no panel showing) has its send button waiting; the composer too
    const inFlight = renderToStaticMarkup(
      <ActorsProvider actors={{ app, chat: world.actor }}>
        <ChatDock open onOpenChange={() => {}} wide={false} />
      </ActorsProvider>,
    );
    expect(clockCount(inFlight)).toBe(2);
    const band = inFlight.slice(inFlight.indexOf("data-script-band"));
    expect(band).toContain("pb-guide__send");
    expect(/<button class="pb-btn[^"]*pb-guide__send"[^>]*data-waiting="true"/.test(band)).toBe(true);
    await world.settle();
    expect(clockCount(renderToStaticMarkup(
      <ActorsProvider actors={{ app, chat: world.actor }}>
        <ChatDock open onOpenChange={() => {}} wide={false} />
      </ActorsProvider>,
    ))).toBe(0);
  });
});

describe("the next line's send button (NextLine, the guide's card and the band)", () => {
  const line = (props: { disabled?: boolean; awaitingRetry?: boolean; waiting?: boolean }) =>
    renderToStaticMarkup(
      <NextLine dict={dictionaries.es} text="hola" locale="pt-BR" disabled={props.disabled ?? false} awaitingRetry={props.awaitingRetry ?? false} waiting={props.waiting} codeFieldShown={false} onSend={() => {}} onCopy={() => {}} />,
    );
  const send = (html: string) => /<button class="pb-btn[^"]*pb-guide__send"[^>]*>.*?<\/button>/.exec(html)![0];
  const copy = (html: string) => /<button class="pb-btn[^"]*pb-guide__copy"[^>]*>.*?<\/button>/.exec(html)![0];

  test("ready: the arrow; waiting: the clock with data-waiting and aria-busy, still disabled and named; the copy button keeps its glyph", () => {
    expect(send(line({}))).toContain("pb-ico--send");
    expect(send(line({}))).not.toContain("data-waiting");
    const waiting = send(line({ disabled: true, waiting: true }));
    expect(waiting).toContain('<i class="pb-ico pb-ico--clock" aria-hidden="true"></i>');
    expect(waiting).toContain('data-waiting="true"');
    expect(waiting).toContain('aria-busy="true"');
    expect(waiting).toContain('disabled=""');
    expect(waiting).toContain('aria-label="Enviar este mensaje"');
    expect(copy(line({ disabled: true, waiting: true }))).toContain("pb-ico--copy");
    expect(copy(line({ disabled: true, waiting: true }))).not.toContain("data-waiting");
  });

  test("off for another reason (gone: disabled; a message awaiting its retry): the arrow, disabled, no waiting marks", () => {
    for (const props of [{ disabled: true }, { awaitingRetry: true }]) {
      const html = send(line(props));
      expect(html).toContain("pb-ico--send");
      expect(html).toContain('disabled=""');
      expect(html).not.toContain("data-waiting");
      expect(html).not.toContain("aria-busy");
    }
  });

  test("the band passes it on", () => {
    const script: ScriptState = startScript("stolenCard");
    const band = renderToStaticMarkup(<NextBand dict={dictionaries.es} script={{ ...script, step: 1 }} disabled awaitingRetry={false} waiting onSend={() => {}} onCopy={() => {}} />);
    expect(send(band)).toContain('data-waiting="true"');
  });
});
