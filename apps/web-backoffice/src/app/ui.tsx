// Small pieces of the design system as React: StatusChip, AlertBanner and the icon. The markup is the
// one of the component previews (packages/design-tokens/reference/components/*/preview.html), so the
// classes and attributes are the design system's, not ours.

import type { HandoffPriority, HandoffStatus } from "@pattern-blue/contracts";
import type { ReactNode } from "react";

export function Icon({ name, large = false }: { name: string; large?: boolean }) {
  return <i className={`pb-ico pb-ico--${name}${large ? " pb-ico--lg" : ""}`} aria-hidden="true" />;
}

// --- StatusChip -----------------------------------------------------------------------------------------

/** An XState value or a raw enum as the chip's `data-state`: `OTP_PENDING` -> `otp-pending`. */
export const chipState = (value: string): string => value.toLowerCase().replace(/_/g, "-");

type Tone = "danger" | "warning" | "neutral" | "info" | "success";

/** A chip: a glyph and the raw enum. The back office shows the enum itself (StatusChip README). */
export function Chip({ tone, icon, children }: { tone: Tone; icon: string; children: ReactNode }) {
  return (
    <span className="pb-chip" data-tone={tone}>
      <Icon name={icon} />
      {children}
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
  const { tone, icon } = PRIORITY_CHIP[priority];
  return (
    <Chip tone={tone} icon={icon}>
      {priority}
    </Chip>
  );
}

const STATUS_CHIP: Record<HandoffStatus, { tone: Tone; icon: string }> = {
  QUEUED: { tone: "info", icon: "clock" },
  ASSIGNED: { tone: "success", icon: "user" },
  PENDING: { tone: "neutral", icon: "clock" },
};

export function HandoffStatusChip({ status }: { status: HandoffStatus }) {
  const { tone, icon } = STATUS_CHIP[status];
  return (
    <Chip tone={tone} icon={icon}>
      {status}
    </Chip>
  );
}

/** The audit decision of a tool call, as a chip. */
export function DecisionChip({ decision }: { decision: "allowed" | "refused" | "error" }) {
  const tone: Tone = decision === "allowed" ? "success" : decision === "refused" ? "warning" : "danger";
  const icon = decision === "allowed" ? "check" : decision === "refused" ? "warning" : "critical";
  return (
    <Chip tone={tone} icon={icon}>
      {decision}
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
export function StateChip({ state }: { state: string }) {
  const glyph = STATE_GLYPH[state];
  if (!glyph) {
    return (
      <span className="pb-chip" data-tone="neutral">
        <Icon name="minus" />
        {state}
      </span>
    );
  }
  return (
    <span className="pb-chip" data-state={chipState(state)}>
      <Icon name={glyph} />
      {state}
    </span>
  );
}
