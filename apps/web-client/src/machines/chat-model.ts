// The pure part of the chat: what the transcript holds, what it proves, and what may be shown of what
// the customer typed. No I/O and no clock, so every rule here is a plain function under test.

import {
  parseBlocks,
  type InboxMessage,
  type Lang,
  type MessageBlock,
  type RawBlock,
  type TranscriptMessage,
  type TurnTrace,
} from "@pattern-blue/contracts";

// --- The transcript the customer sees ------------------------------------------------------------------

/**
 * What the log renders. It is built on the client from what the customer typed (masked for display) and
 * from what the API returned. The OTP code is never in an entry: the inbox keeps it apart.
 */
export type Entry =
  /** `text` is the display text: a code or a card number the customer typed is already masked. */
  | { id: string; kind: "customer"; text: string; at: string; lang: Lang; status: "sent" | "failed" }
  /**
   * One turn of the assistant: its blocks, raw as they came. The renderer runs `parseBlocks`. `trace` is
   * the turn's timeline, there only while detective mode is on (ADR-0019).
   */
  | { id: string; kind: "assistant"; blocks: RawBlock[]; at: string; lang: Lang; trace?: TurnTrace }
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

/**
 * The id of the newest assistant entry with a block that matches, or null. The log uses it to attach things to
 * one block: the countdown to the `otp.send` receipt whose code is still live, the feedback line to the handoff.
 */
export function lastEntryWith(entries: readonly Entry[], matches: (block: MessageBlock) => boolean): string | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index]!;
    if (entry.kind === "assistant" && parseBlocks(entry.blocks).blocks.some(matches)) return entry.id;
  }
  return null;
}

export const isOtpSendReceipt = (block: MessageBlock): boolean => block.type === "receipt" && block.receipt.action === "otp.send";
export const isHandoff = (block: MessageBlock): boolean => block.type === "handoff";

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

// --- The code mode of the composer -----------------------------------------------------------------------

/** The one-time code has this many digits (`otp_send.py` in banking-core). */
export const CODE_LENGTH = 6;

/** What the code field keeps of what was typed or pasted: only digits, at most `CODE_LENGTH` ("588 820" is "588820"). */
export function sanitizeCode(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, CODE_LENGTH);
}

/**
 * What the code field does with a change of its value (`raw` is what the input holds now: typed, pasted or both).
 * Only digits stay, six at most. The sixth digit sends the code, once, and the field empties, so a code that
 * failed starts again from nothing and the same six digits are never sent twice. While a turn is in flight
 * (`disabled`) the digits are kept and nothing is sent.
 */
export function codeFieldChange(raw: string, disabled: boolean): { digits: string; send: string | null } {
  const kept = sanitizeCode(raw);
  if (kept.length < CODE_LENGTH || disabled) return { digits: kept, send: null };
  return { digits: "", send: kept };
}

/**
 * The id of the entry that holds the newest `otp.send` receipt: it names the challenge. A new code is a new
 * receipt and so a new id, which is how "cancelled" belongs to one challenge only.
 */
export const challengeKey = (entries: readonly Entry[]): string | null => lastEntryWith(entries, isOtpSendReceipt);

/**
 * What the composer is for a challenge:
 *  - `off`        the normal composer: no challenge, or it was verified, or the session is locked, handed to an
 *                 agent or gone;
 *  - `entry`      the code field (`failed`: the last turn proved the code was not accepted, and only then);
 *  - `expired`    the code ran out: "Pedir otro código";
 *  - `dismissed`  the customer cancelled this challenge: the normal composer, and while the code is still live
 *                 (`resumable`) the notice offers to go back to the field.
 */
export type CodeMode =
  | { kind: "off" }
  | { kind: "entry"; failed: boolean }
  | { kind: "expired" }
  | { kind: "dismissed"; resumable: boolean };

export interface CodeModeInput {
  entries: readonly Entry[];
  /** The live notice (what the inbox region holds): a code received after the last verification, not yet expired. */
  inbox: { message: { expires_at: string } } | null;
  takeoverActive: boolean;
  /** The challenge the customer cancelled (`challengeKey`), or null. */
  dismissed: string | null;
  /** The conversation expired (404). */
  gone: boolean;
  /** Epoch milliseconds. */
  now: number;
}

/**
 * Pure: whether the composer is the code field, and in which state. The rule of the notice (an unexpired inbox
 * message received after the last verification) says a challenge is live; the receipts say it is still open
 * (sent, not verified) and whether the session ended it (locked, handed off).
 */
export function codeModeOf({ entries, inbox, takeoverActive, dismissed, gone, now }: CodeModeInput): CodeMode {
  if (gone) return { kind: "off" };
  const chip = deriveChip(entries, takeoverActive);
  if (chip === "locked" || chip === "handed-off") return { kind: "off" };
  // A handoff wins for good: a code sent after it (the chip would read "pending" again) does not bring the field back.
  if (lastEntryWith(entries, isHandoff) !== null) return { kind: "off" };
  const key = challengeKey(entries);
  if (key === null || !isOtpPending(entries)) return { kind: "off" };
  const live = inbox !== null && Date.parse(inbox.message.expires_at) > now;
  // Expired: the clock says so, or the log already says so after this challenge's receipt.
  const keyAt = entries.findIndex((entry) => entry.id === key);
  const expired = !live && (inbox !== null || entries.slice(keyAt + 1).some((entry) => entry.kind === "system" && entry.code === "codeExpired"));
  if (!live && !expired) return { kind: "off" };
  if (dismissed === key) return { kind: "dismissed", resumable: live };
  if (!live) return { kind: "expired" };
  return { kind: "entry", failed: lastTurnRejectedCode(entries) };
}

/** The newest entry is an assistant turn with an `otp.verify` receipt that did not end verified (or locked: that ends the mode). */
function lastTurnRejectedCode(entries: readonly Entry[]): boolean {
  const last = entries[entries.length - 1];
  if (last?.kind !== "assistant") return false;
  return parseBlocks(last.blocks).blocks.some(
    (block) => block.type === "receipt" && block.receipt.action === "otp.verify" && block.receipt.state_after !== "VERIFIED" && block.receipt.state_after !== "LOCKED",
  );
}

/** The language of the conversation: that of the customer's last message, else `fallback` (the page's). */
export function conversationLang(entries: readonly Entry[], fallback: Lang): Lang {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index]!;
    if (entry.kind === "customer") return entry.lang;
  }
  return fallback;
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
  return clock(iso, lang, { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone });
}

/** `10:39:07`: when a receipt was verified, to the second. */
export function formatClockSeconds(iso: string, lang: Lang, timeZone?: string): string {
  return clock(iso, lang, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZone });
}

function clock(iso: string, lang: Lang, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(lang, options).format(date);
}
