// Display formatting, following the design system's data rules: a currency code first (`USD 139.99`),
// times as ISO with 24 h and the zone, waits as tabular `mm:ss`. Pure functions, no locale surprises:
// the same input reads the same in es, pt and en.

/** Group the digits of a whole number by thousands: 2000000 -> "2,000,000". */
function group(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Minor units (cents) as a major-unit amount without the currency: `13999` -> "139.99".
 * COP shows no decimals when there are none (the seed values are "COP 2,000,000").
 */
export function majorText(minor: number, currency: string): string {
  const negative = minor < 0;
  const abs = Math.abs(minor);
  const whole = Math.trunc(abs / 100);
  const cents = abs % 100;
  const text = currency === "COP" && cents === 0 ? group(String(whole)) : `${group(String(whole))}.${String(cents).padStart(2, "0")}`;
  return negative ? `-${text}` : text;
}

/** `USD 139.99`: the currency code first. */
export function money(minor: number, currency: string): string {
  return `${currency} ${majorText(minor, currency)}`;
}

/**
 * What an agent typed as a threshold, in minor units, or null if it is not an amount greater than zero
 * with at most two decimals. The dot is the decimal point; a comma is accepted only as a thousands
 * separator in its right place (`2,000,000`). A decimal comma (`2500,50`) is refused, never read as
 * `250050`: a threshold that is off by a factor of a hundred is worse than one that is refused.
 */
export function parseMajor(text: string): number | null {
  const match = /^(\d{1,15}|\d{1,3}(?:,\d{3})+)(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!match) return null;
  const whole = (match[1] as string).replaceAll(",", "");
  const minor = Number(whole) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return Number.isSafeInteger(minor) && minor > 0 ? minor : null;
}

const pad = (value: number) => String(value).padStart(2, "0");

/** How long ago `since` was, as `mm:ss`, `h:mm:ss` from an hour on, and `Nd hh:mm:ss` from a day on. */
export function waitText(sinceMs: number, nowMs: number): string {
  const total = Math.max(0, Math.floor((nowMs - sinceMs) / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600) % 24;
  const days = Math.floor(total / 86_400);
  if (days > 0) return `${days}d ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  if (hours > 0) return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  return `${pad(minutes)}:${pad(seconds)}`;
}

/** `2026-09-29 10:42:18 UTC`: ISO date, 24 h time and the zone. The API speaks UTC. */
export function dateTimeText(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())} UTC`;
}

/** `10:42` for a message stamp. */
export function clockText(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

/** Share of a total, as a whole percentage. */
export function percent(count: number, total: number): number {
  return total > 0 ? Math.round((count / total) * 100) : 0;
}
