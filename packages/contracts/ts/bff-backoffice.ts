// The web-backoffice BFF (apps/web-backoffice, port 5174), same origin as the page under `/api`.
//
// The agent logs in with DEMO_AGENT_EMAIL / DEMO_AGENT_PASSWORD; the session is an HttpOnly,
// SameSite=Strict cookie signed with HMAC-SHA256 (8 h). Every route below except `POST /api/session`
// needs it (401 otherwise), and every mutating route also needs `Content-Type: application/json`. The
// BFF holds ADMIN_API_TOKEN and AGENT_API_TOKEN; neither reaches the browser. It also serves
// `GET /healthz`.
//
// Data paths: the queue, the handoff detail, the claim, the guardrails and the metrics come from the
// banking-core admin API; the conversation (masked transcript, takeover, agent reply) comes from the
// orchestrator agent API. The shapes are the ones of those APIs unless this file defines them.

import { z } from "zod";
import { AgentRefSchema, ConversationIdSchema, HandoffRefSchema } from "./common";
import { DepartmentSchema } from "./enums";
import {
  DemoResetResponseSchema,
  HandoffDetailSchema,
  HandoffOutcomeSchema,
  RejectReasonSchema,
  HandoffListQuerySchema,
  HandoffListResponseSchema,
  MetricsQuerySchema,
  MetricsResponseSchema,
  PolicyConfigRequestSchema,
  PolicyConfigResponseSchema,
  ToolPolicyRequestSchema,
  ToolPolicyResponseSchema,
} from "./banking-admin";
import {
  AgentMessageRequestSchema,
  AgentMessageResponseSchema,
  AgentTranscriptResponseSchema,
  TakeoverResponseSchema,
} from "./orchestrator-agent";
import { ConversationParamsSchema } from "./orchestrator-chat";
import { defineRoute } from "./route";

// --- Session ------------------------------------------------------------------------------------------------------

export const LoginRequestSchema = z.strictObject({
  email: AgentRefSchema,
  password: z.string().min(1).max(1024),
});
export type LoginRequest = z.infer<typeof LoginRequestSchema>;

/** `GET /api/session`: who is logged in. The `agent_ref` is the e-mail the session was opened with. */
export const SessionResponseSchema = z.object({
  agent_ref: z.string().min(1),
});
export type SessionResponse = z.infer<typeof SessionResponseSchema>;

// --- Handoffs -----------------------------------------------------------------------------------------------------

export const HandoffRefParamsSchema = z.object({ ref: HandoffRefSchema });

/**
 * `GET /api/handoffs/:ref`: the admin detail plus the conversation of that handoff, resolved through the
 * agent API. `conversation_id` is null when the conversation cannot be found (its TTL expired).
 */
export const BackofficeHandoffDetailSchema = HandoffDetailSchema.extend({
  conversation_id: ConversationIdSchema.nullable(),
});
export type BackofficeHandoffDetail = z.infer<typeof BackofficeHandoffDetailSchema>;

/**
 * `POST /api/handoffs/:ref/claim`. `handoff` is the claim answer of the admin API; `takeover` is the
 * answer of the agent API's takeover, verbatim (`{conversation_id, takeover: {active, since, agent_ref}}`),
 * so the caller finds the conversation to open in `takeover.conversation_id`.
 *
 * Both steps are idempotent for the same agent. If the takeover fails after the claim succeeded the
 * route answers 502 `claimed_but_takeover_failed` (ERROR_DETAIL.claimedButTakeoverFailed), and the same
 * call can simply be repeated. Another agent holding the handoff is a 409 `claimed_by_another_agent`;
 * holding the conversation, a 409 `taken_over_by_another_agent`.
 */
export const ClaimHandoffResponseSchema = z.object({
  handoff: HandoffDetailSchema,
  takeover: TakeoverResponseSchema,
});
export type ClaimHandoffResponse = z.infer<typeof ClaimHandoffResponseSchema>;

/**
 * `POST /api/handoffs/:ref/close` (ADR-0018). The BFF closes the case in banking-core for the agent of the
 * session, then takes the conversation over for that agent (idempotent) and sends the closing message in the
 * conversation's language with `client_message_id = close_<ref>`, so a retry cannot send it twice.
 * `customer_notified` is false when the conversation has expired or another agent holds it; the case is
 * closed either way. banking-core's 404 and 409 codes pass through.
 */
export const CloseCaseRequestSchema = z.strictObject({
  outcome: HandoffOutcomeSchema,
  reason: RejectReasonSchema.nullable().optional(),
});
export type CloseCaseRequest = z.infer<typeof CloseCaseRequestSchema>;

export const CloseCaseResponseSchema = z.object({
  handoff: HandoffDetailSchema,
  customer_notified: z.boolean(),
});
export type CloseCaseResponse = z.infer<typeof CloseCaseResponseSchema>;

/**
 * `POST /api/handoffs/:ref/escalate`. The case goes back to the queue in banking-core, then the BFF
 * releases the conversation if this agent held it, so the next agent can take it over.
 */
export const EscalateCaseRequestSchema = z.strictObject({
  department: DepartmentSchema,
  raise_to_urgent: z.boolean(),
});
export type EscalateCaseRequest = z.infer<typeof EscalateCaseRequestSchema>;

export const EscalateCaseResponseSchema = z.object({ handoff: HandoffDetailSchema });
export type EscalateCaseResponse = z.infer<typeof EscalateCaseResponseSchema>;

// --- Routes -------------------------------------------------------------------------------------------------------

/** The closed list of routes the BFF answers under `/api`. */
export const backofficeBffRoutes = {
  login: defineRoute({
    method: "POST",
    pattern: "/api/session",
    successStatus: 204,
    body: LoginRequestSchema,
  }),
  logout: defineRoute({
    method: "DELETE",
    pattern: "/api/session",
    successStatus: 204,
  }),
  getSession: defineRoute({
    method: "GET",
    pattern: "/api/session",
    successStatus: 200,
    response: SessionResponseSchema,
  }),
  listHandoffs: defineRoute({
    method: "GET",
    pattern: "/api/handoffs",
    successStatus: 200,
    query: HandoffListQuerySchema,
    response: HandoffListResponseSchema,
  }),
  getHandoff: defineRoute({
    method: "GET",
    pattern: "/api/handoffs/:ref",
    successStatus: 200,
    params: HandoffRefParamsSchema,
    response: BackofficeHandoffDetailSchema,
  }),
  claimHandoff: defineRoute({
    method: "POST",
    pattern: "/api/handoffs/:ref/claim",
    successStatus: 200,
    params: HandoffRefParamsSchema,
    response: ClaimHandoffResponseSchema,
  }),
  closeHandoff: defineRoute({
    method: "POST",
    pattern: "/api/handoffs/:ref/close",
    successStatus: 200,
    params: HandoffRefParamsSchema,
    body: CloseCaseRequestSchema,
    response: CloseCaseResponseSchema,
  }),
  escalateHandoff: defineRoute({
    method: "POST",
    pattern: "/api/handoffs/:ref/escalate",
    successStatus: 200,
    params: HandoffRefParamsSchema,
    body: EscalateCaseRequestSchema,
    response: EscalateCaseResponseSchema,
  }),
  getConversation: defineRoute({
    method: "GET",
    pattern: "/api/conversations/:id",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: AgentTranscriptResponseSchema,
  }),
  sendAgentMessage: defineRoute({
    method: "POST",
    pattern: "/api/conversations/:id/messages",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: AgentMessageRequestSchema,
    response: AgentMessageResponseSchema,
  }),
  getPolicyConfig: defineRoute({
    method: "GET",
    pattern: "/api/policy-config",
    successStatus: 200,
    response: PolicyConfigResponseSchema,
  }),
  putPolicyConfig: defineRoute({
    method: "PUT",
    pattern: "/api/policy-config",
    successStatus: 200,
    body: PolicyConfigRequestSchema,
    response: PolicyConfigResponseSchema,
  }),
  getToolPolicy: defineRoute({
    method: "GET",
    pattern: "/api/tool-policy",
    successStatus: 200,
    response: ToolPolicyResponseSchema,
  }),
  putToolPolicy: defineRoute({
    method: "PUT",
    pattern: "/api/tool-policy",
    successStatus: 200,
    body: ToolPolicyRequestSchema,
    response: ToolPolicyResponseSchema,
  }),
  resetDemo: defineRoute({
    method: "POST",
    pattern: "/api/demo/reset",
    successStatus: 200,
    response: DemoResetResponseSchema,
  }),
  getMetrics: defineRoute({
    method: "GET",
    pattern: "/api/metrics",
    successStatus: 200,
    query: MetricsQuerySchema,
    response: MetricsResponseSchema,
  }),
} as const;
