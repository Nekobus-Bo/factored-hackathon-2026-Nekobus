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
import { TraceOpen, TracePanel, type TracePanelProps } from "../src/app/chat/TracePanel";
import { replyCount, tracedTurns } from "../src/app/chat/trace-model";
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
  SEND_RESPONSE,
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

  test("a list of transactions is a ledger: date, merchant and amount per row", () => {
    const text = "Estas son tus últimas transacciones:\n\n- 2 oct.: Local Artisan Bakery — 25.000 COP\n- 1 oct.: Falabella — 214.475,55 COP";
    const html = render([{ type: "text", text }]);
    expect(html).toContain('<span class="chat-text">Estas son tus últimas transacciones:</span><ul class="pb-ledger">');
    expect(html).toContain(
      '<li class="pb-ledger__row"><span class="pb-ledger__date">2 oct.</span><span class="pb-ledger__label"><span class="pb-ledger__name" title="Local Artisan Bakery">Local Artisan Bakery</span></span><span class="pb-ledger__amount">25.000 COP</span></li>',
    );
    expect(html.match(/pb-ledger__row/g)).toHaveLength(2);
  });

  test("a status after the amount is a note next to the merchant", () => {
    const html = render([{ type: "text", text: "- 21 sep: Uber Brasil — R$ 248,40 (liquidada)" }], "pt");
    expect(html).toContain('Uber Brasil</span><span class="pb-ledger__note">liquidada</span>');
    expect(html).toContain('<span class="pb-ledger__amount">R$ 248,40</span>');
  });

  test("an amount in a sentence stays on one line", () => {
    const html = render([{ type: "text", text: "Tu saldo disponible es 1.234.567,89 COP." }]);
    expect(html).toContain('Tu saldo disponible es <span class="pb-amount">1.234.567,89 COP</span>.');
  });

  test("a ledger row is still escaped and never shows a full card number", () => {
    const html = render([{ type: "text", text: "- 2 oct.: <b>Tienda</b> 4111 1111 1111 1111 — 25.000 COP" }]);
    expect(html).not.toContain("<b>");
    expect(html).not.toContain("4111");
    expect(html).toContain("&lt;b&gt;Tienda&lt;/b&gt; •••• 1111");
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

  test("the brand in the bar and the footer is two parts, with the text unchanged: \"Pattern\" in the ink, \"Blue\" in the brand blue", () => {
    const html = page("es");
    const nav = html.slice(html.indexOf('class="pb-nav__brand"'), html.indexOf("</a>", html.indexOf('class="pb-nav__brand"')));
    expect(nav).toContain('<span class="pb-wordmark__ink">Pattern</span> <span class="pb-wordmark__blue">Blue</span>');
    expect(nav.replace(/<[^>]+>/g, "")).toContain("Pattern Blue");
    // the accessible name does not change, and the text is not typed in capitals (the stylesheet does that)
    expect(html).toContain('class="pb-nav__brand" href="#top" aria-label="Pattern Blue, inicio"');
    expect(html).not.toContain("PATTERN BLUE");
    const footer = html.slice(html.indexOf('class="pb-footer__wordmark"'), html.indexOf("</span></span>", html.indexOf('class="pb-footer__wordmark"')) + "</span>".length);
    expect(footer).toContain('<span class="pb-wordmark__ink">Pattern</span> <span class="pb-wordmark__blue">Blue</span>');
    // the drawn card of the hero keeps its own text
    expect(html).toContain("pb-cardvis__brand");
  });

  test("the hero and the launcher open the chat, the navigation bar does not", () => {
    // the hero's button and the launcher; the navigation bar has none
    const html = page("es");
    expect(html.match(/data-open-chat/g)).toHaveLength(1);
    expect(html).toContain('class="pb-launcher pb-launcher--label pb-dock__launcher"');
    const nav = html.slice(html.indexOf('class="pb-nav"'), html.indexOf("</header>"));
    expect(nav).not.toContain("data-open-chat");
    expect(nav).not.toContain("Abrir chat");
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

  /** The header tools of the page: [label, the radio group it names]. */
  const tools = (html: string) =>
    [...html.matchAll(/<div class="pb-navtool"><span class="pb-navtool__label" id="([^"]+)">([^<]*)<\/span><div class="pb-lang pb-lang--fill" role="radiogroup" aria-labelledby="\1">(.*?)<\/div><\/div>/g)].map((match) => ({
      label: match[2]!,
      group: match[3]!,
    }));

  test("each header tool is a group with a visible label and radios: language (ES, PT), and the theme as two radios", () => {
    const html = page("pt-BR");
    expect(tools(html).map((tool) => tool.label)).toEqual(["Idioma"]);
    expect(html.match(/role="radiogroup"/g)).toHaveLength(2);
    expect([...html.matchAll(/data-lang="(\w+)"/g)].map((match) => match[1])).toEqual(["es", "pt"]);
    expect(html).toMatch(/aria-checked="true"[^>]*data-lang="pt"/);
    // the theme: a sun and a moon, named, the one in force checked (the system's, until one is pinned); no square toggle
    // the theme has no visible label: its group names itself, inside its own tool (groups are told apart by room)
    const themeGroup = /<div class="pb-navtool"><div class="pb-lang pb-lang--fill" role="radiogroup" aria-label="Tema">(.*?)<\/div><\/div>/.exec(html);
    expect(themeGroup).not.toBeNull();
    expect(html).not.toMatch(/pb-navtool__label"[^>]*>Tema</);
    const theme = themeGroup![1]!;
    expect(theme).toContain('aria-label="Claro" title="Claro" data-theme-set="light"');
    expect(theme).toContain('aria-label="Escuro" title="Escuro" data-theme-set="dark"');
    expect(theme).toContain("pb-ico--sun");
    expect(theme).toContain("pb-ico--moon");
    expect(theme.match(/aria-checked="true"/g)).toHaveLength(1);
    expect(theme.match(/role="radio"/g)).toHaveLength(2);
    expect(html).not.toContain("pb-theme");
    expect(html).not.toMatch(/Mudar para o tema|Cambiar a tema/);
  });

  test("the theme names are in each language; the language and market labels are visible text, not only an aria-label", () => {
    expect(tools(page("es-CO")).map((tool) => tool.label)).toEqual(["Idioma", "País"]);
    expect(page("es-CO")).toContain('role="radiogroup" aria-label="Tema"');
    expect(page("es-CO")).toContain('aria-label="Oscuro"');
    for (const [lang, light, dark, theme] of [["es", "Claro", "Oscuro", "Tema"], ["pt", "Claro", "Escuro", "Tema"], ["en", "Light", "Dark", "Theme"]] as const) {
      const nav = dictionaries[lang].nav;
      expect([nav.themeLight, nav.themeDark, nav.themeLabel]).toEqual([light, dark, theme]);
    }
    expect([dictionaries.es.nav.marketLabel, dictionaries.pt.nav.marketLabel, dictionaries.en.nav.marketLabel]).toEqual(["País", "País", "Country"]);
  });

  test("Spanish adds the market tool, labelled País, between language and theme, with the browser's market checked", () => {
    const html = page("es-MX");
    expect(tools(html).map((tool) => tool.label)).toEqual(["Idioma", "País"]);
    expect(html.match(/role="radiogroup"/g)).toHaveLength(3);
    // the options are the country codes, each named by its country
    expect(tools(html)[1]!.group).toMatch(/>MX<.*>AR<.*>CO</);
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
        total={replyCount(traced)}
        selectedId={null}
        view="steps"
        onSelect={() => {}}
        onView={() => {}}
        {...props}
      />,
    );

  test("case 1: a control under each reply that has a trace, the icon and the time; none under the one without; no bar in the log", () => {
    const html = renderToStaticMarkup(<Transcript entries={traced} lang="es" detective />);
    expect(html.match(/data-trace-open/g)).toHaveLength(2);
    expect(html).toContain(
      `<button class="pb-action pb-trace-open" type="button" aria-label="Ver detective, 812 ms" data-trace-open="true"><i class="pb-ico pb-ico--detective" aria-hidden="true"></i><span>Ver detective <span class="pb-trace-open__time">· 812 ms</span></span><i class="pb-ico pb-ico--arrow" aria-hidden="true"></i></button>`,
    );
    expect(html).toContain('aria-label="Ver detective, 2.40 s"');
    expect(html.match(/class="pb-msg pb-msg--assistant"/g)).toHaveLength(3);
    // the reply of 15:41 came without a trace: the next thing after it is the next reply
    expect(html).toContain('15:41</span></div><div class="pb-msg pb-msg--assistant">');
    expect(html).not.toContain("pb-trace-spark");
    expect(html).not.toContain("pb-trace-strip");
    expect(renderToStaticMarkup(<Transcript entries={traced} lang="es" />)).not.toContain("data-trace-open");
  });

  test("the control says what it is: an action of the system with the icon, 'Ver detective', the time and an arrow; its name carries the time", () => {
    const html = renderToStaticMarkup(<TraceOpen dict={dictionaries.es} trace={TRACE_TOOL} />);
    expect(html).toMatch(/^<button class="pb-action pb-trace-open"/);
    expect(html.replace(/<[^>]+>/g, "")).toBe("Ver detective · 2.40 s");
    expect(html.indexOf("pb-ico--detective")).toBeLessThan(html.indexOf("<span>Ver detective"));
    // it does not say the whole chat is in detective mode: that is the name of the mode, kept for the title and the tab
    expect(html).not.toContain("Modo detective");
    expect(html.indexOf("pb-ico--arrow")).toBeGreaterThan(html.indexOf("2.40 s"));
    expect(html).toContain(`aria-label="${t.open.replace("{time}", "2.40 s")}"`);
    // label in name: the accessible name starts with the visible words
    expect(t.open.startsWith(t.view)).toBe(true);
    expect(dictionaries.pt.chat.detective.open.startsWith(dictionaries.pt.chat.detective.view)).toBe(true);
    expect(dictionaries.en.chat.detective.open.startsWith(dictionaries.en.chat.detective.view)).toBe(true);
    expect(html).not.toContain("aria-current");
    // in each language the words are the dictionary's
    expect(renderToStaticMarkup(<TraceOpen dict={dictionaries.pt} trace={TRACE_TOOL} />).replace(/<[^>]+>/g, "")).toBe("Ver detetive · 2.40 s");
    expect(renderToStaticMarkup(<TraceOpen dict={dictionaries.en} trace={TRACE_TOOL} />).replace(/<[^>]+>/g, "")).toBe("View detective · 2.40 s");
  });

  test("case 4: the stepper reads 'Turno n de total' among every reply, and its ends are disabled", () => {
    const first = panel({ selectedId: "1" });
    expect(first).toContain("<b aria-live=\"polite\">Turno 1 de 3</b>");
    // aria-disabled, not disabled: a disabled button drops the focus to the body and Escape stops answering
    expect(first).toMatch(/aria-label="Turno anterior" aria-disabled="true"/);
    expect(first).not.toMatch(/aria-label="Turno siguiente" aria-disabled/);
    expect(first).not.toMatch(/data-trace-(prev|next)[^>]*disabled=""/);
    const last = panel();
    expect(last).toContain("Turno 3 de 3");
    expect(last).toMatch(/aria-label="Turno siguiente" aria-disabled="true"/);
    expect(last).not.toMatch(/aria-label="Turno anterior" aria-disabled/);
    // one stepper, not a row of numbered squares
    expect(last).not.toContain("data-trace-turn");
    expect(last.match(/pb-trace__stepper/g)).toHaveLength(1);
  });

  test("case 9: the totals are two lines of label and data, in USD, and there is no table", () => {
    const html = panel();
    expect(html).toContain(
      '<dl class="pb-trace__totals"><dt>Turno</dt><dd><span>2.40 s</span><span>LLM 1.90 s</span><span>2530 tok</span><span>USD 0.00034</span></dd><dt>Conversación</dt><dd><span>2530 tok</span><span>USD 0.00034</span></dd></dl>',
    );
    expect(html).not.toContain("<table");
    expect(html).not.toContain("$0.");
  });

  test("the panel follows the newest turn: a row per step, details folded, one view selected", () => {
    const html = panel();
    expect(html).toContain('<div class="pb-trace pb-trace--inpanel">');
    expect(html).not.toContain("<aside");
    expect(html).not.toContain("dock-trace");
    expect(html.match(/data-trace-step=/g)).toHaveLength(2);
    expect(html).toContain('<code class="pb-trace-name">customer.match</code>');
    expect(html).toContain("INVALID_ARGUMENTS");
    expect(html).not.toContain("pb-trace-code");
    expect(html).toMatch(/aria-checked="true"[^>]*data-trace-view="steps"/);
  });

  test("case 10: a step's marker is a hexagon dot with its kind, and only a step that went wrong carries a status", () => {
    const html = panel();
    expect(html).toContain('<span class="pb-trace-dot" data-kind="llm_call"></span>');
    expect(html).toContain('<span class="pb-trace-dot" data-kind="tool_call"></span>');
    expect(html.match(/class="pb-chip"/g)).toHaveLength(1);
    expect(html).toContain(`data-tone="danger">${t.status.error}<`);
  });

  test("case 10: a step that was skipped has no chip either: the engine closes every turn with a skipped decisions step", () => {
    const skipped = { ...TRACE_TOOL.events[1]!, seq: 2, kind: "decisions" as const, label: "decisions", status: "skipped" as const, tool_call: null, note: "no decision points ran" };
    const withSkipped = [{ ...tracedTurns(traced)[1]!, trace: { ...TRACE_TOOL, events: [...TRACE_TOOL.events, skipped] } }];
    const html = panel({ turns: withSkipped });
    expect(html.match(/data-trace-step=/g)).toHaveLength(3);
    expect(html.match(/class="pb-chip"/g)).toHaveLength(1);
    expect(html).not.toContain(`>${t.status.skipped}<`);
    expect(html).toContain("no decision points ran");
    const timeline = panel({ turns: withSkipped, view: "timeline", selectedId: null });
    expect(timeline).not.toContain(`>${t.status.skipped}<`);
  });

  test("a picked turn shows instead of the newest", () => {
    const html = panel({ selectedId: "1" });
    expect(html).toContain("Turno 1 de 3");
    expect(html.match(/data-trace-step=/g)).toHaveLength(1);
  });

  test("the timeline opens on the LLM call: one line, the call it asked for, masked, the rest folded", () => {
    const html = panel({ view: "timeline" });
    expect(html).toMatch(/aria-checked="true"[^>]*data-trace-view="timeline"/);
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("pb-trace-wf__bar");
    expect(html).toContain("test-model · 2500 → 30 tok · USD 0.00034<");
    expect(html).not.toContain("openai/");
    expect(html).toContain('<mark class="pb-trace-ph">[DOC_1]</mark>');
    expect(html).toContain("<summary>Prompt (2)</summary>");
    expect(html).toContain(`<summary>${t.detail.tools.replace("{n}", "2")}</summary>`);
    expect(html).not.toContain("<details open");
  });

  test("case 14: the masking step is the masked text, placeholders marked", () => {
    const html = panel({ selectedId: "1", view: "timeline" });
    expect(html).toContain('<pre class="pb-trace-code">perdí mi tarjeta, soy <mark class="pb-trace-ph">[DOC_1]</mark></pre>');
    expect(html).not.toContain("pb-trace-detail__line");
  });

  test("case 12: with no traced turn yet the view says so, and has no stepper to move", () => {
    const html = panel({ turns: [], total: 2 });
    expect(html).toContain(t.empty);
    expect(html).not.toContain("pb-trace__stepper");
  });

  const appWith = (stored: Record<string, string> = {}) => {
    const store = new Map(Object.entries(stored));
    const env: AppEnv = {
      storage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => void store.set(key, value), removeItem: (key) => void store.delete(key) },
      root: null,
      navigatorLanguage: "es-CO",
    };
    return createActor(createAppMachine(env)).start();
  };

  /** A chat with three replies, the first and the last with a trace, in an environment that offers the mode or not. */
  async function chatWith(offered: boolean | "error") {
    const w = createWorld();
    world = w;
    w.script("getCapabilities", offered === "error" ? json({ detail: "boom" }, 500) : json({ detective: offered }));
    w.script("sendMessage", json({ ...SEND_RESPONSE, trace: TRACE }), json(SEND_RESPONSE), json({ ...SEND_RESPONSE, trace: TRACE_TOOL }));
    for (const text of ["uno", "dos", "tres"]) {
      w.send(text);
      await w.settle();
    }
    w.actor.send({ type: "CAPABILITIES.CHECK" });
    await w.settle();
    return w;
  }

  const dock = (props: { stored?: Record<string, string>; startInDetective?: boolean; startWithGuide?: boolean; wide?: boolean } = {}) =>
    renderToStaticMarkup(
      <ActorsProvider actors={{ app: appWith(props.stored), chat: world!.actor }}>
        <ChatDock open onOpenChange={() => {}} startInDetective={props.startInDetective} startWithGuide={props.startWithGuide} wide={props.wide} />
      </ActorsProvider>,
    );
  /** The demo panel's markup, or "" when the dock has none open. */
  const side = (html: string) => html.slice(html.indexOf('<aside class="pb-cut pb-side'), html.indexOf("</aside>"));
  /** Its opening tag: where `hidden` says whether it shows (the trace's own folded details carry `hidden` too). */
  const sideTag = (html: string) => /<aside[^>]*>/.exec(html)?.[0] ?? "";

  test("case 1: the mode is offered: the header has the hexagonal magnifier, one explicit action under each traced reply", async () => {
    await chatWith(true);
    const html = dock();
    // one header button with text, the demo menu, for the whole panel: not a button for the detective
    expect(html.match(/data-demo-toggle/g)).toHaveLength(1);
    expect(html).toContain("pb-btn pb-btn--secondary pb-btn--sm pb-demo-toggle");
    expect(html).toContain('aria-pressed="false" aria-controls="side-panel" data-demo-toggle');
    expect(html).toContain('<i class="pb-ico pb-ico--menu" aria-hidden="true"></i><span class="pb-demo-toggle__text">Menú demo</span>');
    expect(html).not.toContain("data-detective-toggle");
    expect(html).not.toContain("pb-trace-toggle");
    // not seen yet: the button calls for attention (the stylesheet does it, from the missing attribute)
    expect(html).not.toContain("data-seen");
    expect(html).not.toContain("pb-ico--search");
    expect(html.match(/data-trace-open/g)).toHaveLength(2);
    expect(html.match(/class="pb-action pb-trace-open"/g)).toHaveLength(2);
    expect(html).not.toContain("pb-trace--inpanel");
    // the panel beside the chat is the demo panel, closed
    expect(html).not.toContain("pb-dock__trace");
    expect(html.match(/<aside/g)).toHaveLength(1);
    expect(html).toContain('<aside class="pb-cut pb-side pb-dock__side"');
    expect(sideTag(html)).toMatch(/ hidden=""/);
  });

  test("case 2, wide: the detective tab of the panel beside the chat: the chat, its log and its composer stay in sight", async () => {
    await chatWith(true);
    const html = dock({ startInDetective: true, wide: true });
    const panel = side(html);
    expect(sideTag(html)).not.toMatch(/ hidden=""/);
    expect(panel).toContain("pb-trace pb-trace--inpanel");
    expect(panel).toContain("Turno 3 de 3");
    expect(panel).toMatch(/role="tab"[^>]*aria-selected="true"[^>]*data-side-tab="detective"/);
    expect(panel).toMatch(/data-side-tab="script"/);
    // not "Solo demo": that tag is the guide's
    expect(panel).not.toContain("Solo demo");
    // the chat is the chat: its title, its chip, its body and its composer, none hidden
    expect(html).toContain(`<section class="pb-chat pb-dock__panel" id="dock-panel" aria-label="${dictionaries.es.chat.panel}"`);
    expect(html).toMatch(/<div class="pb-chat__body">/);
    expect(html).toMatch(/<form class="pb-chat__composer">/);
    // the header button reads "pressed", is filled, and still says "Menú demo" (it is not a way back)
    expect(html).toContain("pb-btn pb-btn--primary pb-btn--sm pb-demo-toggle");
    expect(html).toContain('aria-label="Menú demo" title="Menú demo" aria-pressed="true"');
    // the panel is open: it has been seen, and the button stops for good
    expect(html).toContain('data-demo-toggle="true" data-seen="true"');
    expect(html).not.toContain(`aria-label="${t.back}"`);
    // the trace is in one place only
    expect(html.match(/pb-trace--inpanel/g)).toHaveLength(1);
    expect(html.match(/data-trace-open/g)).toHaveLength(2);
  });

  test("case 2, narrow: with no room for the panel the view takes the chat's place: its title, the way back, the log and the composer kept but hidden", async () => {
    await chatWith(true);
    const html = dock({ startInDetective: true, wide: false });
    expect(html).toContain(`<section class="pb-chat pb-dock__panel" id="dock-panel" aria-label="${t.toggle}"`);
    expect(html).toContain(`<i class="pb-ico pb-ico--detective" aria-hidden="true"></i> ${t.toggle}</span>`);
    // the same button, now the way back to the chat: icon only, filled, pressed
    expect(html).toContain("pb-btn pb-btn--primary pb-btn--sm pb-demo-toggle pb-btn--icon");
    expect(html).toContain(`aria-label="${t.back}" title="${t.back}"`);
    expect(html).toContain('<i class="pb-ico pb-ico--chat" aria-hidden="true"></i></button>');
    // a way back is not a toggle, and the panel it would control is hidden: no pressed state, no aria-controls
    const back = /<button[^>]*pb-demo-toggle[^>]*>/.exec(html)![0];
    expect(back).not.toContain("aria-pressed");
    expect(back).not.toContain("aria-controls");
    expect(html).toContain("pb-trace pb-trace--inpanel");
    expect(html).toContain("Turno 3 de 3");
    // still mounted, out of sight: the scroll and the draft survive
    expect(html).toMatch(/<div class="pb-chat__body" hidden="">/);
    expect(html).toMatch(/<form class="pb-chat__composer" hidden="">/);
    expect(html).toContain('role="log"');
    expect(html).toContain("<textarea");
    // the replies' controls are in the hidden log, intact
    expect(html.match(/data-trace-open/g)).toHaveLength(2);
    // the chat's state chip is not shown over the view
    expect(html).not.toContain("chat-head-chip");
    // the panel beside the chat is closed and empty: the trace is not drawn twice
    expect(sideTag(html)).toMatch(/ hidden=""/);
    expect(html.match(/pb-trace--inpanel/g)).toHaveLength(1);
  });

  test("case 3: with the panel closed, or open on a tab, the log and the composer are in sight", async () => {
    await chatWith(true);
    for (const html of [dock(), dock({ startInDetective: true }), dock({ startWithGuide: true })]) {
      expect(html).toMatch(/<div class="pb-chat__body">/);
      expect(html).toMatch(/<form class="pb-chat__composer">/);
    }
  });

  test("the panel has the two tabs, the guide first; the script tab shows the guide with its 'Solo demo' tag and no trace", async () => {
    await chatWith(true);
    const panel = side(dock({ startWithGuide: true, wide: true }));
    expect(panel).toContain('role="tablist"');
    expect(panel).toMatch(/aria-selected="true"[^>]*data-side-tab="script"/);
    expect(panel).toMatch(/aria-selected="false"[^>]*data-side-tab="detective"/);
    expect(panel.indexOf('data-side-tab="script"')).toBeLessThan(panel.indexOf('data-side-tab="detective"'));
    expect(panel).toContain(">Guion</button>");
    expect(panel).toContain(">Detective</button>");
    expect(panel).toContain("Solo demo");
    expect(panel).toContain("Elige un guion");
    expect(panel).not.toContain("pb-trace");
    // the tab that shows is the one that can be reached by the keyboard, and the panel is named by it
    expect(panel).toMatch(/aria-selected="true" aria-controls="side-panel-content" tabindex="0"/);
    expect(panel).toMatch(/role="tabpanel" aria-labelledby="side-tab-script"/);
  });

  test("case 6: where the environment does not offer the mode there is no button, no tab and no control, traces or not", async () => {
    for (const offered of [false, "error"] as const) {
      await chatWith(offered);
      expect(world!.snapshot.context.entries.filter((entry) => entry.kind === "assistant" && entry.trace)).toHaveLength(2);
      const html = dock({ startWithGuide: true, wide: true });
      // the demo menu is still there (the guide is in it); only the detective is gone
      expect(html).toContain("data-demo-toggle");
      expect(html).not.toContain("data-trace-open");
      expect(html).not.toContain("data-side-tab");
      expect(html).not.toContain('role="tablist"');
      // the panel is the guide alone
      expect(side(html)).toContain("Elige un guion");
      expect(side(html)).toContain("Solo demo");
      // with no room for the panel and no detective to show, there is nothing for the button to open: no button
      const narrow = dock({ wide: false });
      expect(narrow).not.toContain("data-demo-toggle");
      expect(narrow).toContain("data-close-chat");
      world!.stop();
    }
  });

  test("with no room for the panel the same button exists for the detective view only: it opens it in place of the chat", async () => {
    await chatWith(true);
    const html = dock({ wide: false });
    // with no room the panel is hidden: the button is a toggle for the view in place of the chat and controls nothing
    const toggle = /<button[^>]*pb-demo-toggle[^>]*>/.exec(html)![0];
    expect(toggle).toContain('aria-pressed="false" data-demo-toggle');
    expect(toggle).not.toContain("aria-controls");
    expect(html).toContain('<span class="pb-demo-toggle__text">Menú demo</span>');
    expect(html).not.toContain("pb-btn--icon pb-btn--sm pb-demo-toggle");
    expect(html).toMatch(/<div class="pb-chat__body">/);
  });

  test("case 7: the back office turned the mode off while the detective tab was open: beside the chat the panel is on the guide; with no room the chat is back, with its composer", async () => {
    await chatWith(false);
    const wide = dock({ startInDetective: true, wide: true });
    expect(wide).not.toContain("pb-trace--inpanel");
    expect(side(wide)).toContain("Elige un guion");
    expect(wide).not.toContain("data-side-tab");
    const narrow = dock({ startInDetective: true, wide: false });
    expect(narrow).not.toContain("pb-trace--inpanel");
    expect(narrow).toMatch(/<div class="pb-chat__body">/);
    expect(narrow).toMatch(/<form class="pb-chat__composer">/);
    expect(narrow).toContain(`aria-label="${dictionaries.es.chat.panel}"`);
  });

  test("case 8: a 'pb-detective=on' left by an earlier version does nothing: the visit opens with the panel closed", async () => {
    await chatWith(true);
    const html = dock({ stored: { "pb-detective": "on" } });
    expect(html).not.toContain("pb-trace--inpanel");
    expect(html).toContain('aria-pressed="false"');
    expect(html).toMatch(/<form class="pb-chat__composer">/);
  });

  test("the panel stays out of a closed dock", async () => {
    await chatWith(true);
    const html = renderToStaticMarkup(
      <ActorsProvider actors={{ app: appWith(), chat: world!.actor }}>
        <ChatDock open={false} onOpenChange={() => {}} startInDetective />
      </ActorsProvider>,
    );
    expect(html).toMatch(/<section class="pb-chat pb-dock__panel" id="dock-panel"[^>]*hidden="">/);
    expect(sideTag(html)).toMatch(/ hidden=""/);
    expect(html).not.toContain("pb-trace--inpanel");
  });
});
