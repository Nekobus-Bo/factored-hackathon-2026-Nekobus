// The design system's icon set: CSS masks on a 16 px grid that take the current text color. An icon
// never carries a status alone (it sits next to a word), so it is `aria-hidden` unless it is given a label.

export type IconName =
  | "check"
  | "arrow"
  | "retry"
  | "plus"
  | "menu"
  | "sun"
  | "moon"
  | "x"
  | "pause"
  | "lock"
  | "user"
  | "user-dashed"
  | "clock"
  | "handoff"
  | "card"
  | "card-blocked"
  | "mail"
  | "chat"
  | "warning"
  | "critical"
  | "info"
  | "shield-check"
  | "chev2"
  | "chev1"
  | "minus"
  | "send"
  | "db"
  | "infinity"
  | "hex"
  | "detective";

export function Icon({ name, label, large = false }: { name: IconName; label?: string; large?: boolean }) {
  const className = `pb-ico pb-ico--${name}${large ? " pb-ico--lg" : ""}`;
  return label ? <i className={className} role="img" aria-label={label} /> : <i className={className} aria-hidden="true" />;
}
