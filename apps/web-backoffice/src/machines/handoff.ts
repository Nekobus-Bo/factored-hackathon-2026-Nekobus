// The handoff detail screen's machine, four regions that run side by side:
//
//   detail      loads the case (summary, status, who holds it) and reloads it after a claim conflict.
//   claim       "Tomar caso": the BFF claims in banking-core and then takes the conversation over in the
//               orchestrator. Repeating a failed claim is safe, both steps are idempotent.
//   transcript  the masked transcript. Loaded once; polled every 2 s (only while the tab is visible) once
//               this agent holds the conversation.
//   composer    an agent reply, with one `client_message_id` per message and a retry that reuses it.
//
// The regions talk through the context: `detail`/`claim` set `conversationId` and `takeover`, and the
// transcript region reacts to them with eventless transitions.

import type { AgentTakeoverState, AgentTranscriptResponse, ClaimHandoffResponse, HandoffDetail, Lang, BackofficeHandoffDetail } from "@pattern-blue/contracts";
import { assign, fromPromise, raise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

export const TRANSCRIPT_POLL_MS = 2000;

export interface HandoffInput {
  api: Api;
  ref: string;
  /** The logged-in agent's e-mail: who "me" is in the takeover. */
  agentRef: string;
  pollMs?: number;
  /** Makes a `client_message_id`; injectable so a test can predict it. */
  newId?: () => string;
}

export interface Outbox {
  text: string;
  client_message_id: string;
}

export type TranscriptMessages = AgentTranscriptResponse["messages"];

export interface HandoffContext {
  api: Api;
  ref: string;
  agentRef: string;
  pollMs: number;
  newId: () => string;
  detail: HandoffDetail | null;
  detailError: ErrorCategory | null;
  conversationId: string | null;
  takeover: AgentTakeoverState | null;
  language: Lang | null;
  messages: TranscriptMessages;
  transcriptError: ErrorCategory | null;
  claimError: ErrorCategory | null;
  outbox: Outbox | null;
  sendError: ErrorCategory | null;
  sendRetryAfterSeconds: number | null;
}

export type HandoffEvent =
  | { type: "RETRY" }
  | { type: "DETAIL.RELOAD" }
  | { type: "CLAIM" }
  | { type: "TRANSCRIPT.RETRY" }
  | { type: "TRANSCRIPT.REFRESH" }
  | { type: "SEND"; text: string }
  | { type: "SEND.RETRY" }
  | { type: "SEND.DISCARD" }
  | { type: "VISIBILITY"; visible: boolean };

/** Whether this agent holds the conversation: what enables the composer and the live polling. */
export function heldByMe(context: Pick<HandoffContext, "takeover" | "agentRef">): boolean {
  return context.takeover?.active === true && context.takeover.agent_ref === context.agentRef;
}

/** Another agent holds the case, in banking-core or in the orchestrator. */
export function heldByAnother(context: Pick<HandoffContext, "detail" | "takeover" | "agentRef">): boolean {
  const assigned = context.detail?.assigned_agent ?? null;
  if (assigned !== null && assigned !== context.agentRef) return true;
  const holder = context.takeover?.active ? context.takeover.agent_ref : null;
  return holder !== null && holder !== context.agentRef;
}

/** "Tomar caso" is offered when the case is queued, or is mine but the conversation is not yet in my hands. */
export function canClaim(context: Pick<HandoffContext, "detail" | "takeover" | "agentRef">): boolean {
  const { detail } = context;
  if (!detail || heldByMe(context) || heldByAnother(context)) return false;
  return detail.status === "QUEUED" || detail.assigned_agent === context.agentRef;
}

const errorOf = (event: unknown): unknown => (event as { error: unknown }).error;
const outputOf = <T>(event: unknown): T => (event as { output: T }).output;

export const handoffMachine = setup({
  types: {
    context: {} as HandoffContext,
    events: {} as HandoffEvent,
    input: {} as HandoffInput,
  },
  actors: {
    loadDetail: fromPromise(({ input }: { input: { api: Api; ref: string } }) => input.api.getHandoff(input.ref)),
    claim: fromPromise(({ input }: { input: { api: Api; ref: string } }) => input.api.claimHandoff(input.ref)),
    loadTranscript: fromPromise(({ input }: { input: { api: Api; conversationId: string } }) => input.api.getConversation(input.conversationId)),
    sendMessage: fromPromise(({ input }: { input: { api: Api; conversationId: string; outbox: Outbox } }) =>
      input.api.sendAgentMessage(input.conversationId, input.outbox),
    ),
  },
  delays: {
    POLL: ({ context }) => context.pollMs,
  },
  guards: {
    hasConversation: ({ context }) => context.conversationId !== null,
    heldByMe: ({ context }) => heldByMe(context),
    canClaim: ({ context }) => canClaim(context),
    canSend: ({ context, event }) => heldByMe(context) && context.conversationId !== null && event.type === "SEND" && event.text.trim() !== "",
    hidden: ({ event }) => event.type === "VISIBILITY" && !event.visible,
    visible: ({ event }) => event.type === "VISIBILITY" && event.visible,
    failedWith: ({ event }, params: { category: ErrorCategory }) => categorize(errorOf(event)) === params.category,
  },
  actions: {
    applyDetail: assign(({ context, event }) => {
      const output = outputOf<BackofficeHandoffDetail>(event);
      const { conversation_id, ...detail } = output;
      return { detail, detailError: null, conversationId: conversation_id ?? context.conversationId };
    }),
    detailFailed: assign({ detailError: ({ event }) => categorize(errorOf(event)) }),
    applyClaim: assign(({ event }) => {
      const output = outputOf<ClaimHandoffResponse>(event);
      return { detail: output.handoff, conversationId: output.takeover.conversation_id, takeover: output.takeover.takeover, claimError: null };
    }),
    claimFailed: assign({ claimError: ({ event }) => categorize(errorOf(event)) }),
    clearClaimError: assign({ claimError: null }),
    reloadDetail: raise({ type: "DETAIL.RELOAD" }),
    applyTranscript: assign(({ event }) => {
      const output = outputOf<AgentTranscriptResponse>(event);
      return { messages: output.messages, takeover: output.takeover, language: output.language, transcriptError: null };
    }),
    transcriptFailed: assign({ transcriptError: ({ event }) => categorize(errorOf(event)) }),
    startSend: assign({
      outbox: ({ context, event }) => (event.type === "SEND" ? { text: event.text.trim(), client_message_id: context.newId() } : context.outbox),
      sendError: null,
      sendRetryAfterSeconds: null,
    }),
    sent: assign({ outbox: null, sendError: null, sendRetryAfterSeconds: null }),
    sendFailed: assign(({ event }) => {
      const error = errorOf(event) as { retryAfterSeconds?: number | null };
      return { sendError: categorize(error), sendRetryAfterSeconds: error.retryAfterSeconds ?? null };
    }),
    discardOutbox: assign({ outbox: null, sendError: null, sendRetryAfterSeconds: null }),
    refreshTranscript: raise({ type: "TRANSCRIPT.REFRESH" }),
    // The reply was refused because this agent no longer holds the conversation: what the screen shows follows.
    lostTakeover: assign({ takeover: null }),
  },
}).createMachine({
  id: "handoff",
  type: "parallel",
  context: ({ input }) => ({
    api: input.api,
    ref: input.ref,
    agentRef: input.agentRef,
    pollMs: input.pollMs ?? TRANSCRIPT_POLL_MS,
    newId: input.newId ?? (() => `msg_${crypto.randomUUID().replaceAll("-", "")}`),
    detail: null,
    detailError: null,
    conversationId: null,
    takeover: null,
    language: null,
    messages: [],
    transcriptError: null,
    claimError: null,
    outbox: null,
    sendError: null,
    sendRetryAfterSeconds: null,
  }),
  states: {
    // --- The case ---------------------------------------------------------------------------------------
    detail: {
      initial: "loading",
      states: {
        loading: {
          invoke: {
            src: "loadDetail",
            input: ({ context }) => ({ api: context.api, ref: context.ref }),
            onDone: { target: "ready", actions: "applyDetail" },
            onError: { target: "failed", actions: "detailFailed" },
          },
        },
        ready: {
          on: { "DETAIL.RELOAD": "refreshing" },
        },
        // Reloading keeps what is on screen; a failure here is not worth replacing the case with an error.
        refreshing: {
          invoke: {
            src: "loadDetail",
            input: ({ context }) => ({ api: context.api, ref: context.ref }),
            onDone: { target: "ready", actions: "applyDetail" },
            onError: { target: "ready" },
          },
        },
        failed: {
          on: { RETRY: "loading" },
        },
      },
    },

    // --- "Tomar caso" -----------------------------------------------------------------------------------
    claim: {
      initial: "idle",
      states: {
        idle: {
          on: { CLAIM: { guard: "canClaim", target: "claiming" } },
        },
        claiming: {
          entry: "clearClaimError",
          invoke: {
            src: "claim",
            input: ({ context }) => ({ api: context.api, ref: context.ref }),
            onDone: { target: "claimed", actions: "applyClaim" },
            onError: [
              // Another agent got there first: show who, by reloading the case.
              { guard: { type: "failedWith", params: { category: "heldByAnother" } }, target: "conflict", actions: ["claimFailed", "reloadDetail"] },
              // The claim is recorded, the takeover is not. Reload the case (it is mine now) and offer the retry.
              { guard: { type: "failedWith", params: { category: "claimedButTakeoverFailed" } }, target: "failed", actions: ["claimFailed", "reloadDetail"] },
              { target: "failed", actions: "claimFailed" },
            ],
          },
        },
        claimed: {},
        conflict: {},
        failed: {
          on: { CLAIM: { guard: "canClaim", target: "claiming" } },
        },
      },
    },

    // --- The masked transcript --------------------------------------------------------------------------
    transcript: {
      initial: "none",
      states: {
        // No conversation yet: the case has not loaded, or its conversation is gone (TTL).
        none: {
          always: { guard: "hasConversation", target: "loading" },
        },
        loading: {
          invoke: {
            src: "loadTranscript",
            input: ({ context }) => ({ api: context.api, conversationId: context.conversationId as string }),
            onDone: { target: "ready", actions: "applyTranscript" },
            onError: { target: "failed", actions: "transcriptFailed" },
          },
        },
        failed: {
          on: { "TRANSCRIPT.RETRY": "loading" },
        },
        ready: {
          initial: "snapshot",
          on: { "TRANSCRIPT.REFRESH": { target: ".fetching", reenter: true } },
          states: {
            // Not mine (yet): what the transcript said when it loaded. It goes live the moment I hold it.
            snapshot: {
              always: { guard: "heldByMe", target: "live" },
            },
            fetching: {
              invoke: {
                src: "loadTranscript",
                input: ({ context }) => ({ api: context.api, conversationId: context.conversationId as string }),
                onDone: { target: "snapshot", actions: "applyTranscript" },
                onError: { target: "snapshot", actions: "transcriptFailed" },
              },
            },
            live: {
              initial: "fetching",
              on: { VISIBILITY: { guard: "hidden", target: ".paused" } },
              states: {
                fetching: {
                  invoke: {
                    src: "loadTranscript",
                    input: ({ context }) => ({ api: context.api, conversationId: context.conversationId as string }),
                    onDone: { target: "waiting", actions: "applyTranscript" },
                    onError: { target: "waiting", actions: "transcriptFailed" },
                  },
                },
                waiting: {
                  after: { POLL: { target: "fetching" } },
                },
                paused: {
                  on: { VISIBILITY: { guard: "visible", target: "fetching" } },
                },
              },
            },
          },
        },
      },
    },

    // --- The reply --------------------------------------------------------------------------------------
    composer: {
      initial: "idle",
      states: {
        idle: {
          on: { SEND: { guard: "canSend", target: "sending", actions: "startSend" } },
        },
        sending: {
          invoke: {
            src: "sendMessage",
            input: ({ context }) => ({ api: context.api, conversationId: context.conversationId as string, outbox: context.outbox as Outbox }),
            onDone: { target: "idle", actions: ["sent", "refreshTranscript"] },
            onError: [
              { guard: { type: "failedWith", params: { category: "noActiveTakeover" } }, target: "failed", actions: ["sendFailed", "lostTakeover"] },
              { target: "failed", actions: "sendFailed" },
            ],
          },
        },
        // The message stays as typed, with the id it was first sent with: a retry cannot post it twice.
        failed: {
          on: {
            "SEND.RETRY": "sending",
            "SEND.DISCARD": { target: "idle", actions: "discardOutbox" },
            SEND: { guard: "canSend", target: "sending", actions: "startSend" },
          },
        },
      },
    },
  },
});
