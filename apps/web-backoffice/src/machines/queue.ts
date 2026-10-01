// The queue screen's machine: load the handoff list, refresh it every 3 s while the tab is visible.
//
//   active ── fetching ──▶ waiting ── after POLL ──▶ fetching ...
//      │  (FILTER.SET and REFRESH restart the fetch)
//      └─ VISIBILITY hidden ──▶ paused ── VISIBILITY visible ──▶ active (fetches at once)
//
// A failed refresh keeps the last list and records the error; the next tick tries again.

import type { HandoffItem, HandoffStatus } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

/** The status filter: the open cases (both statuses, the API's default) or one status. */
export type QueueFilter = "OPEN" | HandoffStatus;

export const QUEUE_POLL_MS = 3000;

export interface QueueInput {
  api: Api;
  pollMs?: number;
  now?: () => number;
}

export interface QueueContext {
  api: Api;
  pollMs: number;
  now: () => number;
  filter: QueueFilter;
  items: HandoffItem[];
  /** True once a list has arrived: before that the screen shows "loading", not "empty". */
  loaded: boolean;
  error: ErrorCategory | null;
  updatedAt: number | null;
}

export type QueueEvent =
  | { type: "FILTER.SET"; filter: QueueFilter }
  | { type: "REFRESH" }
  | { type: "VISIBILITY"; visible: boolean };

const statusesOf = (filter: QueueFilter): HandoffStatus[] | undefined => (filter === "OPEN" ? undefined : [filter]);

export const queueMachine = setup({
  types: {
    context: {} as QueueContext,
    events: {} as QueueEvent,
    input: {} as QueueInput,
  },
  actors: {
    load: fromPromise(({ input }: { input: { api: Api; filter: QueueFilter } }) => input.api.listHandoffs(statusesOf(input.filter))),
  },
  delays: {
    POLL: ({ context }) => context.pollMs,
  },
  guards: {
    hidden: ({ event }) => event.type === "VISIBILITY" && !event.visible,
    visible: ({ event }) => event.type === "VISIBILITY" && event.visible,
  },
  actions: {
    store: assign(({ context, event }) => {
      const output = (event as unknown as { output: { items: HandoffItem[] } }).output;
      return { items: output.items, loaded: true, error: null, updatedAt: context.now() };
    }),
    storeError: assign(({ event }) => {
      const error = (event as unknown as { error: unknown }).error;
      return { loaded: true, error: categorize(error) };
    }),
    setFilter: assign({ filter: ({ event }) => (event.type === "FILTER.SET" ? event.filter : "OPEN") }),
  },
}).createMachine({
  id: "queue",
  context: ({ input }) => ({
    api: input.api,
    pollMs: input.pollMs ?? QUEUE_POLL_MS,
    now: input.now ?? Date.now,
    filter: "OPEN",
    items: [],
    loaded: false,
    error: null,
    updatedAt: null,
  }),
  initial: "active",
  states: {
    active: {
      initial: "fetching",
      on: {
        "FILTER.SET": { target: ".fetching", reenter: true, actions: "setFilter" },
        REFRESH: { target: ".fetching", reenter: true },
        VISIBILITY: { guard: "hidden", target: "paused" },
      },
      states: {
        fetching: {
          invoke: {
            src: "load",
            input: ({ context }) => ({ api: context.api, filter: context.filter }),
            onDone: { target: "waiting", actions: "store" },
            onError: { target: "waiting", actions: "storeError" },
          },
        },
        waiting: {
          after: { POLL: { target: "fetching" } },
        },
      },
    },
    paused: {
      on: {
        VISIBILITY: { guard: "visible", target: "active" },
        "FILTER.SET": { actions: "setFilter" },
      },
    },
  },
});

