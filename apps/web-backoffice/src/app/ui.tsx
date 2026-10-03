// Small pieces of the design system as React: StatusChip, AlertBanner, the icon and the case id. The
// markup is the one of the component previews (packages/design-tokens/reference/components/*/preview.html)
// and of local.css, so the classes and attributes are the design system's, not ours.
//
// Chips speak the agent's language (the declutter review of 2026-10-02): the word is the chip's text and
// the raw enum is its tooltip, instead of both side by side.

import type { HandoffPriority, HandoffStatus } from "@pattern-blue/contracts";
import type { ReactNode } from "react";
import { useI18n } from "./context";

export function Icon({ name, large = false }: { name: string; large?: boolean }) {
  return <i className={`pb-ico pb-ico--${name}${large ? " pb-ico--lg" : ""}`} aria-hidden="true" />;
}

// --- StatusChip -----------------------------------------------------------------------------------------

/** An XState value or a raw enum as the chip's `data-state`: `OTP_PENDING` -> `otp-pending`. */
export const chipState = (value: string): string => value.toLowerCase().replace(/_/g, "-");

type Tone = "danger" | "warning" | "neutral" | "info" | "success";

/** A chip: a glyph and a word, with the raw enum as its tooltip when there is one. */
export function Chip({ tone, icon, title, children }: { tone: Tone; icon: string; title?: string; children: ReactNode }) {
  return (
    <span className="pb-chip" data-tone={tone} title={title}>
      <Icon name={icon} />
      {children}
    </span>
  );
}

/** A case id in mono, lowercase, in groups of four. The groups are spans, so a copy gives the plain id. */
export function CaseRef({ value, large = false }: { value: string; large?: boolean }) {
  const cut = value.indexOf("_") + 1;
  const head = value.slice(0, cut);
  const rest = value.slice(cut);
  const groups = rest.match(/.{1,4}/g) ?? [];
  return (
    <span className={`pb-caseref${large ? " pb-caseref--lg" : ""}`}>
      {head && <span>{head}</span>}
      {groups.map((group, index) => (
        <span key={index}>{group}</span>
      ))}
    </span>
  );
}

const PRIORITY_CHIP: Record<HandoffPriority, { tone: Tone; icon: string }> = {
  URGENT: { tone: "danger", icon: "chev2" },
  HIGH: { tone: "warning", icon: "chev1" },
  NORMAL: { tone: "neutral", icon: "minus" },
  LOW: { tone: "neutral", icon: "minus" },
};

export function PriorityChip({ priority }: { priority: HandoffPriority }) {
  const { t } = useI18n();
  const { tone, icon } = PRIORITY_CHIP[priority];
  return (
    <Chip tone={tone} icon={icon} title={priority}>
      {t(`enums.priority.${priority}`)}
    </Chip>
  );
}

const STATUS_CHIP: Record<HandoffStatus, { tone: Tone; icon: string }> = {
  QUEUED: { tone: "info", icon: "clock" },
  ASSIGNED: { tone: "success", icon: "user" },
  PENDING: { tone: "neutral", icon: "clock" },
  CLOSED: { tone: "neutral", icon: "check" },
};

export function HandoffStatusChip({ status }: { status: HandoffStatus }) {
  const { t } = useI18n();
  const { tone, icon } = STATUS_CHIP[status];
  return (
    <Chip tone={tone} icon={icon} title={status}>
      {t(`enums.status.${status}`)}
    </Chip>
  );
}

/** The audit decision of a tool call, as a chip in words; `title` carries the raw codes. */
export function DecisionChip({ decision, title }: { decision: "allowed" | "refused" | "error"; title?: string }) {
  const { t } = useI18n();
  const tone: Tone = decision === "allowed" ? "success" : decision === "refused" ? "warning" : "danger";
  const icon = decision === "allowed" ? "check" : decision === "refused" ? "warning" : "critical";
  return (
    <Chip tone={tone} icon={icon} title={title ?? decision}>
      {t(`enums.decision.${decision}`)}
    </Chip>
  );
}

// --- AlertBanner ----------------------------------------------------------------------------------------

export type AlertTone = "info" | "success" | "caution" | "critical";

const ALERT_ICON: Record<AlertTone, string> = { info: "info", success: "shield-check", caution: "warning", critical: "critical" };

/**
 * `stripe` adds the hazard stripe: only for caution and critical, and only when the reader must stop or
 * change course (an attempt to widen a tool, a write that was not confirmed). One per screen region.
 */
export function Alert({
  tone,
  eyebrow,
  stripe = false,
  action,
  hint,
  children,
  id,
}: {
  tone: AlertTone;
  eyebrow: string;
  stripe?: boolean;
  action?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  const striped = stripe && (tone === "caution" || tone === "critical");
  return (
    <div id={id} className={`pb-alert${striped ? " pb-alert--stripe" : ""}`} data-tone={tone} role={tone === "critical" ? "alert" : "status"}>
      {striped && <span className="pb-hazard" aria-hidden="true" />}
      <Icon name={ALERT_ICON[tone]} />
      <div>
        <span className="pb-alert__eyebrow">{eyebrow}</span>
        <p className="pb-alert__text">
          {children}
          {hint && <small>{hint}</small>}
        </p>
      </div>
      {action}
    </div>
  );
}

// --- FSM and resource states ----------------------------------------------------------------------------

export const STATE_GLYPH: Record<string, string> = {
  ANONYMOUS: "user-dashed",
  IDENTIFIED: "user",
  OTP_PENDING: "clock",
  VERIFIED: "shield-check",
  LOCKED: "lock",
  HANDED_OFF: "handoff",
  ACTIVE: "card",
  BLOCKED: "card-blocked",
};

/**
 * A StatusChip for a verification state or a card status, with the raw enum as its word. A state the
 * design system has no color for (NONE, QUEUED, ...) is a neutral chip: the word still says what it is.
 */
export function StateChip({ state, words = false }: { state: string; words?: boolean }) {
  const { t } = useI18n();
  const glyph = STATE_GLYPH[state];
  const known = state in STATE_WORD_KEYS;
  const word = words && known ? t(STATE_WORD_KEYS[state as keyof typeof STATE_WORD_KEYS]) : state;
  if (!glyph) {
    return (
      <span className="pb-chip" data-tone="neutral" title={words ? state : undefined}>
        <Icon name="minus" />
        {word}
      </span>
    );
  }
  return (
    <span className="pb-chip" data-state={chipState(state)} title={words ? state : undefined}>
      <Icon name={glyph} />
      {word}
    </span>
  );
}

const STATE_WORD_KEYS = {
  ANONYMOUS: "enums.state.ANONYMOUS",
  IDENTIFIED: "enums.state.IDENTIFIED",
  OTP_PENDING: "enums.state.OTP_PENDING",
  VERIFIED: "enums.state.VERIFIED",
  LOCKED: "enums.state.LOCKED",
  HANDED_OFF: "enums.state.HANDED_OFF",
} as const;
