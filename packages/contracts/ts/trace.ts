// The detective-mode turn trace (ADR-0019), mirroring contracts.trace (packages/contracts/src/contracts/trace.py)
// and checked against schemas/trace/turn_trace.json by tests/drift.test.ts.
//
// A trace is the timeline of one customer turn, masked values only. Each event carries exactly one detail,
// in the field named after its kind (an `engine_handoff` carries a `tool_call`); `canned_reply` and
// `takeover` carry only a `note`. Every field is present, null where a value is missing.

import { z } from "zod";
import { ReasonCodeSchema, ToolResultStatusSchema, TraceEventKindSchema, TraceEventStatusSchema, VerificationStateSchema } from "./enums";

const nonNegative = z.number().min(0);
const probability = z.number().min(0).max(1);
const count = z.number().int().min(0);

export const TraceCountSchema = z.object({ type: z.string().min(1), count });
export type TraceCount = z.infer<typeof TraceCountSchema>;

export const TraceDecisionPointSchema = z.object({
  dp_id: z.string().min(1),
  outcome: z.string().min(1),
  label: z.string().nullable(),
  confidence: probability,
  raw_confidence: z.number().nullable(),
  runner_up_label: z.string().nullable(),
  runner_up_confidence: z.number().nullable(),
  tau: z.number().nullable(),
});
export type TraceDecisionPoint = z.infer<typeof TraceDecisionPointSchema>;

export const EncoderDetailSchema = z.object({
  available: z.boolean(),
  intent: z.string().nullable(),
  confidence: z.number().nullable(),
  abstain: z.boolean().nullable(),
  model_id: z.string().nullable(),
  config_version: z.string().nullable(),
  server_latency_ms: nonNegative.nullable(),
  slots: z.array(z.string()),
  pii_spans: z.array(TraceCountSchema),
  decision_points: z.array(TraceDecisionPointSchema),
});
export type EncoderDetail = z.infer<typeof EncoderDetailSchema>;

export const MaskingDetailSchema = z.object({
  masked_text: z.string().nullable(),
  placeholders: z.array(z.string()),
  regex_only: z.boolean(),
  encoder_spans_added: count,
  otp_pending: z.boolean(),
  failed: z.boolean(),
});
export type MaskingDetail = z.infer<typeof MaskingDetailSchema>;

export const TraceDecisionSchema = z.object({
  dp_id: z.string().min(1),
  effect: z.string().min(1),
  mode: z.string().min(1),
  outcome: z.string().min(1),
  label: z.string().nullable(),
  confidence: probability,
  unavailable_reason: z.string().nullable(),
});
export type TraceDecision = z.infer<typeof TraceDecisionSchema>;

export const TraceEffectSchema = z.object({
  dp_id: z.string().min(1),
  effect: z.string().min(1),
  mode: z.string().min(1),
  tool: z.string().nullable(),
  applied: z.boolean(),
  would_apply: z.boolean(),
});
export type TraceEffect = z.infer<typeof TraceEffectSchema>;

export const DecisionsDetailSchema = z.object({
  config_version: z.string().nullable(),
  decisions: z.array(TraceDecisionSchema),
  effects: z.array(TraceEffectSchema),
});
export type DecisionsDetail = z.infer<typeof DecisionsDetailSchema>;

export const TraceMessageSchema = z.object({
  role: z.string().min(1),
  content: z.string().nullable(),
  /** The assistant's tool calls, as JSON. */
  tool_calls: z.string().nullable(),
  tool_call_id: z.string().nullable(),
});
export type TraceMessage = z.infer<typeof TraceMessageSchema>;

export const TraceToolRequestSchema = z.object({ call_id: z.string(), name: z.string(), arguments: z.string() });
export type TraceToolRequest = z.infer<typeof TraceToolRequestSchema>;

export const LlmCallDetailSchema = z.object({
  round: z.number().int().min(1),
  model: z.string().nullable(),
  prompt_version: z.string(),
  cached: z.boolean(),
  recording_key: z.string().nullable(),
  tools_offered: z.array(z.string()),
  /** Index of the first message in `messages`: 0 on the first call of the turn, then only the new ones. */
  messages_from: count,
  messages: z.array(TraceMessageSchema),
  response_content: z.string().nullable(),
  response_tool_calls: z.array(TraceToolRequestSchema),
  prompt_tokens: z.number().int().nullable(),
  completion_tokens: z.number().int().nullable(),
  total_tokens: z.number().int().nullable(),
  cost_usd: z.number().nullable(),
});
export type LlmCallDetail = z.infer<typeof LlmCallDetailSchema>;

export const ToolCallDetailSchema = z.object({
  call_id: z.string().nullable(),
  llm_name: z.string().nullable(),
  tool: z.string(),
  /** Masked arguments as JSON, as the model sent them. */
  arguments: z.string().nullable(),
  /** False when refused before reaching banking-core. */
  executed: z.boolean(),
  /** Why the engine refused it without calling banking-core. */
  local_reason: z.string().nullable(),
  status: ToolResultStatusSchema.nullable(),
  reason_code: ReasonCodeSchema.nullable(),
  flow_state: VerificationStateSchema.nullable(),
  flow_next: z.array(z.string()),
  flow_allowed: z.array(z.string()),
  /** The masked result the LLM received, as JSON. */
  feedback: z.string().nullable(),
});
export type ToolCallDetail = z.infer<typeof ToolCallDetailSchema>;

export const BlocksDetailSchema = z.object({
  kept: z.array(z.string()),
  dropped: z.array(z.string()),
  internal_lines_withheld: count,
  receipts: count,
  handoffs: count,
  fallback: z.boolean(),
});
export type BlocksDetail = z.infer<typeof BlocksDetailSchema>;

/** One step of the turn. Times are milliseconds from the start of the turn. */
export const TraceEventSchema = z.object({
  seq: count,
  kind: TraceEventKindSchema,
  label: z.string().min(1).max(128),
  start_ms: nonNegative,
  duration_ms: nonNegative.nullable(),
  status: TraceEventStatusSchema,
  note: z.string().nullable(),
  encoder: EncoderDetailSchema.nullable(),
  masking: MaskingDetailSchema.nullable(),
  decisions: DecisionsDetailSchema.nullable(),
  llm_call: LlmCallDetailSchema.nullable(),
  tool_call: ToolCallDetailSchema.nullable(),
  blocks: BlocksDetailSchema.nullable(),
});
export type TraceEvent = z.infer<typeof TraceEventSchema>;

/** The timeline of one customer turn. */
export const TurnTraceSchema = z.object({
  trace_version: z.string().min(1),
  turn_id: z.string().min(1),
  prompt_version: z.string().min(1),
  total_ms: nonNegative,
  tool_rounds: count,
  events: z.array(TraceEventSchema),
});
export type TurnTrace = z.infer<typeof TurnTraceSchema>;
