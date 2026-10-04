import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { AGENT_EMAIL, CONVERSATION_ID, policyConfig, toolPolicy } from "./support/fixtures";
import { makeHarness, type Harness } from "./support/harness";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(body, { status, headers });

let harness: Harness;
let cookie: string;

beforeEach(async () => {
  harness = makeHarness();
  cookie = await harness.login();
});
afterEach(() => harness.stop());

const send = (path: string, method: string, body?: unknown, headers?: Record<string, string>) =>
  harness.request(path, { method, body, cookie, headers });

describe("agent messages", () => {
  const message = { text: "Hola, ya revisé tu caso.", client_message_id: "msg_0123456789" };
  const takeOver = () => send("/api/handoffs/hnd_qwertyuiopasdfgh/claim", "POST");

  test("go to the agent API with the session's agent in X-Agent-Ref, never the browser's", async () => {
    expect((await takeOver()).status).toBe(200);
    harness.orchestrator.requests.length = 0;

    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message, { "X-Agent-Ref": "evil@example.com", "x-agent-ref": "worse@example.com" });
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ message: { role: "agent", content: message.text, blocks: [] } });

    expect(harness.orchestrator.requests).toHaveLength(1);
    const [upstream] = harness.orchestrator.requests;
    expect(upstream?.method).toBe("POST");
    expect(upstream?.path).toBe(`/v1/agent/conversations/${CONVERSATION_ID}/messages`);
    expect(upstream?.headers["x-agent-ref"]).toBe(AGENT_EMAIL);
    expect(upstream?.headers.authorization).toBe("Bearer test-agent-token");
    expect(upstream?.headers["content-type"]).toBe("application/json");
    expect(upstream?.body).toEqual(message);
    expect(harness.bankingCore.requests.filter((request) => request.path.includes("messages"))).toHaveLength(0);
  });

  test("the header is set on every send, so the fake's own check would refuse a different agent", async () => {
    expect((await takeOver()).status).toBe(200);
    // The fake orchestrator only accepts a message from the agent who holds the takeover: the header is the session's.
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message, { "X-Agent-Ref": "someone.else@example.com" });
    expect(response.status).toBe(200);
  });

  test("without a takeover the agent API's 409 no_active_takeover is passed on", async () => {
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: "no_active_takeover" });
  });

  test("a customer turn in flight is 503 turn_in_progress with Retry-After, so the same message can be retried", async () => {
    harness.orchestrator.on("POST /v1/agent/conversations/:id/messages", () => json({ detail: "turn_in_progress" }, 503, { "Retry-After": "2" }));
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("2");
    expect(await response.json()).toEqual({ detail: "turn_in_progress" });
  });

  test("any other 503 is plain unavailable, without Retry-After", async () => {
    harness.orchestrator.on("POST /v1/agent/conversations/:id/messages", () => json({ detail: "busy" }, 503));
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBeNull();
    expect(await response.json()).toEqual({ detail: "unavailable" });
  });

  test("the orchestrator unreachable is 503 unavailable", async () => {
    harness.orchestrator.stop();
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ detail: "unavailable" });
  });

  test.each([
    ["an empty text", { ...message, text: "" }],
    ["a text over 2000 characters", { ...message, text: "x".repeat(2001) }],
    ["a missing client_message_id", { text: "hola" }],
    ["a client_message_id that is too short", { ...message, client_message_id: "abc" }],
    ["a client_message_id with a space", { ...message, client_message_id: "msg 0123456789" }],
    ["an agent_ref smuggled in the body", { ...message, agent_ref: "evil@example.com" }],
    ["an unknown key", { ...message, role: "assistant" }],
  ])("%s is 422 and never forwarded", async (_label, body) => {
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", body);
    expect(response.status).toBe(422);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("a text of exactly 2000 characters goes through", async () => {
    await takeOver();
    const response = await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", { ...message, text: "x".repeat(2000) });
    expect(response.status).toBe(200);
  });

  test("a repeated client_message_id is forwarded as it is: the orchestrator returns the stored message", async () => {
    await takeOver();
    await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    await send(`/api/conversations/${CONVERSATION_ID}/messages`, "POST", message);
    const sent = harness.orchestrator.requests.filter((request) => request.path.endsWith("/messages"));
    expect(sent.map((request) => (request.body as { client_message_id: string }).client_message_id)).toEqual([message.client_message_id, message.client_message_id]);
  });
});

describe("policy config", () => {
  test("GET forwards to banking-core with the admin token", async () => {
    const response = await send("/api/policy-config", "GET");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(policyConfig());
    expect(harness.bankingCore.requests[0]).toMatchObject({ method: "GET", path: "/v1/admin/policy-config" });
    expect(harness.bankingCore.requests[0]?.headers.authorization).toBe("Bearer test-admin-token");
  });

  test("PUT forwards the body and answers with the new version", async () => {
    const body = { amount_mode: "flag", thresholds_minor: { USD: 10000, EUR: 50000 } };
    const response = await send("/api/policy-config", "PUT", body);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ...body, version: policyConfig().version + 1 });
    expect(harness.bankingCore.requests[0]).toMatchObject({ method: "PUT", path: "/v1/admin/policy-config", body });
  });

  test.each([
    ["an unknown mode", { amount_mode: "recommend", thresholds_minor: { USD: 100 } }],
    ["no currency", { amount_mode: "flag", thresholds_minor: {} }],
    ["a threshold of zero", { amount_mode: "flag", thresholds_minor: { USD: 0 } }],
    ["a fractional threshold", { amount_mode: "flag", thresholds_minor: { USD: 1.5 } }],
    ["a lower-case currency", { amount_mode: "flag", thresholds_minor: { usd: 100 } }],
    ["an unknown key", { amount_mode: "flag", thresholds_minor: { USD: 100 }, version: 99 }],
  ])("PUT with %s is 422 and never forwarded", async (_label, body) => {
    const response = await send("/api/policy-config", "PUT", body);
    expect(response.status).toBe(422);
    expect(harness.bankingCore.requests).toHaveLength(0);
  });
});

describe("tool policy", () => {
  test("GET forwards and returns the policy with its code floor", async () => {
    const response = await send("/api/tool-policy", "GET");
    expect(response.status).toBe(200);
    const body = (await response.json()) as ReturnType<typeof toolPolicy>;
    expect(body.code_floor["card.block"]).toEqual(["VERIFIED"]);
    expect(harness.bankingCore.requests[0]).toMatchObject({ method: "GET", path: "/v1/admin/tool-policy" });
  });

  test("PUT forwards the tools and answers with the new version", async () => {
    const body = { tools: { "account.get_summary": ["VERIFIED"] } };
    const response = await send("/api/tool-policy", "PUT", body);
    expect(response.status).toBe(200);
    const saved = (await response.json()) as ReturnType<typeof toolPolicy>;
    expect(saved.version).toBe(toolPolicy().version + 1);
    expect(saved.tools["account.get_summary"]).toEqual(["VERIFIED"]);
    expect(saved.disabled).not.toContain("account.get_summary");
    expect(harness.bankingCore.requests[0]?.body).toEqual(body);
  });

  test("banking-core's 422 for a widening is passed on with its list of issues", async () => {
    const detail = [{ loc: ["body", "tools", "card.block"], msg: "card.block cannot be enabled in ANONYMOUS", type: "code_floor_violation" }];
    harness.bankingCore.on("PUT /v1/admin/tool-policy", () => json({ detail }, 422));
    const response = await send("/api/tool-policy", "PUT", { tools: { "card.block": ["ANONYMOUS"] } });
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ detail });
  });

  test.each([
    ["a state that is not an FSM state", { tools: { "card.block": ["SUPERUSER"] } }],
    ["no tool", { tools: {} }],
    ["an unknown key", { tools: { "card.block": [] }, force: true }],
  ])("PUT with %s is 422 and never forwarded", async (_label, body) => {
    expect((await send("/api/tool-policy", "PUT", body)).status).toBe(422);
    expect(harness.bankingCore.requests).toHaveLength(0);
  });
});

describe("demo reset", () => {
  test("posts to banking-core and answers with what it reset", async () => {
    const response = await send("/api/demo/reset", "POST");
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ cards_reset: 12, tool_policy_changed: true });
    expect(harness.bankingCore.requests[0]).toMatchObject({ method: "POST", path: "/v1/admin/demo/reset-fixtures", body: undefined });
    expect(harness.bankingCore.requests[0]?.headers.authorization).toBe("Bearer test-admin-token");
  });

  test("banking-core's 403 (disabled in production) is passed on", async () => {
    harness.bankingCore.on("POST /v1/admin/demo/reset-fixtures", () => json({ detail: "Demo fixture reset is disabled in production" }, 403));
    const response = await send("/api/demo/reset", "POST");
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "Demo fixture reset is disabled in production" });
  });
});

describe("metrics", () => {
  test("defaults to a 24 hour window and forwards it", async () => {
    const response = await send("/api/metrics", "GET");
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ window_hours: 24, cards_blocked: 26 });
    expect(harness.bankingCore.requests[0]).toMatchObject({ method: "GET", path: "/v1/admin/metrics", search: "?hours=24" });
  });

  test("forwards the window asked for", async () => {
    const response = await send("/api/metrics?hours=168", "GET");
    expect(((await response.json()) as { window_hours: number }).window_hours).toBe(168);
    expect(harness.bankingCore.requests[0]?.search).toBe("?hours=168");
  });

  test.each(["0", "721", "abc", "1.5", "-3"])("hours=%s is 422 and never forwarded", async (hours) => {
    expect((await send(`/api/metrics?hours=${hours}`, "GET")).status).toBe(422);
    expect(harness.bankingCore.requests).toHaveLength(0);
  });
});

describe("when an upstream misbehaves", () => {
  test("banking-core unreachable is 503 unavailable on every admin route", async () => {
    harness.bankingCore.stop();
    for (const [method, path, body] of [
      ["GET", "/api/handoffs", undefined],
      ["GET", "/api/policy-config", undefined],
      ["PUT", "/api/policy-config", { amount_mode: "flag", thresholds_minor: { USD: 1 } }],
      ["GET", "/api/tool-policy", undefined],
      ["POST", "/api/demo/reset", undefined],
      ["GET", "/api/metrics", undefined],
    ] as const) {
      const response = await send(path, method, body);
      expect(response.status, `${method} ${path}`).toBe(503);
      expect(await response.json()).toEqual({ detail: "unavailable" });
    }
  });

  test("an upstream that never answers is 503 after the timeout", async () => {
    const slow = makeHarness({ env: { UPSTREAM_TIMEOUT_MS: "150" } });
    try {
      const slowCookie = await slow.login();
      slow.bankingCore.on("GET /v1/admin/policy-config", async () => {
        await Bun.sleep(600);
        return json(policyConfig());
      });
      const response = await slow.request("/api/policy-config", { cookie: slowCookie });
      expect(response.status).toBe(503);
    } finally {
      slow.stop();
    }
  });

  test("a refused BFF token is 502, never a 401 that would send the agent back to the login", async () => {
    harness.bankingCore.on("GET /v1/admin/policy-config", () => json({ detail: "Invalid administrator token" }, 401));
    const response = await send("/api/policy-config", "GET");
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "upstream_unauthorized" });
  });

  test("a wrong token in the BFF's configuration is what makes the fakes refuse it", async () => {
    const misconfigured = makeHarness({ env: { ADMIN_API_TOKEN: "not-the-token" } });
    try {
      const misCookie = await misconfigured.login();
      expect((await misconfigured.request("/api/handoffs", { cookie: misCookie })).status).toBe(502);
    } finally {
      misconfigured.stop();
    }
  });

  test.each([
    ["an answer that breaks the contract", () => json({ amount_mode: "recommend", thresholds_minor: {}, version: 1 })],
    ["a body that is not JSON", () => new Response("<html>oops</html>", { headers: { "Content-Type": "text/html" } })],
    ["another success status", () => json(policyConfig(), 202)],
  ])("%s is 502 invalid_upstream_response", async (_label, responder) => {
    harness.bankingCore.on("GET /v1/admin/policy-config", responder);
    const response = await send("/api/policy-config", "GET");
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "invalid_upstream_response" });
  });

  test("an upstream 500 is 502 and its message stays inside", async () => {
    harness.bankingCore.on("GET /v1/admin/policy-config", () => json({ detail: "Active tool policy v3 is invalid: secret internals" }, 500));
    const response = await send("/api/policy-config", "GET");
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "upstream_error" });
  });

  test("an upstream 4xx keeps its status and its detail", async () => {
    harness.bankingCore.on("GET /v1/admin/handoffs/:handoff_ref", () => json({ detail: "Handoff not found" }, 404));
    const response = await send("/api/handoffs/hnd_unknownunknownun", "GET");
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "Handoff not found" });
  });

  test("the answer is what the contract names: unknown fields from an upstream are dropped", async () => {
    harness.bankingCore.on("GET /v1/admin/policy-config", () => json({ ...policyConfig(), db_password: "hunter2" }));
    const body = (await (await send("/api/policy-config", "GET")).json()) as Record<string, unknown>;
    expect(body).toEqual(policyConfig());
    expect(body.db_password).toBeUndefined();
  });
});

describe("detective mode (ADR-0019)", () => {
  test("GET reads the orchestrator's switch through the agent API", async () => {
    const res = await send("/api/detective", "GET");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ available: true, enabled: true });
    expect(harness.orchestrator.requests.at(-1)?.path).toBe("/v1/agent/detective");
  });

  test("PUT turns it off and on", async () => {
    const off = await send("/api/detective", "PUT", { enabled: false });
    expect(await off.json()).toEqual({ available: true, enabled: false });
    expect((await (await send("/api/detective", "GET")).json()).enabled).toBe(false);
    const on = await send("/api/detective", "PUT", { enabled: true });
    expect(await on.json()).toEqual({ available: true, enabled: true });
  });

  test("where it is not offered, the agent API's 409 is passed on", async () => {
    harness.orchestrator.on("PUT /v1/agent/detective", () => Response.json({ detail: "detective_unavailable" }, { status: 409 }));
    const res = await send("/api/detective", "PUT", { enabled: true });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ detail: "detective_unavailable" });
  });

  test("the body is strict and the session is required", async () => {
    expect((await send("/api/detective", "PUT", { enabled: true, all: true })).status).toBe(422);
    expect((await harness.request("/api/detective", { method: "GET" })).status).toBe(401);
  });
});
