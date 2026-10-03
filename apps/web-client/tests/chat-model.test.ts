import { describe, expect, test } from "bun:test";
import type { InboxMessage } from "@pattern-blue/contracts";
import {
  agentKey,
  CODE_MASK,
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
