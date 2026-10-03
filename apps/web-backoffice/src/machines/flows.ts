// The flows screen's machine: the policy config and the tool policy, read once to draw the state machine,
// the tool by state matrix and the flows from what is in force. Read only: changes are made in Guardrails.

import type { PolicyConfigResponse, ToolPolicyResponse } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

export interface FlowsInput {
  api: Api;
}

export interface FlowsContext {
  api: Api;
  policy: PolicyConfigResponse | null;
  tools: ToolPolicyResponse | null;
  error: ErrorCategory | null;
}

export type FlowsEvent = { type: "RETRY" };

export const flowsMachine = setup({
  types: {
    context: {} as FlowsContext,
    events: {} as FlowsEvent,
    input: {} as FlowsInput,
  },
  actors: {
    load: fromPromise(async ({ input }: { input: { api: Api } }) => {
      const [policy, tools] = await Promise.all([input.api.getPolicyConfig(), input.api.getToolPolicy()]);
      return { policy, tools };
    }),
  },
  actions: {
    store: assign(({ event }) => {
      const { policy, tools } = (event as unknown as { output: { policy: PolicyConfigResponse; tools: ToolPolicyResponse } }).output;
      return { policy, tools, error: null };
    }),
    fail: assign({ error: ({ event }) => categorize((event as unknown as { error: unknown }).error) }),
  },
}).createMachine({
  id: "flows",
  context: ({ input }) => ({ api: input.api, policy: null, tools: null, error: null }),
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
    ready: {},
    failed: { on: { RETRY: "loading" } },
  },
});
