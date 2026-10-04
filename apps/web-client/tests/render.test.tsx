// Block rendering against fixtures, with react-dom/server: no DOM library. What the customer sees is the
// markup, so the rules of the chat are checked on the markup.

import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { Blocks } from "../src/app/chat/Blocks";
import { ChatDock } from "../src/app/chat/ChatDock";
import { OtpFoot, OtpSheet } from "../src/app/chat/Notices";
import { FeedbackLine } from "../src/app/chat/Feedback";
import { TracePanel, TraceStrip, type TracePanelProps } from "../src/app/chat/TracePanel";
import { tracedTurns } from "../src/app/chat/trace-model";
import { Transcript } from "../src/app/chat/Transcript";
import { Landing } from "../src/app/landing/Landing";
import { dictionaries } from "../src/i18n";
import { createAppMachine, type AppEnv } from "../src/machines/app.machine";
import type { Entry } from "../src/machines/chat-model";
import {
  CARD_BLOCK_RECEIPT,
  HANDOFF_BLOCK,
  INBOX_CODE,
  inboxResponse,
  OTP_SEND_RECEIPT,
  OTP_VERIFY_RECEIPT,
  SECRET_ACTION,
  SECRET_FACT,
  SECRET_QUESTION,
  TEXT_BLOCK,
  UNKNOWN_BLOCK,
  TRACE,
  TRACE_TOOL,
} from "./fixtures";
import { createWorld, json } from "./world";

const AT = "2026-09-29T15:42:00Z";
const render = (blocks: unknown[], lang: "es" | "pt" | "en" = "es", turnLang: "es" | "pt" | "en" = lang) =>
  renderToStaticMarkup(<Blocks blocks={blocks as never} lang={lang} turnLang={turnLang} at={AT} />);

describe("text", () => {
  test("an assistant bubble: the sender for screen readers only, then the text and the time", () => {
    const html = render([TEXT_BLOCK]);
    expect(html).toContain("pb-msg pb-msg--assistant");
    expect(html).toContain('<span class="pb-sr">Asistente: </span>');
    expect(html).not.toContain("pb-msg__meta");
    expect(html).toContain("Hola, puedo ayudarte con tu tarjeta.");
    expect(html).toMatch(/<span class="pb-msg__time">\d{2}:\d{2}<\/span>/);
  });

  test("text is escaped, not interpreted", () => {
    const html = render([{ type: "text", text: '<img src=x onerror="alert(1)"> **bold**' }]);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x onerror=");
  });

  test("a turn in another language than the page carries its own lang", () => {
    expect(render([TEXT_BLOCK], "es", "pt")).toContain('lang="pt"');
    expect(render([TEXT_BLOCK], "es", "es")).not.toContain("lang=");
  });

  test("a full card number is never shown, even if the model wrote one", () => {
    const html = render([{ type: "text", text: "Tu tarjeta 4111 1111 1111 1111 quedó bloqueada." }]);
    expect(html).not.toContain("4111");
    expect(html).toContain("•••• 1111");
  });
});

describe("receipts", () => {
  test("card.block: the result with the masked card, and the receipt reference", () => {
    const html = render([CARD_BLOCK_RECEIPT]);
    expect(html).toContain("pb-cut pb-proof");
    expect(html).toContain('Bloqueé tu tarjeta <span class="pb-proof__data">•••• 4821</span>');
    expect(html).not.toContain("****");
    expect(html).toContain('Comprobante <span class="pb-proof__data">aud_20481abc</span>');
    // the tool name is back-office vocabulary
    expect(html).not.toContain("card.block");
  });

  test("the state change and the database check are in the markup, hidden until the reference is opened", () => {
    const html = render([CARD_BLOCK_RECEIPT]);
    expect(html).toContain('aria-expanded="false" aria-controls="receipt-aud_20481abc"');
    expect(html).toMatch(/<div class="pb-proof__more" id="receipt-aud_20481abc" hidden="">/);
    expect(html).toContain('data-state="active"');
    expect(html).toContain('data-state="blocked"');
    expect(html).toContain("Activa");
    expect(html).toContain("Bloqueada");
    expect(html).toMatch(/Verificado contra la base de datos · \d{2}:\d{2}:\d{2}/);
    // customer wording, never the raw enums
    expect(html).not.toMatch(/>ACTIVE<|>BLOCKED<|>OTP_PENDING</);
  });

  test("card.block on a card that was already blocked says so, and shows no change", () => {
    const already = { type: "receipt", receipt: { ...CARD_BLOCK_RECEIPT.receipt, state_before: "BLOCKED" } };
    const html = render([already]);
    expect(html).toContain('Tu tarjeta <span class="pb-proof__data">•••• 4821</span> ya estaba bloqueada');
    expect(html).not.toContain("Bloqueé");
    expect(html).toContain("Sin cambios");
    expect(html).not.toContain("cambió a");
    expect(html).not.toContain('data-state="active"');
    expect(render([already], "pt")).toContain("já estava bloqueado");
    expect(render([already], "en")).toContain("was already blocked");
  });

  test("otp.send: where the code went, and the customer wording of both states", () => {
    const html = render([OTP_SEND_RECEIPT]);
    expect(html).toContain('Te envié un código a <span class="pb-proof__data">d***@example.com</span>');
    expect(html).toContain("Identificado");
    expect(html).toContain("Código pendiente");
    expect(html).toContain('data-state="otp-pending"');
  });

  test("otp.verify: a verified system line with its reference, no internal challenge reference", () => {
    const html = render([OTP_VERIFY_RECEIPT]);
    expect(html).toContain('<p class="pb-sys" data-tone="verified">');
    expect(html).toContain("Identidad verificada");
    expect(html).toContain("aud_20480abc");
    expect(html).not.toContain("chal_");
    expect(html).not.toContain("pb-proof");
  });

  test("otp.verify that locks the session says so, not that the identity was verified", () => {
    const html = render([{ type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: "LOCKED" } }]);
    expect(html).toContain('data-tone="locked"');
    expect(html).toContain("Sesión bloqueada");
    expect(html).not.toContain("Identidad verificada");
  });

  test("in Portuguese and English, with the design system's wording", () => {
    const pt = render([CARD_BLOCK_RECEIPT], "pt");
    expect(pt).toContain("Bloqueei seu cartão");
    expect(pt).toContain("Comprovante");
    expect(pt).toContain("Ativo");
    expect(pt).toContain("Bloqueado");
    expect(pt).toContain("Verificado no banco de dados");
    const en = render([CARD_BLOCK_RECEIPT], "en");
    expect(en).toContain("I blocked your card");
    expect(en).toContain("Receipt");
    expect(en).toContain("Active");
    expect(en).toContain("Blocked");
    expect(en).toContain("Verified against the database");
  });

  test("a receipt for an action this build has no title for is still a receipt", () => {
    const html = render([{ type: "receipt", receipt: { ...CARD_BLOCK_RECEIPT.receipt, action: "account.freeze", state_before: "ACTIVE", state_after: "FROZEN" } }]);
    expect(html).toContain("Acción confirmada");
    expect(html).toContain("Congelada");
    expect(html).toContain("aud_20481abc");
  });

  test("the countdown goes inside the otp.send receipt it belongs to, and nowhere else", () => {
    const foot = <i data-test="otp-foot" />;
    expect(renderToStaticMarkup(<Blocks blocks={[OTP_SEND_RECEIPT] as never} lang="es" turnLang="es" at={AT} otpFoot={foot} />)).toContain('data-test="otp-foot"');
    expect(renderToStaticMarkup(<Blocks blocks={[CARD_BLOCK_RECEIPT] as never} lang="es" turnLang="es" at={AT} otpFoot={foot} />)).not.toContain('data-test="otp-foot"');
  });
});

describe("handoff, customer view", () => {
  const html = render([HANDOFF_BLOCK]);

  test("the department in words, the case reference and the closing sentence", () => {
    expect(html).toContain('data-tone="handoff"');
    expect(html).toContain("Te pasé con un agente de Disputas");
    expect(html).toContain('Caso <span class="pb-proof__data">hnd_abcd1234efgh</span>');
    expect(html).toContain("Desde aquí el asistente deja de actuar");
    expect(html).not.toMatch(/>URGENT<|>DISPUTES<|>QUEUED</);
  });

  test("no queue details: status, position and priority belong to the back office", () => {
    for (const detail of ["Urgente", "En la fila", "2 en la fila", "Prioridad", "Posición"]) expect(html, detail).not.toContain(detail);
  });

  test("never the summary, the audit id or the receipt of the handoff", () => {
    for (const secret of [SECRET_FACT, SECRET_ACTION, SECRET_QUESTION, "verified_facts", "actions_taken", "otp_email", "aud_handoff-secret-audit", "handoff.create"]) {
      expect(html, secret).not.toContain(secret);
    }
  });

  test("every department has words in every language, and no enum leaks", () => {
    for (const lang of ["es", "pt", "en"] as const) {
      for (const department of ["FRAUD_OPERATIONS", "CUSTOMER_SUPPORT", "DISPUTES"]) {
        for (const priority of ["URGENT", "HIGH", "NORMAL", "LOW"]) {
          for (const status of ["QUEUED", "ASSIGNED", "PENDING"]) {
            const out = render([{ ...HANDOFF_BLOCK, department, priority, status }], lang);
            expect(out).not.toMatch(/FRAUD_OPERATIONS|CUSTOMER_SUPPORT|DISPUTES|URGENT|QUEUED|ASSIGNED|PENDING/);
            expect(out).not.toContain("undefined");
          }
        }
      }
    }
  });

  test("what follows the handoff (the feedback line) comes right after it", () => {
    const out = renderToStaticMarkup(<Blocks blocks={[HANDOFF_BLOCK, TEXT_BLOCK] as never} lang="es" turnLang="es" at={AT} afterHandoff={<i data-test="after" />} />);
    expect(out.indexOf('data-test="after"')).toBeGreaterThan(out.indexOf("hnd_abcd1234efgh"));
    expect(out.indexOf('data-test="after"')).toBeLessThan(out.indexOf("Hola, puedo ayudarte"));
  });
});

describe("what is not rendered", () => {
  test("a block type this build does not know is ignored and the rest of the turn is shown", () => {
    const html = render([TEXT_BLOCK, UNKNOWN_BLOCK, CARD_BLOCK_RECEIPT]);
    expect(html).toContain("Hola, puedo ayudarte");
    expect(html).toContain("Bloqueé tu tarjeta");
    expect(html).not.toContain("carousel");
  });

  test("a known block that fails its schema is ignored", () => {
    const html = render([{ type: "receipt", receipt: { action: "card.block" } }, { type: "text", text: "" }, TEXT_BLOCK]);
    expect(html.match(/pb-msg--assistant/g)).toHaveLength(1);
  });

  test("nothing at all is a normal answer", () => {
    expect(render([])).toBe("");
    expect(render([UNKNOWN_BLOCK])).toBe("");
  });
});

describe("the transcript", () => {
  const entries: Entry[] = [
    { id: "1", kind: "customer", text: "Perdí mi tarjeta", at: AT, lang: "es", status: "sent" },
    { id: "2", kind: "assistant", blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT], at: AT, lang: "es" },
    { id: "3", kind: "customer", text: "Código: ••••••", at: AT, lang: "es", status: "sent" },
    { id: "4", kind: "system", code: "takeover", at: AT },
    { id: "5", kind: "agent", text: "Hola, soy del equipo de Disputas.", at: AT, key: "k" },
    { id: "6", kind: "system", code: "codeExpired", at: AT },
    { id: "7", kind: "customer", text: "sin enviar", at: AT, lang: "es", status: "failed" },
  ];
  const html = renderToStaticMarkup(
    <Transcript entries={entries} lang="es" failure={{ entryId: "7", retry: true, reason: "El asistente no está disponible." }} onRetry={() => {}} />,
  );

  test("customer, assistant, agent and system entries each in their own markup", () => {
    expect(html).toContain("pb-msg pb-msg--customer");
    expect(html).toContain("pb-msg pb-msg--assistant");
    expect(html).toContain("pb-msg pb-msg--agent");
    expect(html).toContain('<span class="pb-sr">Tú: </span>');
    expect(html).toContain("Agente humano");
    expect(html).toContain('<div class="pb-sys" data-tone="joined">');
    expect(html).toContain("Un agente está atendiendo tu caso");
    expect(html).toContain("El código venció");
  });

  test("a customer's code is shown masked", () => {
    expect(html).toContain("Código: ••••••");
  });

  test("the message that just failed says why under it, as an alert, and offers the retry", () => {
    expect(html).toContain('data-status="failed"');
    expect(html).toContain('<p class="pb-unsent" role="alert">');
    expect(html).toContain("No pudimos enviar tu mensaje. El asistente no está disponible.");
    expect(html).toContain("Reintentar");
  });

  test("an older failed message only says it was not sent", () => {
    const old = renderToStaticMarkup(<Transcript entries={entries} lang="es" onRetry={() => {}} />);
    expect(old).toContain("No pudimos enviar tu mensaje.");
    expect(old).not.toContain("Reintentar");
    expect(old).not.toContain('role="alert"');
  });

  test("the countdown goes to the newest otp.send receipt only", () => {
    const twice: Entry[] = [entries[1]!, { ...entries[1]!, id: "2b", blocks: [OTP_SEND_RECEIPT] } as Entry];
    const out = renderToStaticMarkup(<Transcript entries={twice} lang="es" otpFoot={<i data-test="otp-foot" />} />);
    expect(out.match(/data-test="otp-foot"/g)).toHaveLength(1);
    expect(out.lastIndexOf("pb-proof")).toBeLessThan(out.indexOf('data-test="otp-foot"'));
  });

  test("the agent's identity is not a thing the markup could hold", () => {
    expect(html).not.toMatch(/@patternblue|agent_ref|agente@/i);
  });
});

describe("the one-time code", () => {
  afterEach(() => world?.stop());
  let world: ReturnType<typeof createWorld> | undefined;

  const appActor = () => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es-CO" };
    return createActor(createAppMachine(env)).start();
  };

  test("never in the rendered transcript, at any point of the flow", async () => {
    world = createWorld();
    world.script("sendMessage", json({ conversation_id: "conv_0123456789abcdef0123456789abcdef", blocks: [TEXT_BLOCK, OTP_SEND_RECEIPT] }), json({ conversation_id: "conv_0123456789abcdef0123456789abcdef", blocks: [TEXT_BLOCK, OTP_VERIFY_RECEIPT] }));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z")));

    world.send("Perdí mi tarjeta");
    await world.settle();
    expect(world.snapshot.context.inbox?.message.code).toBe(INBOX_CODE);

    // the customer types the code; even revealed, it is not in the log
    world.actor.send({ type: "CODE.REVEAL" });
    world.send(`mi código es ${INBOX_CODE}`);
    await world.settle();

    const transcript = renderToStaticMarkup(<Transcript entries={world.snapshot.context.entries} lang="es" />);
    expect(transcript).not.toContain(INBOX_CODE);
    expect(transcript).toContain("mi código es ••••••");

    const dock = renderToStaticMarkup(
      <ActorsProvider actors={{ app: appActor(), chat: world.actor }}>
        <ChatDock open onOpenChange={() => {}} />
      </ActorsProvider>,
    );
    expect(dock).not.toContain(INBOX_CODE);
  });

  test("the receipt's foot: the countdown and the action, never the code", () => {
    const dict = dictionaries.es;
    const message = { channel: "email", destination_masked: "d***@example.com", code: INBOX_CODE, received_at: "2026-09-29T15:40:02Z", expires_at: "2026-09-29T15:45:02Z" };
    const now = Date.parse("2026-09-29T15:40:30Z");
    const foot = renderToStaticMarkup(<OtpFoot dict={dict} notice={{ message, revealed: false }} now={now} open={false} onToggle={() => {}} />);
    expect(foot).toContain("Vence en");
    expect(foot).toContain('role="timer"');
    expect(foot).toContain("04:32");
    expect(foot).toContain("Abrir bandeja");
    expect(foot).toContain('aria-controls="otp-inbox"');
    expect(foot).not.toContain(INBOX_CODE);
  });

  test("the sheet: simulated and demo in sight, and the code only once it is asked for", () => {
    const dict = dictionaries.es;
    const message = { channel: "email", destination_masked: "d***@example.com", code: INBOX_CODE, received_at: "2026-09-29T15:40:02Z", expires_at: "2026-09-29T15:45:02Z" };
    const now = Date.parse("2026-09-29T15:40:30Z");
    const sheet = (revealed: boolean) =>
      renderToStaticMarkup(<OtpSheet dict={dict} notice={{ message, revealed }} now={now} onClose={() => {}} onReveal={() => {}} onHide={() => {}} />);

    const hidden = sheet(false);
    expect(hidden).toContain('id="otp-inbox"');
    expect(hidden).toContain("Bandeja simulada");
    expect(hidden).toContain("DEMO");
    expect(hidden).toContain("Entrega simulada");
    expect(hidden).toContain("nunca te pedirá este código");
    expect(hidden).toContain("Mostrar código");
    expect(hidden).toContain("Código oculto");
    expect(hidden).not.toContain(INBOX_CODE);
    expect(hidden).not.toMatch(/>4<|>8<|>2<|>9<|>1<|>6</);

    const shown = sheet(true);
    expect(shown).toContain("Código: 4 8 2 9 1 6");
    expect(shown).toContain("Ocultar código");
    for (const digit of INBOX_CODE) expect(shown).toContain(`>${digit}<`);
  });

  test("the countdown turns to the alert state in the last minute and never goes negative", () => {
    const dict = dictionaries.en;
    const message = { channel: "email", destination_masked: "d***@example.com", code: INBOX_CODE, received_at: "2026-09-29T15:40:00Z", expires_at: "2026-09-29T15:45:00Z" };
    const sheet = (now: string) =>
      renderToStaticMarkup(<OtpSheet dict={dict} notice={{ message, revealed: false }} now={Date.parse(now)} onClose={() => {}} onReveal={() => {}} onHide={() => {}} />);
    const late = sheet("2026-09-29T15:44:30Z");
    expect(late).toContain('data-state="abstained"');
    expect(late).toContain("00:30");
    expect(sheet("2026-09-29T15:50:00Z")).toContain("00:00");
  });
});

describe("feedback after a handoff", () => {
  const dict = dictionaries.es;
  const line = (state: "asking" | "sending" | "sent" | "failed") =>
    renderToStaticMarkup(<FeedbackLine dict={dict} state={state} onAnswer={() => {}} />);

  test("the question and two equal buttons whose labels say what they mean", () => {
    const html = line("asking");
    expect(html).toContain("¿Te ayudó el asistente?");
    expect(html).toContain('aria-label="Sí, el asistente me ayudó"');
    expect(html).toContain('aria-label="No, el asistente no me ayudó"');
    expect(html.match(/pb-rate__face/g)).toHaveLength(2);
    expect(html).not.toContain("pb-btn--primary");
    expect(html).not.toContain("disabled");
  });

  test("sending disables both; a failure says so, as an alert, and keeps them", () => {
    expect(line("sending").match(/disabled=""/g)).toHaveLength(2);
    const failed = line("failed");
    expect(failed).toContain("No pudimos guardar tu respuesta.");
    expect(failed).toContain('role="alert"');
    expect(failed).not.toContain("disabled");
  });

  test("once answered: the thanks, as a status, and no buttons", () => {
    const html = line("sent");
    expect(html).toContain("Gracias por tu respuesta.");
    expect(html).toContain('role="status"');
    expect(html).not.toContain("<button");
  });

  test("the dock asks only after a handoff block", async () => {
    const dock = async (blocks: unknown[]) => {
      const world = createWorld();
      world.script("sendMessage", json({ conversation_id: "conv_0123456789abcdef0123456789abcdef", blocks }));
      world.send("hola");
      await world.settle();
      const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es" };
      const html = renderToStaticMarkup(
        <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world.actor }}>
          <ChatDock open onOpenChange={() => {}} />
        </ActorsProvider>,
      );
      world.stop();
      return html;
    };
    expect(await dock([TEXT_BLOCK])).not.toContain("¿Te ayudó el asistente?");
    const after = await dock([TEXT_BLOCK, HANDOFF_BLOCK]);
    expect(after).toContain("¿Te ayudó el asistente?");
    expect(after.indexOf("¿Te ayudó el asistente?")).toBeGreaterThan(after.indexOf("hnd_abcd1234efgh"));
  });
});

describe("the landing", () => {
  const page = (navigatorLanguage: string) => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage };
    const world = createWorld();
    const html = renderToStaticMarkup(
      <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world.actor }}>
        <Landing />
      </ActorsProvider>,
    );
    world.stop();
    return html;
  };

  test("follows the browser's language and carries the demo note and the S² small print in each", () => {
    for (const [navigatorLanguage, title, demo, tag] of [
      ["es-CO", "Tu banco", "datos sintéticos", "Solo demo"],
      ["pt-BR", "Seu banco", "dados sintéticos", "Somente demo"],
      // English is not offered on the page: an English browser gets the Spanish one.
      ["en-US", "Tu banco", "datos sintéticos", "Solo demo"],
    ] as const) {
      const html = page(navigatorLanguage);
      expect(html).toContain(title);
      expect(html).toContain(demo);
      expect(html).toContain(tag);
      expect(html).toContain("Factored AI &amp; Data Hackathon 2026");
      expect(html).not.toContain("undefined");
      expect(html).not.toContain("{");
    }
  });

  test("a bank's home page: the sections, in order, and the dock last", () => {
    const html = page("es");
    const order = ['class="pb-nav"', 'id="top"', 'id="productos"', 'id="tarjeta-perdida"', 'id="s2"', 'id="ayuda"', 'class="pb-footer"', 'class="pb-dock"'];
    const positions = order.map((needle) => html.indexOf(needle));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  test("the hero shows an active card and no system vocabulary", () => {
    const html = page("es");
    expect(html).toContain('class="pb-cardvis" data-state="active"');
    expect(html).not.toContain("base de datos");
  });

  test("the navbar and the hero open the chat", () => {
    expect(page("es").match(/data-open-chat/g)).toHaveLength(2);
  });

  test("the FAQ is the design system's accordion: five items, the first open, no div inside a trigger", () => {
    const html = page("es");
    const triggers = [...html.matchAll(/<button[^>]*pb-faq__trigger[^>]*>(.*?)<\/button>/gs)];
    expect(triggers).toHaveLength(5);
    expect(triggers.map((match) => match[0].includes('aria-expanded="true"'))).toEqual([true, false, false, false, false]);
    for (const trigger of triggers) expect(trigger[1]).not.toContain("<div");
    expect(html).toContain('data-scope="accordion"');
    expect(html).toContain("pb-faq__indicator");
  });

  test("no chat request is made by rendering it: the conversation is lazy", () => {
    const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es" };
    const world = createWorld();
    renderToStaticMarkup(
      <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world.actor }}>
        <Landing />
      </ActorsProvider>,
    );
    expect(world.calls).toHaveLength(0);
    world.stop();
  });

  test("the language switch is a radio group of ES and PT, and the theme one button whose label says what it does", () => {
    const html = page("pt-BR");
    expect(html.match(/role="radiogroup"/g)).toHaveLength(1);
    expect([...html.matchAll(/data-lang="(\w+)"/g)].map((match) => match[1])).toEqual(["es", "pt"]);
    expect(html).toMatch(/aria-checked="true"[^>]*data-lang="pt"/);
    expect(html.match(/pb-theme--single/g)).toHaveLength(1);
    expect(html).toMatch(/aria-label="Mudar para o tema (escuro|claro)"/);
  });

  test("Spanish adds the market switch to the navbar, with the browser's market checked", () => {
    const html = page("es-MX");
    expect(html.match(/role="radiogroup"/g)).toHaveLength(2);
    expect(html.match(/aria-label="País"/g)).toHaveLength(1);
    for (const [locale, name] of [["es-MX", "México"], ["es-AR", "Argentina"], ["es-CO", "Colombia"]] as const) {
      expect(html).toMatch(new RegExp(`data-locale="${locale}" aria-label="${name}"`));
    }
    expect(html.match(/aria-checked="true"[^>]*data-locale="es-MX"/g)).toHaveLength(1);
    expect(html).not.toMatch(/aria-checked="true"[^>]*data-locale="es-(AR|CO)"/);
  });

  test("a Spanish browser that names no market starts in Colombia", () => {
    const html = page("es-ES");
    expect(html.match(/aria-checked="true"[^>]*data-locale="es-CO"/g)).toHaveLength(1);
    expect(html).not.toMatch(/aria-checked="true"[^>]*data-locale="es-(AR|MX)"/);
  });
});

describe("detective mode (ADR-0019)", () => {
  afterEach(() => world?.stop());
  let world: ReturnType<typeof createWorld> | undefined;

  const t = dictionaries.es.chat.detective;
  const traced: Entry[] = [
    { id: "1", kind: "assistant", blocks: [TEXT_BLOCK], at: "2026-09-29T15:40:05Z", lang: "es", trace: TRACE } as Entry,
    { id: "2", kind: "assistant", blocks: [TEXT_BLOCK], at: "2026-09-29T15:41:05Z", lang: "es" },
    { id: "3", kind: "assistant", blocks: [TEXT_BLOCK], at: "2026-09-29T15:42:05Z", lang: "es", trace: TRACE_TOOL } as Entry,
  ];
  const panel = (props: Partial<TracePanelProps> = {}) =>
    renderToStaticMarkup(
      <TracePanel
        dict={dictionaries.es}
        turns={tracedTurns(traced)}
        selectedId={null}
        view="steps"
        pane="chat"
        onSelect={() => {}}
        onView={() => {}}
        onBack={() => {}}
        {...props}
      />,
    );

  test("a strip only with detective on, under each reply that has a trace; the panel's turn is marked", () => {
    const off = renderToStaticMarkup(<Transcript entries={traced} lang="es" />);
    expect(off).not.toContain("data-detective");
    const on = renderToStaticMarkup(<Transcript entries={traced} lang="es" detective traceSelectedId="3" />);
    expect(on.match(/data-detective/g)).toHaveLength(2);
    expect(on.match(/aria-current="true"/g)).toHaveLength(1);
    expect(on).toContain('aria-controls="dock-trace"');
    expect(on).toContain(t.open);
  });

  test("the strip is the turn's time and its bar, nothing else", () => {
    const html = renderToStaticMarkup(<TraceStrip dict={dictionaries.es} trace={TRACE_TOOL} selected={false} />);
    expect(html).toContain("<b>2.40 s</b>");
    expect(html).toContain("pb-trace-spark");
    expect(html).not.toContain("aria-current");
    expect(html.replace(/<[^>]+>/g, "").replace(t.open, "")).toBe("2.40 s");
  });

  test("the panel follows the newest turn: numbered tabs, the turn's numbers, a row per step, details folded", () => {
    const html = panel();
    expect(html).toContain('id="dock-trace"');
    expect(html).toContain(`aria-label="${t.toggle}"`);
    expect(html.match(/data-trace-turn=/g)).toHaveLength(2);
    expect(html).toMatch(/aria-checked="true" aria-label="Turno 3" data-trace-turn="3">3</);
    expect(html).toContain("<b>2.40 s</b><span>LLM 1.90 s</span><span>2530 tok</span><span>$0.00034</span>");
    expect(html).toContain(`<table class="pb-trace__total" aria-label="${t.conversationTotal}">`);
    expect(html).toContain(`rowSpan="2">${t.total}</th><td>2530 tok</td></tr><tr><td>$0.00034</td>`);
    expect(html.match(/data-trace-step=/g)).toHaveLength(2);
    expect(html).toContain('<code class="pb-trace-name">customer.match</code>');
    expect(html).toContain("INVALID_ARGUMENTS");
    expect(html).not.toContain("pb-trace-code");
    expect(html).toMatch(/aria-checked="true"[^>]*data-trace-view="steps"/);
  });

  test("only a step that went wrong carries a status", () => {
    const html = panel();
    expect(html.match(/class="pb-chip"/g)).toHaveLength(1);
    expect(html).toContain(`data-tone="danger">${t.status.error}<`);
  });

  test("a picked turn shows instead of the newest", () => {
    const html = panel({ selectedId: "1" });
    expect(html).toMatch(/aria-checked="true" aria-label="Turno 1" data-trace-turn="1"/);
    expect(html.match(/data-trace-step=/g)).toHaveLength(1);
  });

  test("the timeline opens on the LLM call: one line, the call it asked for, masked, the rest folded", () => {
    const html = panel({ view: "timeline" });
    expect(html).toMatch(/aria-checked="true"[^>]*data-trace-view="timeline"/);
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("pb-trace-wf__bar");
    expect(html).toContain("test-model · 2500 → 30 tok · $0.00034<");
    expect(html).not.toContain("openai/");
    expect(html).toContain('<mark class="pb-trace-ph">[DOC_1]</mark>');
    expect(html).toContain("<summary>Prompt (2)</summary>");
    expect(html).toContain(`<summary>${t.detail.tools.replace("{n}", "2")}</summary>`);
    expect(html).not.toContain("<details open");
  });

  test("the masking step is the masked text, placeholders marked", () => {
    const html = panel({ selectedId: "1", view: "timeline" });
    expect(html).toContain('<pre class="pb-trace-code">perdí mi tarjeta, soy <mark class="pb-trace-ph">[DOC_1]</mark></pre>');
    expect(html).not.toContain("pb-trace-detail__line");
  });

  test("with no traced turn yet the panel says so", () => {
    const html = panel({ turns: [] });
    expect(html).toContain(t.empty);
    expect(html).not.toContain("data-trace-turn");
  });

  const appWith = (stored: Record<string, string>) => {
    const store = new Map(Object.entries(stored));
    const env: AppEnv = {
      storage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => void store.set(key, value), removeItem: (key) => void store.delete(key) },
      root: null,
      navigatorLanguage: "es-CO",
    };
    return createActor(createAppMachine(env)).start();
  };

  const dock = (stored: Record<string, string> = {}) =>
    renderToStaticMarkup(
      <ActorsProvider actors={{ app: appWith(stored), chat: world!.actor }}>
        <ChatDock open onOpenChange={() => {}} />
      </ActorsProvider>,
    );

  test("no switch in the header where detective mode is off", async () => {
    world = createWorld();
    world.actor.send({ type: "CAPABILITIES.CHECK" });
    await world.settle();
    expect(dock()).not.toContain("data-detective-toggle");
  });

  test("where it is on, the header has the switch, pressed when the viewer turned it on", async () => {
    world = createWorld();
    world.script("getCapabilities", json({ detective: true }));
    world.actor.send({ type: "CAPABILITIES.CHECK" });
    await world.settle();
    const off = dock();
    expect(off).toContain("data-detective-toggle");
    expect(off).toContain('aria-pressed="false"');
    expect(off).toContain(`aria-label="${dictionaries.es.chat.detective.toggle}"`);
    expect(off).toContain(`title="${dictionaries.es.chat.detective.toggle}"`);
    expect(off).toContain("pb-btn--secondary pb-btn--icon pb-btn--sm pb-trace-toggle");
    expect(off).toContain("pb-ico--search");
    expect(off).not.toContain('id="dock-trace"');
    const on = dock({ "pb-detective": "on" });
    expect(on).toContain('aria-pressed="true"');
    expect(on).toContain('id="dock-trace"');
    expect(on).toContain(dictionaries.es.chat.detective.empty);
  });

  test("the panel stays out of a closed dock", async () => {
    world = createWorld();
    world.script("getCapabilities", json({ detective: true }));
    world.actor.send({ type: "CAPABILITIES.CHECK" });
    await world.settle();
    const html = renderToStaticMarkup(
      <ActorsProvider actors={{ app: appWith({ "pb-detective": "on" }), chat: world.actor }}>
        <ChatDock open={false} onOpenChange={() => {}} />
      </ActorsProvider>,
    );
    expect(html).not.toContain('id="dock-trace"');
  });
});
