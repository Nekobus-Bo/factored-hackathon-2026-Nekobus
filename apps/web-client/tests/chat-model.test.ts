import { describe, expect, test } from "bun:test";
import type { InboxMessage } from "@pattern-blue/contracts";
import {
  agentKey,
  challengeKey,
  CODE_LENGTH,
  CODE_MASK,
  codeFieldChange,
  codeModeOf,
  conversationLang,
  deriveChip,
  displayTarget,
  formatClock,
  formatClockSeconds,
  isHandoff,
  isOtpSendReceipt,
  lastEntryWith,
  formatCountdown,
  isOtpPending,
  maskCardNumbers,
  maskTypedSecrets,
  newAgentMessages,
  pickInboxMessage,
  sanitizeCode,
  verifiedAtOf,
  type Entry,
} from "../src/machines/chat-model";
import { CARD_BLOCK_RECEIPT, HANDOFF_BLOCK, OTP_SEND_RECEIPT, OTP_VERIFY_RECEIPT, TEXT_BLOCK, UNKNOWN_BLOCK } from "./fixtures";

const assistant = (id: string, ...blocks: Array<Record<string, unknown>>): Entry => ({
  id,
  kind: "assistant",
  blocks,
  at: "2026-09-29T15:40:00Z",
  lang: "es",
});

describe("maskTypedSecrets", () => {
  const pending = { otpPending: true, knownCodes: [] as string[], codePrefix: "Código" };
  const idle = { otpPending: false, knownCodes: [] as string[], codePrefix: "Código" };

  test("a bare code while a challenge is pending", () => {
    expect(maskTypedSecrets("482916", pending)).toBe("Código: ••••••");
    expect(maskTypedSecrets("  482916 ", pending)).toBe("Código: ••••••");
    expect(maskTypedSecrets("482 916", pending)).toBe("Código: ••••••");
    expect(maskTypedSecrets("482-916", pending)).toBe("Código: ••••••");
    expect(maskTypedSecrets("es 482916 gracias", pending)).toBe(`es ${CODE_MASK} gracias`);
    expect(maskTypedSecrets("1234", pending)).toBe("Código: ••••••");
    expect(maskTypedSecrets("12345678", pending)).toBe("Código: ••••••");
  });

  test("the prefix follows the language", () => {
    expect(maskTypedSecrets("482916", { ...pending, codePrefix: "Code" })).toBe("Code: ••••••");
  });

  test("digits are left alone when no challenge is pending", () => {
    expect(maskTypedSecrets("482916", idle)).toBe("482916");
    expect(maskTypedSecrets("mi documento es 12345678", idle)).toBe("mi documento es 12345678");
  });

  test("a number that is not 4 to 8 digits is not a code", () => {
    expect(maskTypedSecrets("123", pending)).toBe("123");
    expect(maskTypedSecrets("123456789", pending)).toBe("123456789");
    expect(maskTypedSecrets("ref_4821", pending)).toBe("ref_4821");
  });

  test("the delivered code is masked even when nothing is pending, with or without separators", () => {
    const known = { ...idle, knownCodes: ["482916"] };
    expect(maskTypedSecrets("482916", known)).toBe("Código: ••••••");
    expect(maskTypedSecrets("el código es 4 8 2 9 1 6.", known)).toBe(`el código es ${CODE_MASK}.`);
    expect(maskTypedSecrets("4829 16", known)).toBe("Código: ••••••");
    expect(maskTypedSecrets("1482916", known)).toBe("1482916");
    expect(maskTypedSecrets("4829160", known)).toBe("4829160");
  });

  test("a malformed known code is ignored instead of breaking the pattern", () => {
    expect(maskTypedSecrets("hola", { ...idle, knownCodes: ["(", "", "12"] })).toBe("hola");
  });

  test("a card number is shown by its last four", () => {
    expect(maskTypedSecrets("mi tarjeta es 4111 1111 1111 1111", idle)).toBe("mi tarjeta es •••• 1111");
    expect(maskTypedSecrets("4111111111111111", pending)).toBe("•••• 1111");
    expect(maskTypedSecrets("4111-1111-1111-1234", idle)).toBe("•••• 1234");
  });
});

describe("maskCardNumbers", () => {
  test("card-shaped numbers only", () => {
    expect(maskCardNumbers("4111 1111 1111 1111")).toBe("•••• 1111");
    expect(maskCardNumbers("3782 822463 10005")).toBe("•••• 0005");
    expect(maskCardNumbers("4111111111111")).toBe("•••• 1111");
    expect(maskCardNumbers("Comprobante 2026-09-29 15:42:18")).toBe("Comprobante 2026-09-29 15:42:18");
    expect(maskCardNumbers("•••• 4821")).toBe("•••• 4821");
    expect(maskCardNumbers("CASE-0427 y 123456789012")).toBe("CASE-0427 y 123456789012");
  });
});

describe("displayTarget", () => {
  test("the masked card of the contract becomes •••• 4821", () => {
    expect(displayTarget("**** **** **** 4821")).toBe("•••• 4821");
    expect(displayTarget("****-****-****-4821")).toBe("•••• 4821");
    expect(displayTarget("********4821")).toBe("•••• 4821");
  });
  test("an e-mail or a reference is already what it should be", () => {
    expect(displayTarget("d***@example.com")).toBe("d***@example.com");
    expect(displayTarget("card_ab12cd34")).toBe("card_ab12cd34");
  });
});

describe("deriveChip", () => {
  test("nothing proven, nothing shown", () => {
    expect(deriveChip([], false)).toBeNull();
    expect(deriveChip([assistant("1", TEXT_BLOCK)], false)).toBeNull();
    expect(deriveChip([assistant("1", UNKNOWN_BLOCK)], false)).toBeNull();
  });

  test("text that claims a state proves nothing", () => {
    const claim = { type: "text", text: "Listo: bloqueé la tarjeta y estás verificado." };
    expect(deriveChip([assistant("1", claim)], false)).toBeNull();
  });

  test("each receipt proves its state", () => {
    expect(deriveChip([assistant("1", OTP_SEND_RECEIPT)], false)).toBe("otp-pending");
    expect(deriveChip([assistant("1", OTP_VERIFY_RECEIPT)], false)).toBe("verified");
    expect(deriveChip([assistant("1", CARD_BLOCK_RECEIPT)], false)).toBe("blocked");
    expect(deriveChip([assistant("1", HANDOFF_BLOCK)], false)).toBe("handed-off");
  });

  test("a receipt that shows another state proves none of these", () => {
    const failed = { type: "receipt", receipt: { ...CARD_BLOCK_RECEIPT.receipt, state_after: "ACTIVE" } };
    expect(deriveChip([assistant("1", failed)], false)).toBeNull();
    const locked = { type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: "LOCKED" } };
    expect(deriveChip([assistant("1", locked)], false)).toBe("locked");
  });

  test("the latest proof wins, across turns and within one", () => {
    expect(deriveChip([assistant("1", OTP_SEND_RECEIPT), assistant("2", OTP_VERIFY_RECEIPT)], false)).toBe("verified");
    expect(deriveChip([assistant("1", OTP_VERIFY_RECEIPT, CARD_BLOCK_RECEIPT)], false)).toBe("blocked");
  });

  test("an invalid receipt is not proof", () => {
    const broken = { type: "receipt", receipt: { action: "card.block", state_after: "BLOCKED" } };
    expect(deriveChip([assistant("1", broken)], false)).toBeNull();
  });

  test("an active takeover is proof of a person, whatever else the blocks say", () => {
    expect(deriveChip([], true)).toBe("handed-off");
    expect(deriveChip([assistant("1", CARD_BLOCK_RECEIPT)], true)).toBe("handed-off");
  });
});

describe("isOtpPending / verifiedAtOf", () => {
  test("pending from the code sent until a verification succeeds", () => {
    expect(isOtpPending([])).toBe(false);
    expect(isOtpPending([assistant("1", OTP_SEND_RECEIPT)])).toBe(true);
    expect(isOtpPending([assistant("1", OTP_SEND_RECEIPT), assistant("2", TEXT_BLOCK)])).toBe(true);
    expect(isOtpPending([assistant("1", OTP_SEND_RECEIPT), assistant("2", OTP_VERIFY_RECEIPT)])).toBe(false);
    expect(isOtpPending([assistant("1", OTP_SEND_RECEIPT, OTP_VERIFY_RECEIPT), assistant("2", OTP_SEND_RECEIPT)])).toBe(true);
  });

  test("verifiedAtOf reads the successful verification only", () => {
    expect(verifiedAtOf([OTP_VERIFY_RECEIPT])).toBe("2026-09-29T15:41:11Z");
    expect(verifiedAtOf([OTP_SEND_RECEIPT, TEXT_BLOCK])).toBeNull();
    expect(verifiedAtOf([{ type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: "LOCKED" } }])).toBeNull();
  });
});

describe("pickInboxMessage", () => {
  const message = (received: string, expires: string, code = "111111"): InboxMessage => ({
    channel: "email",
    destination_masked: "d***@example.com",
    code,
    received_at: received,
    expires_at: expires,
  });
  const now = Date.parse("2026-09-29T15:40:00Z");

  test("the unexpired message, newest first", () => {
    const older = message("2026-09-29T15:36:00Z", "2026-09-29T15:41:00Z", "111111");
    const newer = message("2026-09-29T15:38:00Z", "2026-09-29T15:43:00Z", "222222");
    expect(pickInboxMessage([older, newer], now, null)).toBe(newer);
    expect(pickInboxMessage([newer, older], now, null)).toBe(newer);
  });

  test("expired messages are skipped, and expiry at this very moment counts as expired", () => {
    expect(pickInboxMessage([message("2026-09-29T15:30:00Z", "2026-09-29T15:35:00Z")], now, null)).toBeNull();
    expect(pickInboxMessage([message("2026-09-29T15:35:00Z", "2026-09-29T15:40:00Z")], now, null)).toBeNull();
    expect(pickInboxMessage([], now, null)).toBeNull();
  });

  test("a code received before the last verification is used", () => {
    const used = message("2026-09-29T15:36:00Z", "2026-09-29T15:41:00Z");
    expect(pickInboxMessage([used], now, "2026-09-29T15:37:00Z")).toBeNull();
    expect(pickInboxMessage([used], now, "2026-09-29T15:35:00Z")).toBe(used);
  });
});

describe("formatCountdown", () => {
  test("mm:ss, rounded up, never negative", () => {
    expect(formatCountdown(300_000)).toBe("05:00");
    expect(formatCountdown(272_000)).toBe("04:32");
    expect(formatCountdown(59_001)).toBe("01:00");
    expect(formatCountdown(999)).toBe("00:01");
    expect(formatCountdown(0)).toBe("00:00");
    expect(formatCountdown(-5_000)).toBe("00:00");
  });
});

describe("newAgentMessages", () => {
  const message = (role: "user" | "assistant" | "agent", content: string, created_at: string) => ({
    role,
    content,
    blocks: [],
    created_at,
  });

  test("only agent messages the log does not hold, oldest first", () => {
    const messages = [
      message("user", "hola", "2026-09-29T15:49:00Z"),
      message("agent", "segundo", "2026-09-29T15:51:00Z"),
      message("agent", "primero", "2026-09-29T15:50:00Z"),
      message("assistant", "respuesta", "2026-09-29T15:49:30Z"),
    ];
    expect(newAgentMessages(messages, []).map((m) => m.content)).toEqual(["primero", "segundo"]);
    const known: Entry[] = [{ id: "x", kind: "agent", text: "primero", at: "2026-09-29T15:50:00Z", key: agentKey(messages[2]!) }];
    expect(newAgentMessages(messages, known).map((m) => m.content)).toEqual(["segundo"]);
  });

  test("an empty agent message is not shown", () => {
    expect(newAgentMessages([message("agent", "  ", "2026-09-29T15:50:00Z")], [])).toEqual([]);
  });
});

describe("formatClock", () => {
  test("24 h", () => {
    expect(formatClock("2026-09-29T15:42:18Z", "es", "UTC")).toBe("15:42");
    expect(formatClock("2026-09-29T05:07:00Z", "en", "UTC")).toBe("05:07");
    expect(formatClock("2026-09-29T15:42:18Z", "pt", "America/Bogota")).toBe("10:42");
  });
  test("an unreadable time is empty, not a crash", () => {
    expect(formatClock("nope", "es")).toBe("");
  });
});

describe("formatClockSeconds", () => {
  test("24 h to the second, in the given zone; an unreadable time is empty", () => {
    expect(formatClockSeconds("2026-09-29T15:42:18Z", "es", "UTC")).toBe("15:42:18");
    expect(formatClockSeconds("2026-09-29T15:42:18Z", "en", "America/Bogota")).toBe("10:42:18");
    expect(formatClockSeconds("nope", "pt")).toBe("");
  });
});

describe("lastEntryWith", () => {
  const otpSend = { type: "receipt", receipt: { action: "otp.send", target_masked: "d***@example.com", state_before: "IDENTIFIED", state_after: "OTP_PENDING", verified_at: "2026-09-29T15:40:00Z", audit_id: "aud_00000001" } };
  const entries = [
    { id: "a", kind: "assistant", blocks: [otpSend], at: "2026-09-29T15:40:00Z", lang: "es" },
    { id: "b", kind: "customer", text: "Código: ••••••", at: "2026-09-29T15:41:00Z", lang: "es", status: "sent" },
    { id: "c", kind: "assistant", blocks: [otpSend, { type: "text", text: "Otra vez." }], at: "2026-09-29T15:42:00Z", lang: "es" },
  ] as const;

  test("the newest assistant entry with a matching block, or null", () => {
    expect(lastEntryWith(entries as never, isOtpSendReceipt)).toBe("c");
    expect(lastEntryWith(entries as never, isHandoff)).toBeNull();
    expect(lastEntryWith([], isOtpSendReceipt)).toBeNull();
  });

  test("a block that fails its schema does not count", () => {
    const broken = [{ id: "x", kind: "assistant", blocks: [{ type: "receipt", receipt: { action: "otp.send" } }], at: "2026-09-29T15:40:00Z", lang: "es" }];
    expect(lastEntryWith(broken as never, isOtpSendReceipt)).toBeNull();
  });
});

describe("the composer's code mode", () => {
  const AT = "2026-09-29T15:40:00Z";
  const NOW = Date.parse("2026-09-29T15:41:00Z");
  const assistant = (id: string, ...blocks: unknown[]) => ({ id, kind: "assistant", blocks, at: AT, lang: "es" }) as Entry;
  const customer = (id: string, text: string, lang: "es" | "pt" | "en" = "es") => ({ id, kind: "customer", text, at: AT, lang, status: "sent" }) as Entry;
  const expiredLine = (id: string) => ({ id, kind: "system", code: "codeExpired", at: AT }) as Entry;
  const rejected = (after: string) => ({ type: "receipt", receipt: { ...OTP_VERIFY_RECEIPT.receipt, state_after: after } });
  const live = { message: { expires_at: "2026-09-29T15:45:02Z" } };
  const past = { message: { expires_at: "2026-09-29T15:40:30Z" } };
  const base = { inbox: live, takeoverActive: false, dismissed: null, gone: false, now: NOW };
  const sent = [customer("e1", "hola"), assistant("e2", TEXT_BLOCK, OTP_SEND_RECEIPT)];

  test("pending: a code was sent, it is live and nobody has verified it: the field", () => {
    expect(codeModeOf({ ...base, entries: sent })).toEqual({ kind: "entry", failed: false });
  });

  test("no challenge, or a code that was sent and verified, is the normal composer", () => {
    expect(codeModeOf({ ...base, inbox: null, entries: [customer("e1", "hola"), assistant("e2", TEXT_BLOCK)] })).toEqual({ kind: "off" });
    // verified: the receipt ends it even if the inbox still holds the used code
    expect(codeModeOf({ ...base, entries: [...sent, customer("e3", "x"), assistant("e4", OTP_VERIFY_RECEIPT)] })).toEqual({ kind: "off" });
    // a live notice with no receipt of a send in the log proves no challenge
    expect(codeModeOf({ ...base, entries: [customer("e1", "hola"), assistant("e2", TEXT_BLOCK)] })).toEqual({ kind: "off" });
  });

  test("a failed attempt stays in the field, and the error shows only while the newest entry proves it", () => {
    const failed = [...sent, customer("e3", "Código: ••••••"), assistant("e4", TEXT_BLOCK, rejected("OTP_PENDING"))];
    expect(codeModeOf({ ...base, entries: failed })).toEqual({ kind: "entry", failed: true });
    // the next attempt is in flight (the newest entry is the customer's): no line
    expect(codeModeOf({ ...base, entries: [...failed, customer("e5", "Código: ••••••")] })).toEqual({ kind: "entry", failed: false });
    // a turn that says it in words but proves nothing shows no line
    expect(codeModeOf({ ...base, entries: [...sent, customer("e3", "x"), assistant("e4", TEXT_BLOCK)] })).toEqual({ kind: "entry", failed: false });
  });

  test("locked ends the mode, and so do a handoff, an agent and an expired conversation", () => {
    expect(codeModeOf({ ...base, entries: [...sent, customer("e3", "x"), assistant("e4", rejected("LOCKED"))] })).toEqual({ kind: "off" });
    expect(codeModeOf({ ...base, entries: [...sent, customer("e3", "x"), assistant("e4", HANDOFF_BLOCK)] })).toEqual({ kind: "off" });
    expect(codeModeOf({ ...base, entries: sent, takeoverActive: true })).toEqual({ kind: "off" });
    expect(codeModeOf({ ...base, entries: sent, gone: true })).toEqual({ kind: "off" });
  });

  test("expired: the clock says so, or the log says so after this challenge's receipt; with neither it is the normal composer", () => {
    expect(codeModeOf({ ...base, inbox: past, entries: sent })).toEqual({ kind: "expired" });
    expect(codeModeOf({ ...base, inbox: null, entries: [...sent, expiredLine("e3")] })).toEqual({ kind: "expired" });
    // an expiry line from an earlier challenge does not count for the new one
    expect(codeModeOf({ ...base, inbox: null, entries: [assistant("e1", OTP_SEND_RECEIPT), expiredLine("e2"), assistant("e3", OTP_SEND_RECEIPT)] })).toEqual({ kind: "off" });
    expect(codeModeOf({ ...base, inbox: null, entries: sent })).toEqual({ kind: "off" });
  });

  test("a new code after the old one expired is the field again", () => {
    const entries = [...sent, expiredLine("e3"), customer("e4", "Envíame un código nuevo."), assistant("e5", TEXT_BLOCK, OTP_SEND_RECEIPT)];
    expect(codeModeOf({ ...base, entries })).toEqual({ kind: "entry", failed: false });
  });

  test("cancelled: the normal composer for that challenge, resumable while its code is live; a new challenge is the field again", () => {
    const key = challengeKey(sent);
    expect(key).toBe("e2");
    expect(codeModeOf({ ...base, entries: sent, dismissed: key })).toEqual({ kind: "dismissed", resumable: true });
    expect(codeModeOf({ ...base, entries: sent, dismissed: key, inbox: past })).toEqual({ kind: "dismissed", resumable: false });
    const again = [...sent, customer("e3", "otro"), assistant("e4", OTP_SEND_RECEIPT)];
    expect(challengeKey(again)).toBe("e4");
    expect(codeModeOf({ ...base, entries: again, dismissed: key })).toEqual({ kind: "entry", failed: false });
  });

  test("a code sent after a handoff does not bring the field back: the handoff wins", () => {
    const entries = [...sent, customer("e3", "x"), assistant("e4", HANDOFF_BLOCK), customer("e5", "otro"), assistant("e6", OTP_SEND_RECEIPT)];
    expect(codeModeOf({ ...base, entries })).toEqual({ kind: "off" });
  });

  test("the field's decision: five digits wait, the sixth sends once and empties the field, an off field sends nothing", () => {
    expect(codeFieldChange("", false)).toEqual({ digits: "", send: null });
    expect(codeFieldChange("58882", false)).toEqual({ digits: "58882", send: null });
    expect(codeFieldChange("588820", false)).toEqual({ digits: "", send: "588820" });
    // pasted: spaces and a dash go, the rest is the code
    expect(codeFieldChange("588 820", false)).toEqual({ digits: "", send: "588820" });
    expect(codeFieldChange("588-820", false)).toEqual({ digits: "", send: "588820" });
    // more than six: the first six
    expect(codeFieldChange("58882012", false)).toEqual({ digits: "", send: "588820" });
    // letters do not count
    expect(codeFieldChange("5a8b", false)).toEqual({ digits: "58", send: null });
    // while the turn is in flight nothing is sent and the digits wait
    expect(codeFieldChange("588820", true)).toEqual({ digits: "588820", send: null });
    // once: after the send the field is empty, so the next change starts from nothing
    const first = codeFieldChange("588820", false);
    expect(codeFieldChange(first.digits + "1", false)).toEqual({ digits: "1", send: null });
  });

  test("the digits kept: only digits, six at most; pasting '588 820' or '588-820' keeps the code", () => {
    expect(sanitizeCode("588820")).toBe("588820");
    expect(sanitizeCode("588 820")).toBe("588820");
    expect(sanitizeCode("588-820")).toBe("588820");
    expect(sanitizeCode("12ab3")).toBe("123");
    expect(sanitizeCode("12345678")).toBe("123456");
    expect(sanitizeCode("")).toBe("");
    expect(sanitizeCode("abc")).toBe("");
    expect(CODE_LENGTH).toBe(6);
  });

  test("the language of the conversation is that of the customer's last message, else the page's", () => {
    expect(conversationLang([customer("e1", "oi", "pt"), assistant("e2", TEXT_BLOCK)], "es")).toBe("pt");
    expect(conversationLang([customer("e1", "hola", "es"), customer("e2", "oi", "pt")], "en")).toBe("pt");
    expect(conversationLang([], "en")).toBe("en");
  });
});
