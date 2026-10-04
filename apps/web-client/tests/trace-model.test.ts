import { describe, expect, test } from "bun:test";
import { defaultStep, formatMs, formatUsd, prettyJson, splitPlaceholders, summarize, tracedTurns } from "../src/app/chat/trace-model";
import type { Entry } from "../src/machines/chat-model";
import { TEXT_BLOCK, TRACE, TRACE_TOOL } from "./fixtures";

const AT = "2026-09-29T15:40:00Z";
const customer = (id: string, text: string): Entry => ({ id, kind: "customer", text, at: AT, lang: "es", status: "sent" });
const assistant = (id: string, trace?: typeof TRACE): Entry => ({ id, kind: "assistant", blocks: [TEXT_BLOCK] as never, at: AT, lang: "es", trace });

describe("tracedTurns", () => {
  test("each traced reply, numbered among the replies, with the bubble it answered", () => {
    const turns = tracedTurns([
      customer("c1", "hola"),
      assistant("a1", TRACE),
      customer("c2", "otra cosa"),
      assistant("a2"),
      customer("c3", "Código: ••••••"),
      assistant("a3", TRACE_TOOL),
    ]);
    expect(turns.map(({ id, n, quote }) => ({ id, n, quote }))).toEqual([
      { id: "a1", n: 1, quote: "hola" },
      { id: "a3", n: 3, quote: "Código: ••••••" },
    ]);
  });

  test("a reply with no bubble before it has no quote", () => {
    expect(tracedTurns([assistant("a1", TRACE), assistant("a2", TRACE)]).map((turn) => turn.quote)).toEqual([null, null]);
  });
});

describe("summarize", () => {
  test("steps, LLM calls and their time, tools, tokens, cost", () => {
    expect(summarize(TRACE_TOOL)).toEqual({ steps: 2, llm: 1, tools: 1, tokens: 2530, costUsd: 0.00034, llmMs: 1900 });
    expect(summarize(TRACE)).toEqual({ steps: 1, llm: 0, tools: 0, tokens: 0, costUsd: 0, llmMs: 0 });
  });
});

describe("formatting", () => {
  test("milliseconds under a second, seconds above, a dash for none", () => {
    expect([formatMs(0.4), formatMs(29.4), formatMs(999), formatMs(1270), formatMs(null)]).toEqual(["0 ms", "29 ms", "999 ms", "1.27 s", "—"]);
  });

  test("dollars: five decimals under a cent", () => {
    expect([formatUsd(0.00034), formatUsd(0.0213)]).toEqual(["$0.00034", "$0.0213"]);
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
