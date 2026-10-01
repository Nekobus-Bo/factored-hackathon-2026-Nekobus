// The metrics screen's machine: one window (24 h or 7 d), loaded on entry and on demand.
// Metrics are a report, not a live view, so there is no polling: "Actualizar" asks again.

import type { MetricsResponse } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

/** The windows the screen offers, in hours. The API accepts 1 to 720. */
export const METRICS_WINDOWS = [24, 168] as const;
export type MetricsWindow = (typeof METRICS_WINDOWS)[number];

export interface MetricsInput {
  api: Api;
  hours?: MetricsWindow;
}

export interface MetricsContext {
  api: Api;
  hours: MetricsWindow;
  data: MetricsResponse | null;
  error: ErrorCategory | null;
}

export type MetricsEvent = { type: "WINDOW.SET"; hours: MetricsWindow } | { type: "REFRESH" };

export const metricsMachine = setup({
  types: {
    context: {} as MetricsContext,
    events: {} as MetricsEvent,
    input: {} as MetricsInput,
  },
  actors: {
    load: fromPromise(({ input }: { input: { api: Api; hours: number } }) => input.api.getMetrics(input.hours)),
  },
  actions: {
    store: assign({ data: ({ event }) => (event as unknown as { output: MetricsResponse }).output, error: null }),
    fail: assign({ error: ({ event }) => categorize((event as unknown as { error: unknown }).error) }),
    setWindow: assign({ hours: ({ event, context }) => (event.type === "WINDOW.SET" ? event.hours : context.hours) }),
  },
}).createMachine({
  id: "metrics",
  context: ({ input }) => ({ api: input.api, hours: input.hours ?? 24, data: null, error: null }),
  initial: "loading",
  states: {
    loading: {
      invoke: {
        src: "load",
        input: ({ context }) => ({ api: context.api, hours: context.hours }),
        onDone: { target: "ready", actions: "store" },
        onError: { target: "ready", actions: "fail" },
      },
      on: { "WINDOW.SET": { target: "loading", reenter: true, actions: "setWindow" } },
    },
    ready: {
      on: {
        "WINDOW.SET": { target: "loading", actions: "setWindow" },
        REFRESH: "loading",
      },
    },
  },
});
