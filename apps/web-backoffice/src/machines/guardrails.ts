// The guardrails screen's machine: thresholds and amount mode (banking-core policy config), the tool by
// state matrix (tool policy) and the demo reset.
//
//   loading ──▶ ready.editing ── SAVE.REQUEST ──▶ confirmingSave ── SAVE.CONFIRM ──▶ savingPolicy ──▶ savingTools ──▶ editing
//                    │                                  (only what changed is sent, each with its own PUT)
//                    └─ RESET.REQUEST ──▶ confirmingReset ── RESET.CONFIRM ──▶ resetting ──▶ editing
//
// The code floor is enforced twice on purpose. The matrix never lets a cell outside the floor be
// switched on (a click is answered with the refusal the API would give), and the API refuses a widening
// with a 422 whatever the client does.

import type {
  AmountMode,
  DemoResetResponse,
  PolicyConfigResponse,
  ToolPolicyResponse,
  VerificationState,
} from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, validationMessages, type ErrorCategory } from "../api/errors";
import { changedTools, draftFrom, floorOf, invalidThresholds, policyDirty, thresholdsMinor, toggleAll, toggleState, toolsDirty, type Draft } from "./policy-draft";

/** Why a cell did not switch on: the click was outside the code floor, or the API said so with a 422. */
export type Refusal =
  | { source: "local"; tool: string; state: VerificationState; floor: VerificationState[] }
  | { source: "api"; messages: string[] };

export interface GuardrailsInput {
  api: Api;
}

export interface GuardrailsContext {
  api: Api;
  policy: PolicyConfigResponse | null;
  tools: ToolPolicyResponse | null;
  draft: Draft;
  refusal: Refusal | null;
  loadError: ErrorCategory | null;
  /** The versions the last save created; only the parts that were saved. */
  saved: { policy?: number; tools?: number } | null;
  saveError: ErrorCategory | null;
  resetResult: DemoResetResponse | null;
  resetError: ErrorCategory | null;
}

export type GuardrailsEvent =
  | { type: "RETRY" }
  | { type: "MODE.SET"; mode: AmountMode }
  | { type: "THRESHOLD.SET"; currency: string; value: string }
  | { type: "CELL.TOGGLE"; tool: string; state: VerificationState }
  | { type: "TOOL.TOGGLE"; tool: string }
  | { type: "REFUSAL.DISMISS" }
  | { type: "DISCARD" }
  | { type: "SAVE.REQUEST" }
  | { type: "SAVE.CONFIRM" }
  | { type: "SAVE.CANCEL" }
  | { type: "RESET.REQUEST" }
  | { type: "RESET.CONFIRM" }
  | { type: "RESET.CANCEL" };

const emptyDraft: Draft = { mode: "flag", thresholds: {}, tools: {} };

const outputOf = <T>(event: unknown): T => (event as { output: T }).output;
const errorOf = (event: unknown): unknown => (event as { error: unknown }).error;

export const guardrailsMachine = setup({
  types: {
    context: {} as GuardrailsContext,
    events: {} as GuardrailsEvent,
    input: {} as GuardrailsInput,
  },
  actors: {
    load: fromPromise(async ({ input }: { input: { api: Api } }) => {
      const [policy, tools] = await Promise.all([input.api.getPolicyConfig(), input.api.getToolPolicy()]);
      return { policy, tools };
    }),
    savePolicy: fromPromise(({ input }: { input: { api: Api; body: { amount_mode: AmountMode; thresholds_minor: Record<string, number> } } }) => input.api.putPolicyConfig(input.body)),
    saveTools: fromPromise(({ input }: { input: { api: Api; tools: Record<string, VerificationState[]> } }) => input.api.putToolPolicy({ tools: input.tools })),
    reset: fromPromise(async ({ input }: { input: { api: Api } }) => {
      const result = await input.api.resetDemo();
      // The reset puts the tool policy back to its seed: what is on screen must follow.
      const tools = await input.api.getToolPolicy();
      return { result, tools };
    }),
  },
  guards: {
    canSave: ({ context }) => {
      const { policy, tools, draft } = context;
      if (!policy || !tools) return false;
      if (invalidThresholds(draft).length > 0) return false;
      return policyDirty(draft, policy) || toolsDirty(draft, tools);
    },
    policyDirty: ({ context }) => context.policy !== null && policyDirty(context.draft, context.policy),
    toolsDirty: ({ context }) => context.tools !== null && toolsDirty(context.draft, context.tools),
    outsideFloor: ({ context, event }) => {
      if (event.type !== "CELL.TOGGLE" || !context.tools) return false;
      return !floorOf(context.tools, event.tool).includes(event.state);
    },
  },
  actions: {
    applyLoaded: assign(({ event }) => {
      const { policy, tools } = outputOf<{ policy: PolicyConfigResponse; tools: ToolPolicyResponse }>(event);
      return { policy, tools, draft: draftFrom(policy, tools), loadError: null };
    }),
    loadFailed: assign({ loadError: ({ event }) => categorize(errorOf(event)) }),
    setMode: assign(({ context, event }) => (event.type === "MODE.SET" ? { draft: { ...context.draft, mode: event.mode } } : {})),
    setThreshold: assign(({ context, event }) =>
      event.type === "THRESHOLD.SET" ? { draft: { ...context.draft, thresholds: { ...context.draft.thresholds, [event.currency]: event.value } } } : {},
    ),
    toggleCell: assign(({ context, event }) => {
      if (event.type !== "CELL.TOGGLE") return {};
      const current = context.draft.tools[event.tool] ?? [];
      return { refusal: null, draft: { ...context.draft, tools: { ...context.draft.tools, [event.tool]: toggleState(current, event.state) } } };
    }),
    toggleTool: assign(({ context, event }) => {
      if (event.type !== "TOOL.TOGGLE" || !context.tools) return {};
      const current = context.draft.tools[event.tool] ?? [];
      const next = toggleAll(current, floorOf(context.tools, event.tool));
      return { refusal: null, draft: { ...context.draft, tools: { ...context.draft.tools, [event.tool]: next } } };
    }),
    refuseCell: assign(({ context, event }) =>
      event.type === "CELL.TOGGLE" && context.tools
        ? { refusal: { source: "local" as const, tool: event.tool, state: event.state, floor: floorOf(context.tools, event.tool) } }
        : {},
    ),
    dismissRefusal: assign({ refusal: null }),
    discard: assign(({ context }) => (context.policy && context.tools ? { draft: draftFrom(context.policy, context.tools), refusal: null, saveError: null, saved: null } : {})),
    clearOutcome: assign({ saved: null, saveError: null, resetResult: null, resetError: null }),
    policySaved: assign(({ context, event }) => {
      const policy = outputOf<PolicyConfigResponse>(event);
      // The saved values become the baseline; the tool draft is untouched.
      const tools = context.tools;
      return {
        policy,
        draft: tools ? { ...draftFrom(policy, tools), tools: context.draft.tools } : context.draft,
        saved: { ...context.saved, policy: policy.version },
      };
    }),
    toolsSaved: assign(({ context, event }) => {
      const tools = outputOf<ToolPolicyResponse>(event);
      const policy = context.policy;
      return {
        tools,
        draft: policy ? { ...draftFrom(policy, tools), mode: context.draft.mode, thresholds: context.draft.thresholds } : context.draft,
        saved: { ...context.saved, tools: tools.version },
      };
    }),
    saveFailed: assign({ saveError: ({ event }) => categorize(errorOf(event)) }),
    saveToolsFailed: assign(({ event }) => {
      const error = errorOf(event);
      const category = categorize(error);
      return {
        saveError: category,
        // A 422 on the matrix is the API refusing a widening: show it the way a local refusal is shown.
        refusal: category === "validation" ? { source: "api" as const, messages: validationMessages(error) } : null,
      };
    }),
    resetDone: assign(({ context, event }) => {
      const { result, tools } = outputOf<{ result: DemoResetResponse; tools: ToolPolicyResponse }>(event);
      const policy = context.policy;
      return {
        tools,
        resetResult: result,
        resetError: null,
        refusal: null,
        // Tool drafts are discarded (the seed is back); the threshold and mode drafts are kept.
        draft: policy ? { ...draftFrom(policy, tools), mode: context.draft.mode, thresholds: context.draft.thresholds } : context.draft,
      };
    }),
    resetFailed: assign({ resetError: ({ event }) => categorize(errorOf(event)), resetResult: null }),
  },
}).createMachine({
  id: "guardrails",
  context: ({ input }) => ({
    api: input.api,
    policy: null,
    tools: null,
    draft: emptyDraft,
    refusal: null,
    loadError: null,
    saved: null,
    saveError: null,
    resetResult: null,
    resetError: null,
  }),
  initial: "loading",
  states: {
    loading: {
      invoke: {
        src: "load",
        input: ({ context }) => ({ api: context.api }),
        onDone: { target: "ready", actions: "applyLoaded" },
        onError: { target: "failed", actions: "loadFailed" },
      },
    },
    failed: {
      on: { RETRY: "loading" },
    },
    ready: {
      initial: "editing",
      states: {
        editing: {
          on: {
            "MODE.SET": { actions: ["setMode", "clearOutcome"] },
            "THRESHOLD.SET": { actions: ["setThreshold", "clearOutcome"] },
            "CELL.TOGGLE": [
              { guard: "outsideFloor", actions: "refuseCell" },
              { actions: ["toggleCell", "clearOutcome"] },
            ],
            "TOOL.TOGGLE": { actions: ["toggleTool", "clearOutcome"] },
            "REFUSAL.DISMISS": { actions: "dismissRefusal" },
            DISCARD: { actions: "discard" },
            "SAVE.REQUEST": { guard: "canSave", target: "confirmingSave" },
            "RESET.REQUEST": { target: "confirmingReset" },
          },
        },
        confirmingSave: {
          on: {
            "SAVE.CANCEL": "editing",
            "SAVE.CONFIRM": [
              { guard: "policyDirty", target: "savingPolicy", actions: "clearOutcome" },
              { guard: "toolsDirty", target: "savingTools", actions: "clearOutcome" },
              { target: "editing" },
            ],
          },
        },
        savingPolicy: {
          invoke: {
            src: "savePolicy",
            input: ({ context }) => ({
              api: context.api,
              body: { amount_mode: context.draft.mode, thresholds_minor: thresholdsMinor(context.draft) ?? {} },
            }),
            onDone: [
              { guard: "toolsDirty", target: "savingTools", actions: "policySaved" },
              { target: "editing", actions: "policySaved" },
            ],
            onError: { target: "editing", actions: "saveFailed" },
          },
        },
        savingTools: {
          invoke: {
            src: "saveTools",
            // Only the tools that changed: a tool that is not listed keeps its states.
            input: ({ context }) => ({ api: context.api, tools: context.tools ? changedTools(context.draft, context.tools) : {} }),
            onDone: { target: "editing", actions: "toolsSaved" },
            onError: { target: "editing", actions: "saveToolsFailed" },
          },
        },
        confirmingReset: {
          on: { "RESET.CANCEL": "editing", "RESET.CONFIRM": { target: "resetting", actions: "clearOutcome" } },
        },
        resetting: {
          invoke: {
            src: "reset",
            input: ({ context }) => ({ api: context.api }),
            onDone: { target: "editing", actions: "resetDone" },
            onError: { target: "editing", actions: "resetFailed" },
          },
        },
      },
    },
  },
});
