// A scripted browser for the machine tests: a fake `fetch` that answers the five BFF routes from queues
// (the last answer of a queue repeats), a clock the tests move by hand, and a chat actor wired to both.

import { clientBffRoutes, type Locale } from "@pattern-blue/contracts";
import { createActor, SimulatedClock, waitFor } from "xstate";
import { createApiClient } from "../src/api/client";
import { chatMachine, conversationState, type ChatSnapshot } from "../src/machines/chat.machine";
import { CONVERSATION_ID, CREATE_RESPONSE, FEEDBACK_RESPONSE, SEND_RESPONSE, TRANSCRIPT } from "./fixtures";

export type RouteKey = keyof typeof clientBffRoutes;
export type Responder = Response | "network" | ((call: Call) => Response | "network");

export interface Call {
  key: RouteKey;
  method: string;
  path: string;
  body: unknown;
  headers: Headers;
}

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Response.json(body, { status, headers });

export const START = Date.parse("2026-09-29T15:40:00Z");

function classify(method: string, path: string): RouteKey {
  if (method === "POST" && path === "/api/conversations") return "createConversation";
  if (method === "POST" && /^\/api\/conversations\/[^/]+\/messages$/.test(path)) return "sendMessage";
  if (method === "GET" && /^\/api\/conversations\/[^/]+\/inbox$/.test(path)) return "getInbox";
  if (method === "POST" && /^\/api\/conversations\/[^/]+\/feedback$/.test(path)) return "sendFeedback";
  if (method === "GET" && /^\/api\/conversations\/[^/]+$/.test(path)) return "getTranscript";
  throw new Error(`the machine called a route that is not in the contract: ${method} ${path}`);
}

export function createWorld(options: { visible?: boolean } = {}) {
  const calls: Call[] = [];
  const queues: Record<RouteKey, Responder[]> = {
    createConversation: [json(CREATE_RESPONSE, 201)],
    sendMessage: [json(SEND_RESPONSE)],
    getTranscript: [json(TRANSCRIPT)],
    getInbox: [json({ messages: [] })],
    sendFeedback: [json(FEEDBACK_RESPONSE)],
  };
  let nowMs = START;
  let ids = 0;
  const clock = new SimulatedClock();

  const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://web.test").pathname;
    const method = init?.method ?? "GET";
    const key = classify(method, path);
    const call: Call = {
      key,
      method,
      path,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      headers: new Headers(init?.headers),
    };
    calls.push(call);
    const queue = queues[key];
    const next = queue.length > 1 ? queue.shift()! : queue[0]!;
    const answer = typeof next === "function" ? next(call) : next;
    if (answer === "network") throw new TypeError("Failed to fetch");
    // A queue that repeats its last answer must hand out a fresh body each time.
    return next instanceof Response ? answer.clone() : answer;
  }) as typeof fetch;

  const now = () => nowMs;
  const actor = createActor(chatMachine, {
    clock,
    input: {
      deps: {
        api: createApiClient({ fetch: fakeFetch, now }),
        now,
        newId: () => `msg_test${String(++ids).padStart(8, "0")}`,
      },
      visible: options.visible ?? true,
    },
  });

  const world = {
    actor,
    calls,
    clock,
    /** Replace the answers of a route. */
    script(key: RouteKey, ...responders: Responder[]) {
      queues[key] = responders;
    },
    callsTo(key: RouteKey) {
      return calls.filter((call) => call.key === key);
    },
    get now() {
      return nowMs;
    },
    /** Move both the wall clock and the machine's timers. */
    advance(ms: number) {
      nowMs += ms;
      clock.increment(ms);
    },
    get snapshot(): ChatSnapshot {
      return actor.getSnapshot();
    },
    get state() {
      return conversationState(actor.getSnapshot());
    },
    send(text: string, lang: "es" | "pt" | "en" = "es", locale: Locale | null = null) {
      actor.send({ type: "SEND", text, lang, locale });
    },
    /** Wait until no request is in flight: the conversation is at rest and the follow-up is done. */
    async settle() {
      await waitFor(
        actor,
        (snapshot) => {
          const state = conversationState(snapshot);
          return (
            state !== "creating" &&
            state !== "sending" &&
            snapshot.matches({ followup: "idle" }) &&
            !snapshot.matches({ takeover: { on: { polling: "fetching" } } })
          );
        },
        { timeout: 2000 },
      );
    },
    async until(predicate: (snapshot: ChatSnapshot) => boolean) {
      await waitFor(actor, predicate, { timeout: 2000 });
    },
    /** Let promises that were already resolved run, then look. */
    async tick() {
      for (let i = 0; i < 5; i += 1) await Promise.resolve();
      await Bun.sleep(0);
    },
    stop() {
      actor.stop();
    },
  };
  actor.start();
  return world;
}

export { CONVERSATION_ID };
