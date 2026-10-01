import { describe, expect, test } from "bun:test";
import {
  BLOCK_TYPES,
  HandoffBlockSchema,
  MessageBlockSchema,
  ReceiptBlockSchema,
  ReceiptSchema,
  TextBlockSchema,
  isKnownBlockType,
  parseBlocks,
  type MessageBlock,
} from "../index";
import { HANDOFF_BLOCK, RECEIPT, RECEIPT_BLOCK, TEXT_BLOCK } from "./fixtures";

describe("the union", () => {
  test("parses each block type and narrows on `type`", () => {
    const blocks: MessageBlock[] = [TEXT_BLOCK, RECEIPT_BLOCK, HANDOFF_BLOCK].map((raw) => MessageBlockSchema.parse(raw));
    const described = blocks.map((block) => {
      switch (block.type) {
        case "text":
          return block.text;
        case "receipt":
          return block.receipt.action;
        case "handoff":
          return `${block.handoff_id}:${block.queue_position}`;
      }
    });
    expect(described).toEqual(["hola", "card.block", "hnd_abcd1234:4"]);
  });

  test("the known types are the Python BLOCK_TYPES", () => {
    expect([...BLOCK_TYPES].sort()).toEqual(["handoff", "receipt", "text"]);
    expect(isKnownBlockType("receipt")).toBe(true);
    expect(isKnownBlockType("button")).toBe(false);
  });

  test("a handoff block keeps the stored summary", () => {
    const block = HandoffBlockSchema.parse(HANDOFF_BLOCK);
    expect(block.summary.verified_facts.verification_state).toBe("VERIFIED");
    expect(block.summary.actions_taken).toEqual(["card.block", { tool: "otp.verify", status: "ok" }]);
    expect(block.summary.open_questions[0]?.source).toBe("model_unverified");
    expect(block.receipt.target_masked).toBe("hnd_abcd1234");
  });

  test("queue_position is null when it is left out, and is at least 1 when given", () => {
    const { queue_position: _omitted, ...withoutPosition } = HANDOFF_BLOCK;
    expect(HandoffBlockSchema.parse(withoutPosition).queue_position).toBeNull();
    expect(HandoffBlockSchema.parse({ ...HANDOFF_BLOCK, queue_position: null }).queue_position).toBeNull();
    expect(HandoffBlockSchema.safeParse({ ...HANDOFF_BLOCK, queue_position: 0 }).success).toBe(false);
    expect(HandoffBlockSchema.safeParse({ ...HANDOFF_BLOCK, queue_position: 1.5 }).success).toBe(false);
  });

  test("text is 1 to 4000 characters", () => {
    expect(TextBlockSchema.safeParse({ type: "text", text: "" }).success).toBe(false);
    expect(TextBlockSchema.safeParse({ type: "text", text: "x".repeat(4000) }).success).toBe(true);
    expect(TextBlockSchema.safeParse({ type: "text", text: "x".repeat(4001) }).success).toBe(false);
  });

  test("keys the contract does not name are stripped, so they cannot be rendered", () => {
    const block = TextBlockSchema.parse({ type: "text", text: "x", html: "<b>x</b>" });
    expect(block).toEqual({ type: "text", text: "x" });
  });

  test("the discriminator is required", () => {
    expect(MessageBlockSchema.safeParse({ text: "hola" }).success).toBe(false);
    expect(ReceiptBlockSchema.safeParse({ receipt: RECEIPT }).success).toBe(false);
  });
});

describe("receipt targets are masked", () => {
  const withTarget = (target_masked: string) => ReceiptSchema.safeParse({ ...RECEIPT, target_masked }).success;

  test("accepts a masked card, e-mail, phone and opaque references", () => {
    expect(withTarget("**** **** **** 1234")).toBe(true);
    expect(withTarget("j***@example.com")).toBe(true);
    expect(withTarget("+57 *** *** 4321")).toBe(true);
    expect(withTarget("card_ab12cd34")).toBe(true);
    expect(withTarget("hnd_abcdefghijklmnop")).toBe(true);
  });

  test("rejects a raw card number", () => {
    expect(withTarget("4532123456789012")).toBe(false);
  });

  test("the PAN guard rejects an opaque reference with 12 or more digits", () => {
    expect(withTarget("hnd_123456789012")).toBe(false);
    expect(withTarget("hnd_12345678901a")).toBe(true);
  });
});

describe("parseBlocks", () => {
  test("keeps the known blocks in order and reports the rest", () => {
    const carousel = { type: "carousel", items: [1, 2] };
    const brokenReceipt = { type: "receipt", receipt: { ...RECEIPT, target_masked: "4532123456789012" } };
    const parsed = parseBlocks([TEXT_BLOCK, carousel, HANDOFF_BLOCK, brokenReceipt, null, "text", { text: "no type" }]);

    expect(parsed.blocks.map((block) => block.type)).toEqual(["text", "handoff"]);
    expect(parsed.unknown.map(({ index, type, reason }) => ({ index, type, reason }))).toEqual([
      { index: 1, type: "carousel", reason: "unknown_type" },
      { index: 3, type: "receipt", reason: "invalid" },
      { index: 4, type: null, reason: "invalid" },
      { index: 5, type: null, reason: "invalid" },
      { index: 6, type: null, reason: "invalid" },
    ]);
    expect(parsed.unknown[0]?.raw).toBe(carousel);
    expect(parsed.unknown[1]?.issues.join("\n")).toContain("receipt.target_masked");
  });

  test("an empty list, and a list of only unknown blocks, are not errors", () => {
    expect(parseBlocks([])).toEqual({ blocks: [], unknown: [] });
    const parsed = parseBlocks([{ type: "future-thing" }]);
    expect(parsed.blocks).toEqual([]);
    expect(parsed.unknown).toHaveLength(1);
  });

  test("never throws, whatever it is given", () => {
    for (const input of [undefined, null, 3, "blocks", {}, { type: "text", text: "not in a list" }]) {
      const parsed = parseBlocks(input);
      expect(parsed.blocks).toEqual([]);
      expect(parsed.unknown).toEqual([
        { index: -1, type: null, reason: "invalid", issues: ["blocks is not a list"], raw: input },
      ]);
    }
    // Odd shapes: a `type` that is not a string, and an object with no prototype.
    expect(() => parseBlocks([{ type: { nested: true } }, { type: 7 }, Object.create(null)])).not.toThrow();
  });

  test("the parsed blocks are typed: no cast is needed to read them", () => {
    const [first] = parseBlocks([TEXT_BLOCK]).blocks;
    if (first?.type === "text") {
      const text: string = first.text;
      expect(text).toBe("hola");
    } else {
      throw new Error("expected a text block");
    }
  });
});
