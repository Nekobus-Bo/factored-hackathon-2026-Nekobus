import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { AGENT_EMAIL, CONVERSATION_ID, SESSION_REF, claimedDetail, takeoverResponse } from "./support/fixtures";
import { makeHarness, type Harness } from "./support/harness";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(body, { status, headers });
const HANDOFF = "hnd_qwertyuiopasdfgh";

let harness: Harness;
let cookie: string;
/** The upstream calls in the order they happened, across both services. */
let order: string[];

beforeEach(async () => {
  harness = makeHarness();
  cookie = await harness.login();
  order = [];
  const claim = (request: { body: unknown }) => {
    order.push("banking-core claim");
    return json(claimedDetail((request.body as { agent_ref: string }).agent_ref));
  };
  harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/claim", claim);
  harness.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => {
    order.push("orchestrator conversation");
    return json({ conversation_id: CONVERSATION_ID });
  });
  harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", (request) => {
    order.push("orchestrator takeover");
    return json(takeoverResponse((request.body as { agent_ref: string }).agent_ref));
  });
});
afterEach(() => harness.stop());

const claim = (init: { cookie?: string | null; body?: unknown; headers?: Record<string, string> } = {}) =>
  harness.request(`/api/handoffs/${HANDOFF}/claim`, { method: "POST", cookie: init.cookie === undefined ? cookie : init.cookie, body: init.body, headers: init.headers });

describe("claim, then take over", () => {
  test("claims in banking-core first, then finds the conversation and takes it over", async () => {
    const response = await claim();
    expect(response.status).toBe(200);
    expect(order).toEqual(["banking-core claim", "orchestrator conversation", "orchestrator takeover"]);

    const body = (await response.json()) as { handoff: Record<string, unknown>; takeover: Record<string, unknown> };
    expect(body.handoff).toMatchObject({ status: "ASSIGNED", assigned_agent: AGENT_EMAIL, session_ref: SESSION_REF });
    expect(body.takeover).toMatchObject({ conversation_id: CONVERSATION_ID, takeover: { active: true, agent_ref: AGENT_EMAIL } });
  });

  test("each step carries its own token and the agent of the session", async () => {
    await claim();
    const [claimRequest] = harness.bankingCore.requests;
    expect(claimRequest).toMatchObject({ method: "POST", path: `/v1/admin/handoffs/${HANDOFF}/claim`, body: { agent_ref: AGENT_EMAIL } });
    expect(claimRequest?.headers.authorization).toBe("Bearer test-admin-token");

    const [lookup, takeover] = harness.orchestrator.requests;
    expect(lookup?.path).toBe(`/v1/agent/sessions/${SESSION_REF}/conversation`);
    expect(lookup?.headers.authorization).toBe("Bearer test-agent-token");
    expect(takeover).toMatchObject({ method: "POST", path: `/v1/agent/conversations/${CONVERSATION_ID}/takeover`, body: { agent_ref: AGENT_EMAIL, handoff_ref: HANDOFF } });
    expect(takeover?.headers.authorization).toBe("Bearer test-agent-token");
  });

  test("the agent is the session's, whatever the browser sends", async () => {
    await claim({ body: { agent_ref: "evil@example.com" }, headers: { "X-Agent-Ref": "evil@example.com" } });
    expect(harness.bankingCore.requests[0]?.body).toEqual({ agent_ref: AGENT_EMAIL });
    expect(harness.orchestrator.requests[1]?.body).toEqual({ agent_ref: AGENT_EMAIL, handoff_ref: HANDOFF });
    expect(harness.orchestrator.requests.every((request) => request.headers["x-agent-ref"] === undefined)).toBe(true);
  });

  test("needs the session", async () => {
    expect((await claim({ cookie: null })).status).toBe(401);
    expect(order).toEqual([]);
  });

  test("calling it again is safe: both steps are idempotent for the same agent", async () => {
    expect((await claim()).status).toBe(200);
    const again = await claim();
    expect(again.status).toBe(200);
    expect(order).toEqual([
      "banking-core claim",
      "orchestrator conversation",
      "orchestrator takeover",
      "banking-core claim",
      "orchestrator conversation",
      "orchestrator takeover",
    ]);
  });
});

describe("the takeover fails after the claim succeeded", () => {
  test("502 claimed_but_takeover_failed, and a retry of the same call finishes the job", async () => {
    let healthy = false;
    harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", (request) => {
      order.push("orchestrator takeover");
      return healthy ? json(takeoverResponse((request.body as { agent_ref: string }).agent_ref)) : json({ detail: "Internal Server Error" }, 500);
    });

    const failed = await claim();
    expect(failed.status).toBe(502);
    expect(await failed.json()).toEqual({ detail: "claimed_but_takeover_failed" });
    // The claim happened and stays: nothing is rolled back.
    expect(order).toEqual(["banking-core claim", "orchestrator conversation", "orchestrator takeover"]);

    healthy = true;
    const retried = await claim();
    expect(retried.status).toBe(200);
    expect(await retried.json()).toMatchObject({ handoff: { status: "ASSIGNED" }, takeover: { takeover: { active: true } } });
    expect(order.slice(3)).toEqual(["banking-core claim", "orchestrator conversation", "orchestrator takeover"]);
  });

  test.each([
    ["the conversation cannot be found", () => harness.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "Not Found" }, 404))],
    ["the agent API is down for the lookup", () => harness.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "x" }, 500))],
    ["a customer turn holds the conversation (503 turn_in_progress)", () => harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ detail: "turn_in_progress" }, 503, { "Retry-After": "2" }))],
    ["the takeover answer breaks the contract", () => harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ conversation_id: CONVERSATION_ID }))],
    ["the takeover answers with another success status", () => harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json(takeoverResponse(), 201))],
    ["the agent API refuses the BFF's token", () => harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ detail: "Invalid token" }, 401))],
    ["the agent API is disabled (route not mounted)", () => harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ detail: "Not Found" }, 404))],
  ])("%s: 502 claimed_but_takeover_failed", async (_label, arrange) => {
    arrange();
    const response = await claim();
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "claimed_but_takeover_failed" });
    expect(order[0]).toBe("banking-core claim");
  });

  test("the orchestrator being unreachable is the same 502, since the claim is already done", async () => {
    harness.orchestrator.stop();
    const response = await claim();
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "claimed_but_takeover_failed" });
    expect(order).toEqual(["banking-core claim"]);
  });
});

describe("the claim itself fails", () => {
  test("another agent holds the handoff: 409, and the orchestrator is never asked", async () => {
    harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/claim", () => json({ detail: "claimed_by_another_agent" }, 409));
    const response = await claim();
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: "claimed_by_another_agent" });
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("an unknown handoff is 404", async () => {
    harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/claim", () => json({ detail: "Handoff not found" }, 404));
    const response = await claim();
    expect(response.status).toBe(404);
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("banking-core unreachable is 503 unavailable, not a half-done claim", async () => {
    harness.bankingCore.stop();
    const response = await claim();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ detail: "unavailable" });
    expect(harness.orchestrator.requests).toHaveLength(0);
  });

  test("a claim answer that breaks the contract is 502, and the orchestrator is not asked", async () => {
    harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/claim", () => json({ handoff_ref: HANDOFF }));
    const response = await claim();
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "invalid_upstream_response" });
    expect(harness.orchestrator.requests).toHaveLength(0);
  });
});

describe("another agent holds the conversation", () => {
  test("the takeover's 409 is passed on as it is, not reported as a failed step", async () => {
    harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ detail: "taken_over_by_another_agent" }, 409));
    const response = await claim();
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: "taken_over_by_another_agent" });
  });
});
