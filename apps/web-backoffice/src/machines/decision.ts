// One decision on one case (ADR-0018): Aprobar, Rechazar, Cerrar or Escalar, confirmed once, then sent.
//
//   idle ── OPEN(kind) ──▶ confirming ── CONFIRM (choice complete) ──▶ sending ──▶ done
//    ▲                       │  ▲                                        │
//    └────── CANCEL ─────────┘  └──────────── error (kept) ──────────────┘
//
// banking-core decides what the case allows and refuses the rest; this machine only holds back an
// incomplete choice: a rejection without a reason, an escalation that names no team and no urgency.

import type { CloseCaseResponse, Department, EscalateCaseResponse, HandoffDetail, RejectReason } from "@pattern-blue/contracts";
import { assign, fromPromise, setup } from "xstate";
import type { Api } from "../api/client";
import { categorize, type ErrorCategory } from "../api/errors";

export type DecisionKind = "APPROVED" | "REJECTED" | "RESOLVED" | "ESCALATE";

export interface DecisionResult {
  kind: DecisionKind;
  handoff: HandoffDetail;
  /** Whether the closing message reached the customer; null for an escalation, which sends none. */
  customerNotified: boolean | null;
  /** When the answer arrived, for "Aprobado por ti · 22:06". */
  at: string;
}

export interface DecisionInput {
  api: Api;
  ref: string;
  /** The case's department: an escalation that only raises the priority stays in it. */
  department: Department;
  now?: () => number;
}

export interface DecisionContext {
  api: Api;
  ref: string;
  currentDepartment: Department;
  now: () => number;
  kind: DecisionKind | null;
  reason: RejectReason | null;
  department: Department | null;
  urgent: boolean;
  result: DecisionResult | null;
  error: ErrorCategory | null;
}

export type DecisionEvent =
  | { type: "OPEN"; kind: DecisionKind }
  | { type: "CANCEL" }
  | { type: "REASON.SET"; reason: RejectReason }
  | { type: "DEPARTMENT.SET"; department: Department }
  | { type: "URGENT.SET"; urgent: boolean }
  | { type: "CONFIRM" };

/** Whether the choice can be sent: a reason for a rejection, a team or the urgency for an escalation. */
export function choiceComplete(context: Pick<DecisionContext, "kind" | "reason" | "department" | "urgent">): boolean {
  if (context.kind === "REJECTED") return context.reason !== null;
  if (context.kind === "ESCALATE") return context.department !== null || context.urgent;
  return context.kind !== null;
}

type SendInput = Pick<DecisionContext, "api" | "ref" | "kind" | "reason" | "department" | "urgent" | "currentDepartment">;

async function send(input: SendInput): Promise<{ kind: DecisionKind; handoff: HandoffDetail; customerNotified: boolean | null }> {
  if (input.kind === "ESCALATE") {
    const answer: EscalateCaseResponse = await input.api.escalateHandoff(input.ref, {
      department: input.department ?? input.currentDepartment,
      raise_to_urgent: input.urgent,
    });
    return { kind: "ESCALATE", handoff: answer.handoff, customerNotified: null };
  }
  if (input.kind === null) throw new Error("no decision to send");
  const answer: CloseCaseResponse = await input.api.closeHandoff(input.ref, {
    outcome: input.kind,
    reason: input.kind === "REJECTED" ? input.reason : null,
  });
  return { kind: input.kind, handoff: answer.handoff, customerNotified: answer.customer_notified };
}

const fresh = { kind: null, reason: null, department: null, urgent: false, error: null } as const;

export const decisionMachine = setup({
  types: {
    context: {} as DecisionContext,
    events: {} as DecisionEvent,
    input: {} as DecisionInput,
  },
  actors: {
    send: fromPromise(({ input }: { input: SendInput }) => send(input)),
  },
  guards: {
    complete: ({ context }) => choiceComplete(context),
  },
}).createMachine({
  id: "decision",
  context: ({ input }) => ({
    api: input.api,
    ref: input.ref,
    currentDepartment: input.department,
    now: input.now ?? Date.now,
    ...fresh,
    result: null,
  }),
  initial: "idle",
  states: {
    idle: {
      on: { OPEN: { target: "confirming", actions: assign(({ event }) => ({ ...fresh, kind: event.kind })) } },
    },
    confirming: {
      on: {
        CANCEL: { target: "idle", actions: assign({ ...fresh }) },
        OPEN: { actions: assign(({ event }) => ({ ...fresh, kind: event.kind })) },
        "REASON.SET": { actions: assign({ reason: ({ event }) => event.reason, error: null }) },
        "DEPARTMENT.SET": { actions: assign({ department: ({ event }) => event.department, error: null }) },
        "URGENT.SET": { actions: assign({ urgent: ({ event }) => event.urgent, error: null }) },
        CONFIRM: { target: "sending", guard: "complete" },
      },
    },
    sending: {
      invoke: {
        src: "send",
        input: ({ context }) => context,
        onDone: {
          target: "done",
          actions: assign({
            result: ({ context, event }) => ({ ...event.output, at: new Date(context.now()).toISOString() }),
            error: null,
          }),
        },
        onError: { target: "confirming", actions: assign({ error: ({ event }) => categorize(event.error) }) },
      },
    },
    done: { type: "final" },
  },
});
