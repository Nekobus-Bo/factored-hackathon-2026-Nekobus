import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { queueMachine } from "../src/machines/queue";
import { handoffItems } from "./support/fixtures";
import { fakeFetch, json, until } from "./support/fake-fetch";

const POLL_MS = 15;

function start(routes: Parameters<typeof fakeFetch>[0] = {}) {
  const network = fakeFetch({
    "GET /api/handoffs": (call) => {
      const wanted = new URLSearchParams(call.search).getAll("status");
      return json({ items: handoffItems().filter((item) => wanted.length === 0 || wanted.includes(item.status)) });
    },
    ...routes,
  });
  const actor = createActor(queueMachine, { input: { api: createApi(network.fetch), pollMs: POLL_MS } }).start();
  return { actor, network };
}

describe("queue machine", () => {
  test("loads the open cases on entry", async () => {
    const { actor, network } = start();
    expect(actor.getSnapshot().context.loaded).toBe(false);
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    expect(actor.getSnapshot().context.items).toHaveLength(4);
    expect(actor.getSnapshot().context.error).toBeNull();
    expect(actor.getSnapshot().context.updatedAt).not.toBeNull();
    // The default filter is the API's default: no status parameter at all.
    expect(network.calls[0]?.search).toBe("");
    actor.stop();
  });

  test("polls: the list is asked for again on every tick", async () => {
    const { actor, network } = start();
    await until(() => network.count("GET /api/handoffs") >= 4);
    actor.stop();
  });

  test("a new case shows up on the next tick", async () => {
    let items = handoffItems();
    const { actor } = start({ "GET /api/handoffs": () => json({ items }) });
    await waitFor(actor, (snapshot) => snapshot.context.items.length === 4);
    items = [...handoffItems(), { ...(handoffItems()[0] as (typeof items)[number]), handoff_ref: "hnd_newnewnewnewnewn", queue_position: 4 }];
    await waitFor(actor, (snapshot) => snapshot.context.items.length === 5);
    actor.stop();
  });

  test("the status filter is sent to the BFF and restarts the fetch", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    actor.send({ type: "FILTER.SET", filter: "QUEUED" });
    await waitFor(actor, (snapshot) => snapshot.context.filter === "QUEUED" && snapshot.context.items.every((item) => item.status === "QUEUED") && snapshot.context.items.length === 3);
    expect(network.calls.some((call) => call.search === "?status=QUEUED")).toBe(true);

    actor.send({ type: "FILTER.SET", filter: "ASSIGNED" });
    await waitFor(actor, (snapshot) => snapshot.context.items.length === 1);
    expect(network.calls.some((call) => call.search === "?status=ASSIGNED")).toBe(true);

    actor.send({ type: "FILTER.SET", filter: "OPEN" });
    await waitFor(actor, (snapshot) => snapshot.context.items.length === 4);
    actor.stop();
  });

  test("stops polling while the tab is hidden and fetches at once when it is visible again", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    actor.send({ type: "VISIBILITY", visible: false });
    expect(actor.getSnapshot().value).toBe("paused");
    await Bun.sleep(POLL_MS * 2); // let a fetch that was in flight land
    const frozen = network.count("GET /api/handoffs");
    await Bun.sleep(POLL_MS * 6);
    expect(network.count("GET /api/handoffs")).toBe(frozen);

    actor.send({ type: "VISIBILITY", visible: true });
    expect(actor.getSnapshot().matches({ active: "fetching" })).toBe(true);
    await until(() => network.count("GET /api/handoffs") > frozen);
    actor.stop();
  });

  test("changing the filter while hidden is remembered and used on return", async () => {
    const { actor, network } = start();
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    actor.send({ type: "VISIBILITY", visible: false });
    actor.send({ type: "FILTER.SET", filter: "ASSIGNED" });
    expect(actor.getSnapshot().value).toBe("paused");
    actor.send({ type: "VISIBILITY", visible: true });
    await until(() => network.calls.some((call) => call.search === "?status=ASSIGNED"));
    actor.stop();
  });

  test("a failed refresh keeps the last list, records why, and recovers on the next tick", async () => {
    let healthy = true;
    const { actor } = start({ "GET /api/handoffs": () => (healthy ? json({ items: handoffItems() }) : json({ detail: "unavailable" }, 503)) });
    await waitFor(actor, (snapshot) => snapshot.context.items.length === 4);

    healthy = false;
    await waitFor(actor, (snapshot) => snapshot.context.error === "unavailable");
    expect(actor.getSnapshot().context.items).toHaveLength(4);

    healthy = true;
    await waitFor(actor, (snapshot) => snapshot.context.error === null);
    actor.stop();
  });

  test("a queue that cannot be loaded is 'loaded' with an error, not stuck loading", async () => {
    const { actor } = start({ "GET /api/handoffs": () => json({ detail: "unavailable" }, 503) });
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    expect(actor.getSnapshot().context.error).toBe("unavailable");
    expect(actor.getSnapshot().context.items).toEqual([]);
    actor.stop();
  });

  test("REFRESH asks again at once", async () => {
    const network = fakeFetch({ "GET /api/handoffs": () => json({ items: handoffItems() }) });
    const actor = createActor(queueMachine, { input: { api: createApi(network.fetch), pollMs: 60_000 } }).start();
    await waitFor(actor, (snapshot) => snapshot.context.loaded);
    expect(network.count("GET /api/handoffs")).toBe(1);
    actor.send({ type: "REFRESH" });
    await until(() => network.count("GET /api/handoffs") === 2);
    actor.stop();
  });
});
