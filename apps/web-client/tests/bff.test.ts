// The BFF against a fake orchestrator: a real Bun.serve on an ephemeral port, and the real app server
// in front of it, so the address the BFF forwards comes from `server.requestIP` and not from a mock.

import { afterAll, afterEach, beforeAll, describe, expect, test } from "bun:test";
import { createBff } from "../src/api/bff";
import { startServer } from "../src/server";
import {
  CONVERSATION_ID,
  CREATE_RESPONSE,
  INBOX_CODE,
  inboxResponse,
  SEND_RESPONSE,
  SEND_RESPONSE_TRACED,
  TEXT_BLOCK,
  TRACE,
  TRANSCRIPT,
  UNKNOWN_BLOCK,
} from "./fixtures";

interface Recorded {
  method: string;
  path: string;
  headers: Headers;
  body: string;
}

function fakeOrchestrator() {
  const calls: Recorded[] = [];
  let handler: (req: Request) => Response | Promise<Response> = () => new Response("unset", { status: 500 });
  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      calls.push({
        method: req.method,
        path: new URL(req.url).pathname,
        headers: req.headers,
        body: await req.text(),
      });
      return handler(req);
    },
  });
  return {
    url: `http://127.0.0.1:${server.port}`,
    calls,
    respond(fn: typeof handler) {
      handler = fn;
    },
    reset() {
      calls.length = 0;
      handler = () => new Response("unset", { status: 500 });
    },
    stop: () => server.stop(true),
  };
}

const upstream = fakeOrchestrator();
const logs: string[] = [];
let app: ReturnType<typeof startServer>;
let base = "";

beforeAll(() => {
  app = startServer({
    port: 0,
    orchestratorUrl: upstream.url,
    log: (line) => logs.push(line),
    development: false,
  });
  base = `http://127.0.0.1:${app.port}`;
});
afterAll(async () => {
  await app.stop(true);
  await upstream.stop();
});
afterEach(() => {
  upstream.reset();
  logs.length = 0;
});

const jsonReply = (body: unknown, status = 200, headers: Record<string, string> = {}) => () =>
  Response.json(body, { status, headers });

const post = (path: string, body?: unknown, headers: Record<string, string> = {}) =>
  fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });

describe("forwarding", () => {
  test("POST /api/conversations forwards the body and answers 201 with the parsed value", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    const res = await post("/api/conversations", { lang: "pt" });
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual(CREATE_RESPONSE);
    expect(upstream.calls).toHaveLength(1);
    const call = upstream.calls[0]!;
    expect(call.method).toBe("POST");
    expect(call.path).toBe("/v1/conversations");
    expect(JSON.parse(call.body)).toEqual({ lang: "pt" });
  });

  test("the body of a conversation may be left out", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    const res = await post("/api/conversations");
    expect(res.status).toBe(201);
    const call = upstream.calls[0]!;
    expect(call.body).toBe("");
    expect(call.headers.get("content-type")).toBeNull();
  });

  test("POST .../messages forwards text, lang and client_message_id on the id's path", async () => {
    upstream.respond(jsonReply(SEND_RESPONSE));
    const body = { text: "Perdí mi tarjeta", lang: "es", client_message_id: "msg_0123456789abcdef" };
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, body);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(SEND_RESPONSE);
    const call = upstream.calls[0]!;
    expect(call.path).toBe(`/v1/conversations/${CONVERSATION_ID}/messages`);
    expect(JSON.parse(call.body)).toEqual(body);
  });

  test("a detective-mode trace goes through whole, nulls included (ADR-0019)", async () => {
    upstream.respond(jsonReply(SEND_RESPONSE_TRACED));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect(res.status).toBe(200);
    expect((await res.json()).trace).toEqual(TRACE);
  });

  test("a trace outside the contract is a body outside the contract: 503", async () => {
    upstream.respond(jsonReply({ ...SEND_RESPONSE, trace: { ...TRACE, events: [{ kind: "masking" }] } }));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect(res.status).toBe(503);
  });

  test("GET /api/capabilities forwards to /v1/capabilities", async () => {
    upstream.respond(jsonReply({ detective: true }));
    const res = await fetch(base + "/api/capabilities");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ detective: true });
    expect(upstream.calls[0]!.path).toBe("/v1/capabilities");
  });

  test("blocks stay raw on the wire: a block type this build does not know goes through untouched", async () => {
    const blocks = [TEXT_BLOCK, UNKNOWN_BLOCK];
    upstream.respond(jsonReply({ conversation_id: CONVERSATION_ID, blocks }));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect((await res.json()).blocks).toEqual(blocks);
  });

  test("an empty block list is a normal answer (takeover)", async () => {
    upstream.respond(jsonReply({ conversation_id: CONVERSATION_ID, blocks: [] }));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ conversation_id: CONVERSATION_ID, blocks: [] });
  });

  test("GET /api/conversations/:id forwards to the transcript and strips what the contract does not name", async () => {
    upstream.respond(
      jsonReply({
        ...TRANSCRIPT,
        takeover: { active: true, since: "2026-09-29T15:50:00Z", agent_ref: "agente@example.com" },
      }),
    );
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.takeover).toEqual({ active: true, since: "2026-09-29T15:50:00Z" });
    expect(JSON.stringify(body)).not.toContain("agente@example.com");
    expect(upstream.calls[0]).toMatchObject({ method: "GET", path: `/v1/conversations/${CONVERSATION_ID}` });
  });

  test("GET /api/conversations/:id/inbox forwards, never caches and never logs the code", async () => {
    upstream.respond(jsonReply(inboxResponse("2026-09-29T15:45:00Z")));
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}/inbox`);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect((await res.json()).messages[0].code).toBe(INBOX_CODE);
    expect(upstream.calls[0]!.path).toBe(`/v1/conversations/${CONVERSATION_ID}/inbox`);
    expect(logs.join("\n")).not.toContain(INBOX_CODE);
  });

  test("a GET does not forward the query string", async () => {
    upstream.respond(jsonReply(TRANSCRIPT));
    await fetch(`${base}/api/conversations/${CONVERSATION_ID}?debug=1&eval=true`);
    expect(upstream.calls[0]!.path).toBe(`/v1/conversations/${CONVERSATION_ID}`);
  });
});

describe("the headers the upstream sees", () => {
  test("X-Forwarded-For is the client address from server.requestIP", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    await post("/api/conversations", { lang: "es" });
    const seen = upstream.calls[0]!.headers.get("x-forwarded-for");
    expect(seen).toMatch(/^(127\.0\.0\.1|::1|::ffff:127\.0\.0\.1)$/);
  });

  test("a forged X-Forwarded-For and the browser's other headers are not forwarded", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    await post(
      "/api/conversations",
      { lang: "es" },
      {
        "X-Forwarded-For": "6.6.6.6, 7.7.7.7",
        Authorization: "Bearer stolen",
        Cookie: "session=abc",
        "X-Agent-Ref": "agente@example.com",
      },
    );
    const headers = upstream.calls[0]!.headers;
    expect(headers.get("x-forwarded-for")).not.toContain("6.6.6.6");
    expect(headers.get("x-forwarded-for")).not.toContain(",");
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("x-agent-ref")).toBeNull();
  });

  test("the address goes to the upstream as given when the BFF is called directly", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    const bff = createBff({ orchestratorUrl: upstream.url, log: () => {} });
    await bff.handle(new Request("http://web/api/conversations", { method: "POST" }), "203.0.113.9");
    expect(upstream.calls[0]!.headers.get("x-forwarded-for")).toBe("203.0.113.9");
    upstream.reset();
    upstream.respond(jsonReply(CREATE_RESPONSE, 201));
    await bff.handle(new Request("http://web/api/conversations", { method: "POST" }), null);
    expect(upstream.calls[0]!.headers.get("x-forwarded-for")).toBeNull();
  });
});

describe("validation rejects before anything is forwarded", () => {
  const messages = `/api/conversations/${CONVERSATION_ID}/messages`;
  const cases: Array<[string, string, unknown]> = [
    ["an unknown key in the body", messages, { text: "hola", debug: true }],
    ["an unknown key when creating", "/api/conversations", { lang: "es", admin: true }],
    ["an empty text", messages, { text: "" }],
    ["a text over 2000 characters", messages, { text: "x".repeat(2001) }],
    ["a language outside es, pt, en", messages, { text: "hola", lang: "fr" }],
    ["a client_message_id that is too short", messages, { text: "hola", client_message_id: "abc" }],
    ["a client_message_id with a space", messages, { text: "hola", client_message_id: "not valid id here" }],
    ["a missing body", messages, undefined],
    ["a body that is not JSON", messages, "{not json"],
    ["a language outside es, pt, en when creating", "/api/conversations", { lang: "de" }],
    ["a conversation id with a dot", "/api/conversations/bad.id/messages", { text: "hola" }],
    ["a conversation id over 64 characters", `/api/conversations/${"a".repeat(65)}/messages`, { text: "hola" }],
    ["an encoded slash in the id", "/api/conversations/..%2Fadmin/messages", { text: "hola" }],
    ["a malformed percent escape", "/api/conversations/%E0%A4%A/messages", { text: "hola" }],
  ];
  for (const [name, path, body] of cases) {
    test(name, async () => {
      const res = await post(path, body);
      expect(res.status).toBe(422);
      const detail = (await res.json()).detail;
      expect(Array.isArray(detail)).toBe(true);
      expect(detail[0]).toHaveProperty("loc");
      expect(upstream.calls).toHaveLength(0);
    });
  }

  test("a GET with an invalid id is rejected too", async () => {
    for (const suffix of ["", "/inbox"]) {
      const res = await fetch(`${base}/api/conversations/bad.id${suffix}`);
      expect(res.status).toBe(422);
    }
    expect(upstream.calls).toHaveLength(0);
  });

  test("a body over the limit is refused by the server", async () => {
    const res = await post(messages, { text: "x".repeat(100_000) }).catch(() => null);
    if (res) expect(res.status).toBe(413);
    expect(upstream.calls).toHaveLength(0);
  });
});

describe("statuses pass through", () => {
  test("429 keeps its Retry-After", async () => {
    upstream.respond(
      jsonReply({ detail: "Too many conversations opened from this address; try again later" }, 429, {
        "Retry-After": "287",
      }),
    );
    const res = await post("/api/conversations", { lang: "es" });
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("287");
    expect((await res.json()).detail).toContain("Too many");
  });

  test("503 replay_miss keeps its detail", async () => {
    upstream.respond(jsonReply({ detail: "replay_miss" }, 503));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ detail: "replay_miss" });
  });

  test("404, 409 and 502 pass through", async () => {
    for (const [status, detail] of [
      [404, "Conversation not found"],
      [409, "A turn is already in progress"],
      [502, "Could not open a banking session"],
    ] as const) {
      upstream.respond(jsonReply({ detail }, status));
      const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual({ detail });
    }
  });

  test("a Retry-After is not invented on a success", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 201, { "Retry-After": "5" }));
    const res = await post("/api/conversations");
    expect(res.headers.get("retry-after")).toBeNull();
  });
});

describe("an upstream that cannot be trusted is a 503 unavailable", () => {
  const unavailable = { detail: "unavailable" };

  test("unreachable", async () => {
    const dead = fakeOrchestrator();
    const url = dead.url;
    await dead.stop();
    const bff = createBff({ orchestratorUrl: url, log: (line) => logs.push(line) });
    const res = await bff.handle(new Request("http://web/api/conversations", { method: "POST" }), "203.0.113.9");
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual(unavailable);
  });

  test("through the server as well", async () => {
    const dead = fakeOrchestrator();
    const url = dead.url;
    await dead.stop();
    const isolated = startServer({ port: 0, orchestratorUrl: url, log: () => {}, development: false });
    try {
      const res = await fetch(`http://127.0.0.1:${isolated.port}/api/conversations/${CONVERSATION_ID}`);
      expect(res.status).toBe(503);
      expect(await res.json()).toEqual(unavailable);
    } finally {
      await isolated.stop(true);
    }
  });

  test("a body outside the contract", async () => {
    upstream.respond(jsonReply({ conversation_id: CONVERSATION_ID }));
    const res = await post(`/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola" });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual(unavailable);
  });

  test("a transcript without the takeover object", async () => {
    const { takeover: _takeover, ...withoutTakeover } = TRANSCRIPT;
    upstream.respond(jsonReply(withoutTakeover));
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
    expect(res.status).toBe(503);
  });

  test("a body that is not JSON", async () => {
    upstream.respond(() => new Response("<html>oops</html>", { status: 200 }));
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual(unavailable);
  });

  test("a success status other than the route's own", async () => {
    upstream.respond(jsonReply(CREATE_RESPONSE, 200));
    const res = await post("/api/conversations");
    expect(res.status).toBe(503);
  });

  test("an error status without a detail", async () => {
    upstream.respond(() => new Response("Bad Gateway", { status: 502 }));
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual(unavailable);
  });

  test("a redirect is not followed", async () => {
    upstream.respond(() => new Response(null, { status: 302, headers: { Location: "http://evil.example/" } }));
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`);
    expect(res.status).toBe(503);
    expect(upstream.calls).toHaveLength(1);
  });

  test("a timeout", async () => {
    upstream.respond(async () => {
      await Bun.sleep(300);
      return Response.json(TRANSCRIPT);
    });
    const bff = createBff({
      orchestratorUrl: upstream.url,
      log: () => {},
      timeoutMs: { turn: 50, read: 50 },
    });
    const res = await bff.handle(new Request(`http://web/api/conversations/${CONVERSATION_ID}`), null);
    expect(res.status).toBe(503);
  });
});

describe("the closed list of routes", () => {
  test("any other /api path is a 404 and reaches nothing", async () => {
    const paths = [
      "/api",
      "/api/",
      "/api/health",
      "/api/conversations/",
      `/api/conversations/${CONVERSATION_ID}/other`,
      `/api/conversations/${CONVERSATION_ID}/inbox/extra`,
      `/api/conversations/${CONVERSATION_ID}/feedback/extra`,
      "/api/v1/conversations",
      "/api/admin/policy-config",
    ];
    for (const path of paths) {
      const res = await fetch(base + path);
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ detail: "not_found" });
    }
    expect(upstream.calls).toHaveLength(0);
  });

  test("a known path with another method is a 405 that names the method", async () => {
    const res = await fetch(`${base}/api/conversations/${CONVERSATION_ID}`, { method: "DELETE" });
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("GET");
    const put = await fetch(`${base}/api/conversations`, { method: "PUT", body: "{}" });
    expect(put.status).toBe(405);
    expect(put.headers.get("allow")).toBe("POST");
    expect(upstream.calls).toHaveLength(0);
  });
});

describe("the rest of the server", () => {
  test("GET /healthz and /health", async () => {
    for (const path of ["/healthz", "/health"]) {
      const res = await fetch(`${base}${path}`);
      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({ status: "ok" });
    }
  });

  test("any other path outside /api is a 404", async () => {
    const res = await fetch(`${base}/admin`);
    expect(res.status).toBe(404);
  });

  test("GET / serves the page", async () => {
    const res = await fetch(base + "/");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/html");
  });
});
