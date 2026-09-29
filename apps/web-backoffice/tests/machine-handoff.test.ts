import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { canClaim, handoffMachine, heldByAnother, heldByMe } from "../src/machines/handoff";
import { AGENT_EMAIL, CONVERSATION_ID, agentMessageResponse, backofficeDetail, claimedDetail, takeoverResponse, transcript } from "./support/fixtures";
import { fakeFetch, json, until } from "./support/fake-fetch";

const POLL_MS = 15;
const REF = "hnd_qwertyuiopasdfgh";

/** The state of the world the fake BFF answers from. */
interface World {
  detail: ReturnType<typeof backofficeDetail>;
  holder: string | null;
  claimFails: (() => Response) | null;
  sendFails: (() => Response) | null;
}

function start(overrides: Partial<World> = {}, options: { agentRef?: string } = {}) {
  const world: World = { detail: backofficeDetail(), holder: null, claimFails: null, sendFails: null, ...overrides };
  const network = fakeFetch({
    "GET /api/handoffs/:ref": () => json(world.detail),
    "POST /api/handoffs/:ref/claim": () => {
      if (world.claimFails) return world.claimFails();
      world.holder = AGENT_EMAIL;
      world.detail = { ...world.detail, ...claimedDetail(AGENT_EMAIL) };
      return json({ handoff: claimedDetail(AGENT_EMAIL), takeover: takeoverResponse(AGENT_EMAIL) });
    },
    "GET /api/conversations/:id": () =>
      json(
        transcript({
          takeover: world.holder ? { active: true, since: new Date().toISOString(), agent_ref: world.holder } : { active: false, since: null, agent_ref: null },
          withAgentMessage: world.holder !== null,
        }),
      ),
    "POST /api/conversations/:id/messages": (call) => {
      if (world.sendFails) return world.sendFails();
      return json(agentMessageResponse((call.body as { text: string }).text));
    },
  });
  let counter = 0;
  const actor = createActor(handoffMachine, {
    input: { api: createApi(network.fetch), ref: REF, agentRef: options.agentRef ?? AGENT_EMAIL, pollMs: POLL_MS, newId: () => `msg_test_${++counter}` },
  }).start();
  return { actor, network, world };
}

const ready = (actor: ReturnType<typeof start>["actor"]) => waitFor(actor, (snapshot) => snapshot.matches({ detail: "ready" }) && snapshot.matches({ transcript: "ready" }));
const live = (actor: ReturnType<typeof start>["actor"]) => waitFor(actor, (snapshot) => snapshot.matches({ transcript: { ready: "live" } }));

describe("loading the case", () => {
  test("loads the detail, then the masked transcript of its conversation", async () => {
    const { actor, network } = start();
    await ready(actor);
    const { context } = actor.getSnapshot();
    expect(context.detail?.handoff_ref).toBe(REF);
    expect(context.conversationId).toBe(CONVERSATION_ID);
    expect(context.messages.length).toBeGreaterThan(0);
    expect(context.language).toBe("es");
    expect(network.calls.map((call) => `${call.method} ${call.path}`)).toEqual([`GET /api/handoffs/${REF}`, `GET /api/conversations/${CONVERSATION_ID}`]);
    actor.stop();
  });

  test("before the takeover the transcript is loaded once and not polled", async () => {
    const { actor, network } = start();
    await ready(actor);
    await Bun.sleep(POLL_MS * 8);
    expect(network.count("GET /api/conversations/:id")).toBe(1);
    expect(actor.getSnapshot().matches({ transcript: { ready: "snapshot" } })).toBe(true);
    actor.stop();
  });

  test("a case whose conversation is gone has no transcript to load", async () => {
    const { actor, network } = start({ detail: backofficeDetail({ conversation_id: null }) });
    await waitFor(actor, (snapshot) => snapshot.matches({ detail: "ready" }));
    await Bun.sleep(POLL_MS * 3);
    expect(actor.getSnapshot().context.conversationId).toBeNull();
    expect(actor.getSnapshot().matches({ transcript: "none" })).toBe(true);
    expect(network.count("GET /api/conversations/:id")).toBe(0);
    actor.stop();
  });

  test("an unknown case is 'notFound'; retry loads it", async () => {
    const network = fakeFetch({ "GET /api/handoffs/:ref": () => json({ detail: "Handoff not found" }, 404) });
    const actor = createActor(handoffMachine, { input: { api: createApi(network.fetch), ref: REF, agentRef: AGENT_EMAIL } }).start();
    await waitFor(actor, (snapshot) => snapshot.matches({ detail: "failed" }));
    expect(actor.getSnapshot().context.detailError).toBe("notFound");
    network.on("GET /api/handoffs/:ref", () => json(backofficeDetail()));
    network.on("GET /api/conversations/:id", () => json(transcript()));
    actor.send({ type: "RETRY" });
    await waitFor(actor, (snapshot) => snapshot.matches({ detail: "ready" }));
    actor.stop();
  });

  test("a transcript that cannot be loaded does not hide the case, and can be retried", async () => {
    const { actor, network } = start();
    network.on("GET /api/conversations/:id", () => json({ detail: "unavailable" }, 503));
    await waitFor(actor, (snapshot) => snapshot.matches({ transcript: "failed" }));
    expect(actor.getSnapshot().context.transcriptError).toBe("unavailable");
    expect(actor.getSnapshot().context.detail).not.toBeNull();
    network.on("GET /api/conversations/:id", () => json(transcript()));
    actor.send({ type: "TRANSCRIPT.RETRY" });
    await waitFor(actor, (snapshot) => snapshot.matches({ transcript: "ready" }));
    actor.stop();
  });
});

describe("taking the case", () => {
  test("claims, then the transcript goes live and is polled every tick", async () => {
    const { actor, network } = start();
    await ready(actor);
    expect(canClaim(actor.getSnapshot().context)).toBe(true);

    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "claimed" }));
    const { context } = actor.getSnapshot();
    expect(context.detail).toMatchObject({ status: "ASSIGNED", assigned_agent: AGENT_EMAIL });
    expect(context.takeover).toMatchObject({ active: true, agent_ref: AGENT_EMAIL });
    expect(heldByMe(context)).toBe(true);
    expect(canClaim(context)).toBe(false);

    await live(actor);
    const seen = network.count("GET /api/conversations/:id");
    await until(() => network.count("GET /api/conversations/:id") >= seen + 3);
    expect(network.count("POST /api/handoffs/:ref/claim")).toBe(1);
    actor.stop();
  });

  test("polling stops while the tab is hidden and resumes when it is visible", async () => {
    const { actor, network } = start();
    await ready(actor);
    actor.send({ type: "CLAIM" });
    await live(actor);

    actor.send({ type: "VISIBILITY", visible: false });
    expect(actor.getSnapshot().matches({ transcript: { ready: { live: "paused" } } })).toBe(true);
    await Bun.sleep(POLL_MS * 2);
    const frozen = network.count("GET /api/conversations/:id");
    await Bun.sleep(POLL_MS * 6);
    expect(network.count("GET /api/conversations/:id")).toBe(frozen);

    actor.send({ type: "VISIBILITY", visible: true });
    await until(() => network.count("GET /api/conversations/:id") > frozen);
    actor.stop();
  });

  test("a case already mine, with the conversation already in my hands, is live from the start", async () => {
    const { actor, network } = start({ holder: AGENT_EMAIL, detail: backofficeDetail({ status: "ASSIGNED", assigned_agent: AGENT_EMAIL, queue_position: null }) });
    await live(actor);
    expect(heldByMe(actor.getSnapshot().context)).toBe(true);
    await until(() => network.count("GET /api/conversations/:id") >= 3);
    actor.stop();
  });

  test("another agent's case can be read but not claimed", async () => {
    const { actor, network } = start({
      holder: "marta@demo.local",
      detail: backofficeDetail({ status: "ASSIGNED", assigned_agent: "marta@demo.local", queue_position: null }),
    });
    await ready(actor);
    const { context } = actor.getSnapshot();
    expect(heldByAnother(context)).toBe(true);
    expect(canClaim(context)).toBe(false);
    actor.send({ type: "CLAIM" });
    await Bun.sleep(POLL_MS * 3);
    expect(network.count("POST /api/handoffs/:ref/claim")).toBe(0);
    // Not mine: no live polling either.
    expect(actor.getSnapshot().matches({ transcript: { ready: "snapshot" } })).toBe(true);
    actor.stop();
  });

  test("a 409 means another agent got there first: conflict, and the case is reloaded to show who", async () => {
    const { actor, network, world } = start();
    await ready(actor);
    world.claimFails = () => {
      world.detail = { ...world.detail, status: "ASSIGNED", assigned_agent: "marta@demo.local", queue_position: null };
      return json({ detail: "claimed_by_another_agent" }, 409);
    };
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "conflict" }));
    expect(actor.getSnapshot().context.claimError).toBe("heldByAnother");
    await waitFor(actor, (snapshot) => snapshot.context.detail?.assigned_agent === "marta@demo.local");
    expect(canClaim(actor.getSnapshot().context)).toBe(false);
    expect(network.count("GET /api/handoffs/:ref")).toBe(2);
    actor.stop();
  });

  test("a 409 from the takeover itself is the same conflict", async () => {
    const { actor, world } = start();
    await ready(actor);
    world.claimFails = () => json({ detail: "taken_over_by_another_agent" }, 409);
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "conflict" }));
    actor.stop();
  });

  test("claimed but the takeover failed: it says so, reloads the case, and the same action can be repeated", async () => {
    const { actor, network, world } = start();
    await ready(actor);
    world.claimFails = () => {
      // The claim did happen in banking-core.
      world.detail = { ...world.detail, ...claimedDetail(AGENT_EMAIL) };
      return json({ detail: "claimed_but_takeover_failed" }, 502);
    };
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "failed" }));
    expect(actor.getSnapshot().context.claimError).toBe("claimedButTakeoverFailed");
    // The reloaded case shows it is mine, so "Tomar caso" is still offered, as a retry.
    await waitFor(actor, (snapshot) => snapshot.context.detail?.assigned_agent === AGENT_EMAIL);
    expect(canClaim(actor.getSnapshot().context)).toBe(true);
    expect(heldByMe(actor.getSnapshot().context)).toBe(false);

    world.claimFails = null;
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "claimed" }));
    expect(actor.getSnapshot().context.claimError).toBeNull();
    await live(actor);
    expect(network.count("POST /api/handoffs/:ref/claim")).toBe(2);
    actor.stop();
  });

  test.each([
    ["the BFF is unreachable", () => json({ detail: "unavailable" }, 503), "unavailable"],
    ["the case vanished", () => json({ detail: "Handoff not found" }, 404), "notFound"],
  ])("%s: claim failed, retry allowed", async (_label, answer, category) => {
    const { actor, world } = start();
    await ready(actor);
    world.claimFails = answer;
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "failed" }));
    expect(actor.getSnapshot().context.claimError).toBe(category as "unavailable");
    world.claimFails = null;
    actor.send({ type: "CLAIM" });
    await waitFor(actor, (snapshot) => snapshot.matches({ claim: "claimed" }));
    actor.stop();
  });
});

describe("replying", () => {
  const takeOver = async (setup: ReturnType<typeof start>) => {
    await ready(setup.actor);
    setup.actor.send({ type: "CLAIM" });
    await live(setup.actor);
  };

  test("a reply carries its own client_message_id, clears the outbox and refreshes the transcript", async () => {
    const setup = start();
    await takeOver(setup);
    const before = setup.network.count("GET /api/conversations/:id");

    setup.actor.send({ type: "SEND", text: "  Hola, ya revisé tu caso.  " });
    expect(setup.actor.getSnapshot().matches({ composer: "sending" })).toBe(true);
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "idle" }));

    const [post] = setup.network.to("POST /api/conversations/:id/messages");
    expect(post?.body).toEqual({ text: "Hola, ya revisé tu caso.", client_message_id: "msg_test_1" });
    expect(setup.actor.getSnapshot().context.outbox).toBeNull();
    await until(() => setup.network.count("GET /api/conversations/:id") > before);

    setup.actor.send({ type: "SEND", text: "Segundo mensaje" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "idle" }) && setup.network.count("POST /api/conversations/:id/messages") === 2);
    expect(setup.network.to("POST /api/conversations/:id/messages")[1]?.body).toMatchObject({ client_message_id: "msg_test_2" });
    setup.actor.stop();
  });

  test("nothing is sent before the takeover, or for an empty text", async () => {
    const setup = start();
    await ready(setup.actor);
    setup.actor.send({ type: "SEND", text: "Hola" });
    expect(setup.actor.getSnapshot().matches({ composer: "idle" })).toBe(true);

    setup.actor.send({ type: "CLAIM" });
    await live(setup.actor);
    setup.actor.send({ type: "SEND", text: "   " });
    expect(setup.actor.getSnapshot().matches({ composer: "idle" })).toBe(true);
    expect(setup.network.count("POST /api/conversations/:id/messages")).toBe(0);
    setup.actor.stop();
  });

  test("a customer turn in flight (503 turn_in_progress) keeps the message and retries it with the same id", async () => {
    const setup = start();
    await takeOver(setup);
    setup.world.sendFails = () => json({ detail: "turn_in_progress" }, 503, { "Retry-After": "2" });

    setup.actor.send({ type: "SEND", text: "Hola" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "failed" }));
    let { context } = setup.actor.getSnapshot();
    expect(context.sendError).toBe("turnInProgress");
    expect(context.sendRetryAfterSeconds).toBe(2);
    expect(context.outbox).toEqual({ text: "Hola", client_message_id: "msg_test_1" });

    setup.world.sendFails = null;
    setup.actor.send({ type: "SEND.RETRY" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "idle" }));
    const ids = setup.network.to("POST /api/conversations/:id/messages").map((call) => (call.body as { client_message_id: string }).client_message_id);
    expect(ids).toEqual(["msg_test_1", "msg_test_1"]);
    expect(setup.actor.getSnapshot().context.sendError).toBeNull();
    setup.actor.stop();
  });

  test("a message that could not be sent can be discarded", async () => {
    const setup = start();
    await takeOver(setup);
    setup.world.sendFails = () => json({ detail: "unavailable" }, 503);
    setup.actor.send({ type: "SEND", text: "Hola" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "failed" }));
    expect(setup.actor.getSnapshot().context.sendError).toBe("unavailable");
    setup.actor.send({ type: "SEND.DISCARD" });
    expect(setup.actor.getSnapshot().matches({ composer: "idle" })).toBe(true);
    expect(setup.actor.getSnapshot().context.outbox).toBeNull();
    setup.actor.stop();
  });

  test("typing a new message after a failure replaces the failed one, with a new id", async () => {
    const setup = start();
    await takeOver(setup);
    setup.world.sendFails = () => json({ detail: "unavailable" }, 503);
    setup.actor.send({ type: "SEND", text: "Primero" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "failed" }));
    setup.world.sendFails = null;
    setup.actor.send({ type: "SEND", text: "Segundo" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "idle" }));
    const bodies = setup.network.to("POST /api/conversations/:id/messages").map((call) => call.body);
    expect(bodies).toEqual([
      { text: "Primero", client_message_id: "msg_test_1" },
      { text: "Segundo", client_message_id: "msg_test_2" },
    ]);
    setup.actor.stop();
  });

  test("losing the takeover (409 no_active_takeover) disables the composer", async () => {
    const setup = start();
    await takeOver(setup);
    setup.world.sendFails = () => json({ detail: "no_active_takeover" }, 409);
    setup.actor.send({ type: "SEND", text: "Hola" });
    await waitFor(setup.actor, (snapshot) => snapshot.matches({ composer: "failed" }));
    expect(setup.actor.getSnapshot().context.sendError).toBe("noActiveTakeover");
    expect(heldByMe(setup.actor.getSnapshot().context)).toBe(false);
    setup.actor.stop();
  });
});
