import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { detectiveMachine } from "../src/machines/detective";
import { fakeFetch, json } from "./support/fake-fetch";

function start(available = true, overrides: Parameters<typeof fakeFetch>[0] = {}) {
  let enabled = available;
  const network = fakeFetch({
    "GET /api/detective": () => json({ available, enabled }),
    "PUT /api/detective": (call) => {
      if (!available) return json({ detail: "detective_unavailable" }, 409);
      enabled = (call.body as { enabled: boolean }).enabled;
      return json({ available, enabled });
    },
    ...overrides,
  });
  const actor = createActor(detectiveMachine, { input: { api: createApi(network.fetch) } }).start();
  return { actor, network };
}

const ready = (actor: ReturnType<typeof start>["actor"]) => waitFor(actor, (snapshot) => snapshot.matches("ready"));

describe("the back office's detective switch (ADR-0019)", () => {
  test("reads the state, then TOGGLE turns it off and on", async () => {
    const { actor, network } = start();
    await ready(actor);
    expect(actor.getSnapshot().context.state).toEqual({ available: true, enabled: true });

    actor.send({ type: "TOGGLE" });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.state?.enabled === false);
    expect(network.calls.at(-1)?.body).toEqual({ enabled: false });

    actor.send({ type: "TOGGLE" });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.state?.enabled === true);
  });

  test("where it is not offered, TOGGLE does nothing", async () => {
    const { actor, network } = start(false);
    await ready(actor);
    actor.send({ type: "TOGGLE" });
    expect(actor.getSnapshot().matches("ready")).toBe(true);
    expect(network.calls.filter((call) => call.method === "PUT")).toHaveLength(0);
  });

  test("a failed change keeps the switch where it was and says why", async () => {
    const { actor } = start(true, { "PUT /api/detective": () => json({ detail: "unavailable" }, 503) });
    await ready(actor);
    actor.send({ type: "TOGGLE" });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.error !== null);
    expect(actor.getSnapshot().context.state?.enabled).toBe(true);
    expect(actor.getSnapshot().context.error).toBe("unavailable");
  });

  test("a failed read can be retried", async () => {
    let answers = 0;
    const { actor } = start(true, {
      "GET /api/detective": () => (++answers === 1 ? json({ detail: "unavailable" }, 503) : json({ available: true, enabled: false })),
    });
    await waitFor(actor, (snapshot) => snapshot.matches("failed"));
    actor.send({ type: "RETRY" });
    await ready(actor);
    expect(actor.getSnapshot().context.state).toEqual({ available: true, enabled: false });
  });
});
