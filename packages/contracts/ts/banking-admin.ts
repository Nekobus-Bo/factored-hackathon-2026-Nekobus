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
});
export type HandoffItem = z.infer<typeof HandoffItemSchema>;

/**
 * The summary exactly as stored in `ops.handoff.summary`: the four keys `handoff.create` writes
 * (`verified_facts`, `actions_taken`, `verification_method`, `open_questions`) and any other key that
 * was stored, kept.
 */
export const StoredHandoffSummarySchema = HandoffSummarySchema.loose();
export type StoredHandoffSummary = z.infer<typeof StoredHandoffSummarySchema>;

export const HandoffDetailSchema = HandoffItemSchema.extend({
  summary: StoredHandoffSummarySchema,
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
});
export type HandoffMetrics = z.infer<typeof HandoffMetricsSchema>;

export const OtpMetricsSchema = z.object({
  sent: CountSchema,
  verified: CountSchema,
  failed: CountSchema,
});
export type OtpMetrics = z.infer<typeof OtpMetricsSchema>;

/** Aggregated from `ops.audit_log` over the window and from `ops.handoff`. No PII. */
export const MetricsResponseSchema = z.object({
  generated_at: IsoDateTimeSchema,
  window_hours: MetricsHoursSchema,
  tool_calls: z.array(ToolCallCountSchema),
  handoffs: HandoffMetricsSchema,
  cards_blocked: CountSchema,
  otp: OtpMetricsSchema,
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

/** Every route answers 401 to a bad token. The claim answers 404 (unknown) and 409 `claimed_by_another_agent`. */
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
