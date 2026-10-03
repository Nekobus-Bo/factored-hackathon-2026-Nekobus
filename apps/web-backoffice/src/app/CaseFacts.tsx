// What a handoff says, as sentences (the declutter review of 2026-10-02). Built only from what banking-core
// stored with the handoff: `verified_facts` are facts a tool returned, `open_questions` are what the model
// wrote and nothing verified. The bank's checks carry an icon in their state's colour; the assistant's
// summary of what the customer asked sits in a dashed quote marked as unverified. Nothing here suggests an
// outcome: the agent decides (ADR-0018).

import type { HandoffDetail, JsonValue } from "@pattern-blue/contracts";
import type { ReactNode } from "react";
import { useI18n } from "./context";
import { clockText, dateTimeText, money } from "./format";
import { Icon } from "./ui";

type Summary = HandoffDetail["summary"];
type Action = Summary["actions_taken"][number];

const isRecord = (value: JsonValue | undefined): value is { [key: string]: JsonValue } =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** `**** **** **** 4821` -> `•••• 4821`: the last four, as the design system prints a mask. */
export const shortMask = (masked: string) => {
  const digits = masked.replace(/[^0-9]/g, "");
  return digits.length >= 4 ? `•••• ${digits.slice(-4)}` : masked.replaceAll("*", "•");
};

export interface Charge {
  merchant: string | null;
  amountMinor: number;
  currency: string;
  postedAt: string | null;
  card: string | null;
  transactionId: string | null;
}

/** The disputed charge handoff.create stored, if the case has one with an amount. */
export function disputedCharge(summary: Summary): Charge | null {
  const value = summary.verified_facts.disputed_transaction;
  if (!isRecord(value)) return null;
  const { amount_minor: amount, currency } = value;
  if (typeof amount !== "number" || typeof currency !== "string") return null;
  const text = (key: string) => (typeof value[key] === "string" ? (value[key] as string) : null);
  return {
    merchant: text("merchant"),
    amountMinor: amount,
    currency,
    postedAt: text("posted_at"),
    card: text("card_masked"),
    transactionId: text("transaction_id"),
  };
}

/** `2026-09-30 21:14 UTC`: the design system's ISO time, without the seconds. */
const minuteText = (iso: string) => dateTimeText(iso).replace(/:\d\d UTC$/, " UTC");

export function ChargeBlock({ charge }: { charge: Charge }) {
  const { t } = useI18n();
  const meta = [
    charge.postedAt ? minuteText(charge.postedAt) : null,
    charge.card ? (
      <span key="card">
        {t("handoff.card")} <span className="pb-t-mono">{shortMask(charge.card)}</span>
      </span>
    ) : null,
    charge.transactionId ? (
      <span key="id" className="pb-t-mono" title={charge.transactionId}>
        {charge.transactionId.slice(0, 8)}
      </span>
    ) : null,
  ].filter((part) => part !== null);
  return (
    <div className="pb-txn">
      <span className="pb-txn__amount">{money(charge.amountMinor, charge.currency)}</span>
      {charge.merchant && <span className="pb-txn__who">{charge.merchant}</span>}
      {meta.length > 0 && (
        <span className="pb-txn__meta">
          {meta.map((part, index) => (
            <span key={index}>
              {index > 0 && " · "}
              {part}
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

/** What the assistant wrote about the customer's request: one quote per open question, marked unverified. */
export function SaidQuotes({ summary }: { summary: Summary }) {
  const { t } = useI18n();
  if (summary.open_questions.length === 0) return <p className="pb-sum__foot">{t("handoff.noAsk")}</p>;
  return (
    <>
      {summary.open_questions.map((question, index) => (
        <p key={index} className="pb-said">
          {question.text}
          <small>{question.source === "model_unverified" ? t("handoff.saidByAssistant") : t("handoff.saidBy", { source: question.source })}</small>
        </p>
      ))}
    </>
  );
}

function Fact({ icon, tone, children }: { icon: string; tone?: "blocked" | "warn" | "muted"; children: ReactNode }) {
  return (
    <li data-tone={tone}>
      <Icon name={icon} />
      <span>{children}</span>
    </li>
  );
}

const IDENTITY = {
  VERIFIED: { icon: "shield-check", tone: undefined, key: "handoff.identity.VERIFIED" },
  IDENTIFIED: { icon: "user", tone: "muted", key: "handoff.identity.IDENTIFIED" },
  OTP_PENDING: { icon: "clock", tone: "muted", key: "handoff.identity.OTP_PENDING" },
  ANONYMOUS: { icon: "user-dashed", tone: "muted", key: "handoff.identity.ANONYMOUS" },
  LOCKED: { icon: "lock", tone: "blocked", key: "handoff.identity.LOCKED" },
  HANDED_OFF: { icon: "handoff", tone: "muted", key: "handoff.identity.HANDED_OFF" },
} as const;

/** One sentence for whether the bank knows who this is, from the state stored with the handoff. */
export function IdentityFact({ summary }: { summary: Summary }) {
  const { t } = useI18n();
  const state = summary.verified_facts.verification_state;
  const known = typeof state === "string" && state in IDENTITY ? IDENTITY[state as keyof typeof IDENTITY] : IDENTITY.ANONYMOUS;
  const withCode = state === "VERIFIED" && summary.verification_method === "document_match_and_otp";
  return (
    <Fact icon={known.icon} tone={known.tone}>
      {withCode ? t("handoff.identity.VERIFIED_WITH_CODE") : t(known.key)}
    </Fact>
  );
}

/** The policy flags in words; none when there are none. A flag the screens do not know shows as it is. */
export function PolicyFacts({ summary }: { summary: Summary }) {
  const { t } = useI18n();
  const raw = summary.verified_facts.policy_flags;
  const flags = Array.isArray(raw) ? raw.filter((flag): flag is string => typeof flag === "string") : [];
  const lines: string[] = [];
  if (flags.includes("HANDOFF_REQUIRED")) lines.push(t("handoff.flags.required"));
  else if (flags.includes("HANDOFF_RECOMMENDED")) lines.push(t("handoff.flags.recommended"));
  else if (flags.includes("POLICY_FLAGGED")) lines.push(t("handoff.flags.flagged"));
  if (flags.includes("PRIORITY")) lines.push(t("handoff.flags.priority"));
  if (flags.includes("RATE_LIMIT_EXCEEDED")) lines.push(t("handoff.flags.rateLimited"));
  const known = new Set(["HANDOFF_REQUIRED", "HANDOFF_RECOMMENDED", "POLICY_FLAGGED", "PRIORITY", "RATE_LIMIT_EXCEEDED"]);
  for (const flag of flags) if (!known.has(flag)) lines.push(flag);
  return (
    <>
      {lines.map((line) => (
        <Fact key={line} icon="warning" tone="warn">
          {line}
        </Fact>
      ))}
    </>
  );
}

/** A tool call as stored: its name, decision, reason code and audit id, whatever shape it came in. */
export function actionParts(action: Action): { name: string; decision: string | null; reasonCode: string | null; auditId: string | null } {
  if (typeof action === "string") return { name: action, decision: null, reasonCode: null, auditId: null };
  const text = (key: string) => (typeof action[key] === "string" ? (action[key] as string) : null);
  return { name: text("action") ?? JSON.stringify(action), decision: text("decision"), reasonCode: text("reason_code"), auditId: text("audit_id") };
}

/** The writes the assistant made, in words. Reads and refusals live in the full log. */
const WRITES = { "card.block": { icon: "card-blocked", tone: "blocked", key: "handoff.did.cardBlock" } } as const;

export function WriteFacts({ summary }: { summary: Summary }) {
  const { t } = useI18n();
  const writes = summary.actions_taken
    .map(actionParts)
    .filter((action) => action.decision === "allowed" && action.name in WRITES);
  if (writes.length === 0) {
    return (
      <Fact icon="minus" tone="muted">
        {t("handoff.did.nothing")}
      </Fact>
    );
  }
  return (
    <>
      {writes.map((action, index) => {
        const write = WRITES[action.name as keyof typeof WRITES];
        return (
          <Fact key={index} icon={write.icon} tone={write.tone}>
            {t(write.key)} {action.auditId && <span className="pb-t-mono">{action.auditId}</span>}
          </Fact>
        );
      })}
    </>
  );
}

/** The customer's answer to "¿Te ayudó el asistente?", as their words, not a bank check. */
export function FeedbackFact({ feedback }: { feedback: HandoffDetail["feedback"] }) {
  const { t } = useI18n();
  if (!feedback) {
    return (
      <Fact icon="minus" tone="muted">
        {t("handoff.feedback.none")}
      </Fact>
    );
  }
  return (
    <Fact icon="user" tone="muted">
      {feedback.helpful ? t("handoff.feedback.yes") : t("handoff.feedback.no")} · {clockText(feedback.recorded_at)}
    </Fact>
  );
}

const REASON_KEYS = {
  STATE_NOT_ALLOWED: "enums.reasonCode.STATE_NOT_ALLOWED",
  POLICY_BLOCKED: "enums.reasonCode.POLICY_BLOCKED",
  POLICY_FLAGGED: "enums.reasonCode.POLICY_FLAGGED",
  RATE_LIMITED: "enums.reasonCode.RATE_LIMITED",
  NOT_MATCHED: "enums.reasonCode.NOT_MATCHED",
  NOT_IMPLEMENTED: "enums.reasonCode.NOT_IMPLEMENTED",
  SESSION_BUSY: "enums.reasonCode.SESSION_BUSY",
  INVALID_ARGUMENTS: "enums.reasonCode.INVALID_ARGUMENTS",
  CODE_FLOOR_VIOLATION: "enums.reasonCode.CODE_FLOOR_VIOLATION",
  CONFIRMATION_REQUIRED: "enums.reasonCode.CONFIRMATION_REQUIRED",
  INTERNAL_ERROR: "enums.reasonCode.INTERNAL_ERROR",
} as const;

/** A reason code in words, in lower case to follow a decision: "estado no permitido". Unknown codes stay raw. */
export function useReasonWord(): (reasonCode: string) => string {
  const { t } = useI18n();
  return (reasonCode) => (reasonCode in REASON_KEYS ? t(REASON_KEYS[reasonCode as keyof typeof REASON_KEYS]).toLowerCase() : reasonCode);
}

/** "Rechazada, estado no permitido": the decision and its reason in words; the raw codes go in a tooltip. */
export function useResultWords(): (decision: string | null, reasonCode: string | null) => string {
  const { t } = useI18n();
  const reasonWord = useReasonWord();
  return (decision, reasonCode) => {
    const word = decision === "allowed" || decision === "refused" || decision === "error" ? t(`enums.decision.${decision}`) : (decision ?? t("common.empty"));
    return reasonCode ? `${word}, ${reasonWord(reasonCode)}` : word;
  };
}

/** Every call the assistant made, one line each: tool, result in words, audit id. */
export function AuditLog({ summary, id }: { summary: Summary; id: string }) {
  const words = useResultWords();
  return (
    <table className="pb-audit" id={id}>
      <tbody>
        {summary.actions_taken.map((action, index) => {
          const parts = actionParts(action);
          const raw = [parts.decision, parts.reasonCode].filter(Boolean).join(" · ");
          return (
            <tr key={index} data-refused={parts.decision !== null && parts.decision !== "allowed" ? "" : undefined}>
              <td>{parts.name}</td>
              <td title={raw || undefined}>{words(parts.decision, parts.reasonCode)}</td>
              <td>{parts.auditId ?? ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
