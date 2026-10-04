// What detective mode's panel reads from the log (ADR-0019): the turns that came with a trace, and the few
// numbers each one is summed up by. Pure functions, no React.

import type { TraceEvent, TurnTrace } from "@pattern-blue/contracts";
import type { Entry } from "../../machines/chat-model";

/** A reply that came with its trace, numbered among the assistant's replies. */
export interface TracedTurn {
  id: string;
  n: number;
  trace: TurnTrace;
}

export function tracedTurns(entries: readonly Entry[]): TracedTurn[] {
  const turns: TracedTurn[] = [];
  let n = 0;
  for (const entry of entries) {
    if (entry.kind !== "assistant") continue;
    n += 1;
    if (entry.trace) turns.push({ id: entry.id, n, trace: entry.trace });
  }
  return turns;
}

/** What a turn spent: time in the LLM, tokens, dollars. */
export interface TraceSummary {
  llmMs: number;
  tokens: number;
  costUsd: number;
}

export function summarize(trace: TurnTrace): TraceSummary {
  const summary: TraceSummary = { llmMs: 0, tokens: 0, costUsd: 0 };
  for (const event of trace.events) {
    if (event.kind !== "llm_call") continue;
    summary.llmMs += event.duration_ms ?? 0;
    summary.tokens += event.llm_call?.total_tokens ?? 0;
    summary.costUsd += event.llm_call?.cost_usd ?? 0;
  }
  return summary;
}

/** `29 ms`, `1.27 s`; a dash for a step that has no duration. */
export function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

/** `$0.00036`: five decimals under a cent, four above. */
export function formatUsd(usd: number): string {
  return `$${usd < 0.01 ? usd.toFixed(5) : usd.toFixed(4)}`;
}

/** The model without its provider: `openai/gpt-6-luna` is `gpt-6-luna`. */
export function shortModel(model: string | null): string | null {
  return model === null ? null : (model.split("/").pop() ?? model);
}

/** JSON indented for reading; anything that is not JSON as it came. */
export function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

/** The step a timeline opens on: the first LLM call, where most of a turn's time goes. */
export function defaultStep(trace: TurnTrace): TraceEvent | null {
  return trace.events.find((event) => event.kind === "llm_call") ?? trace.events[0] ?? null;
}

/** The placeholders in a masked text, kept in place: `[DOC_1]` is the part the panel marks. */
export function splitPlaceholders(text: string): { text: string; placeholder: boolean }[] {
  return text
    .split(/(\[[A-Z]+_\d+\])/)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, placeholder: /^\[[A-Z]+_\d+\]$/.test(part) }));
}
