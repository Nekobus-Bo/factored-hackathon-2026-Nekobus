// The chat machine. One actor per page; it makes no request until the customer opens the chat (to ask
// whether detective mode is on) or sends a first message (a conversation is created lazily: creation is
// rate limited per address, so a page load must not spend it).
//
// Five regions run side by side:
//
//   conversation  idle -> creating -> sending -> ready, and the ways out of a failure:
//                   unavailable   503 and the like, and a network failure: "Reintentar" resends the same
//                                 client_message_id, so the orchestrator answers a turn it already ran from its store
//                   rateLimited   429: the composer is disabled until Retry-After, then the message can be retried
//                   gone          404: the conversation expired; "Empezar de nuevo" opens a new one
//   followup      after every completed turn, once: the transcript (to detect a takeover) and the inbox
//   takeover      from the handoff on (while waiting for an agent, and while one holds the conversation):
//                 the transcript every 2 s while the tab is visible, and the agent's messages join the log
//   inbox         the OTP notice: shown while the simulated inbox holds a message that has not expired
//                 and has not been used, hidden at expiry. The code is revealed only by CODE.REVEAL
//   capabilities  whether detective mode is on (ADR-0019): asked when the chat opens (CAPABILITIES.CHECK)
//                 and after every turn, since the back office can turn it off and on at any time
//
// The demo guide (ScriptChoice): `context.script` is where the customer stands in one of the team's scripts.
// It moves in `startSend` (the one place a send is detected: the raw text exists only there) and when a turn
// brings the verification receipt. SCRIPT.START opens a NEW conversation with the script's first line, in the
// script's own market: it resets the log, the takeover, the inbox and the feedback along with it.
//
// While a takeover is active a send returns `blocks: []` by design; that is a normal answer, not an error.
//
// The customer's market (`locale`, ADR-0014) is sent only when the conversation is created: the chat API
// takes no market on a turn, so a market picked after the first message reaches the next conversation.
//
// The machine keeps what the customer sees (`entries`) apart from the one-time code, which lives only in
// `inbox.message`: nothing that reaches an entry can contain it, and what the customer typed is masked
// before it is stored.

import type {
  CapabilitiesResponse,
  CreateConversationRequest,
  InboxMessage,
  InboxResponse,
  Lang,
  Locale,
  SendMessageResponse,
  TranscriptResponse,
} from "@pattern-blue/contracts";
import {
  currentStep,
  getScript,
  nextClientState,
  parseBlocks,
  scriptVerified,
  startScript,
  type DemoScriptId,
  type ScriptState,
} from "@pattern-blue/contracts";
import { assign, enqueueActions, fromPromise, not, setup, type SnapshotFrom } from "xstate";
import type { ApiClient, ApiResult } from "../api/client";
import { dictionaries, langOf } from "../i18n";
import {
  challengeKey,
  codeModeOf,
  deriveChip,
  isHandoff,
  isOtpPending,
  lastEntryWith,
  maskTypedSecrets,
  newAgentMessages,
  pickInboxMessage,
  verifiedAtOf,
  agentKey,
  type ChipState,
  type CodeMode,
  type Entry,
} from "./chat-model";

export const POLL_INTERVAL_MS = 2000;
export const MAX_MESSAGE_LENGTH = 2000;

export interface ChatDeps {
  api: ApiClient;
  /** Epoch milliseconds. */
  now: () => number;
  /** A new client message id: unique per message, repeated unchanged on a retry. */
  newId: () => string;
}

/** The message in flight, or the last one that failed: what a retry resends. */
export interface PendingSend {
  clientMessageId: string;
  /** As typed. Kept only here, only until the turn is accepted, and never rendered. */
  text: string;
  lang: Lang;
  /** The market when the message was sent, or null. */
  locale: Locale | null;
  entryId: string;
}

export interface InboxNotice {
  message: InboxMessage;
  /** The customer asked to see the code. */
  revealed: boolean;
}

export interface ChatContext {
  deps: ChatDeps;
  conversationId: string | null;
  entries: Entry[];
  nextEntry: number;
  pending: PendingSend | null;
  /** Epoch milliseconds until which sending is disabled (a 429), or null. */
  retryUntil: number | null;
  takeover: { active: boolean; since: string | null };
  inbox: InboxNotice | null;
  /** `verified_at` of the last successful otp.verify: codes received before it are used. */
  verifiedAt: string | null;
  visible: boolean;
  /** Detective mode is on: the view offers its switch and turns carry their trace (ADR-0019). */
  detective: boolean;
  /** Where the customer stands in a demo script, or null when none was chosen (or the guide was reset). */
  script: ScriptState | null;
  /** The code challenge the customer cancelled (`challengeKey`), or null: the composer is the normal one for it. */
  codeDismissed: string | null;
}

export type ChatEvent =
  /**
   * `codeRequest`: the message is the chat's own "Pedir otro código". At the code step of a demo script it leaves the
   * script where it is (the customer did what the chat offered); anywhere else it is a message like any other.
   */
  | { type: "SEND"; text: string; lang: Lang; locale?: Locale | null; codeRequest?: boolean }
  | { type: "RETRY" }
  | { type: "CODE.REVEAL" }
  | { type: "CODE.HIDE" }
  | { type: "VISIBLE" }
  | { type: "HIDDEN" }
  /** The customer's answer to "did the assistant help?", after a handoff (ADR-0017). */
  | { type: "FEEDBACK.SEND"; helpful: boolean }
  /** The chat opened: ask whether detective mode is on. */
  | { type: "CAPABILITIES.CHECK" }
  /** A script was chosen: a new conversation, opened with the script's first line in the script's market. */
  | { type: "SCRIPT.START"; scriptId: DemoScriptId }
  /** "Cambiar de guion": the guide forgets the script. The conversation goes on as it was. */
  | { type: "SCRIPT.RESET" }
  /** "Cancelar" in the code field: this challenge no longer takes over the composer. Sends nothing. */
  | { type: "CODE.DISMISS" }
  /** "Escribir el código": back to the field for the challenge that was cancelled. */
  | { type: "CODE.RESUME" }
  // Internal: raised by the machine itself.
  | { type: "TURN_DONE" }
  | { type: "SCRIPT.STARTED" }
  | { type: "INBOX.FOUND"; message: InboxMessage }
  | { type: "INBOX.NONE" };

export interface ChatInput {
  deps: ChatDeps;
  /** `document.visibilityState === "visible"`. */
  visible?: boolean;
}

const sameMessage = (a: InboxMessage, b: InboxMessage) =>
  a.received_at === b.received_at && a.expires_at === b.expires_at && a.code === b.code;

/** The body of a new conversation. A market of another language is left out: the orchestrator would answer 422. */
export function createConversationBody(lang: Lang, locale: Locale | null): CreateConversationRequest {
  return locale && langOf(locale) === lang ? { lang, locale } : { lang };
}

/** The script after a send. The chat's own request for another code, made at the code step, does not move it. */
function nextScriptState(script: ScriptState, text: string, codeRequest: boolean): ScriptState {
  return codeRequest && currentStep(script)?.kind === "code" ? script : nextClientState(script, text);
}

function withStatus(entries: Entry[], entryId: string | undefined, status: "sent" | "failed"): Entry[] {
  return entries.map((entry) => (entry.id === entryId && entry.kind === "customer" ? { ...entry, status } : entry));
}

export const chatMachine = setup({
  types: {} as { context: ChatContext; events: ChatEvent; input: ChatInput },
  actors: {
    createConversation: fromPromise(({ input }: { input: { api: ApiClient; lang: Lang; locale: Locale | null } }) =>
      input.api.createConversation(createConversationBody(input.lang, input.locale)),
    ),
    sendMessage: fromPromise(
      ({ input }: { input: { api: ApiClient; conversationId: string; pending: PendingSend } }) =>
        input.api.sendMessage(input.conversationId, {
          text: input.pending.text,
          lang: input.pending.lang,
          client_message_id: input.pending.clientMessageId,
        }),
    ),
    loadTranscript: fromPromise(({ input }: { input: { api: ApiClient; conversationId: string } }) =>
      input.api.getTranscript(input.conversationId),
    ),
    loadInbox: fromPromise(({ input }: { input: { api: ApiClient; conversationId: string } }) =>
      input.api.getInbox(input.conversationId),
    ),
    sendFeedback: fromPromise(({ input }: { input: { api: ApiClient; conversationId: string; helpful: boolean } }) =>
      input.api.sendFeedback(input.conversationId, { helpful: input.helpful }),
    ),
    loadCapabilities: fromPromise(({ input }: { input: { api: ApiClient } }) => input.api.getCapabilities()),
  },
  guards: {
    canSend: ({ event }) =>
      event.type === "SEND" && event.text.trim().length > 0 && event.text.trim().length <= MAX_MESSAGE_LENGTH,
    canSendHere: ({ context, event }) =>
      context.conversationId !== null &&
      event.type === "SEND" &&
      event.text.trim().length > 0 &&
      event.text.trim().length <= MAX_MESSAGE_LENGTH,
    hasConversation: ({ context }) => context.conversationId !== null,
    /** A handoff was shown, or an agent already holds the conversation: the agent's messages may arrive any time. */
    awaitingAgent: ({ context }) => context.takeover.active || lastEntryWith(context.entries, isHandoff) !== null,
    takeoverInactive: ({ context }) => !context.takeover.active,
    isVisible: ({ context }) => context.visible,
  },
  delays: {
    retryAfter: ({ context }) => Math.max(0, (context.retryUntil ?? 0) - context.deps.now()),
    inboxExpiry: ({ context }) =>
      context.inbox ? Math.max(0, Date.parse(context.inbox.message.expires_at) - context.deps.now()) : 0,
    pollInterval: POLL_INTERVAL_MS,
  },
  actions: {
    /** The customer's message enters the log at once, masked for display; the raw text waits in `pending`. */
    startSend: assign(({ context, event }) => {
      if (event.type !== "SEND") return {};
      const text = event.text.trim();
      const entryId = `e${context.nextEntry}`;
      const display = maskTypedSecrets(text, {
        otpPending: isOtpPending(context.entries),
        knownCodes: context.inbox ? [context.inbox.message.code] : [],
        codePrefix: dictionaries[event.lang].chat.codePrefix,
      });
      const entry: Entry = {
        id: entryId,
        kind: "customer",
        text: display,
        at: new Date(context.deps.now()).toISOString(),
        lang: event.lang,
        status: "sent",
      };
      return {
        entries: [...context.entries, entry],
        nextEntry: context.nextEntry + 1,
        pending: { clientMessageId: context.deps.newId(), text, lang: event.lang, locale: event.locale ?? null, entryId },
        retryUntil: null,
        // A retry does not come through here (it resends `pending`), so a message counts once.
        script: context.script ? nextScriptState(context.script, text, event.codeRequest === true) : null,
      };
    }),
    /**
     * A script was chosen: a new conversation whose first message is the script's first line, sent in the
     * script's own language and market (not the page's: the page switches in the same click, after this).
     * Everything of the old conversation goes, the feedback and the inbox regions included (SCRIPT.STARTED).
     */
    beginScript: enqueueActions(({ context, event, enqueue }) => {
      if (event.type !== "SCRIPT.START") return;
      const script = getScript(event.scriptId);
      const first = script.steps[0];
      if (first?.kind !== "message") return;
      const text = first.text;
      const entryId = `e${context.nextEntry}`;
      const entry: Entry = {
        id: entryId,
        kind: "customer",
        text: maskTypedSecrets(text, { otpPending: false, knownCodes: [], codePrefix: dictionaries[script.lang].chat.codePrefix }),
        at: new Date(context.deps.now()).toISOString(),
        lang: script.lang,
        status: "sent",
      };
      enqueue.assign({
        conversationId: null,
        entries: [entry],
        nextEntry: context.nextEntry + 1,
        pending: { clientMessageId: context.deps.newId(), text, lang: script.lang, locale: script.locale, entryId },
        retryUntil: null,
        takeover: { active: false, since: null },
        inbox: null,
        verifiedAt: null,
        codeDismissed: null,
        script: nextClientState(startScript(script.id), text),
      });
      enqueue.raise({ type: "SCRIPT.STARTED" });
    }),
    resetScript: assign({ script: null }),
    dismissCode: assign(({ context }) => ({ codeDismissed: challengeKey(context.entries) })),
    resumeCode: assign({ codeDismissed: null }),
    /** A retry resends the same message under the same client_message_id. */
    startRetry: assign(({ context }) => ({
      entries: withStatus(context.entries, context.pending?.entryId, "sent"),
      retryUntil: null,
    })),
    /** "Empezar de nuevo": a new conversation, keeping only the message that was not sent. */
    startOver: assign(({ context }) => ({
      conversationId: null,
      entries: context.entries.filter((entry) => entry.id === context.pending?.entryId).map((entry) =>
        entry.kind === "customer" ? { ...entry, status: "sent" as const } : entry,
      ),
      takeover: { active: false, since: null },
      inbox: null,
      verifiedAt: null,
      retryUntil: null,
      codeDismissed: null,
      // The new conversation holds only the message that was not sent: the lines sent before are not in it.
      script: context.script && context.script.status === "running" ? { ...context.script, status: "stopped" as const } : context.script,
    })),
    markFailed: assign(({ context }) => ({ entries: withStatus(context.entries, context.pending?.entryId, "failed") })),
    setRetryUntil: assign(({ context, event }) => {
      const output = (event as unknown as { output?: ApiResult<unknown> }).output;
      const seconds = output && !output.ok && output.kind === "rate_limited" ? output.retryAfterSeconds : 60;
      return { retryUntil: context.deps.now() + seconds * 1000 };
    }),
    setConversation: assign(({ event }) => {
      const output = (event as unknown as { output: ApiResult<{ conversation_id: string }> }).output;
      return output.ok ? { conversationId: output.data.conversation_id } : {};
    }),
    /** A completed turn: the assistant's blocks join the log; a verified code hides the notice. */
    applyTurn: enqueueActions(({ context, event, enqueue }) => {
      const output = (event as unknown as { output: ApiResult<SendMessageResponse> }).output;
      if (!output.ok) return;
      const { blocks, trace } = output.data;
      const pending = context.pending;
      const entries = withStatus(context.entries, pending?.entryId, "sent");
      let nextEntry = context.nextEntry;
      // An empty list is the normal answer during a takeover; blocks this build cannot render add nothing.
      if (parseBlocks(blocks).blocks.length > 0) {
        entries.push({
          id: `e${nextEntry}`,
          kind: "assistant",
          blocks,
          at: new Date(context.deps.now()).toISOString(),
          lang: pending?.lang ?? "es",
          ...(trace ? { trace } : {}),
        });
        nextEntry += 1;
      }
      const verifiedAt = verifiedAtOf(blocks) ?? context.verifiedAt;
      // The verification the chat proved passes the script's code step (only when it goes from none to some).
      const script = context.script && verifiedAt !== null && context.verifiedAt === null ? scriptVerified(context.script) : context.script;
      enqueue.assign({ entries, nextEntry, pending: null, verifiedAt, script });
      if (verifiedAt !== context.verifiedAt) enqueue.raise({ type: "INBOX.NONE" });
      enqueue.raise({ type: "TURN_DONE" });
    }),
    /** The transcript: has an agent taken over, and what did the agent write. */
    applyTranscript: assign(({ context, event }) => {
      const output = (event as unknown as { output: ApiResult<TranscriptResponse> }).output;
      if (!output.ok) return {};
      const { takeover, messages } = output.data;
      const entries = [...context.entries];
      let nextEntry = context.nextEntry;
      const wasActive = context.takeover.active;
      const active = wasActive || takeover.active;
      if (active && !wasActive) {
        entries.push({ id: `e${nextEntry}`, kind: "system", code: "takeover", at: takeover.since ?? new Date(context.deps.now()).toISOString() });
        nextEntry += 1;
      }
      if (active) {
        for (const message of newAgentMessages(messages, entries)) {
          entries.push({
            id: `e${nextEntry}`,
            kind: "agent",
            text: message.content,
            at: message.created_at,
            key: agentKey(message),
          });
          nextEntry += 1;
        }
      }
      return {
        entries,
        nextEntry,
        takeover: { active, since: wasActive ? context.takeover.since : takeover.since },
      };
    }),
    /** The inbox answered: tell the inbox region what is there. Unreadable answers change nothing. */
    reportInbox: enqueueActions(({ context, event, enqueue }) => {
      const output = (event as unknown as { output: ApiResult<InboxResponse> }).output;
      if (!output.ok) return;
      const message = pickInboxMessage(output.data.messages, context.deps.now(), context.verifiedAt);
      enqueue.raise(message ? { type: "INBOX.FOUND", message } : { type: "INBOX.NONE" });
    }),
    showInbox: assign(({ context, event }) => {
      if (event.type !== "INBOX.FOUND") return {};
      const same = context.inbox !== null && sameMessage(context.inbox.message, event.message);
      return { inbox: { message: event.message, revealed: same ? context.inbox!.revealed : false } };
    }),
    clearInbox: assign({ inbox: null }),
    /** The code ran out unused: the notice goes, and the log says so once. */
    expireInbox: assign(({ context }) => ({
      inbox: null,
      entries: [
        ...context.entries,
        { id: `e${context.nextEntry}`, kind: "system" as const, code: "codeExpired" as const, at: new Date(context.deps.now()).toISOString() },
      ],
      nextEntry: context.nextEntry + 1,
    })),
    reveal: assign(({ context }) => (context.inbox ? { inbox: { ...context.inbox, revealed: true } } : {})),
    concealCode: assign(({ context }) => (context.inbox ? { inbox: { ...context.inbox, revealed: false } } : {})),
    /** Off when the answer is not ok: the switch is offered only when the orchestrator says so. */
    applyCapabilities: assign(({ event }) => {
      const output = (event as unknown as { output: ApiResult<CapabilitiesResponse> }).output;
      return { detective: output.ok && output.data.detective };
    }),
    setVisible: assign({ visible: true }),
    setHidden: assign({ visible: false }),
  },
}).createMachine({
  id: "chat",
  context: ({ input }): ChatContext => ({
    deps: input.deps,
    conversationId: null,
    entries: [],
    nextEntry: 1,
    pending: null,
    retryUntil: null,
    takeover: { active: false, since: null },
    inbox: null,
    verifiedAt: null,
    visible: input.visible ?? true,
    detective: false,
    script: null,
    codeDismissed: null,
  }),
  type: "parallel",
  // The guide forgets its script at any time: it changes nothing else.
  on: {
    "SCRIPT.RESET": { actions: "resetScript" },
    "CODE.DISMISS": { actions: "dismissCode" },
    "CODE.RESUME": { actions: "resumeCode" },
  },
  states: {
    conversation: {
      initial: "idle",
      states: {
        idle: {
          on: {
            SEND: { guard: "canSend", target: "creating", actions: "startSend" },
            "SCRIPT.START": { target: "creating", actions: "beginScript" },
          },
        },
        creating: {
          invoke: {
            src: "createConversation",
            input: ({ context }) => ({
              api: context.deps.api,
              lang: context.pending?.lang ?? "es",
              locale: context.pending?.locale ?? null,
            }),
            onDone: [
              { guard: ({ event }) => event.output.ok, target: "sending", actions: "setConversation" },
              {
                guard: ({ event }) => !event.output.ok && event.output.kind === "rate_limited",
                target: "rateLimited",
                actions: ["markFailed", "setRetryUntil"],
              },
              { target: "unavailable", actions: "markFailed" },
            ],
            onError: { target: "unavailable", actions: "markFailed" },
          },
        },
        sending: {
          invoke: {
            src: "sendMessage",
            input: ({ context }) => ({
              api: context.deps.api,
              conversationId: context.conversationId as string,
              pending: context.pending as PendingSend,
            }),
            onDone: [
              { guard: ({ event }) => event.output.ok, target: "ready", actions: "applyTurn" },
              {
                guard: ({ event }) => !event.output.ok && event.output.kind === "rate_limited",
                target: "rateLimited",
                actions: ["markFailed", "setRetryUntil"],
              },
              { guard: ({ event }) => !event.output.ok && event.output.kind === "not_found", target: "gone", actions: "markFailed" },
              { target: "unavailable", actions: "markFailed" },
            ],
            onError: { target: "unavailable", actions: "markFailed" },
          },
        },
        ready: {
          on: {
            SEND: { guard: "canSend", target: "sending", actions: "startSend" },
            "SCRIPT.START": { target: "creating", actions: "beginScript" },
          },
        },
        unavailable: {
          on: {
            RETRY: [
              { guard: "hasConversation", target: "sending", actions: "startRetry" },
              { target: "creating", actions: "startRetry" },
            ],
            SEND: [
              { guard: "canSendHere", target: "sending", actions: "startSend" },
              { guard: "canSend", target: "creating", actions: "startSend" },
            ],
            "SCRIPT.START": { target: "creating", actions: "beginScript" },
          },
        },
        rateLimited: {
          after: { retryAfter: "retryable" },
        },
        retryable: {
          on: {
            RETRY: [
              { guard: "hasConversation", target: "sending", actions: "startRetry" },
              { target: "creating", actions: "startRetry" },
            ],
            SEND: [
              { guard: "canSendHere", target: "sending", actions: "startSend" },
              { guard: "canSend", target: "creating", actions: "startSend" },
            ],
            "SCRIPT.START": { target: "creating", actions: "beginScript" },
          },
        },
        gone: {
          // Choosing a script opens a new conversation by itself: no need to "start over" first (which would spend one more creation).
          on: { RETRY: { target: "creating", actions: "startOver" }, "SCRIPT.START": { target: "creating", actions: "beginScript" } },
        },
      },
    },

    followup: {
      initial: "idle",
      // A new conversation: whatever was being read belongs to the old one.
      on: { "SCRIPT.STARTED": ".idle" },
      states: {
        idle: {
          on: { TURN_DONE: { guard: "takeoverInactive", target: "loading" } },
        },
        loading: {
          type: "parallel",
          on: { TURN_DONE: { guard: "takeoverInactive", target: "loading", reenter: true } },
          onDone: "idle",
          states: {
            transcript: {
              initial: "run",
              states: {
                run: {
                  invoke: {
                    src: "loadTranscript",
                    input: ({ context }) => ({ api: context.deps.api, conversationId: context.conversationId as string }),
                    onDone: { target: "done", actions: "applyTranscript" },
                    onError: "done",
                  },
                },
                done: { type: "final" },
              },
            },
            inbox: {
              initial: "run",
              states: {
                run: {
                  invoke: {
                    src: "loadInbox",
                    input: ({ context }) => ({ api: context.deps.api, conversationId: context.conversationId as string }),
                    onDone: { target: "done", actions: "reportInbox" },
                    onError: "done",
                  },
                },
                done: { type: "final" },
              },
            },
          },
        },
      },
    },

    takeover: {
      initial: "off",
      on: {
        VISIBLE: { actions: "setVisible" },
        HIDDEN: { actions: "setHidden" },
      },
      states: {
        off: { always: { guard: "awaitingAgent", target: "on" } },
        on: {
          // Starting over clears the handoff and the takeover: the old conversation is no longer read.
          always: { guard: not("awaitingAgent"), target: "off" },
          initial: "route",
          states: {
            route: { always: [{ guard: "isVisible", target: "polling" }, { target: "paused" }] },
            polling: {
              initial: "waiting",
              on: { HIDDEN: { target: "paused", actions: "setHidden" } },
              states: {
                waiting: { after: { pollInterval: "fetching" } },
                fetching: {
                  invoke: {
                    src: "loadTranscript",
                    input: ({ context }) => ({ api: context.deps.api, conversationId: context.conversationId as string }),
                    onDone: { target: "waiting", actions: "applyTranscript" },
                    onError: "waiting",
                  },
                },
              },
            },
            // Back on the tab: read at once instead of waiting out the interval.
            paused: { on: { VISIBLE: { target: "polling.fetching", actions: "setVisible" } } },
          },
        },
      },
    },

    inbox: {
      initial: "hidden",
      on: { "SCRIPT.STARTED": ".hidden" },
      states: {
        hidden: {
          on: { "INBOX.FOUND": { target: "shown", actions: "showInbox" } },
        },
        shown: {
          after: { inboxExpiry: { target: "hidden", actions: "expireInbox" } },
          on: {
            "INBOX.FOUND": { target: "shown", reenter: true, actions: "showInbox" },
            "INBOX.NONE": { target: "hidden", actions: "clearInbox" },
            "CODE.REVEAL": { actions: "reveal" },
            "CODE.HIDE": { actions: "concealCode" },
          },
        },
      },
    },

    // Detective mode (ADR-0019): asked when the chat opens and after every turn. A failure means off.
    capabilities: {
      initial: "unknown",
      states: {
        unknown: {
          on: { "CAPABILITIES.CHECK": "loading" },
        },
        loading: {
          invoke: {
            src: "loadCapabilities",
            input: ({ context }) => ({ api: context.deps.api }),
            onDone: { target: "known", actions: "applyCapabilities" },
            onError: { target: "known", actions: assign({ detective: false }) },
          },
        },
        known: {
          on: { "CAPABILITIES.CHECK": "loading", TURN_DONE: "loading" },
        },
      },
    },

    // The answer to "did the assistant help?". The view asks only after a handoff block; banking-core
    // decides whether there is a handoff to rate. A failed answer can be sent again.
    feedback: {
      initial: "asking",
      // A new conversation has nothing to rate yet (the region does not reset on its own: it only reads its events).
      on: { "SCRIPT.STARTED": ".asking" },
      states: {
        asking: {
          on: { "FEEDBACK.SEND": { guard: "hasConversation", target: "sending" } },
        },
        sending: {
          invoke: {
            src: "sendFeedback",
            input: ({ context, event }) => ({
              api: context.deps.api,
              conversationId: context.conversationId as string,
              helpful: event.type === "FEEDBACK.SEND" && event.helpful,
            }),
            onDone: [{ guard: ({ event }) => event.output.ok, target: "sent" }, { target: "failed" }],
            onError: { target: "failed" },
          },
        },
        sent: {},
        failed: {
          on: { "FEEDBACK.SEND": { guard: "hasConversation", target: "sending" } },
        },
      },
    },
  },
});

export type ChatMachine = typeof chatMachine;

// --- What the view reads -------------------------------------------------------------------------------------------

export type ChatSnapshot = SnapshotFrom<ChatMachine>;

export type ConversationState =
  | "idle"
  | "creating"
  | "sending"
  | "ready"
  | "unavailable"
  | "rateLimited"
  | "retryable"
  | "gone";

const CONVERSATION_STATES: readonly ConversationState[] = [
  "creating",
  "sending",
  "unavailable",
  "rateLimited",
  "retryable",
  "gone",
  "ready",
  "idle",
];

export function conversationState(snapshot: ChatSnapshot): ConversationState {
  return CONVERSATION_STATES.find((state) => snapshot.matches({ conversation: state })) ?? "idle";
}

export type FeedbackState = "asking" | "sending" | "sent" | "failed";

const FEEDBACK_STATES: readonly FeedbackState[] = ["sending", "sent", "failed", "asking"];

/** Where the answer to "did the assistant help?" stands. */
export function selectFeedback(snapshot: ChatSnapshot): FeedbackState {
  return FEEDBACK_STATES.find((state) => snapshot.matches({ feedback: state })) ?? "asking";
}

/** The header chip: what the blocks prove, or nothing. */
export function selectChip(snapshot: ChatSnapshot): ChipState | null {
  return deriveChip(snapshot.context.entries, snapshot.context.takeover.active);
}

/** The assistant is working on it: show the typing indicator (not while a person has the conversation). */
export function selectTyping(snapshot: ChatSnapshot): boolean {
  const state = conversationState(snapshot);
  return (state === "creating" || state === "sending") && !snapshot.context.takeover.active;
}

/** Sending is off while a message is in flight, until a 429 has run its course, and when the conversation is gone. */
export function selectSendDisabled(snapshot: ChatSnapshot): boolean {
  const state = conversationState(snapshot);
  return state === "creating" || state === "sending" || state === "rateLimited" || state === "gone";
}

/** Where the customer stands in a demo script, or null (the guide offers the six). */
export function selectScript(snapshot: ChatSnapshot): ScriptState | null {
  return snapshot.context.script;
}

/**
 * The guide's next line is off while a message waits for its retry: it was counted when it first went, and a
 * different message now would leave the script ahead of what the conversation holds.
 */
export function selectAwaitingRetry(snapshot: ChatSnapshot): boolean {
  const state = conversationState(snapshot);
  return state === "unavailable" || state === "retryable";
}

/** What the composer is for the code challenge, if there is one: the field, "el código venció", the normal composer. */
export function selectCodeMode(snapshot: ChatSnapshot): CodeMode {
  const { entries, inbox, takeover, codeDismissed, deps } = snapshot.context;
  return codeModeOf({
    entries,
    inbox,
    takeoverActive: takeover.active,
    dismissed: codeDismissed,
    gone: conversationState(snapshot) === "gone",
    now: deps.now(),
  });
}

/**
 * A script can be chosen: it opens a new conversation, so it works from every state that can open one (also an
 * expired conversation) and not while a message is in flight or a rate limit runs.
 */
export function selectCanStartScript(snapshot: ChatSnapshot): boolean {
  const state = conversationState(snapshot);
  return state !== "creating" && state !== "sending" && state !== "rateLimited";
}
