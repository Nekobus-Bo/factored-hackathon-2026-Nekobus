import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { choiceComplete, decisionMachine } from "../src/machines/decision";
import { AGENT_EMAIL, closedDetail, escalatedDetail } from "./support/fixtures";
import { fakeFetch, json } from "./support/fake-fetch";

const REF = "hnd_qwertyuiopasdfgh";
const NOW = Date.UTC(2026, 9, 2, 22, 6, 0);

function start(answers: { close?: () => Response; escalate?: () => Response } = {}) {
  const network = fakeFetch({
    "POST /api/handoffs/:ref/close": () => answers.close?.() ?? json({ handoff: closedDetail("APPROVED", AGENT_EMAIL), customer_notified: true }),
    "POST /api/handoffs/:ref/escalate": () => answers.escalate?.() ?? json({ handoff: escalatedDetail() }),
  });
  const actor = createActor(decisionMachine, { input: { api: createApi(network.fetch), ref: REF, department: "FRAUD_OPERATIONS", now: () => NOW } }).start();
  return { actor, network };
}

describe("a decision on a case", () => {
  test("Aprobar asks once, then sends the outcome and keeps what came back", async () => {
    const { actor, network } = start();
    expect(network.calls).toEqual([]);

    actor.send({ type: "OPEN", kind: "APPROVED" });
    expect(actor.getSnapshot().matches("confirming")).toBe(true);
    expect(network.calls).toEqual([]);

    actor.send({ type: "CONFIRM" });
    await waitFor(actor, (snapshot) => snapshot.matches("done"));
    expect(network.calls.map((call) => [call.method, call.path, call.body])).toEqual([["POST", `/api/handoffs/${REF}/close`, { outcome: "APPROVED", reason: null }]]);
    const { result } = actor.getSnapshot().context;
    expect(result).toMatchObject({ kind: "APPROVED", customerNotified: true, at: new Date(NOW).toISOString() });
    expect(result?.handoff.status).toBe("CLOSED");
  });

  test("Rechazar cannot be sent without a reason, and sends the one chosen", async () => {
    const { actor, network } = start({ close: () => json({ handoff: closedDetail("REJECTED", AGENT_EMAIL), customer_notified: false }) });
    actor.send({ type: "OPEN", kind: "REJECTED" });
    actor.send({ type: "CONFIRM" });
    expect(actor.getSnapshot().matches("confirming")).toBe(true);
    expect(network.calls).toEqual([]);

    actor.send({ type: "REASON.SET", reason: "OTHER" });
    actor.send({ type: "CONFIRM" });
    await waitFor(actor, (snapshot) => snapshot.matches("done"));
    expect(network.calls[0]?.body).toEqual({ outcome: "REJECTED", reason: "OTHER" });
    expect(actor.getSnapshot().context.result?.customerNotified).toBe(false);
  });

  test("Escalar needs a team or the urgency; urgency alone keeps the case's department", async () => {
    const { actor, network } = start();
    actor.send({ type: "OPEN", kind: "ESCALATE" });
    actor.send({ type: "CONFIRM" });
    expect(network.calls).toEqual([]);

    actor.send({ type: "URGENT.SET", urgent: true });
    actor.send({ type: "CONFIRM" });
    await waitFor(actor, (snapshot) => snapshot.matches("done"));
    expect(network.calls[0]).toMatchObject({ path: `/api/handoffs/${REF}/escalate`, body: { department: "FRAUD_OPERATIONS", raise_to_urgent: true } });
    expect(actor.getSnapshot().context.result).toMatchObject({ kind: "ESCALATE", customerNotified: null });
  });

  test("Cancelar closes the choice and forgets it; another button replaces it", () => {
    const { actor } = start();
    actor.send({ type: "OPEN", kind: "REJECTED" });
    actor.send({ type: "REASON.SET", reason: "OUT_OF_TIME" });
    actor.send({ type: "OPEN", kind: "ESCALATE" });
    expect(actor.getSnapshot().context).toMatchObject({ kind: "ESCALATE", reason: null });
    actor.send({ type: "CANCEL" });
    expect(actor.getSnapshot().matches("idle")).toBe(true);
    expect(actor.getSnapshot().context.kind).toBeNull();
  });

  test.each([
    [409, "already_closed", "alreadyClosed"],
    [409, "claimed_by_another_agent", "heldByAnother"],
    [409, "outcome_not_allowed", "notAllowed"],
    [503, "unavailable", "unavailable"],
  ] as const)("a %i %s goes back to the choice with the error kept", async (status, detail, category) => {
    const { actor } = start({ close: () => json({ detail }, status) });
    actor.send({ type: "OPEN", kind: "APPROVED" });
    actor.send({ type: "CONFIRM" });
    await waitFor(actor, (snapshot) => snapshot.matches("confirming") && snapshot.context.error !== null);
    expect(actor.getSnapshot().context.error).toBe(category);
    expect(actor.getSnapshot().context.kind).toBe("APPROVED");
  });

  test("a complete choice is what each kind needs", () => {
    const base = { reason: null, department: null, urgent: false } as const;
    expect(choiceComplete({ ...base, kind: "APPROVED" })).toBe(true);
    expect(choiceComplete({ ...base, kind: "RESOLVED" })).toBe(true);
    expect(choiceComplete({ ...base, kind: "REJECTED" })).toBe(false);
    expect(choiceComplete({ ...base, kind: "REJECTED", reason: "OTHER" })).toBe(true);
    expect(choiceComplete({ ...base, kind: "ESCALATE" })).toBe(false);
    expect(choiceComplete({ ...base, kind: "ESCALATE", department: "DISPUTES" })).toBe(true);
    expect(choiceComplete({ ...base, kind: null })).toBe(false);
  });
});
