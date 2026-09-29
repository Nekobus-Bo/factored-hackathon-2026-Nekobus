import { describe, expect, test } from "bun:test";
import type { PolicyConfigResponse, ToolPolicyResponse } from "@pattern-blue/contracts";
import { clockText, dateTimeText, majorText, money, parseMajor, percent, waitText } from "../src/app/format";
import { changedTools, draftFrom, floorOf, invalidThresholds, policyDirty, thresholdsMinor, toggleAll, toggleState, toolsDirty } from "../src/machines/policy-draft";
import { policyConfig, toolPolicy } from "./support/fixtures";

describe("amounts", () => {
  test("show the currency code first and the major units", () => {
    expect(money(13999, "USD")).toBe("USD 139.99");
    expect(money(10000, "USD")).toBe("USD 100.00");
    expect(money(250000, "BRL")).toBe("BRL 2,500.00");
    expect(money(50000, "EUR")).toBe("EUR 500.00");
    expect(money(5, "USD")).toBe("USD 0.05");
  });

  test("COP shows no decimals when there are none, like its seed", () => {
    expect(money(200000000, "COP")).toBe("COP 2,000,000");
    expect(money(200000050, "COP")).toBe("COP 2,000,000.50");
    expect(majorText(200000000, "COP")).toBe("2,000,000");
  });

  test.each([
    ["100", 10000],
    ["100.00", 10000],
    ["100.5", 10050],
    ["2,000,000", 200000000],
    ["2,000,000.25", 200000025],
    ["1,000", 100000],
    ["0.01", 1],
    [" 500.00 ", 50000],
  ])("parses %p as %p minor units", (text, minor) => {
    expect(parseMajor(text)).toBe(minor);
  });

  test.each(["", "  ", "0", "0.00", "-1", "1.234", "abc", "1e3", "1.", ".5", "10 USD", "99999999999999999", "1,5,", "1,5", "2500,50", "2,50", "1,00", "2 000 000", "1,0000"])("refuses %p", (text) => {
    expect(parseMajor(text)).toBeNull();
  });

  test("what is shown parses back to the same value", () => {
    for (const [currency, minor] of Object.entries(policyConfig().thresholds_minor)) {
      expect(parseMajor(majorText(minor, currency))).toBe(minor);
    }
  });
});

describe("time", () => {
  const base = Date.UTC(2026, 8, 29, 10, 0, 0);
  test("a wait is mm:ss, then h:mm:ss, then days", () => {
    expect(waitText(base, base)).toBe("00:00");
    expect(waitText(base, base + 462_000)).toBe("07:42");
    expect(waitText(base, base + 3_599_000)).toBe("59:59");
    expect(waitText(base, base + 3_661_000)).toBe("1:01:01");
    expect(waitText(base, base + 2 * 86_400_000 + 3 * 3_600_000 + 12 * 60_000 + 44_000)).toBe("2d 03:12:44");
  });

  test("a wait never goes negative when clocks disagree", () => {
    expect(waitText(base + 5000, base)).toBe("00:00");
  });

  test("dates are ISO with 24 h time and the zone", () => {
    expect(dateTimeText("2026-09-27T14:03:11+00:00")).toBe("2026-09-27 14:03:11 UTC");
    expect(dateTimeText("2026-09-27T09:03:11-05:00")).toBe("2026-09-27 14:03:11 UTC");
    expect(dateTimeText("not a date")).toBe("not a date");
    expect(clockText("2026-09-27T14:03:11Z")).toBe("14:03");
  });

  test("percent is a whole number and safe for a zero total", () => {
    expect(percent(1, 3)).toBe(33);
    expect(percent(2, 3)).toBe(67);
    expect(percent(0, 0)).toBe(0);
  });
});

describe("policy draft", () => {
  const policy: PolicyConfigResponse = policyConfig();
  const tools: ToolPolicyResponse = toolPolicy();

  test("a fresh draft is clean", () => {
    const draft = draftFrom(policy, tools);
    expect(policyDirty(draft, policy)).toBe(false);
    expect(toolsDirty(draft, tools)).toBe(false);
    expect(invalidThresholds(draft)).toEqual([]);
    expect(thresholdsMinor(draft)).toEqual(policy.thresholds_minor);
  });

  test("a typed threshold that means the same value is not an edit", () => {
    const draft = draftFrom(policy, tools);
    draft.thresholds.USD = "100";
    expect(policyDirty(draft, policy)).toBe(false);
    draft.thresholds.USD = "100.01";
    expect(policyDirty(draft, policy)).toBe(true);
  });

  test("an invalid threshold is reported by currency and blocks the minor-unit conversion", () => {
    const draft = draftFrom(policy, tools);
    draft.thresholds.COP = "many";
    expect(invalidThresholds(draft)).toEqual(["COP"]);
    expect(thresholdsMinor(draft)).toBeNull();
  });

  test("the floor is in FSM order and unknown tools have none", () => {
    expect(floorOf(tools, "handoff.create")).toEqual(["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"]);
    expect(floorOf(tools, "no.such.tool")).toEqual([]);
  });

  test("toggling keeps the FSM order; the master switch is all or nothing", () => {
    expect(toggleState(["VERIFIED"], "IDENTIFIED")).toEqual(["IDENTIFIED", "VERIFIED"]);
    expect(toggleState(["IDENTIFIED", "VERIFIED"], "IDENTIFIED")).toEqual(["VERIFIED"]);
    expect(toggleAll(["VERIFIED"], ["ANONYMOUS", "VERIFIED"])).toEqual([]);
    expect(toggleAll([], ["VERIFIED", "ANONYMOUS"])).toEqual(["ANONYMOUS", "VERIFIED"]);
  });

  test("changed tools lists only what differs, whatever the order the states came in", () => {
    const draft = draftFrom(policy, tools);
    draft.tools["otp.send"] = ["OTP_PENDING"];
    draft.tools["kb.search"] = [...(tools.tools["kb.search"] ?? [])].reverse() as never;
    draft.tools["card.list"] = ["VERIFIED"];
    expect(changedTools(draft, tools)).toEqual({ "otp.send": ["OTP_PENDING"] });
  });
});
