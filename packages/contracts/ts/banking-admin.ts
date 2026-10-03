// The banking-core admin API (`/v1/admin`, `Authorization: Bearer <ADMIN_API_TOKEN>`, internal network only).
//
// Policy config, tool policy and demo reset mirror apps/banking-core/src/banking_core/api/routes_admin.py
// as it is today. The handoff routes and the metrics are NEW; their shapes come from the front-end
// spec (decision 8 and the HTTP contract), since the code that serves them is written alongside.

import { z } from "zod";
import { HandoffSummarySchema } from "./blocks";
import {
  AgentRefSchema,
  CountSchema,
  HandoffRefSchema,
  IsoDateTimeSchema,
  SessionRefSchema,
} from "./common";
import {
  DepartmentSchema,
  HandoffPrioritySchema,
  HandoffReasonSchema,
  HandoffStatusSchema,
  ReasonCodeSchema,
  VerificationStateSchema,
} from "./enums";
import { defineRoute } from "./route";

/** routes_admin.py: `amount_mode: Literal["flag", "block"]`. `flag` recommends a handoff, `block` requires one (ADR-0003). */
export const AmountModeSchema = z.enum(["flag", "block"]);
export type AmountMode = z.infer<typeof AmountModeSchema>;

/** ops.audit_log `ck_audit_log_decision`. */
export const AuditDecisionSchema = z.enum(["allowed", "refused", "error"]);
export type AuditDecision = z.infer<typeof AuditDecisionSchema>;

// --- Handoffs (NEW) ---------------------------------------------------------------------------------------------

/** banking_core.handoff.decisions.HandoffOutcome: how an agent closed a case (ADR-0018). */
export const HandoffOutcomeSchema = z.enum(["APPROVED", "REJECTED", "RESOLVED"]);
export type HandoffOutcome = z.infer<typeof HandoffOutcomeSchema>;

/** banking_core.handoff.decisions.RejectReason. decisions.json picks which apply to each reason. */
export const RejectReasonSchema = z.enum([
  "CUSTOMER_RECOGNIZES_CHARGE",
  "MADE_BY_FAMILY_MEMBER",
  "OUT_OF_TIME",
  "INSUFFICIENT_EVIDENCE",
  "IDENTITY_NOT_VERIFIED",
  "OTHER",
]);
export type RejectReason = z.infer<typeof RejectReasonSchema>;

/** The disputed charge's amount, read from the stored summary. */
export const DisputedAmountSchema = z.object({
  amount_minor: z.number().int(),
  currency: z.string().regex(/^[A-Z]{3}$/),
});
export type DisputedAmount = z.infer<typeof DisputedAmountSchema>;

/** What the queue shows for one handoff. */
export const HandoffItemSchema = z.object({
  handoff_ref: HandoffRefSchema,
  status: HandoffStatusSchema,
  priority: HandoffPrioritySchema,
  department: DepartmentSchema,
  reason: HandoffReasonSchema,
  created_at: IsoDateTimeSchema,
  /** Set only while the handoff is QUEUED, by the rule the handoff block uses. */
  queue_position: z.number().int().min(1).nullable(),
  assigned_agent: z.string().min(1).nullable(),
  assigned_at: IsoDateTimeSchema.nullable(),
  /** The banking-core session the handoff came from. */
  session_ref: SessionRefSchema,
  /** Set together when an agent closed the case (ADR-0018). */
  outcome: HandoffOutcomeSchema.nullable(),
  outcome_reason: RejectReasonSchema.nullable(),
  closed_by: z.string().min(1).nullable(),
  closed_at: IsoDateTimeSchema.nullable(),
  disputed_amount: DisputedAmountSchema.nullable(),
});
export type HandoffItem = z.infer<typeof HandoffItemSchema>;

/**
 * The summary exactly as stored in `ops.handoff.summary`: the four keys `handoff.create` writes
 * (`verified_facts`, `actions_taken`, `verification_method`, `open_questions`) and any other key that
 * was stored, kept.
 */
export const StoredHandoffSummarySchema = HandoffSummarySchema.loose();
export type StoredHandoffSummary = z.infer<typeof StoredHandoffSummarySchema>;

/** The customer's answer to "¿Te ayudó el asistente?" (ADR-0017). */
export const HandoffFeedbackSchema = z.object({
  helpful: z.boolean(),
  recorded_at: IsoDateTimeSchema,
});
export type HandoffFeedback = z.infer<typeof HandoffFeedbackSchema>;

/** A closing message in each language the chat speaks. */
export const ClosingMessageSchema = z.object({
  es: z.string().min(1).max(2000),
  pt: z.string().min(1).max(2000),
  en: z.string().min(1).max(2000),
});
export type ClosingMessage = z.infer<typeof ClosingMessageSchema>;

/**
 * What the case allows now (ADR-0018). Once it is closed the lists are empty and `closing_messages` keeps only
 * the message of the outcome it was closed with: what the customer was sent.
 */
export const HandoffDecisionsSchema = z.object({
  outcomes: z.array(HandoffOutcomeSchema),
  reject_reasons: z.array(RejectReasonSchema),
  escalate_to: z.array(DepartmentSchema),
  closing_messages: z.partialRecord(HandoffOutcomeSchema, ClosingMessageSchema),
});
export type HandoffDecisions = z.infer<typeof HandoffDecisionsSchema>;

export const HandoffDetailSchema = HandoffItemSchema.extend({
  summary: StoredHandoffSummarySchema,
  feedback: HandoffFeedbackSchema.nullable(),
  decisions: HandoffDecisionsSchema,
});
export type HandoffDetail = z.infer<typeof HandoffDetailSchema>;

/** `GET /v1/admin/handoffs?status=QUEUED&status=ASSIGNED`: the statuses listed when `status` is left out. */
export const DEFAULT_HANDOFF_STATUSES: readonly z.infer<typeof HandoffStatusSchema>[] = ["QUEUED", "ASSIGNED"];

/**
 * `status` repeats in the query string. One value or a list is accepted; the parsed value is always a
 * list, and absent stays absent (the admin API applies its default).
 */
export const HandoffListQuerySchema = z.object({
  status: z
    .union([HandoffStatusSchema, z.array(HandoffStatusSchema).min(1)])
    .transform((value) => (Array.isArray(value) ? value : [value]))
    .optional(),
});
export type HandoffListQuery = z.input<typeof HandoffListQuerySchema>;

/** Ordered by priority (URGENT, HIGH, NORMAL, LOW), then `created_at`. */
export const HandoffListResponseSchema = z.object({
  items: z.array(HandoffItemSchema),
});
export type HandoffListResponse = z.infer<typeof HandoffListResponseSchema>;

export const HandoffParamsSchema = z.object({ handoff_ref: HandoffRefSchema });

export const ClaimHandoffRequestSchema = z.strictObject({ agent_ref: AgentRefSchema });
export type ClaimHandoffRequest = z.infer<typeof ClaimHandoffRequestSchema>;

/** `POST /v1/admin/handoffs/:handoff_ref/close`. A reason only, and always, with REJECTED. */
export const CloseHandoffRequestSchema = z.strictObject({
  agent_ref: AgentRefSchema,
  outcome: HandoffOutcomeSchema,
  reason: RejectReasonSchema.nullable().optional(),
});
export type CloseHandoffRequest = z.infer<typeof CloseHandoffRequestSchema>;

/** `POST /v1/admin/handoffs/:handoff_ref/escalate`. The priority only goes up, to URGENT. */
export const EscalateHandoffRequestSchema = z.strictObject({
  agent_ref: AgentRefSchema,
  department: DepartmentSchema,
  raise_to_urgent: z.boolean(),
});
export type EscalateHandoffRequest = z.infer<typeof EscalateHandoffRequestSchema>;

// --- Metrics (NEW) -----------------------------------------------------------------------------------------------

const MetricsHoursSchema = z.number().int().min(1).max(720);

/** `GET /v1/admin/metrics?hours=24` (1 to 720). */
export const MetricsQuerySchema = z.object({
  hours: z.coerce.number().pipe(MetricsHoursSchema).default(24),
});
export type MetricsQuery = z.input<typeof MetricsQuerySchema>;

/** One row of `ops.audit_log` grouped by what happened. `action` is the audit action name, e.g. `card.block`. */
export const ToolCallCountSchema = z.object({
  action: z.string().min(1),
  decision: AuditDecisionSchema,
  reason_code: ReasonCodeSchema.nullable(),
  count: CountSchema,
});
export type ToolCallCount = z.infer<typeof ToolCallCountSchema>;

/** A count per enum value. A value with no handoffs may be left out. */
const countsBy = <K extends z.ZodEnum>(keys: K) => z.partialRecord(keys, CountSchema);

export const HandoffMetricsSchema = z.object({
  total: CountSchema,
  by_status: countsBy(HandoffStatusSchema),
  by_priority: countsBy(HandoffPrioritySchema),
  by_department: countsBy(DepartmentSchema),
  by_outcome: countsBy(HandoffOutcomeSchema),
});
export type HandoffMetrics = z.infer<typeof HandoffMetricsSchema>;

export const OtpMetricsSchema = z.object({
  sent: CountSchema,
  verified: CountSchema,
  failed: CountSchema,
});
export type OtpMetrics = z.infer<typeof OtpMetricsSchema>;

/** Answers to "did the assistant help?" for the handoffs created in the window. */
export const FeedbackMetricsSchema = z.object({
  helpful: CountSchema,
  not_helpful: CountSchema,
});
export type FeedbackMetrics = z.infer<typeof FeedbackMetricsSchema>;

/** A recent case whose customer answered no: an opaque ref and an enum, no PII. */
export const NotHelpfulCaseSchema = z.object({
  handoff_ref: HandoffRefSchema,
  reason: HandoffReasonSchema,
  recorded_at: IsoDateTimeSchema,
});
export type NotHelpfulCase = z.infer<typeof NotHelpfulCaseSchema>;

/** The queue as the metrics are read, whatever the window. */
export const QueueMetricsSchema = z.object({
  waiting: CountSchema,
  urgent: CountSchema,
  oldest_created_at: IsoDateTimeSchema.nullable(),
});
export type QueueMetrics = z.infer<typeof QueueMetricsSchema>;

/** The headline numbers of the window just before, for the change next to each one. */
export const WindowSummarySchema = z.object({
  cards_blocked: CountSchema,
  otp: OtpMetricsSchema,
  handoffs_total: CountSchema,
  feedback: FeedbackMetricsSchema,
});
export type WindowSummary = z.infer<typeof WindowSummarySchema>;

/** Aggregated from `ops.audit_log` over the window and from `ops.handoff`. No PII. */
export const MetricsResponseSchema = z.object({
  generated_at: IsoDateTimeSchema,
  window_hours: MetricsHoursSchema,
  tool_calls: z.array(ToolCallCountSchema),
  handoffs: HandoffMetricsSchema,
  cards_blocked: CountSchema,
  otp: OtpMetricsSchema,
  feedback: FeedbackMetricsSchema,
  recent_not_helpful: z.array(NotHelpfulCaseSchema),
  queue: QueueMetricsSchema,
  previous: WindowSummarySchema,
});
export type MetricsResponse = z.infer<typeof MetricsResponseSchema>;

// --- Policy config (as routes_admin.py defines it) -------------------------------------------------------------------

/** An ISO 4217 code in the form the API stores: three capital letters. It normalizes, but a client sends this. */
export const CurrencyCodeSchema = z.string().regex(/^[A-Z]{3}$/);

/**
 * AdminPolicyConfigRequest: the threshold per currency, in minor units (cents), greater than zero,
 * at least one currency.
 */
export const PolicyConfigRequestSchema = z.strictObject({
  amount_mode: AmountModeSchema,
  thresholds_minor: z
    .record(CurrencyCodeSchema, z.number().int().positive())
    .refine((thresholds) => Object.keys(thresholds).length >= 1, "at least one currency is required"),
});
export type PolicyConfigRequest = z.infer<typeof PolicyConfigRequestSchema>;

/** PolicyConfigResponse. */
export const PolicyConfigResponseSchema = z.object({
  amount_mode: AmountModeSchema,
  thresholds_minor: z.record(z.string(), z.number().int()),
  version: z.number().int(),
});
export type PolicyConfigResponse = z.infer<typeof PolicyConfigResponseSchema>;

// --- Tool policy (as routes_admin.py defines it) ---------------------------------------------------------------------

/** Tool name to the verification states that enable it. */
const ToolStatesSchema = z.record(z.string().min(1), z.array(VerificationStateSchema));

/**
 * AdminToolPolicyRequest: the tools to change, each with the states that enable it. `[]` disables a
 * tool; a tool not listed keeps its states; a state outside the tool's code floor is refused with a 422
 * (an `ApiError` whose `detail` is a list of validation issues), never dropped.
 */
export const ToolPolicyRequestSchema = z.strictObject({
  tools: ToolStatesSchema.refine((tools) => Object.keys(tools).length >= 1, "at least one tool is required"),
});
export type ToolPolicyRequest = z.infer<typeof ToolPolicyRequestSchema>;

/** ToolPolicyResponse: the policy in force and the ceiling (`code_floor`) no configuration can exceed. */
export const ToolPolicyResponseSchema = z.object({
  version: z.number().int(),
  tools: ToolStatesSchema,
  disabled: z.array(z.string()),
  code_floor: ToolStatesSchema,
});
export type ToolPolicyResponse = z.infer<typeof ToolPolicyResponseSchema>;

// --- Demo reset ---------------------------------------------------------------------------------------------------------

/** DemoResetResponse. The route answers 403 under APP_ENV=production unless DEMO_RESET_ENABLED is set. */
export const DemoResetResponseSchema = z.object({
  cards_reset: CountSchema,
  cards_changed: CountSchema,
  cards_missing: CountSchema,
  attempt_limits_cleared: CountSchema,
  tool_policy_version: z.number().int(),
  tool_policy_changed: z.boolean(),
});
export type DemoResetResponse = z.infer<typeof DemoResetResponseSchema>;

// --- Routes --------------------------------------------------------------------------------------------------------------

/**
 * Every route answers 401 to a bad token. The claim answers 404 (unknown) and 409 `claimed_by_another_agent`.
 * Close and escalate also answer 409 `already_closed`, and close a 409 code for an outcome or reason the
 * case does not allow (`outcome_not_allowed`, `reason_required`, `reason_not_allowed`); escalate
 * `nothing_to_escalate`.
 */
export const bankingAdminRoutes = {
  listHandoffs: defineRoute({
    method: "GET",
    pattern: "/v1/admin/handoffs",
    successStatus: 200,
    query: HandoffListQuerySchema,
    response: HandoffListResponseSchema,
  }),
  getHandoff: defineRoute({
    method: "GET",
    pattern: "/v1/admin/handoffs/:handoff_ref",
    successStatus: 200,
    params: HandoffParamsSchema,
    response: HandoffDetailSchema,
  }),
  claimHandoff: defineRoute({
    method: "POST",
    pattern: "/v1/admin/handoffs/:handoff_ref/claim",
    successStatus: 200,
    params: HandoffParamsSchema,
    body: ClaimHandoffRequestSchema,
    response: HandoffDetailSchema,
  }),
  closeHandoff: defineRoute({
    method: "POST",
    pattern: "/v1/admin/handoffs/:handoff_ref/close",
    successStatus: 200,
    params: HandoffParamsSchema,
    body: CloseHandoffRequestSchema,
    response: HandoffDetailSchema,
  }),
  escalateHandoff: defineRoute({
    method: "POST",
    pattern: "/v1/admin/handoffs/:handoff_ref/escalate",
    successStatus: 200,
    params: HandoffParamsSchema,
    body: EscalateHandoffRequestSchema,
    response: HandoffDetailSchema,
  }),
  getMetrics: defineRoute({
    method: "GET",
    pattern: "/v1/admin/metrics",
    successStatus: 200,
    query: MetricsQuerySchema,
    response: MetricsResponseSchema,
  }),
  getPolicyConfig: defineRoute({
    method: "GET",
    pattern: "/v1/admin/policy-config",
    successStatus: 200,
    response: PolicyConfigResponseSchema,
  }),
  putPolicyConfig: defineRoute({
    method: "PUT",
    pattern: "/v1/admin/policy-config",
    successStatus: 200,
    body: PolicyConfigRequestSchema,
    response: PolicyConfigResponseSchema,
  }),
  getToolPolicy: defineRoute({
    method: "GET",
    pattern: "/v1/admin/tool-policy",
    successStatus: 200,
    response: ToolPolicyResponseSchema,
  }),
  putToolPolicy: defineRoute({
    method: "PUT",
    pattern: "/v1/admin/tool-policy",
    successStatus: 200,
    body: ToolPolicyRequestSchema,
    response: ToolPolicyResponseSchema,
  }),
  resetDemoFixtures: defineRoute({
    method: "POST",
    pattern: "/v1/admin/demo/reset-fixtures",
    successStatus: 200,
    response: DemoResetResponseSchema,
  }),
} as const;
