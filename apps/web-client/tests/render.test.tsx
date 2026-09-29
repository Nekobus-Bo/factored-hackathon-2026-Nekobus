// Block rendering against fixtures, with react-dom/server: no DOM library. What the customer sees is the
// markup, so the rules of the chat are checked on the markup.

import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../src/app/actors";
import { Blocks } from "../src/app/chat/Blocks";
import { ChatDock } from "../src/app/chat/ChatDock";
import { OtpNotice } from "../src/app/chat/Notices";
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
} from "./fixtures";
import { createWorld, json } from "./world";

const AT = "2026-09-29T15:42:00Z";
const render = (blocks: unknown[], lang: "es" | "pt" | "en" = "es", turnLang: "es" | "pt" | "en" = lang) =>
  renderToStaticMarkup(<Blocks blocks={blocks as never} lang={lang} turnLang={turnLang} at={AT} />);

describe("text", () => {
  test("an assistant bubble with the sender and the time", () => {
    const html = render([TEXT_BLOCK]);
    expect(html).toContain("pb-msg pb-msg--assistant");
    expect(html).toContain("Asistente · ");
    expect(html).toContain("Hola, puedo ayudarte con tu tarjeta.");
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
  test("card.block: what was done, from which state to which, the masked card, the reference, the proof line", () => {
    const html = render([CARD_BLOCK_RECEIPT]);
    expect(html).toContain('data-tone="receipt"');
    expect(html).toContain("Comprobante · card.block");
    expect(html).toContain("Bloqueé tu tarjeta");
    expect(html).toContain('data-state="active"');
    expect(html).toContain('data-state="blocked"');
    expect(html).toContain("Activa");
    expect(html).toContain("Bloqueada");
    expect(html).toContain("•••• 4821");
    expect(html).not.toContain("****");
    expect(html).toContain("aud_20481abc");
    expect(html).toContain("Verificado contra la base de datos");
    // customer wording, never the raw enums
    expect(html).not.toMatch(/>ACTIVE<|>BLOCKED<|>OTP_PENDING</);
  });

  test("otp.send: the masked destination and the customer wording of both states", () => {
    const html = render([OTP_SEND_RECEIPT]);
    expect(html).toContain("Te envié un código");
    expect(html).toContain("Destino");
    expect(html).toContain("d***@example.com");
    expect(html).toContain("Identificado");
    expect(html).toContain("Código pendiente");
    expect(html).toContain('data-state="otp-pending"');
  });

  test("otp.verify: no internal challenge reference on screen", () => {
    const html = render([OTP_VERIFY_RECEIPT]);
    expect(html).toContain("Identidad verificada");
    expect(html).toContain('data-state="verified"');
    expect(html).not.toContain("chal_");
    expect(html).toContain("aud_20480abc");
  });

  test("in Portuguese and English, with the design system's wording", () => {
    const pt = render([CARD_BLOCK_RECEIPT], "pt");
    expect(pt).toContain("Comprovante · card.block");
    expect(pt).toContain("Bloqueei seu cartão");
    expect(pt).toContain("Ativo");
    expect(pt).toContain("Bloqueado");
    expect(pt).toContain("Verificado no banco de dados");
    const en = render([CARD_BLOCK_RECEIPT], "en");
    expect(en).toContain("Receipt · card.block");
    expect(en).toContain("I blocked your card");
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
});

describe("handoff, customer view", () => {
  const html = render([HANDOFF_BLOCK]);

  test("the department and the priority in words, the status, the position and the case reference", () => {
    expect(html).toContain('data-tone="handoff"');
    expect(html).toContain("Te pasé con un agente de Disputas");
    expect(html).toContain("Urgente");
    expect(html).toContain("En la fila");
    expect(html).toContain("2 en la fila");
    expect(html).toContain("hnd_abcd1234efgh");
    expect(html).toContain("El agente ya sabe");
    expect(html).toContain("Desde aquí el asistente deja de actuar");
    expect(html).not.toMatch(/>URGENT<|>DISPUTES<|>QUEUED</);
  });

  test("never the summary, the audit id or the receipt of the handoff", () => {
    for (const secret of [SECRET_FACT, SECRET_ACTION, SECRET_QUESTION, "verified_facts", "actions_taken", "otp_email", "aud_handoff-secret-audit", "handoff.create"]) {
      expect(html, secret).not.toContain(secret);
    }
  });

  test("a queue position that is not known is not guessed", () => {
    const withoutPosition = render([{ ...HANDOFF_BLOCK, queue_position: null }]);
    expect(withoutPosition).not.toContain("Posición");
    expect(withoutPosition).not.toContain("en la fila");
  });

  test("every department, priority and status has words in every language", () => {
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
  const html = renderToStaticMarkup(<Transcript entries={entries} lang="es" retryEntryId="7" onRetry={() => {}} />);

  test("customer, assistant, agent and system entries each in their own markup", () => {
    expect(html).toContain("pb-msg pb-msg--customer");
    expect(html).toContain("pb-msg pb-msg--assistant");
    expect(html).toContain("pb-msg pb-msg--agent");
    expect(html).toContain("Agente humano · ");
    expect(html).toContain('<div class="pb-sys" data-tone="joined">');
    expect(html).toContain("Un agente está atendiendo tu caso");
    expect(html).toContain("El código venció");
  });

  test("a customer's code is shown masked", () => {
    expect(html).toContain("Código: ••••••");
  });

  test("a message that was not sent says so and offers the retry", () => {
    expect(html).toContain('data-status="failed"');
    expect(html).toContain("No enviado");
    expect(html).toContain("Reintentar");
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

  test("the notice: masked destination, the countdown, and the code only once it is asked for", () => {
    const dict = dictionaries.es;
    const message = { channel: "email", destination_masked: "d***@example.com", code: INBOX_CODE, received_at: "2026-09-29T15:40:02Z", expires_at: "2026-09-29T15:45:02Z" };
    const now = Date.parse("2026-09-29T15:40:30Z");
    const closed = renderToStaticMarkup(<OtpNotice dict={dict} notice={{ message, revealed: false }} now={now} open={false} onToggle={() => {}} onReveal={() => {}} onHide={() => {}} />);
    expect(closed).toContain("Te llegó un correo con el código");
    expect(closed).toContain("d***@example.com");
    expect(closed).toContain('role="timer"');
    expect(closed).toContain("04:32");
    expect(closed).not.toContain(INBOX_CODE);
    expect(closed).not.toContain("pb-inbox");

    const hidden = renderToStaticMarkup(<OtpNotice dict={dict} notice={{ message, revealed: false }} now={now} open onToggle={() => {}} onReveal={() => {}} onHide={() => {}} />);
    expect(hidden).toContain("Bandeja simulada");
    expect(hidden).toContain("DEMO");
    expect(hidden).toContain("Entrega simulada para la demo");
    expect(hidden).toContain("Mostrar código");
    expect(hidden).toContain("Código oculto");
    expect(hidden).not.toContain(INBOX_CODE);
    expect(hidden).not.toMatch(/>4<|>8<|>2<|>9<|>1<|>6</);

    const shown = renderToStaticMarkup(<OtpNotice dict={dict} notice={{ message, revealed: true }} now={now} open onToggle={() => {}} onReveal={() => {}} onHide={() => {}} />);
    expect(shown).toContain("Código: 4 8 2 9 1 6");
    expect(shown).toContain("Ocultar código");
    for (const digit of INBOX_CODE) expect(shown).toContain(`>${digit}<`);
  });

  test("the countdown turns to the alert state in the last minute and never goes negative", () => {
    const dict = dictionaries.en;
    const message = { channel: "email", destination_masked: "d***@example.com", code: INBOX_CODE, received_at: "2026-09-29T15:40:00Z", expires_at: "2026-09-29T15:45:00Z" };
    const late = renderToStaticMarkup(<OtpNotice dict={dict} notice={{ message, revealed: false }} now={Date.parse("2026-09-29T15:44:30Z")} open onToggle={() => {}} onReveal={() => {}} onHide={() => {}} />);
    expect(late).toContain('data-state="abstained"');
    expect(late).toContain("00:30");
    const over = renderToStaticMarkup(<OtpNotice dict={dict} notice={{ message, revealed: false }} now={Date.parse("2026-09-29T15:50:00Z")} open onToggle={() => {}} onReveal={() => {}} onHide={() => {}} />);
    expect(over).toContain("00:00");
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
      ["es-CO", "Tu tarjeta", "datos sintéticos", "Solo demo"],
      ["pt-BR", "Seu cartão", "dados sintéticos", "Somente demo"],
      ["en-US", "Your card", "synthetic data", "Demo only"],
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

  test("the composition of the design system: the sections, in order, and the dock last", () => {
    const html = page("es");
    const order = ['class="pb-nav"', 'id="top"', 'id="funciones"', 'id="como-funciona"', 'id="s2"', 'id="ayuda"', 'class="pb-footer"', 'class="pb-dock"'];
    const positions = order.map((needle) => html.indexOf(needle));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
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

  test("the language and theme switches are radio groups, in the navbar and the footer", () => {
    const html = page("pt-BR");
    expect(html.match(/role="radiogroup"/g)).toHaveLength(4);
    expect(html).toContain('data-lang="pt"');
    expect(html).toMatch(/aria-checked="true"[^>]*data-lang="pt"/);
  });
});
