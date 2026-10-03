import { afterEach, describe, expect, test } from "bun:test";
import { selectChip, selectSendDisabled, selectTyping } from "../src/machines/chat.machine";
import {
  CARD_BLOCK_RECEIPT,
  CONVERSATION_ID,
  HANDOFF_BLOCK,
  INBOX_CODE,
  inboxResponse,
  OTP_SEND_RECEIPT,
  OTP_VERIFY_RECEIPT,
  SEND_RESPONSE,
  TEXT_BLOCK,
  TRANSCRIPT,
  UNKNOWN_BLOCK,
} from "./fixtures";
import { createWorld, json, START } from "./world";

let world = createWorld();
afterEach(() => world.stop());
const fresh = (options?: Parameters<typeof createWorld>[0]) => {
  world.stop();
  world = createWorld(options);
  return world;
};

const turn = (...blocks: unknown[]) => json({ conversation_id: CONVERSATION_ID, blocks });
const takeoverTranscript = (...agent: Array<[string, string]>) =>
  json({
    ...TRANSCRIPT,
    messages: [
      ...TRANSCRIPT.messages,
      ...agent.map(([content, created_at]) => ({ role: "agent", content, blocks: [], created_at })),
    ],
    takeover: { active: true, since: "2026-09-29T15:50:00Z" },
  });

describe("a conversation is created lazily", () => {
  test("nothing is requested until the first message", async () => {
    fresh();
    await world.tick();
    expect(world.calls).toHaveLength(0);
    expect(world.state).toBe("idle");
    expect(world.snapshot.context.conversationId).toBeNull();
  });

  test("the first message creates the conversation, then sends the turn", async () => {
    fresh();
    world.send("Perdí mi tarjeta", "pt");
    expect(world.state).toBe("creating");
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.callsTo("createConversation")).toHaveLength(1);
    expect(world.callsTo("createConversation")[0]!.body).toEqual({ lang: "pt" });
    const sent = world.callsTo("sendMessage")[0]!;
    expect(sent.path).toBe(`/api/conversations/${CONVERSATION_ID}/messages`);
    expect(sent.body).toEqual({ text: "Perdí mi tarjeta", lang: "pt", client_message_id: "msg_test00000001" });
    expect(world.snapshot.context.conversationId).toBe(CONVERSATION_ID);
    expect(world.snapshot.context.entries.map((e) => e.kind)).toEqual(["customer", "assistant"]);
    expect(world.snapshot.context.pending).toBeNull();
  });

  test("the market goes with the conversation's creation, never with a turn", async () => {
    fresh();
    world.send("Perdí mi tarjeta", "es", "es-MX");
    await world.settle();
    expect(world.callsTo("createConversation")[0]!.body).toEqual({ lang: "es", locale: "es-MX" });
    world.send("otra vez", "es", "es-AR");
    await world.settle();
    expect(world.callsTo("createConversation")).toHaveLength(1);
    for (const call of world.callsTo("sendMessage")) expect(call.body).not.toHaveProperty("locale");
  });

  test("a market of another language than the message is left out", async () => {
    fresh();
    world.send("Perdi meu cartão", "pt", "es-CO");
    await world.settle();
    expect(world.callsTo("createConversation")[0]!.body).toEqual({ lang: "pt" });
  });

  test("the second message reuses the conversation and sends its own language", async () => {
    fresh();
    world.send("hola", "es");
    await world.settle();
    world.send("hello", "en");
    await world.settle();
    expect(world.callsTo("createConversation")).toHaveLength(1);
    const bodies = world.callsTo("sendMessage").map((call) => call.body);
    expect(bodies).toEqual([
      { text: "hola", lang: "es", client_message_id: "msg_test00000001" },
      { text: "hello", lang: "en", client_message_id: "msg_test00000002" },
    ]);
  });

  test("an empty message, or one over 2000 characters, is ignored", async () => {
    fresh();
    world.send("   ");
    world.send("x".repeat(2001));
    await world.tick();
    expect(world.state).toBe("idle");
    expect(world.calls).toHaveLength(0);
    world.send("x".repeat(2000));
    await world.settle();
    expect(world.callsTo("sendMessage")).toHaveLength(1);
  });

  test("a message is not accepted while another is in flight", async () => {
    fresh();
    world.send("uno");
    world.send("dos");
    await world.settle();
    expect(world.callsTo("sendMessage")).toHaveLength(1);
    expect(world.snapshot.context.entries.filter((e) => e.kind === "customer")).toHaveLength(1);
  });

  test("the typing indicator and the disabled composer follow the request", async () => {
    fresh();
    expect(selectTyping(world.snapshot)).toBe(false);
    world.send("hola");
    expect(selectTyping(world.snapshot)).toBe(true);
    expect(selectSendDisabled(world.snapshot)).toBe(true);
    await world.settle();
    expect(selectTyping(world.snapshot)).toBe(false);
    expect(selectSendDisabled(world.snapshot)).toBe(false);
  });
});

describe("after every completed turn: the transcript and the inbox, once", () => {
  test("one read of each per turn", async () => {
    fresh();
    world.send("uno");
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(1);
    expect(world.callsTo("getInbox")).toHaveLength(1);
    world.send("dos");
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(2);
    expect(world.callsTo("getInbox")).toHaveLength(2);
    expect(world.callsTo("getTranscript")[0]!.path).toBe(`/api/conversations/${CONVERSATION_ID}`);
    expect(world.callsTo("getInbox")[0]!.path).toBe(`/api/conversations/${CONVERSATION_ID}/inbox`);
  });

  test("nothing is polled without a takeover, however long the wait", async () => {
    fresh();
    world.send("uno");
    await world.settle();
    world.advance(60_000);
    await world.tick();
    expect(world.callsTo("getTranscript")).toHaveLength(1);
  });

  test("a failed read of either changes nothing and is not an error", async () => {
    fresh();
    world.script("getTranscript", "network");
    world.script("getInbox", json({ detail: "The inbox is temporarily unavailable" }, 503));
    world.send("uno");
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.snapshot.context.takeover.active).toBe(false);
    expect(world.snapshot.context.inbox).toBeNull();
  });
});

describe("failures", () => {
  test("503 on the turn: unavailable, the message is marked, retry resends the same client_message_id", async () => {
    fresh();
    world.script("sendMessage", json({ detail: "replay_miss" }, 503), json(SEND_RESPONSE));
    world.send("Perdí mi tarjeta");
    await world.settle();
    expect(world.state).toBe("unavailable");
    expect(world.snapshot.context.entries.map((e) => e.kind === "customer" && e.status)).toEqual(["failed"]);
    expect(world.snapshot.context.pending?.clientMessageId).toBe("msg_test00000001");
    expect(world.callsTo("getTranscript")).toHaveLength(0);

    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
    const sends = world.callsTo("sendMessage");
    expect(sends).toHaveLength(2);
    expect(sends[1]!.body).toEqual(sends[0]!.body);
    expect((sends[1]!.body as { client_message_id: string }).client_message_id).toBe("msg_test00000001");
    expect(world.callsTo("createConversation")).toHaveLength(1);
    const entries = world.snapshot.context.entries;
    expect(entries.map((e) => e.kind)).toEqual(["customer", "assistant"]);
    expect(entries[0]).toMatchObject({ status: "sent" });
  });

  test("503 when the conversation is created: retry creates it again and sends under the same id", async () => {
    fresh();
    world.script("createConversation", json({ detail: "Conversations are temporarily unavailable" }, 503), json({ conversation_id: CONVERSATION_ID, language: "es" }, 201));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("unavailable");
    expect(world.snapshot.context.conversationId).toBeNull();
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.callsTo("createConversation")).toHaveLength(2);
    expect(world.callsTo("sendMessage")).toHaveLength(1);
    expect((world.callsTo("sendMessage")[0]!.body as { client_message_id: string }).client_message_id).toBe("msg_test00000001");
  });

  test("a retried creation keeps the market of the message", async () => {
    fresh();
    world.script("createConversation", json({ detail: "Conversations are temporarily unavailable" }, 503), json({ conversation_id: CONVERSATION_ID, language: "es" }, 201));
    world.send("hola", "es", "es-CO");
    await world.settle();
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.callsTo("createConversation").map((call) => call.body)).toEqual([
      { lang: "es", locale: "es-CO" },
      { lang: "es", locale: "es-CO" },
    ]);
  });

  test("a network failure is treated like a 503", async () => {
    fresh();
    world.script("sendMessage", "network", json(SEND_RESPONSE));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("unavailable");
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
  });

  test("an answer outside the contract, a 409 and a 502 are treated like a 503", async () => {
    fresh();
    world.script("sendMessage", json({ nope: true }), json({ detail: "A turn is already in progress" }, 409), json({ detail: "x" }, 502), json(SEND_RESPONSE));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("unavailable");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      world.actor.send({ type: "RETRY" });
      await world.settle();
      expect(world.state).toBe("unavailable");
    }
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
  });

  test("a new message while unavailable is a new message: it gets its own id", async () => {
    fresh();
    world.script("sendMessage", json({ detail: "replay_miss" }, 503), json(SEND_RESPONSE));
    world.send("primero");
    await world.settle();
    world.send("segundo");
    await world.settle();
    expect(world.state).toBe("ready");
    const ids = world.callsTo("sendMessage").map((call) => (call.body as { client_message_id: string }).client_message_id);
    expect(ids).toEqual(["msg_test00000001", "msg_test00000002"]);
    const customers = world.snapshot.context.entries.filter((e) => e.kind === "customer");
    expect(customers.map((e) => e.kind === "customer" && e.status)).toEqual(["failed", "sent"]);
  });
});

describe("rate limit", () => {
  test("429 on creation: the wait comes from Retry-After, sending is off until then, then the message can be retried", async () => {
    fresh();
    world.script("createConversation", json({ detail: "Too many conversations" }, 429, { "Retry-After": "120" }), json({ conversation_id: CONVERSATION_ID, language: "es" }, 201));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("rateLimited");
    expect(world.snapshot.context.retryUntil).toBe(START + 120_000);
    expect(selectSendDisabled(world.snapshot)).toBe(true);

    world.send("otra vez");
    world.actor.send({ type: "RETRY" });
    await world.tick();
    expect(world.state).toBe("rateLimited");
    expect(world.callsTo("createConversation")).toHaveLength(1);

    world.advance(119_999);
    await world.tick();
    expect(world.state).toBe("rateLimited");
    world.advance(1);
    expect(world.state).toBe("retryable");
    expect(selectSendDisabled(world.snapshot)).toBe(false);

    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.callsTo("createConversation")).toHaveLength(2);
    expect((world.callsTo("sendMessage")[0]!.body as { client_message_id: string }).client_message_id).toBe("msg_test00000001");
  });

  test("without a readable Retry-After the wait is a minute", async () => {
    fresh();
    world.script("createConversation", json({ detail: "Too many" }, 429), json({ conversation_id: CONVERSATION_ID, language: "es" }, 201));
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.retryUntil).toBe(START + 60_000);
  });

  test("Retry-After as an HTTP date", async () => {
    fresh();
    world.script("createConversation", json({ detail: "Too many" }, 429, { "Retry-After": new Date(START + 90_000).toUTCString() }));
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.retryUntil).toBe(START + 90_000);
  });

  test("429 on a turn works the same way", async () => {
    fresh();
    world.script("sendMessage", json({ detail: "slow down" }, 429, { "Retry-After": "30" }), json(SEND_RESPONSE));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("rateLimited");
    expect(world.callsTo("createConversation")).toHaveLength(1);
    world.advance(30_000);
    expect(world.state).toBe("retryable");
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.callsTo("createConversation")).toHaveLength(1);
  });
});

describe("a conversation that expired", () => {
  test("404 on a turn: gone; starting over opens a new conversation with the message that was not sent", async () => {
    fresh();
    world.send("uno");
    await world.settle();
    world.script("sendMessage", json({ detail: "Conversation not found" }, 404), json(SEND_RESPONSE));
    world.script("createConversation", json({ conversation_id: "conv_ffffffffffffffffffffffffffffffff", language: "es" }, 201));
    world.send("dos");
    await world.settle();
    expect(world.state).toBe("gone");
    expect(selectSendDisabled(world.snapshot)).toBe(true);

    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.callsTo("createConversation")).toHaveLength(2);
    expect(world.snapshot.context.conversationId).toBe("conv_ffffffffffffffffffffffffffffffff");
    const texts = world.snapshot.context.entries.flatMap((e) => (e.kind === "customer" ? [e.text] : []));
    expect(texts).toEqual(["dos"]);
    expect((world.callsTo("sendMessage").at(-1)!.body as { text: string }).text).toBe("dos");
  });
});

describe("takeover", () => {
  test("the transcript after a turn detects it: the status line, the agent's messages, the chip", async () => {
    fresh();
    world.script("getTranscript", takeoverTranscript(["Hola, soy del equipo de Disputas.", "2026-09-29T15:50:05Z"]));
    world.send("hola");
    await world.settle();
    const { entries, takeover } = world.snapshot.context;
    expect(takeover).toEqual({ active: true, since: "2026-09-29T15:50:00Z" });
    expect(entries.map((e) => e.kind)).toEqual(["customer", "assistant", "system", "agent"]);
    expect(entries[2]).toMatchObject({ kind: "system", code: "takeover" });
    expect(entries[3]).toMatchObject({ kind: "agent", text: "Hola, soy del equipo de Disputas." });
    expect(selectChip(world.snapshot)).toBe("handed-off");
    expect(selectTyping(world.snapshot)).toBe(false);
  });

  test("the transcript is polled every 2 s and a new agent message joins once", async () => {
    fresh();
    world.script("getTranscript", takeoverTranscript(["Hola", "2026-09-29T15:50:05Z"]));
    world.send("hola");
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(1);

    world.advance(1_999);
    await world.tick();
    expect(world.callsTo("getTranscript")).toHaveLength(1);
    world.script("getTranscript", takeoverTranscript(["Hola", "2026-09-29T15:50:05Z"], ["Ya revisé tu caso.", "2026-09-29T15:50:30Z"]));
    world.advance(1);
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(2);
    world.advance(2_000);
    await world.settle();
    world.advance(2_000);
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(4);
    const agentTexts = world.snapshot.context.entries.flatMap((e) => (e.kind === "agent" ? [e.text] : []));
    expect(agentTexts).toEqual(["Hola", "Ya revisé tu caso."]);
    expect(world.snapshot.context.entries.filter((e) => e.kind === "system")).toHaveLength(1);
  });

  test("a message sent during a takeover comes back with no blocks: not an error, no follow-up reads", async () => {
    fresh();
    world.script("getTranscript", takeoverTranscript());
    world.send("hola");
    await world.settle();
    const readsBefore = world.callsTo("getTranscript").length;
    const inboxBefore = world.callsTo("getInbox").length;
    world.script("sendMessage", json({ conversation_id: CONVERSATION_ID, blocks: [] }));
    world.send("¿me ayudas?");
    await world.settle();
    expect(world.state).toBe("ready");
    expect(world.snapshot.context.entries.at(-1)).toMatchObject({ kind: "customer", status: "sent" });
    expect(world.snapshot.context.entries.filter((e) => e.kind === "assistant")).toHaveLength(1);
    expect(world.callsTo("getTranscript")).toHaveLength(readsBefore);
    expect(world.callsTo("getInbox")).toHaveLength(inboxBefore);
  });

  test("polling stops while the tab is hidden and resumes, with a read at once, when it is visible", async () => {
    fresh();
    world.script("getTranscript", takeoverTranscript());
    world.send("hola");
    await world.settle();
    world.actor.send({ type: "HIDDEN" });
    world.advance(10_000);
    await world.tick();
    expect(world.callsTo("getTranscript")).toHaveLength(1);
    world.actor.send({ type: "VISIBLE" });
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(2);
    world.advance(2_000);
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(3);
  });

  test("a page that starts hidden does not poll until it is visible", async () => {
    fresh({ visible: false });
    world.script("getTranscript", takeoverTranscript());
    world.send("hola");
    await world.settle();
    world.advance(20_000);
    await world.tick();
    expect(world.callsTo("getTranscript")).toHaveLength(1);
    world.actor.send({ type: "VISIBLE" });
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(2);
  });

  test("a failed poll is skipped and the next one goes on", async () => {
    fresh();
    world.script("getTranscript", takeoverTranscript(), "network", takeoverTranscript(["De vuelta", "2026-09-29T15:51:00Z"]));
    world.send("hola");
    await world.settle();
    world.advance(2_000);
    await world.settle();
    expect(world.callsTo("getTranscript")).toHaveLength(2);
    world.advance(2_000);
    await world.settle();
    expect(world.snapshot.context.entries.some((e) => e.kind === "agent" && e.text === "De vuelta")).toBe(true);
  });

  test("the agent's identity never reaches the log even if the API sent one", async () => {
    fresh();
    world.script("getTranscript", json({ ...TRANSCRIPT, takeover: { active: true, since: "2026-09-29T15:50:00Z", agent_ref: "marta@patternblue.example" } }));
    world.send("hola");
    await world.settle();
    expect(JSON.stringify(world.snapshot.context)).not.toContain("marta@patternblue.example");
  });
});

describe("the OTP notice", () => {
  const withOtp = () => {
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_SEND_RECEIPT));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z")));
  };

  test("an unexpired message shows the notice; the code is not revealed and not in the log", async () => {
    fresh();
    withOtp();
    world.send("Perdí mi tarjeta");
    await world.settle();
    const { inbox, entries } = world.snapshot.context;
    expect(inbox?.message.destination_masked).toBe("d***@example.com");
    expect(inbox?.message.expires_at).toBe("2026-09-29T15:45:02Z");
    expect(inbox?.revealed).toBe(false);
    expect(JSON.stringify(entries)).not.toContain(INBOX_CODE);
  });

  test("the code is revealed only by an explicit action, and can be hidden again", async () => {
    fresh();
    withOtp();
    world.send("hola");
    await world.settle();
    world.actor.send({ type: "CODE.REVEAL" });
    expect(world.snapshot.context.inbox?.revealed).toBe(true);
    expect(JSON.stringify(world.snapshot.context.entries)).not.toContain(INBOX_CODE);
    world.actor.send({ type: "CODE.HIDE" });
    expect(world.snapshot.context.inbox?.revealed).toBe(false);
  });

  test("revealing survives the next turn's read of the same message", async () => {
    fresh();
    withOtp();
    world.send("hola");
    await world.settle();
    world.actor.send({ type: "CODE.REVEAL" });
    world.send("¿cuál era el código?");
    await world.settle();
    expect(world.snapshot.context.inbox?.revealed).toBe(true);
  });

  test("with no inbox message there is no notice, and revealing does nothing", async () => {
    fresh();
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.inbox).toBeNull();
    world.actor.send({ type: "CODE.REVEAL" });
    expect(world.snapshot.context.inbox).toBeNull();
  });

  test("a message that already expired is not shown", async () => {
    fresh();
    world.script("getInbox", json(inboxResponse("2026-09-29T15:39:59Z", "2026-09-29T15:34:59Z")));
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.inbox).toBeNull();
  });

  test("the notice is hidden at expiry, once, and the log says so", async () => {
    fresh();
    withOtp();
    world.send("hola");
    await world.settle();
    world.advance(301_999);
    await world.tick();
    expect(world.snapshot.context.inbox).not.toBeNull();
    world.advance(1);
    await world.tick();
    expect(world.snapshot.context.inbox).toBeNull();
    const system = world.snapshot.context.entries.filter((e) => e.kind === "system");
    expect(system).toEqual([expect.objectContaining({ code: "codeExpired" })]);
    world.actor.send({ type: "CODE.REVEAL" });
    expect(world.snapshot.context.inbox).toBeNull();
  });

  test("a successful verification hides the notice even though the inbox still holds the code", async () => {
    fresh();
    withOtp();
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.inbox).not.toBeNull();

    // The inbox keeps a used code until it expires: same answer as before, but a verification receipt came.
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_VERIFY_RECEIPT));
    world.send("482916");
    await world.settle();
    expect(world.snapshot.context.inbox).toBeNull();
    expect(world.snapshot.context.verifiedAt).toBe(OTP_VERIFY_RECEIPT.receipt.verified_at);
    expect(world.snapshot.context.entries.filter((e) => e.kind === "system")).toHaveLength(0);

    // A code sent after the verification is news again.
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_SEND_RECEIPT));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:49:02Z", "2026-09-29T15:44:02Z")));
    world.send("otro código");
    await world.settle();
    expect(world.snapshot.context.inbox?.message.expires_at).toBe("2026-09-29T15:49:02Z");
  });

  test("the notice goes with the verification even when the inbox cannot be read afterwards", async () => {
    fresh();
    withOtp();
    world.send("hola");
    await world.settle();
    expect(world.snapshot.context.inbox).not.toBeNull();
    world.script("getInbox", "network");
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_VERIFY_RECEIPT));
    world.send("482916");
    await world.settle();
    expect(world.snapshot.context.inbox).toBeNull();
  });

  test("a code delivered before the verification stays out of later reads", async () => {
    fresh();
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_VERIFY_RECEIPT));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z", "2026-09-29T15:40:02Z")));
    world.send("482916");
    await world.settle();
    expect(world.snapshot.context.inbox).toBeNull();
  });
});

describe("what the customer typed", () => {
  test("a code typed while a challenge is pending is masked in the log and sent as typed", async () => {
    fresh();
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_SEND_RECEIPT), turn(TEXT_BLOCK, OTP_VERIFY_RECEIPT));
    world.send("Perdí mi tarjeta");
    await world.settle();
    world.send("482916");
    await world.settle();
    const customers = world.snapshot.context.entries.flatMap((e) => (e.kind === "customer" ? [e.text] : []));
    expect(customers).toEqual(["Perdí mi tarjeta", "Código: ••••••"]);
    expect((world.callsTo("sendMessage")[1]!.body as { text: string }).text).toBe("482916");
    expect(JSON.stringify(world.snapshot.context.entries)).not.toContain("482916");
  });

  test("the code the inbox delivered is masked wherever it appears, in any language", async () => {
    fresh();
    world.script("sendMessage", turn(TEXT_BLOCK, OTP_SEND_RECEIPT), turn(TEXT_BLOCK));
    world.script("getInbox", json(inboxResponse("2026-09-29T15:45:02Z")));
    world.send("hola");
    await world.settle();
    world.send("meu código é 482 916, valeu", "pt");
    await world.settle();
    const last = world.snapshot.context.entries.filter((e) => e.kind === "customer").at(-1);
    expect(last).toMatchObject({ text: "meu código é ••••••, valeu" });
  });

  test("the pending message keeps the raw text only until the turn is accepted", async () => {
    fresh();
    world.script("sendMessage", json({ detail: "replay_miss" }, 503));
    world.send("mi número es 4111 1111 1111 1111");
    await world.settle();
    expect(world.snapshot.context.pending?.text).toBe("mi número es 4111 1111 1111 1111");
    expect(JSON.stringify(world.snapshot.context.entries)).not.toContain("4111 1111 1111 1111");
    expect(world.snapshot.context.entries[0]).toMatchObject({ text: "mi número es •••• 1111" });
    world.script("sendMessage", json(SEND_RESPONSE));
    world.actor.send({ type: "RETRY" });
    await world.settle();
    expect(world.snapshot.context.pending).toBeNull();
  });
});

describe("the header chip comes only from what the blocks prove", () => {
  test("none at the start, and none from text alone", async () => {
    fresh();
    expect(selectChip(world.snapshot)).toBeNull();
    world.script("sendMessage", turn({ type: "text", text: "Bloqueé tu tarjeta. Tu identidad está verificada. Te pasé con un agente." }));
    world.send("hola");
    await world.settle();
    expect(selectChip(world.snapshot)).toBeNull();
  });

  test("code sent, verified, card blocked, handed off: each receipt moves it", async () => {
    fresh();
    const steps: Array<[unknown[], string]> = [
      [[TEXT_BLOCK, OTP_SEND_RECEIPT], "otp-pending"],
      [[TEXT_BLOCK, OTP_VERIFY_RECEIPT], "verified"],
      [[TEXT_BLOCK, CARD_BLOCK_RECEIPT], "blocked"],
      [[TEXT_BLOCK, HANDOFF_BLOCK], "handed-off"],
    ];
    for (const [blocks, chip] of steps) {
      world.script("sendMessage", turn(...blocks));
      world.send("siguiente");
      await world.settle();
      expect(selectChip(world.snapshot)).toBe(chip as never);
    }
  });

  test("a block this build does not know proves nothing and shows nothing", async () => {
    fresh();
    world.script("sendMessage", turn(UNKNOWN_BLOCK));
    world.send("hola");
    await world.settle();
    expect(world.state).toBe("ready");
    expect(selectChip(world.snapshot)).toBeNull();
    expect(world.snapshot.context.entries.map((e) => e.kind)).toEqual(["customer"]);
  });
});
