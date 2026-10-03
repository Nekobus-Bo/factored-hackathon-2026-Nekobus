// The agent's decision on a case (ADR-0018), in the queue's summary and in the case header: the buttons
// banking-core allows, one confirmation that quotes what the customer will receive, then the result.
// Aprobar and Rechazar look the same on purpose, and nothing is preselected: the screen never suggests
// an outcome.

import type { Department, HandoffDetail, HandoffOutcome, Lang, RejectReason } from "@pattern-blue/contracts";
import { useMachine } from "@xstate/react";
import { useEffect, useRef, type ReactNode } from "react";
import { decisionMachine, type DecisionKind, type DecisionResult } from "../machines/decision";
import { useAppServices, useI18n } from "./context";
import { clockText } from "./format";
import { Icon } from "./ui";

const BUTTON: Record<DecisionKind, { icon: string; key: "decide.approve" | "decide.reject" | "decide.resolve" | "decide.escalate"; ghost?: boolean }> = {
  APPROVED: { icon: "check", key: "decide.approve" },
  REJECTED: { icon: "x", key: "decide.reject" },
  RESOLVED: { icon: "check", key: "decide.resolve" },
  ESCALATE: { icon: "chev2", key: "decide.escalate", ghost: true },
};

const QUESTION = {
  APPROVED: "decide.approveQ",
  REJECTED: "decide.rejectQ",
  RESOLVED: "decide.resolveQ",
  ESCALATE: "decide.escalateQ",
} as const;

const CONFIRM = {
  APPROVED: "decide.confirmApprove",
  REJECTED: "decide.confirmReject",
  RESOLVED: "decide.confirmResolve",
  ESCALATE: "decide.confirmEscalate",
} as const;

const DONE = {
  APPROVED: "decide.done.APPROVED",
  REJECTED: "decide.done.REJECTED",
  RESOLVED: "decide.done.RESOLVED",
} as const;

const ERROR = {
  alreadyClosed: "decide.errors.alreadyClosed",
  heldByAnother: "decide.errors.heldByAnother",
  notAllowed: "decide.errors.notAllowed",
  unavailable: "errors.unavailable",
} as const;

/** The first part of an e-mail: how the back office names an agent in a line. */
export const agentName = (agentRef: string | null): string | null => (agentRef ? (agentRef.split("@")[0] ?? agentRef) : null);

export interface DecisionsProps {
  detail: HandoffDetail;
  /** The agent signed in. */
  me: string;
  /** Whether the conversation still exists: without it the customer cannot be told. */
  conversationAlive: boolean;
  /** The customer's language, when the conversation is loaded; else the agent's. */
  messageLang: Lang;
  onDone?: (result: DecisionResult) => void;
}

export interface DecisionsView {
  /** The buttons, or a note when the agent may not decide; null while a choice is open or done. */
  buttons: ReactNode;
  /** The open choice, the result, or a closed case's outcome. */
  panel: ReactNode;
  /** True while nothing is open: the place where the buttons go can show. */
  idle: boolean;
}

/** The outcome of a closed case, as its line: "Aprobado por ana · 22:06". */
export function ClosedLine({ detail, me }: { detail: HandoffDetail; me: string }) {
  const { t } = useI18n();
  if (detail.status !== "CLOSED" || !detail.outcome) return null;
  const who = detail.closed_by === me ? t("decide.you") : (agentName(detail.closed_by) ?? t("common.unknown"));
  const message = detail.decisions.closing_messages[detail.outcome];
  return (
    <p className="pb-done" role="status">
      <Icon name="check" />
      <span>
        {t("decide.closedBy", { outcome: t(`enums.outcome.${detail.outcome}`), agent: who, time: detail.closed_at ? clockText(detail.closed_at) : "" })}
        {detail.outcome_reason && ` · ${t(`enums.rejectReason.${detail.outcome_reason}`)}`}
      </span>
      {message && <small>{t("decide.sentMessage")}</small>}
    </p>
  );
}

export function useDecisions({ detail, me, conversationAlive, messageLang, onDone }: DecisionsProps): DecisionsView {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(decisionMachine, { input: { api, ref: detail.handoff_ref, department: detail.department } });
  const { context } = snapshot;
  const reported = useRef(false);

  useEffect(() => {
    if (snapshot.status === "done" && context.result && !reported.current) {
      reported.current = true;
      onDone?.(context.result);
    }
  }, [snapshot.status, context.result, onDone]);

  if (snapshot.matches("done") && context.result) {
    const { result } = context;
    const time = clockText(result.at);
    const line =
      result.kind === "ESCALATE"
        ? t("decide.done.escalated", { department: t(`enums.department.${result.handoff.department}`), time })
        : t(DONE[result.kind], { time });
    const sub = result.kind === "ESCALATE" ? t("decide.backToQueue") : result.customerNotified ? t("decide.notified") : t("decide.notNotified");
    return {
      buttons: null,
      idle: false,
      panel: (
        <p className="pb-done" role="status">
          <Icon name="check" />
          <span>{line}</span>
          <small>{sub}</small>
        </p>
      ),
    };
  }

  if (detail.status === "CLOSED") return { buttons: null, idle: true, panel: <ClosedLine detail={detail} me={me} /> };

  const holder = detail.assigned_agent;
  if (holder !== null && holder !== me) {
    return {
      idle: true,
      panel: null,
      buttons: (
        <p className="pb-decide__note">
          <Icon name="user" />
          {t("decide.heldBy", { agent: holder })}
        </p>
      ),
    };
  }

  const { outcomes, reject_reasons: reasons, escalate_to: teams } = detail.decisions;
  const kinds: DecisionKind[] = [...outcomes, ...(teams.length > 0 ? (["ESCALATE"] as const) : [])];
  if (kinds.length === 0) return { buttons: null, idle: true, panel: null };
  // A rejection without approval exists only when approving needs a verified customer (decisions.json).
  const approveBlocked = outcomes.includes("REJECTED") && !outcomes.includes("APPROVED");

  const buttons = (
    <>
      {kinds.map((kind) => (
        <button
          key={kind}
          type="button"
          className={`pb-btn pb-btn--sm ${BUTTON[kind].ghost ? "pb-btn--ghost" : "pb-btn--secondary"}`}
          onClick={() => send({ type: "OPEN", kind })}
        >
          <Icon name={BUTTON[kind].icon} />
          {t(BUTTON[kind].key)}
        </button>
      ))}
      {approveBlocked && (
        <p className="pb-decide__note">
          <Icon name="info" />
          {t("decide.approveNeedsVerified")}
        </p>
      )}
    </>
  );

  if (snapshot.matches("idle")) return { buttons, idle: true, panel: null };

  const kind = context.kind as DecisionKind;
  const sending = snapshot.matches("sending");
  const queued = holder === null;
  const message = kind === "ESCALATE" ? undefined : detail.decisions.closing_messages[kind as HandoffOutcome];
  const errorKey = context.error === null ? null : context.error in ERROR ? ERROR[context.error as keyof typeof ERROR] : "errors.generic";

  const panel = (
    <div className="pb-confirm" role="group" aria-label={t(QUESTION[kind])}>
      <p className="pb-confirm__q">{t(QUESTION[kind])}</p>
      {kind === "REJECTED" && (
        <div className="pb-choices" role="radiogroup" aria-label={t("decide.reasonLabel")}>
          {reasons.map((reason: RejectReason) => (
            <button
              key={reason}
              type="button"
              className="pb-btn pb-btn--secondary pb-btn--sm"
              role="radio"
              aria-checked={context.reason === reason}
              onClick={() => send({ type: "REASON.SET", reason })}
            >
              {t(`enums.rejectReason.${reason}`)}
            </button>
          ))}
        </div>
      )}
      {kind === "ESCALATE" && (
        <>
          <div className="pb-choices" role="radiogroup" aria-label={t("decide.teamLabel")}>
            {teams.map((team: Department) => (
              <button
                key={team}
                type="button"
                className="pb-btn pb-btn--secondary pb-btn--sm"
                role="radio"
                aria-checked={context.department === team}
                onClick={() => send({ type: "DEPARTMENT.SET", department: team })}
              >
                {t(`enums.department.${team}`)}
              </button>
            ))}
          </div>
          {detail.priority !== "URGENT" && (
            <label className="pb-check">
              <input type="checkbox" checked={context.urgent} onChange={(event) => send({ type: "URGENT.SET", urgent: event.target.checked })} />
              {t("decide.urgent")}
            </label>
          )}
          <p className="pb-confirm__msg">{t("decide.escalateNote")}</p>
        </>
      )}
      {kind !== "ESCALATE" && (
        <p className="pb-confirm__msg">
          {queued ? t("decide.claimsIt") : t("decide.closes")}{" "}
          {!conversationAlive ? t("decide.noConversation") : message ? <>{t("decide.customerGets")} <q>{message[messageLang]}</q></> : null}
        </p>
      )}
      {errorKey && (
        <p className="pb-confirm__error" role="alert">
          <Icon name="warning" />
          {t(errorKey)}
        </p>
      )}
      <div className="pb-confirm__row">
        <button type="button" className="pb-btn pb-btn--primary pb-btn--sm" disabled={sending || !snapshot.can({ type: "CONFIRM" })} onClick={() => send({ type: "CONFIRM" })}>
          {sending ? t("decide.sending") : t(CONFIRM[kind])}
        </button>
        <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" disabled={sending} onClick={() => send({ type: "CANCEL" })}>
          {t("common.cancel")}
        </button>
      </div>
    </div>
  );
  return { buttons: null, idle: false, panel };
}
