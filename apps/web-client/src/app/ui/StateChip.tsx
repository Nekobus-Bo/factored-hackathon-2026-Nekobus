// StatusChip: a word, a glyph and a color, never a color alone. The state comes from the machine or the
// receipt; the word is the customer's (never the raw enum: that belongs to the back office).

import type { HandoffPriority, ResourceState } from "@pattern-blue/contracts";
import { Icon, type IconName } from "./Icon";

export type ChipStateName =
  | "anonymous"
  | "identified"
  | "otp-pending"
  | "verified"
  | "locked"
  | "handed-off"
  | "active"
  | "blocked";

const STATE_ICON: Record<ChipStateName, IconName> = {
  anonymous: "user-dashed",
  identified: "user",
  "otp-pending": "clock",
  verified: "shield-check",
  locked: "lock",
  "handed-off": "handoff",
  active: "card",
  blocked: "card-blocked",
};

/** Derive `data-state` from a machine or enum value: `OTP_PENDING` -> `otp-pending`. */
export const chipState = (value: string) => value.toLowerCase().replace(/_/g, "-");

export function StateChip({ state, label }: { state: ChipStateName; label: string }) {
  return (
    <span className="pb-chip" data-state={state}>
      <Icon name={STATE_ICON[state]} />
      {label}
    </span>
  );
}

const RESOURCE_CHIP: Partial<Record<ResourceState, ChipStateName>> = {
  ACTIVE: "active",
  BLOCKED: "blocked",
  ANONYMOUS: "anonymous",
  IDENTIFIED: "identified",
  OTP_PENDING: "otp-pending",
  VERIFIED: "verified",
  LOCKED: "locked",
  HANDED_OFF: "handed-off",
};

/** A receipt's state before or after: an FSM or card state keeps its color, any other is a neutral chip. */
export function ResourceChip({ state, label }: { state: ResourceState; label: string }) {
  const known = RESOURCE_CHIP[state];
  if (known) return <StateChip state={known} label={label} />;
  return (
    <span className="pb-chip" data-tone="neutral">
      <Icon name="minus" />
      {label}
    </span>
  );
}

const PRIORITY: Record<HandoffPriority, { tone: "danger" | "warning" | "neutral"; icon: IconName }> = {
  URGENT: { tone: "danger", icon: "chev2" },
  HIGH: { tone: "warning", icon: "chev1" },
  NORMAL: { tone: "neutral", icon: "minus" },
  LOW: { tone: "neutral", icon: "minus" },
};

export function PriorityChip({ priority, label }: { priority: HandoffPriority; label: string }) {
  const { tone, icon } = PRIORITY[priority];
  return (
    <span className="pb-chip" data-tone={tone}>
      <Icon name={icon} />
      {label}
    </span>
  );
}
