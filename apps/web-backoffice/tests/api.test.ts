import { describe, expect, test } from "bun:test";
import {
  AgentTranscriptResponseSchema,
  BackofficeHandoffDetailSchema,
  ClaimHandoffResponseSchema,
  DemoResetResponseSchema,
  HandoffDetailSchema,
  HandoffListResponseSchema,
  MetricsResponseSchema,
  PolicyConfigResponseSchema,
  TakeoverResponseSchema,
  ToolPolicyResponseSchema,
  AgentMessageResponseSchema,
} from "@pattern-blue/contracts";
import { ApiError, createApi } from "../src/api/client";
import { categorize, validationMessages } from "../src/api/errors";
import { parseHash } from "../src/app/router";
import * as fixtures from "./support/fixtures";
import { fakeFetch, json, noContent } from "./support/fake-fetch";

describe("the fixtures are what the contract says (so the tests are testing the real shapes)", () => {
  test("every fixture parses with its schema", () => {
    expect(() => HandoffListResponseSchema.parse({ items: fixtures.handoffItems() })).not.toThrow();
    expect(() => HandoffDetailSchema.parse(fixtures.handoffDetail())).not.toThrow();
    expect(() => BackofficeHandoffDetailSchema.parse(fixtures.backofficeDetail())).not.toThrow();
    expect(() => ClaimHandoffResponseSchema.parse({ handoff: fixtures.claimedDetail(), takeover: fixtures.takeoverResponse() })).not.toThrow();
    expect(() => TakeoverResponseSchema.parse(fixtures.takeoverResponse())).not.toThrow();
    expect(() => AgentTranscriptResponseSchema.parse(fixtures.transcript({ withAgentMessage: true }))).not.toThrow();
    expect(() => AgentMessageResponseSchema.parse(fixtures.agentMessageResponse("hola"))).not.toThrow();
    expect(() => PolicyConfigResponseSchema.parse(fixtures.policyConfig())).not.toThrow();
    expect(() => ToolPolicyResponseSchema.parse(fixtures.toolPolicy())).not.toThrow();
    expect(() => MetricsResponseSchema.parse(fixtures.metrics())).not.toThrow();
    expect(() => DemoResetResponseSchema.parse(fixtures.demoReset())).not.toThrow();
  });
});

describe("the browser client", () => {
  test("builds its URLs from the contract and validates what comes back", async () => {
    const network = fakeFetch({
      "GET /api/handoffs": () => json({ items: fixtures.handoffItems() }),
      "GET /api/handoffs/:ref": () => json(fixtures.backofficeDetail()),
      "GET /api/metrics": () => json(fixtures.metrics(168)),
    });
    const api = createApi(network.fetch);
    expect((await api.listHandoffs(["QUEUED", "ASSIGNED"])).items).toHaveLength(4);
    expect(network.calls[0]).toMatchObject({ method: "GET", path: "/api/handoffs", search: "?status=QUEUED&status=ASSIGNED" });
    await api.listHandoffs();
    expect(network.calls[1]?.search).toBe("");
    expect((await api.getHandoff("hnd_qwertyuiopasdfgh")).conversation_id).toBe(fixtures.CONVERSATION_ID);
    expect(network.calls[2]?.path).toBe("/api/handoffs/hnd_qwertyuiopasdfgh");
    expect((await api.getMetrics(168)).window_hours).toBe(168);
    expect(network.calls[3]?.search).toBe("?hours=168");
  });

  test("a mutating call always carries the JSON content type and the cookie, a GET does not need it", async () => {
    const seen: { method: string; contentType: string | undefined }[] = [];
    const api = createApi(async (_url, init) => {
      seen.push({ method: init.method as string, contentType: (init.headers as Record<string, string>)["Content-Type"] });
      expect(init.credentials).toBe("same-origin");
      if (init.method === "GET") return json({ agent_ref: "a@b.c" });
      return init.method === "POST" && String(_url).endsWith("/claim") ? json({ handoff: fixtures.claimedDetail(), takeover: fixtures.takeoverResponse() }) : noContent();
    });
    await api.getSession();
    await api.logout();
    await api.claimHandoff("hnd_qwertyuiopasdfgh");
    expect(seen).toEqual([
      { method: "GET", contentType: undefined },
      { method: "DELETE", contentType: "application/json" },
      { method: "POST", contentType: "application/json" },
    ]);
  });

  test("sends the message with its client_message_id, and encodes the id in the path", async () => {
    const network = fakeFetch({ "POST /api/conversations/:id/messages": (call) => json(fixtures.agentMessageResponse((call.body as { text: string }).text)) });
    const api = createApi(network.fetch);
    await api.sendAgentMessage(fixtures.CONVERSATION_ID, { text: "hola", client_message_id: "msg_12345678" });
    expect(network.calls[0]?.body).toEqual({ text: "hola", client_message_id: "msg_12345678" });
    expect(network.calls[0]?.path).toBe(`/api/conversations/${fixtures.CONVERSATION_ID}/messages`);
    // A crafted id cannot add a path segment.
    await api.getConversation("a/b?c").catch(() => {});
    expect(network.calls[1]?.path).toBe("/api/conversations/a%2Fb%3Fc");
  });

  test("an error status is an ApiError with the BFF's detail and Retry-After", async () => {
    const api = createApi(async () => json({ detail: "turn_in_progress" }, 503, { "Retry-After": "2" }));
    const error = await api.sendAgentMessage("conv_x", { text: "hola", client_message_id: "msg_12345678" }).catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "http", status: 503, detail: "turn_in_progress", retryAfterSeconds: 2 });
    expect(categorize(error)).toBe("turnInProgress");
  });

  test("a network failure is kind 'network', and an answer off the contract is kind 'invalid'", async () => {
    const offline = createApi(async () => {
      throw new TypeError("Failed to fetch");
    });
    const down = await offline.getPolicyConfig().catch((caught) => caught);
    expect(down).toMatchObject({ kind: "network", status: 0 });
    expect(categorize(down)).toBe("unavailable");

    const odd = createApi(async () => json({ amount_mode: "recommend", thresholds_minor: {}, version: 1 }));
    const invalid = await odd.getPolicyConfig().catch((caught) => caught);
    expect(invalid).toMatchObject({ kind: "invalid" });
    expect(categorize(invalid)).toBe("other");
  });

  test("a 401 tells the app the session ended, except for the login's own", async () => {
    let ended = 0;
    const api = createApi(async () => json({ detail: "unauthorized" }, 401), { onUnauthorized: () => void ended++ });
    await api.listHandoffs().catch(() => {});
    await api.claimHandoff("hnd_qwertyuiopasdfgh").catch(() => {});
    expect(ended).toBe(2);
    await api.login("a@b.c", "wrong").catch(() => {});
    expect(ended).toBe(2);
  });
});

describe("error categories", () => {
  const http = (status: number, detail: ApiError["detail"] = null) => new ApiError({ kind: "http", status, detail });
  test.each([
    [http(401), "unauthorized"],
    [http(404, "Handoff not found"), "notFound"],
    [http(403, "disabled"), "forbidden"],
    [http(409, "claimed_by_another_agent"), "heldByAnother"],
    [http(409, "taken_over_by_another_agent"), "heldByAnother"],
    [http(409, "no_active_takeover"), "noActiveTakeover"],
    [http(422, []), "validation"],
    [http(502, "claimed_but_takeover_failed"), "claimedButTakeoverFailed"],
    [http(502, "upstream_error"), "unavailable"],
    [http(503, "unavailable"), "unavailable"],
    [http(503, "turn_in_progress"), "turnInProgress"],
    [http(500), "other"],
    [new Error("x"), "other"],
  ])("%p is %s", (error, category) => {
    expect(categorize(error)).toBe(category as never);
  });

  test("the messages of a 422", () => {
    const error = http(422, [{ loc: ["body"], msg: "one", type: "x" }, { loc: ["body"], msg: "two", type: "x" }]);
    expect(validationMessages(error)).toEqual(["one", "two"]);
    expect(validationMessages(http(422, "text"))).toEqual([]);
  });
});

describe("hash routes", () => {
  test.each([
    ["", { name: "queue" }],
    ["#", { name: "queue" }],
    ["#/", { name: "queue" }],
    ["#/guardrails", { name: "guardrails" }],
    ["#/guardrails/", { name: "guardrails" }],
    ["#/metrics", { name: "metrics" }],
    ["#/handoffs/hnd_qwertyuiopasdfgh", { name: "handoff", ref: "hnd_qwertyuiopasdfgh" }],
    ["#/handoffs/hnd_x%2Fy", { name: "queue" }],
    ["#/handoffs/..%2Fadmin", { name: "queue" }],
    ["#/handoffs/%E0%A4%A", { name: "queue" }],
    ["#/handoffs/", { name: "queue" }],
    ["#/handoffs/a/b", { name: "queue" }],
    ["#/nowhere", { name: "queue" }],
  ])("%p", (hash, route) => {
    expect(parseHash(hash)).toEqual(route as never);
  });
});
