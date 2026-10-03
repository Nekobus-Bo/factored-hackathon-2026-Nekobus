// Closing and escalating a case through the BFF (ADR-0018): banking-core decides, then the orchestrator
// hears about it, with the session's agent and each service's own token.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { AGENT_EMAIL, CLOSING_MESSAGES, CONVERSATION_ID, SESSION_REF, transcript } from "./support/fixtures";
import { makeHarness, type Harness } from "./support/harness";

const json = (body: unknown, status = 200) => Response.json(body, { status });
const HANDOFF = "hnd_qwertyuiopasdfgh";

let harness: Harness;
let cookie: string;

beforeEach(async () => {
  harness = makeHarness();
  cookie = await harness.login();
});
afterEach(() => harness.stop());

const close = (body: unknown, init: { cookie?: string | null } = {}) =>
  harness.request(`/api/handoffs/${HANDOFF}/close`, { method: "POST", cookie: init.cookie === undefined ? cookie : init.cookie, body });
const escalate = (body: unknown) => harness.request(`/api/handoffs/${HANDOFF}/escalate`, { method: "POST", cookie, body });
const paths = (requests: { method: string; path: string }[]) => requests.map((request) => `${request.method} ${request.path}`);

describe("close", () => {
  test("closes in banking-core for the session's agent, then sends the closing message as that agent", async () => {
    const response = await close({ outcome: "APPROVED" });

    expect(response.status).toBe(200);
    const body = (await response.json()) as { handoff: { status: string; outcome: string }; customer_notified: boolean };
    expect(body.handoff).toMatchObject({ status: "CLOSED", outcome: "APPROVED" });
    expect(body.customer_notified).toBe(true);

    const [decision] = harness.bankingCore.requests;
    expect(decision).toMatchObject({ method: "POST", path: `/v1/admin/handoffs/${HANDOFF}/close`, body: { agent_ref: AGENT_EMAIL, outcome: "APPROVED", reason: null } });
    expect(decision?.headers.authorization).toBe("Bearer test-admin-token");
    expect(paths(harness.orchestrator.requests)).toEqual([
      `GET /v1/agent/sessions/${SESSION_REF}/conversation`,
      `GET /v1/agent/conversations/${CONVERSATION_ID}`,
      `POST /v1/agent/conversations/${CONVERSATION_ID}/takeover`,
      `POST /v1/agent/conversations/${CONVERSATION_ID}/messages`,
    ]);
    const message = harness.orchestrator.requests.at(-1);
    expect(message?.headers["x-agent-ref"]).toBe(AGENT_EMAIL);
    // The conversation is in Spanish, and a retry reuses the same id, so it cannot send twice.
    expect(message?.body).toEqual({ text: CLOSING_MESSAGES.APPROVED.es, client_message_id: `close_${HANDOFF}` });
  });

  test("the message follows the conversation's language", async () => {
    harness.orchestrator.on("GET /v1/agent/conversations/:id", () => json({ ...transcript(), language: "pt" }));

    await close({ outcome: "REJECTED", reason: "OTHER" });

    const [decision] = harness.bankingCore.requests;
    expect(decision?.body).toEqual({ agent_ref: AGENT_EMAIL, outcome: "REJECTED", reason: "OTHER" });
    expect((harness.orchestrator.requests.at(-1)?.body as { text: string }).text).toBe(CLOSING_MESSAGES.REJECTED.pt);
  });

  test("an expired conversation still closes the case, and says the customer was not told", async () => {
    harness.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "Conversation not found" }, 404));

    const response = await close({ outcome: "APPROVED" });

    expect(response.status).toBe(200);
    expect(((await response.json()) as { customer_notified: boolean }).customer_notified).toBe(false);
    expect(paths(harness.orchestrator.requests)).toEqual([`GET /v1/agent/sessions/${SESSION_REF}/conversation`]);
  });

  test("another agent holding the conversation means no message, not a failed close", async () => {
    harness.orchestrator.on("POST /v1/agent/conversations/:id/takeover", () => json({ detail: "taken_over_by_another_agent" }, 409));

    const response = await close({ outcome: "APPROVED" });

    expect(response.status).toBe(200);
    expect(((await response.json()) as { customer_notified: boolean }).customer_notified).toBe(false);
    expect(paths(harness.orchestrator.requests)).not.toContain(`POST /v1/agent/conversations/${CONVERSATION_ID}/messages`);
  });

  test.each([
    [409, "already_closed"],
    [409, "claimed_by_another_agent"],
    [409, "outcome_not_allowed"],
    [409, "reason_required"],
    [404, "handoff_not_found"],
  ])("banking-core's %i %s passes through and nothing reaches the orchestrator", async (status, detail) => {
    harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/close", () => json({ detail }, status));

    const response = await close({ outcome: "APPROVED" });

    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail });
    expect(harness.orchestrator.requests).toEqual([]);
  });

  test.each([
    { outcome: "MAYBE" },
    { outcome: "REJECTED", reason: "BECAUSE" },
    { outcome: "APPROVED", agent_ref: "someone@else.example" },
    {},
  ])("a malformed body is 422 and reaches no upstream: %j", async (body) => {
    const response = await close(body);

    expect(response.status).toBe(422);
    expect(harness.bankingCore.requests).toEqual([]);
  });

  test("needs the session", async () => {
    expect((await close({ outcome: "APPROVED" }, { cookie: null })).status).toBe(401);
    expect(harness.bankingCore.requests).toEqual([]);
  });
});

describe("escalate", () => {
  test("goes back to the queue in banking-core, then releases the conversation for the next agent", async () => {
    const response = await escalate({ department: "DISPUTES", raise_to_urgent: true });

    expect(response.status).toBe(200);
    expect(((await response.json()) as { handoff: { status: string } }).handoff.status).toBe("QUEUED");
    expect(harness.bankingCore.requests[0]?.body).toEqual({ agent_ref: AGENT_EMAIL, department: "DISPUTES", raise_to_urgent: true });
    const release = harness.orchestrator.requests.at(-1);
    expect(release).toMatchObject({ method: "POST", path: `/v1/agent/conversations/${CONVERSATION_ID}/release`, body: { agent_ref: AGENT_EMAIL, handoff_ref: HANDOFF } });
    expect(release?.headers.authorization).toBe("Bearer test-agent-token");
  });

  test("a conversation that is gone has nothing to release; the escalation stands", async () => {
    harness.orchestrator.on("GET /v1/agent/sessions/:session_ref/conversation", () => json({ detail: "Conversation not found" }, 404));

    const response = await escalate({ department: "DISPUTES", raise_to_urgent: false });

    expect(response.status).toBe(200);
    expect(paths(harness.orchestrator.requests)).toEqual([`GET /v1/agent/sessions/${SESSION_REF}/conversation`]);
  });

  test("banking-core's refusal passes through and nothing is released", async () => {
    harness.bankingCore.on("POST /v1/admin/handoffs/:handoff_ref/escalate", () => json({ detail: "nothing_to_escalate" }, 409));

    const response = await escalate({ department: "FRAUD_OPERATIONS", raise_to_urgent: false });

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ detail: "nothing_to_escalate" });
    expect(harness.orchestrator.requests).toEqual([]);
  });

  test("the body is a department and the flag, nothing else", async () => {
    expect((await escalate({ department: "LEGAL", raise_to_urgent: false })).status).toBe(422);
    expect((await escalate({ department: "DISPUTES" })).status).toBe(422);
    expect(harness.bankingCore.requests).toEqual([]);
  });
});
