import { describe, expect, test } from "bun:test";
import { createApiClient, DEFAULT_RETRY_AFTER_SECONDS, parseRetryAfter } from "../src/api/client";
import { CONVERSATION_ID, CREATE_RESPONSE, FEEDBACK_RESPONSE, inboxResponse, SEND_RESPONSE, TRANSCRIPT } from "./fixtures";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Response.json(body, { status, headers });

function client(answer: Response | "network") {
  const seen: Array<{ url: string; init: RequestInit | undefined }> = [];
  const fake = (async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), init });
    if (answer === "network") throw new TypeError("Failed to fetch");
    return answer.clone();
  }) as typeof fetch;
  return { api: createApiClient({ fetch: fake, now: () => Date.parse("2026-09-29T15:40:00Z") }), seen };
}

describe("parseRetryAfter", () => {
  const now = Date.parse("2026-09-29T15:40:00Z");
  test("seconds", () => {
    expect(parseRetryAfter("287", now)).toBe(287);
    expect(parseRetryAfter(" 5 ", now)).toBe(5);
  });
  test("an HTTP date", () => {
    expect(parseRetryAfter("Tue, 29 Sep 2026 15:41:30 GMT", now)).toBe(90);
  });
  test("zero, a past date and nonsense do not disable the composer for nothing or forever", () => {
    expect(parseRetryAfter("0", now)).toBe(1);
    expect(parseRetryAfter("Tue, 29 Sep 2026 15:00:00 GMT", now)).toBe(1);
    expect(parseRetryAfter("soon", now)).toBe(DEFAULT_RETRY_AFTER_SECONDS);
    expect(parseRetryAfter("", now)).toBe(DEFAULT_RETRY_AFTER_SECONDS);
    expect(parseRetryAfter(null, now)).toBe(DEFAULT_RETRY_AFTER_SECONDS);
    expect(parseRetryAfter("99999999999", now)).toBe(86_400);
  });
});

describe("the four routes", () => {
  test("createConversation posts {lang} to /api/conversations", async () => {
    const { api, seen } = client(json(CREATE_RESPONSE, 201));
    const result = await api.createConversation({ lang: "pt" });
    expect(result).toEqual({ ok: true, data: CREATE_RESPONSE });
    expect(seen[0]!.url).toBe("/api/conversations");
    expect(seen[0]!.init).toMatchObject({ method: "POST", body: '{"lang":"pt"}', cache: "no-store" });
  });

  test("sendMessage posts to the id's path", async () => {
    const { api, seen } = client(json(SEND_RESPONSE));
    const result = await api.sendMessage(CONVERSATION_ID, { text: "hola", lang: "es", client_message_id: "msg_0123456789" });
    expect(result.ok).toBe(true);
    expect(seen[0]!.url).toBe(`/api/conversations/${CONVERSATION_ID}/messages`);
    expect(JSON.parse(seen[0]!.init!.body as string)).toEqual({ text: "hola", lang: "es", client_message_id: "msg_0123456789" });
  });

  test("getTranscript and getInbox are GETs without a body", async () => {
    const transcript = client(json(TRANSCRIPT));
    expect((await transcript.api.getTranscript(CONVERSATION_ID)).ok).toBe(true);
    expect(transcript.seen[0]!.url).toBe(`/api/conversations/${CONVERSATION_ID}`);
    expect(transcript.seen[0]!.init).toMatchObject({ method: "GET", body: undefined, cache: "no-store" });

    const inbox = client(json(inboxResponse("2026-09-29T15:45:00Z")));
    expect((await inbox.api.getInbox(CONVERSATION_ID)).ok).toBe(true);
    expect(inbox.seen[0]!.url).toBe(`/api/conversations/${CONVERSATION_ID}/inbox`);
  });

  test("sendFeedback posts the answer to the conversation's feedback route", async () => {
    const { api, seen } = client(json(FEEDBACK_RESPONSE));
    const result = await api.sendFeedback(CONVERSATION_ID, { helpful: false });
    expect(result).toEqual({ ok: true, data: FEEDBACK_RESPONSE });
    expect(seen[0]!.url).toBe(`/api/conversations/${CONVERSATION_ID}/feedback`);
    expect(seen[0]!.init).toMatchObject({ method: "POST", cache: "no-store" });
    expect(JSON.parse(seen[0]!.init!.body as string)).toEqual({ helpful: false });
  });

  test("a feedback refusal (409) is unavailable, like any other answer the client cannot use", async () => {
    const { api } = client(json({ detail: "already_answered" }, 409));
    expect(await api.sendFeedback(CONVERSATION_ID, { helpful: true })).toEqual({ ok: false, kind: "unavailable" });
  });

  test("the id is encoded into the path", async () => {
    const { api, seen } = client(json(TRANSCRIPT));
    await api.getTranscript("a b/c");
    expect(seen[0]!.url).toBe("/api/conversations/a%20b%2Fc");
  });

  test("blocks come back raw: a type this build does not know is still there", async () => {
    const { api } = client(json({ conversation_id: CONVERSATION_ID, blocks: [{ type: "carousel", items: [] }] }));
    const result = await api.sendMessage(CONVERSATION_ID, { text: "hola" });
    expect(result).toEqual({ ok: true, data: { conversation_id: CONVERSATION_ID, blocks: [{ type: "carousel", items: [] }] } });
  });
});

describe("failures come back as values", () => {
  test("429 carries the wait", async () => {
    const { api } = client(json({ detail: "x" }, 429, { "Retry-After": "120" }));
    expect(await api.createConversation({})).toEqual({ ok: false, kind: "rate_limited", retryAfterSeconds: 120 });
  });
  test("404 is not_found", async () => {
    const { api } = client(json({ detail: "Conversation not found" }, 404));
    expect(await api.sendMessage(CONVERSATION_ID, { text: "hola" })).toEqual({ ok: false, kind: "not_found" });
  });
  test("503, 409, 500, a body outside the contract, not JSON, and no network are all unavailable", async () => {
    const unavailable = { ok: false as const, kind: "unavailable" as const };
    for (const answer of [
      json({ detail: "replay_miss" }, 503),
      json({ detail: "busy" }, 409),
      json({ detail: "boom" }, 500),
      json({ nope: 1 }, 200),
      json(CREATE_RESPONSE, 200),
      new Response("<html>", { status: 200 }),
      "network" as const,
    ]) {
      const { api } = client(answer);
      expect(await api.sendMessage(CONVERSATION_ID, { text: "hola" })).toEqual(unavailable);
    }
  });
  test("a transcript without the takeover object is unavailable, not half a transcript", async () => {
    const { takeover: _takeover, ...without } = TRANSCRIPT;
    const { api } = client(json(without));
    expect(await api.getTranscript(CONVERSATION_ID)).toEqual({ ok: false, kind: "unavailable" });
  });
});
