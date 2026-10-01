// The pure part of the chat: what the transcript holds, what it proves, and what may be shown of what
// the customer typed. No I/O and no clock, so every rule here is a plain function under test.

import {
  parseBlocks,
  type InboxMessage,
  type Lang,
  type MessageBlock,
  type RawBlock,
  type TranscriptMessage,
} from "@pattern-blue/contracts";

// --- The transcript the customer sees ------------------------------------------------------------------

/**
 * What the log renders. It is built on the client from what the customer typed (masked for display) and
 * from what the API returned. The OTP code is never in an entry: the inbox keeps it apart.
 */
export type Entry =
  /** `text` is the display text: a code or a card number the customer typed is already masked. */
  | { id: string; kind: "customer"; text: string; at: string; lang: Lang; status: "sent" | "failed" }
  /** One turn of the assistant: its blocks, raw as they came. The renderer runs `parseBlocks`. */
  | { id: string; kind: "assistant"; blocks: RawBlock[]; at: string; lang: Lang }
  /** A message a person wrote after taking the conversation over. `key` deduplicates the polling. */
  | { id: string; kind: "agent"; text: string; at: string; key: string }
  /** A client-derived line between messages: the strings live in the dictionary, keyed by `code`. */
  | { id: string; kind: "system"; code: "takeover" | "codeExpired"; at: string };

export type ChipState = "otp-pending" | "verified" | "locked" | "blocked" | "handed-off";

// --- The header chip: only what the blocks prove --------------------------------------------------------

/**
 * The state the header chip shows, or null when nothing proves one. It reads receipts and handoff
 * blocks, never text (the model may say anything), and the takeover the server reported. The latest
 * proof wins: the flow moves from a pending code to verified, to a blocked card, to a person.
 */
export function deriveChip(entries: readonly Entry[], takeoverActive: boolean): ChipState | null {
  let chip: ChipState | null = null;
  for (const entry of entries) {
    if (entry.kind !== "assistant") continue;
    for (const block of parseBlocks(entry.blocks).blocks) {
      const proven = chipOfBlock(block);
      if (proven) chip = proven;
    }
  }
  return takeoverActive ? "handed-off" : chip;
}

function chipOfBlock(block: MessageBlock): ChipState | null {
  if (block.type === "handoff") return "handed-off";
  if (block.type !== "receipt") return null;
  const { action, state_after: after } = block.receipt;
  if (action === "otp.send" && after === "OTP_PENDING") return "otp-pending";
  if (action === "otp.verify" && after === "VERIFIED") return "verified";
  if (action === "otp.verify" && after === "LOCKED") return "locked";
  if (action === "card.block" && after === "BLOCKED") return "blocked";
  return null;
}

/** True while a code was sent and no verification has succeeded since: the next digits are the code. */
export function isOtpPending(entries: readonly Entry[]): boolean {
  let pending = false;
  for (const entry of entries) {
    if (entry.kind !== "assistant") continue;
    for (const block of parseBlocks(entry.blocks).blocks) {
      if (block.type !== "receipt") continue;
      if (block.receipt.action === "otp.send" && block.receipt.state_after === "OTP_PENDING") pending = true;
      if (block.receipt.action === "otp.verify" && block.receipt.state_after === "VERIFIED") pending = false;
    }
  }
  return pending;
}

/** The `verified_at` of the newest successful `otp.verify` in these blocks, or null. */
export function verifiedAtOf(rawBlocks: readonly RawBlock[]): string | null {
  let verifiedAt: string | null = null;
  for (const block of parseBlocks(rawBlocks).blocks) {
    if (block.type === "receipt" && block.receipt.action === "otp.verify" && block.receipt.state_after === "VERIFIED") {
      verifiedAt = block.receipt.verified_at;
    }
  }
  return verifiedAt;
}

// --- What the customer typed -----------------------------------------------------------------------------

export const CODE_MASK = "••••••";

// The orchestrator's own pattern for a bare code while a challenge is pending (engine.py `_BARE_OTP_RE`):
// 4 to 8 digits with at most one internal space or dash. Keeping the two alike means the log hides what the
// backend hides.
const BARE_CODE = /(?<![\w[\]])\d+(?:[ -]\d+)?(?![\w[\]])(?![ -]\d)/g;

/**
 * The text of a customer bubble. A one-time code is shown as `••••••`: the digits of a code the inbox
 * delivered wherever they appear, and, while a challenge is pending, any bare 4 to 8 digit number. When
 * nothing but the code was typed the bubble reads "Código: ••••••" (`codePrefix`).
 */
export function maskTypedSecrets(
  text: string,
  options: { otpPending: boolean; knownCodes: readonly string[]; codePrefix: string },
): string {
  let masked = text;
  for (const code of options.knownCodes) {
    if (!/^\d{4,8}$/.test(code)) continue;
    const digits = [...code].join("[ -]?");
    masked = masked.replace(new RegExp(`(?<!\\d)${digits}(?!\\d)`, "g"), CODE_MASK);
  }
  if (options.otpPending) {
    masked = masked.replace(BARE_CODE, (match) => {
      const count = match.replace(/[ -]/g, "").length;
      return count >= 4 && count <= 8 ? CODE_MASK : match;
    });
  }
  masked = maskCardNumbers(masked);
  return masked.trim() === CODE_MASK ? `${options.codePrefix}: ${CODE_MASK}` : masked;
}

// 13 to 19 digits in a row, or 4-4-4-4 (also 4-6-5) with a space or a dash: a card number.
const CARD_NUMBER = /(?<![\d\w])(?:\d{13,19}|\d{4}(?:[ -]\d{4}){3}|\d{4}[ -]\d{6}[ -]\d{5})(?![\d\w])/g;

/** Never render a full card number, whoever wrote it: `•••• 4821`. */
export function maskCardNumbers(text: string): string {
  return text.replace(CARD_NUMBER, (match) => `•••• ${match.replace(/\D/g, "").slice(-4)}`);
}

/**
 * The masked target of a receipt as the chat shows it. The contract's masked card is `**** **** **** 4821`;
 * the chat writes it `•••• 4821`. Anything else (an e-mail `d***@example.com`) is already in its display form.
 */
export function displayTarget(targetMasked: string): string {
  const card = /^(?:\*{4}[\s-]?\*{4}[\s-]?\*{4}[\s-]?|\*{4,12})(\d{4})$/.exec(targetMasked);
  return card ? `•••• ${card[1]}` : targetMasked;
}

// --- The simulated inbox -------------------------------------------------------------------------------------

/**
 * The message the notice is about: unexpired, and received after the last successful verification (the
 * inbox keeps a used code until it expires; a used code is not news). Newest first when there are several.
 */
export function pickInboxMessage(
  messages: readonly InboxMessage[],
  nowMs: number,
  verifiedAt: string | null,
): InboxMessage | null {
  const verifiedMs = verifiedAt === null ? Number.NEGATIVE_INFINITY : Date.parse(verifiedAt);
  const live = messages.filter(
    (message) => Date.parse(message.expires_at) > nowMs && Date.parse(message.received_at) > verifiedMs,
  );
  live.sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at));
  return live[0] ?? null;
}

/** `mm:ss` for a countdown; never negative. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

// --- Agent messages from the transcript ------------------------------------------------------------------------

export function agentKey(message: Pick<TranscriptMessage, "created_at" | "content">): string {
  return `${message.created_at}|${message.content}`;
}

/** The agent messages of a transcript that the log does not hold yet, oldest first. */
export function newAgentMessages(
  messages: readonly TranscriptMessage[],
  entries: readonly Entry[],
): TranscriptMessage[] {
  const known = new Set(entries.flatMap((entry) => (entry.kind === "agent" ? [entry.key] : [])));
  return messages
    .filter((message) => message.role === "agent" && message.content.trim() !== "")
    .filter((message) => !known.has(agentKey(message)))
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

// --- Time ----------------------------------------------------------------------------------------------------------

/** `10:39` in 24 h, in the viewer's time zone (or `timeZone`, for tests). */
export function formatClock(iso: string, lang: Lang, timeZone?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone }).format(date);
}
