// Detective mode's switch in the back office (ADR-0019): read from the orchestrator through the BFF, and turned
// on or off for every customer conversation at once. It moves only within what the environment offers
// (DETECTIVE_MODE); where that is off the switch is shown, disabled, with the reason.

import type { DetectiveState } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

export interface DetectiveInput {
  api: Api;
}

export interface DetectiveContext {
  api: Api;
  state: DetectiveState | null;
  /** Why the last read or change failed. */
  error: ErrorCategory | null;
}

export type DetectiveEvent = { type: "TOGGLE" } | { type: "RETRY" };

export const detectiveMachine = setup({
  types: {
    context: {} as DetectiveContext,
    events: {} as DetectiveEvent,
    input: {} as DetectiveInput,
  },
  actors: {
    load: fromPromise(({ input }: { input: { api: Api } }) => input.api.getDetective()),
    save: fromPromise(({ input }: { input: { api: Api; enabled: boolean } }) => input.api.setDetective(input.enabled)),
  },
  guards: {
    offered: ({ context }) => context.state?.available === true,
  },
  actions: {
    store: assign(({ event }) => ({ state: (event as unknown as { output: DetectiveState }).output, error: null })),
    fail: assign({ error: ({ event }) => categorize((event as unknown as { error: unknown }).error) }),
  },
}).createMachine({
  id: "detective",
  context: ({ input }) => ({ api: input.api, state: null, error: null }),
  initial: "loading",
  states: {
    loading: {
      invoke: {
        src: "load",
        input: ({ context }) => ({ api: context.api }),
        onDone: { target: "ready", actions: "store" },
        onError: { target: "failed", actions: "fail" },
      },
    },
    ready: {
      on: { TOGGLE: { guard: "offered", target: "saving" } },
    },
    saving: {
      invoke: {
        src: "save",
        input: ({ context }) => ({ api: context.api, enabled: !context.state?.enabled }),
        onDone: { target: "ready", actions: "store" },
        // The switch stays where it was; the error says why.
        onError: { target: "ready", actions: "fail" },
      },
    },
    failed: { on: { RETRY: "loading" } },
  },
});
