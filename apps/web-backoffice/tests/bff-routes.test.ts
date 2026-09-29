import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { backofficeBffRoutes, routePath, type RouteShape } from "@pattern-blue/contracts";
import { CONVERSATION_ID, SESSION_REF, handoffDetail } from "./support/fixtures";
import { makeHarness, type Harness } from "./support/harness";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(body, { status, headers });


let harness: Harness;
let cookie: string;

beforeAll(async () => {
  harness = makeHarness();
  cookie = await harness.login();
});
afterAll(() => harness.stop());

const last = (service: "bankingCore" | "orchestrator") => {
  const requests = harness[service].requests;
  return requests[requests.length - 1];
};
const forget = () => {
  harness.bankingCore.requests.length = 0;
  harness.orchestrator.requests.length = 0;
};

describe("the closed list of routes", () => {
  const routes = Object.entries(backofficeBffRoutes) as [string, RouteShape][];

  test("the BFF answers exactly the routes of the contract: each one exists and, but for login, needs the cookie", async () => {
    for (const [name, route] of routes) {
      const path = route.pattern.replace(":ref", "hnd_qwertyuiopasdfgh").replace(":id", CONVERSATION_ID);
      const response = await harness.request(path, { method: route.method });
      // The login is the one route without a session: with no body it is a validation error, not a 401.
      expect(response.status, `${route.method} ${route.pattern} (${name})`).toBe(name === "login" ? 422 : 401);
    }
  });

  test.each([
    ["GET", "/api"],
    ["GET", "/api/"],
    ["GET", "/api/unknown"],
    ["GET", "/api/v1/admin/policy-config"],
    ["GET", "/api/handoffs/hnd_qwertyuiopasdfgh/claim"],
    ["POST", "/api/handoffs"],
    ["DELETE", "/api/handoffs/hnd_qwertyuiopasdfgh"],
    ["GET", "/api/conversations"],
    ["POST", "/api/conversations"],
    ["GET", "/api/conversations/conv_x/messages"],
    ["PATCH", "/api/policy-config"],
    ["OPTIONS", "/api/policy-config"],
    ["GET", "/api/demo/reset"],
    ["GET", "/api/session/extra"],
  ])("%s %s is a 404, with or without the cookie", async (method, path) => {
    for (const withCookie of [null, cookie]) {
      const response = await harness.request(path, { method, cookie: withCookie });
      expect(response.status).toBe(404);
      expect(await response.json()).toEqual({ detail: "not_found" });
    }
  });

  test("nothing under /api reaches an upstream on a path the contract does not list", async () => {
    forget();
    await harness.request("/api/v1/admin/policy-config", { cookie });
    await harness.request("/api/handoffs/..%2F..%2Fmetrics", { cookie });
    expect(harness.bankingCore.requests).toHaveLength(0);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });
});

describe("the gate", () => {
  test("a tampered cookie is 401", async () => {
    const tampered = cookie.slice(0, -3) + (cookie.endsWith("AAA") ? "BBB" : "AAA");
    expect((await harness.request("/api/handoffs", { cookie: tampered })).status).toBe(401);
    expect((await harness.request("/api/handoffs", { cookie: "pb_session=" })).status).toBe(401);
  });

  test("a mutating route without the JSON content type is 415, before anything is validated or forwarded", async () => {
    forget();
    for (const [method, path, body] of [
      ["PUT", "/api/policy-config", { amount_mode: "flag", thresholds_minor: { USD: 100 } }],
      ["PUT", "/api/tool-policy", { tools: { "card.block": [] } }],
      ["POST", "/api/demo/reset", undefined],
      ["POST", "/api/handoffs/hnd_qwertyuiopasdfgh/claim", undefined],
      ["POST", `/api/conversations/${CONVERSATION_ID}/messages`, { text: "hola", client_message_id: "msg_12345678" }],
      ["DELETE", "/api/session", undefined],
    ] as const) {
      for (const contentType of [null, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]) {
        const response = await harness.request(path, { method, body, cookie, contentType });
        expect(response.status, `${method} ${path} as ${contentType}`).toBe(415);
      }
    }
    expect(harness.bankingCore.requests).toHaveLength(0);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("the JSON content type may carry a charset", async () => {
    const response = await harness.request("/api/demo/reset", { method: "POST", cookie, contentType: "application/json; charset=utf-8" });
    expect(response.status).toBe(200);
  });

  test("GET routes do not need a content type", async () => {
    expect((await harness.request("/api/policy-config", { cookie })).status).toBe(200);
  });

  test("the session comes before the content type: no cookie is 401 even for a bad content type", async () => {
    expect((await harness.request("/api/demo/reset", { method: "POST", contentType: "text/plain" })).status).toBe(401);
  });

  test("every answer says not to cache it", async () => {
    for (const path of ["/api/policy-config", "/api/nope"]) {
      const response = await harness.request(path, { cookie });
      expect(response.headers.get("cache-control")).toBe("no-store");
    }
  });

  test("a path parameter that is not an opaque token is 422 and never reaches an upstream", async () => {
    forget();
    for (const ref of ["..%2F..%2Fadmin", "hnd%20x", "a".repeat(65), "hnd;drop", "%00"]) {
      const response = await harness.request(`/api/handoffs/${ref}`, { cookie });
      expect(response.status, ref).toBe(422);
      const claim = await harness.request(`/api/handoffs/${ref}/claim`, { method: "POST", cookie });
      expect(claim.status, ref).toBe(422);
    }
    expect((await harness.request(`/api/conversations/${"c".repeat(65)}`, { cookie })).status).toBe(422);
    expect(harness.bankingCore.requests).toHaveLength(0);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });
});

describe("GET /api/handoffs", () => {
  test("forwards to banking-core with the admin token and nothing from the browser", async () => {
    forget();
    const response = await harness.request("/api/handoffs", {
      cookie,
      headers: { Authorization: "Bearer browser-token", "X-Agent-Ref": "browser@evil.example", "X-Forwarded-For": "6.6.6.6" },
    });
    expect(response.status).toBe(200);
    const { items } = (await response.json()) as { items: { handoff_ref: string }[] };
    expect(items.map((item) => item.handoff_ref)).toEqual(["hnd_qwertyuiopasdfgh", "hnd_zxcvbnmasdfghjkl", "hnd_poiuytrewqlkjhgf", "hnd_mnbvcxzlkjhgfdsa"]);

    const upstream = last("bankingCore");
    expect(harness.bankingCore.requests).toHaveLength(1);
    expect(harness.orchestrator.requests).toHaveLength(0);
    expect(upstream?.method).toBe("GET");
    expect(upstream?.path).toBe("/v1/admin/handoffs");
    expect(upstream?.search).toBe("");
    expect(upstream?.headers.authorization).toBe("Bearer test-admin-token");
    expect(upstream?.headers["x-agent-ref"]).toBeUndefined();
    expect(upstream?.headers["x-forwarded-for"]).toBeUndefined();
    expect(upstream?.headers.cookie).toBeUndefined();
  });

  test("repeats the status filter, one value or a list", async () => {
    forget();
    await harness.request("/api/handoffs?status=QUEUED", { cookie });
    expect(last("bankingCore")?.search).toBe("?status=QUEUED");
    await harness.request("/api/handoffs?status=QUEUED&status=ASSIGNED", { cookie });
    expect(last("bankingCore")?.search).toBe("?status=QUEUED&status=ASSIGNED");
    const response = await harness.request("/api/handoffs?status=ASSIGNED", { cookie });
    const { items } = (await response.json()) as { items: { status: string }[] };
    expect(items.map((item) => item.status)).toEqual(["ASSIGNED"]);
  });

  test("a status the contract does not know is 422, and other query keys are not forwarded", async () => {
    forget();
    expect((await harness.request("/api/handoffs?status=RESOLVED", { cookie })).status).toBe(422);
    expect(harness.bankingCore.requests).toHaveLength(0);
    await harness.request("/api/handoffs?status=QUEUED&agent=me&token=1", { cookie });
    expect(last("bankingCore")?.search).toBe("?status=QUEUED");
  });
});

describe("GET /api/handoffs/:ref", () => {
  test("adds the conversation id, resolved through the agent API with the agent token", async () => {
    forget();
    const response = await harness.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie });
    expect(response.status).toBe(200);
    const detail = (await response.json()) as Record<string, unknown> & { summary: { verified_facts: unknown } };
    expect(detail.handoff_ref).toBe("hnd_qwertyuiopasdfgh");
    expect(detail.conversation_id).toBe(CONVERSATION_ID);
    expect(detail.summary.verified_facts).toBeDefined();

    expect(last("bankingCore")?.path).toBe("/v1/admin/handoffs/hnd_qwertyuiopasdfgh");
    expect(last("bankingCore")?.headers.authorization).toBe("Bearer test-admin-token");
    expect(last("orchestrator")?.path).toBe(`/v1/agent/sessions/${SESSION_REF}/conversation`);
    expect(last("orchestrator")?.headers.authorization).toBe("Bearer test-agent-token");
  });

  test("a conversation the agent API does not know is null, not an error", async () => {
    const own = makeHarness();
    try {
      const ownCookie = await own.login();
      own.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "Not Found" }, 404));
      const response = await own.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie: ownCookie });
      expect(response.status).toBe(200);
      expect(((await response.json()) as { conversation_id: unknown }).conversation_id).toBeNull();
    } finally {
      own.stop();
    }
  });

  test("any other failure of the agent API fails the read: 503 when it is down, 502 when it answers wrongly", async () => {
    const own = makeHarness();
    try {
      const ownCookie = await own.login();
      own.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "boom" }, 500));
      expect((await own.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie: ownCookie })).status).toBe(502);
      own.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ conversation_id: "not a safe id!" }));
      expect((await own.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie: ownCookie })).status).toBe(502);
      own.orchestrator.stop();
      const down = await own.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie: ownCookie });
      expect(down.status).toBe(503);
      expect(await down.json()).toEqual({ detail: "unavailable" });
    } finally {
      own.stop();
    }
  });

  test("an unknown handoff is 404 and the agent API is not asked", async () => {
    forget();
    const response = await harness.request("/api/handoffs/hnd_doesnotexistatall", { cookie });
    expect(response.status).toBe(404);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("keeps the stored summary as it is, including keys the contract does not name, and drops other extras", async () => {
    const own = makeHarness();
    try {
      const ownCookie = await own.login();
      own.bankingCore.on("GET /v1/admin/handoffs/:handoff_ref", () =>
        json({
          ...handoffDetail(),
          internal_debug: "must not reach the browser",
          summary: { verified_facts: { a: 1 }, actions_taken: [], verification_method: "none", open_questions: [], extra_note: "kept" },
        }),
      );
      const detail = (await (await own.request("/api/handoffs/hnd_qwertyuiopasdfgh", { cookie: ownCookie })).json()) as Record<string, unknown>;
      expect(detail.internal_debug).toBeUndefined();
      expect((detail.summary as Record<string, unknown>).extra_note).toBe("kept");
    } finally {
      own.stop();
    }
  });
});

describe("conversations", () => {
  test("GET forwards to the agent API with the agent token", async () => {
    forget();
    const response = await harness.request(`/api/conversations/${CONVERSATION_ID}`, { cookie });
    expect(response.status).toBe(200);
    const body = (await response.json()) as { conversation_id: string; takeover: { active: boolean; agent_ref: string | null }; messages: unknown[] };
    expect(body.conversation_id).toBe(CONVERSATION_ID);
    expect(body.takeover).toMatchObject({ active: expect.any(Boolean) });
    expect(body.messages.length).toBeGreaterThan(0);
    expect(last("orchestrator")?.path).toBe(`/v1/agent/conversations/${CONVERSATION_ID}`);
    expect(last("orchestrator")?.headers.authorization).toBe("Bearer test-agent-token");
    expect(harness.bankingCore.requests).toHaveLength(0);
  });
});
