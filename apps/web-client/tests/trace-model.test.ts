import { describe, expect, test } from "bun:test";
import { conversationTotal, defaultStep, formatMs, formatUsd, prettyJson, shortModel, splitPlaceholders, summarize, tracedTurns } from "../src/app/chat/trace-model";
import type { Entry } from "../src/machines/chat-model";
import { TEXT_BLOCK, TRACE, TRACE_TOOL } from "./fixtures";

const AT = "2026-09-29T15:40:00Z";
const customer = (id: string, text: string): Entry => ({ id, kind: "customer", text, at: AT, lang: "es", status: "sent" });
const assistant = (id: string, trace?: typeof TRACE): Entry => ({ id, kind: "assistant", blocks: [TEXT_BLOCK] as never, at: AT, lang: "es", trace });

describe("tracedTurns", () => {
  test("each traced reply, numbered among the replies", () => {
    const turns = tracedTurns([
      customer("c1", "hola"),
      assistant("a1", TRACE),
      customer("c2", "otra cosa"),
      assistant("a2"),
      customer("c3", "Código: ••••••"),
      assistant("a3", TRACE_TOOL),
    ]);
    expect(turns.map(({ id, n }) => ({ id, n }))).toEqual([
      { id: "a1", n: 1 },
      { id: "a3", n: 3 },
    ]);
  });
});

describe("summarize", () => {
  test("time in the LLM, tokens, cost", () => {
    expect(summarize(TRACE_TOOL)).toEqual({ llmMs: 1900, tokens: 2530, costUsd: 0.00034 });
    expect(summarize(TRACE)).toEqual({ llmMs: 0, tokens: 0, costUsd: 0 });
  });
});

describe("conversationTotal", () => {
  test("every traced turn's tokens and dollars, added up", () => {
    const turns = tracedTurns([assistant("a1", TRACE_TOOL), assistant("a2"), assistant("a3", TRACE_TOOL), assistant("a4", TRACE)]);
    const total = conversationTotal(turns);
    expect(total.tokens).toBe(5060);
    expect(total.costUsd).toBeCloseTo(0.00068, 10);
    expect(conversationTotal([])).toEqual({ tokens: 0, costUsd: 0 });
  });
});

describe("formatting", () => {
  test("milliseconds under a second, seconds above, a dash for none", () => {
    expect([formatMs(0.4), formatMs(29.4), formatMs(999), formatMs(1270), formatMs(null)]).toEqual(["0 ms", "29 ms", "999 ms", "1.27 s", "—"]);
  });

  test("dollars: five decimals under a cent", () => {
    expect([formatUsd(0.00034), formatUsd(0.0213)]).toEqual(["$0.00034", "$0.0213"]);
  });

  test("the model without its provider", () => {
    expect([shortModel("openai/gpt-6-luna"), shortModel("gpt-6-luna"), shortModel(null)]).toEqual(["gpt-6-luna", "gpt-6-luna", null]);
  });

  test("JSON indented, anything else as it came", () => {
    expect(prettyJson('{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(prettyJson("not json")).toBe("not json");
  });

  test("placeholders split out in place", () => {
    expect(splitPlaceholders("soy [DOC_1] y [NAME_12].")).toEqual([
      { text: "soy ", placeholder: false },
      { text: "[DOC_1]", placeholder: true },
      { text: " y ", placeholder: false },
      { text: "[NAME_12]", placeholder: true },
      { text: ".", placeholder: false },
    ]);
    expect(splitPlaceholders("[x_1] [DOC]")).toEqual([{ text: "[x_1] [DOC]", placeholder: false }]);
  });
});

describe("defaultStep", () => {
  test("the first LLM call, or the first step when there is none", () => {
    expect(defaultStep(TRACE_TOOL)?.kind).toBe("llm_call");
    expect(defaultStep(TRACE)?.kind).toBe("masking");
    expect(defaultStep({ ...TRACE, events: [] })).toBeNull();
  });
});
