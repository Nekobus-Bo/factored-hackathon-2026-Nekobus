import { describe, expect, test } from "bun:test";
import type { ToolPolicyResponse } from "@pattern-blue/contracts";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { guardrailsMachine } from "../src/machines/guardrails";
import { demoReset, policyConfig, toolPolicy } from "./support/fixtures";
import { fakeFetch, json } from "./support/fake-fetch";

function start(overrides: Parameters<typeof fakeFetch>[0] = {}) {
  let tools = toolPolicy();
  const network = fakeFetch({
    "GET /api/policy-config": () => json(policyConfig()),
    "PUT /api/policy-config": (call) => json({ ...(call.body as object), version: policyConfig().version + 1 }),
    "GET /api/tool-policy": () => json(tools),
    "PUT /api/tool-policy": (call) => {
      const changes = (call.body as { tools: Record<string, string[]> }).tools;
      tools = { ...tools, version: tools.version + 1, tools: { ...tools.tools, ...changes } } as ToolPolicyResponse;
      return json(tools);
    },
    "POST /api/demo/reset": () => {
      tools = { ...toolPolicy(), version: tools.version + 1 };
      return json(demoReset());
    },
    ...overrides,
  });
  const actor = createActor(guardrailsMachine, { input: { api: createApi(network.fetch) } }).start();
  return { actor, network };
}

const editing = (actor: ReturnType<typeof start>["actor"]) => waitFor(actor, (snapshot) => snapshot.matches({ ready: "editing" }));
const ctx = (actor: ReturnType<typeof start>["actor"]) => actor.getSnapshot().context;

describe("loading", () => {
  test("loads the policy and the tool policy and builds the draft from them", async () => {
    const { actor } = start();
    await editing(actor);
    expect(ctx(actor).draft.mode).toBe("block");
    expect(ctx(actor).draft.thresholds).toEqual({ USD: "100.00", COP: "2,000,000", BRL: "2,500.00", EUR: "500.00" });
    expect(ctx(actor).draft.tools["card.block"]).toEqual(["VERIFIED"]);
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual([]);
    expect(ctx(actor).policy?.version).toBe(7);
    expect(ctx(actor).tools?.version).toBe(4);
    actor.stop();
  });

  test("a failed load can be retried", async () => {
    const { actor, network } = start({ "GET /api/policy-config": () => json({ detail: "unavailable" }, 503) });
    await waitFor(actor, (snapshot) => snapshot.matches("failed"));
    expect(ctx(actor).loadError).toBe("unavailable");
    network.on("GET /api/policy-config", () => json(policyConfig()));
    actor.send({ type: "RETRY" });
    await editing(actor);
    actor.stop();
  });
});

describe("the tool matrix", () => {
  test("a cell outside the code floor does not switch on: it is refused, as the API would", async () => {
    const { actor } = start();
    await editing(actor);
    actor.send({ type: "CELL.TOGGLE", tool: "card.block", state: "ANONYMOUS" });
    expect(ctx(actor).draft.tools["card.block"]).toEqual(["VERIFIED"]);
    expect(ctx(actor).refusal).toEqual({ source: "local", tool: "card.block", state: "ANONYMOUS", floor: ["VERIFIED"] });
    actor.send({ type: "SAVE.REQUEST" });
    expect(actor.getSnapshot().matches({ ready: "editing" })).toBe(true); // nothing to save
    actor.stop();
  });

  test("a cell inside the floor toggles, and a refusal is dismissed by the next change", async () => {
    const { actor } = start();
    await editing(actor);
    actor.send({ type: "CELL.TOGGLE", tool: "otp.send", state: "OTP_PENDING" });
    expect(ctx(actor).draft.tools["otp.send"]).toEqual(["IDENTIFIED"]);
    actor.send({ type: "CELL.TOGGLE", tool: "card.block", state: "LOCKED" });
    expect(ctx(actor).refusal).not.toBeNull();
    actor.send({ type: "CELL.TOGGLE", tool: "otp.send", state: "OTP_PENDING" });
    expect(ctx(actor).draft.tools["otp.send"]).toEqual(["IDENTIFIED", "OTP_PENDING"]);
    expect(ctx(actor).refusal).toBeNull();
    actor.send({ type: "CELL.TOGGLE", tool: "card.block", state: "LOCKED" });
    actor.send({ type: "REFUSAL.DISMISS" });
    expect(ctx(actor).refusal).toBeNull();
    actor.stop();
  });

  test("the master switch turns a tool off everywhere, or back on within its floor only", async () => {
    const { actor } = start();
    await editing(actor);
    actor.send({ type: "TOOL.TOGGLE", tool: "handoff.create" });
    expect(ctx(actor).draft.tools["handoff.create"]).toEqual([]);
    actor.send({ type: "TOOL.TOGGLE", tool: "handoff.create" });
    expect(ctx(actor).draft.tools["handoff.create"]).toHaveLength(6);

    // A tool that is off comes back only in the states its floor allows.
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual(["VERIFIED"]);
    actor.send({ type: "TOOL.TOGGLE", tool: "customer.match" });
    expect(ctx(actor).draft.tools["customer.match"]).toEqual([]);
    actor.send({ type: "TOOL.TOGGLE", tool: "customer.match" });
    expect(ctx(actor).draft.tools["customer.match"]).toEqual(["ANONYMOUS", "IDENTIFIED"]);
    actor.stop();
  });

  test("discard puts the draft back to what is in force", async () => {
    const { actor } = start();
    await editing(actor);
    actor.send({ type: "MODE.SET", mode: "flag" });
    actor.send({ type: "THRESHOLD.SET", currency: "USD", value: "50" });
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    actor.send({ type: "DISCARD" });
    expect(ctx(actor).draft.mode).toBe("block");
    expect(ctx(actor).draft.thresholds.USD).toBe("100.00");
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual([]);
    actor.stop();
  });
});

describe("saving", () => {
  test("nothing changed: there is nothing to confirm", async () => {
    const { actor } = start();
    await editing(actor);
    actor.send({ type: "SAVE.REQUEST" });
    expect(actor.getSnapshot().matches({ ready: "editing" })).toBe(true);
    actor.stop();
  });

  test("an invalid threshold blocks the save", async () => {
    const { actor } = start();
    await editing(actor);
    for (const value of ["", "abc", "0", "-5", "1.234", "1e3", "12,50,0x"]) {
      actor.send({ type: "THRESHOLD.SET", currency: "USD", value });
      actor.send({ type: "SAVE.REQUEST" });
      expect(actor.getSnapshot().matches({ ready: "editing" }), value).toBe(true);
    }
    actor.stop();
  });

  test("a save asks for confirmation, then sends only what changed: the policy, then the tools", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "MODE.SET", mode: "flag" });
    actor.send({ type: "THRESHOLD.SET", currency: "USD", value: "250.50" });
    actor.send({ type: "CELL.TOGGLE", tool: "otp.send", state: "OTP_PENDING" });
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });

    actor.send({ type: "SAVE.REQUEST" });
    expect(actor.getSnapshot().matches({ ready: "confirmingSave" })).toBe(true);
    expect(network.count("PUT /api/policy-config")).toBe(0);

    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);

    expect(network.to("PUT /api/policy-config")[0]?.body).toEqual({
      amount_mode: "flag",
      thresholds_minor: { USD: 25050, COP: 200000000, BRL: 250000, EUR: 50000 },
    });
    // Only the two tools that changed; a tool that is not listed keeps its states.
    expect(network.to("PUT /api/tool-policy")[0]?.body).toEqual({ tools: { "account.get_summary": ["VERIFIED"], "otp.send": ["IDENTIFIED"] } });
    const order = network.calls.filter((call) => call.method === "PUT").map((call) => call.path);
    expect(order).toEqual(["/api/policy-config", "/api/tool-policy"]);

    expect(ctx(actor).saved).toEqual({ policy: 8, tools: 5 });
    expect(ctx(actor).policy?.amount_mode).toBe("flag");
    expect(ctx(actor).tools?.version).toBe(5);
    // Saved: the draft is now the baseline, so there is nothing left to save.
    actor.send({ type: "SAVE.REQUEST" });
    expect(actor.getSnapshot().matches({ ready: "editing" })).toBe(true);
    actor.stop();
  });

  test("only the policy changed: the tool policy is not written", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "MODE.SET", mode: "flag" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);
    expect(network.count("PUT /api/policy-config")).toBe(1);
    expect(network.count("PUT /api/tool-policy")).toBe(0);
    expect(ctx(actor).saved).toEqual({ policy: 8 });
    actor.stop();
  });

  test("only the tools changed: the policy is not written", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);
    expect(network.count("PUT /api/policy-config")).toBe(0);
    expect(network.count("PUT /api/tool-policy")).toBe(1);
    expect(ctx(actor).saved).toEqual({ tools: 5 });
    actor.stop();
  });

  test("cancelling the confirmation writes nothing and keeps the draft", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "MODE.SET", mode: "flag" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CANCEL" });
    expect(actor.getSnapshot().matches({ ready: "editing" })).toBe(true);
    expect(ctx(actor).draft.mode).toBe("flag");
    expect(network.calls.filter((call) => call.method === "PUT")).toHaveLength(0);
    actor.stop();
  });

  test("the API's 422 on the matrix is shown as a refusal, and the draft stays for the agent to fix", async () => {
    const issues = [{ loc: ["body", "tools", "otp.send"], msg: "otp.send cannot be enabled in VERIFIED", type: "code_floor_violation" }];
    const { actor } = start({ "PUT /api/tool-policy": () => json({ detail: issues }, 422) });
    await editing(actor);
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);
    expect(ctx(actor).saveError).toBe("validation");
    expect(ctx(actor).refusal).toEqual({ source: "api", messages: ["otp.send cannot be enabled in VERIFIED"] });
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual(["VERIFIED"]);
    actor.stop();
  });

  test("if the policy saves and the tools do not, the policy stays saved and the error is about the tools", async () => {
    const { actor, network } = start({ "PUT /api/tool-policy": () => json({ detail: "unavailable" }, 503) });
    await editing(actor);
    actor.send({ type: "MODE.SET", mode: "flag" });
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);
    expect(ctx(actor).saved).toEqual({ policy: 8 });
    expect(ctx(actor).saveError).toBe("unavailable");
    expect(ctx(actor).policy?.amount_mode).toBe("flag");
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual(["VERIFIED"]);
    expect(network.count("PUT /api/policy-config")).toBe(1);
    actor.stop();
  });

  test("a policy the API refuses is an error on the screen, not a lost draft", async () => {
    const { actor } = start({ "PUT /api/policy-config": () => json({ detail: "unavailable" }, 503) });
    await editing(actor);
    actor.send({ type: "THRESHOLD.SET", currency: "EUR", value: "600" });
    actor.send({ type: "SAVE.REQUEST" });
    actor.send({ type: "SAVE.CONFIRM" });
    await editing(actor);
    expect(ctx(actor).saveError).toBe("unavailable");
    expect(ctx(actor).draft.thresholds.EUR).toBe("600");
    actor.stop();
  });
});

describe("demo reset", () => {
  test("asks first; on confirm resets, then reloads the tool policy the reset changed", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "TOOL.TOGGLE", tool: "account.get_summary" });
    actor.send({ type: "RESET.REQUEST" });
    expect(actor.getSnapshot().matches({ ready: "confirmingReset" })).toBe(true);
    expect(network.count("POST /api/demo/reset")).toBe(0);

    actor.send({ type: "RESET.CONFIRM" });
    await editing(actor);
    expect(network.count("POST /api/demo/reset")).toBe(1);
    expect(ctx(actor).resetResult).toMatchObject({ cards_reset: 12, tool_policy_changed: true });
    // The unsaved tool draft is gone; the seed is back.
    expect(ctx(actor).draft.tools["account.get_summary"]).toEqual([]);
    expect(ctx(actor).tools?.version).toBe(5);
    actor.stop();
  });

  test("cancelling resets nothing", async () => {
    const { actor, network } = start();
    await editing(actor);
    actor.send({ type: "RESET.REQUEST" });
    actor.send({ type: "RESET.CANCEL" });
    expect(actor.getSnapshot().matches({ ready: "editing" })).toBe(true);
    expect(network.count("POST /api/demo/reset")).toBe(0);
    actor.stop();
  });

  test("a reset that is disabled in this environment (403) says so", async () => {
    const { actor } = start({ "POST /api/demo/reset": () => json({ detail: "Demo fixture reset is disabled in production" }, 403) });
    await editing(actor);
    actor.send({ type: "RESET.REQUEST" });
    actor.send({ type: "RESET.CONFIRM" });
    await editing(actor);
    expect(ctx(actor).resetError).toBe("forbidden");
    expect(ctx(actor).resetResult).toBeNull();
    actor.stop();
  });
});
