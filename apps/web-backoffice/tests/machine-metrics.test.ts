import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { metricsMachine } from "../src/machines/metrics";
import { metrics } from "./support/fixtures";
import { fakeFetch, json } from "./support/fake-fetch";

const start = (routes: Parameters<typeof fakeFetch>[0] = {}) => {
  const network = fakeFetch({ "GET /api/metrics": (call) => json(metrics(Number(new URLSearchParams(call.search).get("hours")))), ...routes });
  const actor = createActor(metricsMachine, { input: { api: createApi(network.fetch) } }).start();
  return { actor, network };
};

describe("metrics machine", () => {
  test("loads the 24 hour window first", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.matches("ready"));
    expect(network.calls[0]?.search).toBe("?hours=24");
    expect(actor.getSnapshot().context.data?.window_hours).toBe(24);
  });

  test("the window selector asks for 7 days and back", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.matches("ready"));
    actor.send({ type: "WINDOW.SET", hours: 168 });
    expect(actor.getSnapshot().matches("loading")).toBe(true);
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.data?.window_hours === 168);
    actor.send({ type: "WINDOW.SET", hours: 24 });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.data?.window_hours === 24);
    expect(network.calls.map((call) => call.search)).toEqual(["?hours=24", "?hours=168", "?hours=24"]);
  });

  test("changing the window while loading restarts the request for the new window", async () => {
    const { actor, network } = start();
    actor.send({ type: "WINDOW.SET", hours: 168 });
    await waitFor(actor, (snapshot) => snapshot.matches("ready"));
    expect(actor.getSnapshot().context.data?.window_hours).toBe(168);
    expect(network.calls.at(-1)?.search).toBe("?hours=168");
  });

  test("REFRESH asks again for the same window", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.matches("ready"));
    actor.send({ type: "REFRESH" });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && network.calls.length === 2);
    expect(network.calls[1]?.search).toBe("?hours=24");
  });

  test("a failure is recorded and a later success clears it", async () => {
    let up = false;
    const { actor } = start({ "GET /api/metrics": () => (up ? json(metrics()) : json({ detail: "unavailable" }, 503)) });
    await waitFor(actor, (snapshot) => snapshot.matches("ready"));
    expect(actor.getSnapshot().context.error).toBe("unavailable");
    expect(actor.getSnapshot().context.data).toBeNull();
    up = true;
    actor.send({ type: "REFRESH" });
    await waitFor(actor, (snapshot) => snapshot.matches("ready") && snapshot.context.data !== null);
    expect(actor.getSnapshot().context.error).toBeNull();
  });
});
