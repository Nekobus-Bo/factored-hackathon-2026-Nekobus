// The pure part of the guardrails editor: what a draft is, when it differs from what is in force, and
// what would be sent. The machine holds the state; this file holds the rules, so they are easy to test.

import { VerificationStateSchema, type AmountMode, type PolicyConfigResponse, type ToolPolicyResponse, type VerificationState } from "@pattern-blue/contracts";
import { majorText, parseMajor } from "../app/format";

/** The FSM states in their natural order: the order cells are shown and states are sent. */
export const FSM_ORDER: readonly VerificationState[] = VerificationStateSchema.options;

const inFsmOrder = (states: readonly VerificationState[]): VerificationState[] => FSM_ORDER.filter((state) => states.includes(state));

export interface Draft {
  mode: AmountMode;
  /** Text as typed, in major units, per currency. */
  thresholds: Record<string, string>;
  /** Enabled states per tool. */
  tools: Record<string, VerificationState[]>;
}

export function draftFrom(policy: PolicyConfigResponse, tools: ToolPolicyResponse): Draft {
  return {
    mode: policy.amount_mode,
    thresholds: Object.fromEntries(Object.entries(policy.thresholds_minor).map(([currency, minor]) => [currency, majorText(minor, currency)])),
    tools: Object.fromEntries(Object.entries(tools.code_floor).map(([tool]) => [tool, inFsmOrder(tools.tools[tool] ?? [])])),
  };
}

/** The floor of a tool, in FSM order. A tool with no entry has no floor: nothing can be enabled for it. */
export function floorOf(tools: ToolPolicyResponse, tool: string): VerificationState[] {
  return inFsmOrder(tools.code_floor[tool] ?? []);
}

/** Currencies whose typed threshold is not an amount greater than zero. */
export function invalidThresholds(draft: Draft): string[] {
  return Object.entries(draft.thresholds)
    .filter(([, text]) => parseMajor(text) === null)
    .map(([currency]) => currency);
}

/** The thresholds a save would send, in minor units; null while any of them is invalid. */
export function thresholdsMinor(draft: Draft): Record<string, number> | null {
  const result: Record<string, number> = {};
  for (const [currency, text] of Object.entries(draft.thresholds)) {
    const minor = parseMajor(text);
    if (minor === null) return null;
    result[currency] = minor;
  }
  return result;
}

export function editedCurrencies(draft: Draft, policy: PolicyConfigResponse): string[] {
  return Object.keys(draft.thresholds).filter((currency) => parseMajor(draft.thresholds[currency] ?? "") !== policy.thresholds_minor[currency]);
}

export function policyDirty(draft: Draft, policy: PolicyConfigResponse): boolean {
  return draft.mode !== policy.amount_mode || editedCurrencies(draft, policy).length > 0;
}

/** Tools whose enabled states differ from the policy in force. */
export function changedTools(draft: Draft, tools: ToolPolicyResponse): Record<string, VerificationState[]> {
  const changed: Record<string, VerificationState[]> = {};
  for (const [tool, states] of Object.entries(draft.tools)) {
    const wanted = inFsmOrder(states);
    const current = inFsmOrder(tools.tools[tool] ?? []);
    if (wanted.length !== current.length || wanted.some((state, index) => state !== current[index])) changed[tool] = wanted;
  }
  return changed;
}

export function toolsDirty(draft: Draft, tools: ToolPolicyResponse): boolean {
  return Object.keys(changedTools(draft, tools)).length > 0;
}

/** Flip one state of one tool, in FSM order. The caller has checked that the state is within the floor. */
export function toggleState(states: readonly VerificationState[], state: VerificationState): VerificationState[] {
  return inFsmOrder(states.includes(state) ? states.filter((candidate) => candidate !== state) : [...states, state]);
}

/** The master switch: everything off if anything is on, otherwise everything the floor allows. */
export function toggleAll(states: readonly VerificationState[], floor: readonly VerificationState[]): VerificationState[] {
  return states.length > 0 ? [] : inFsmOrder(floor);
}
