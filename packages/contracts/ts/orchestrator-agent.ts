// The orchestrator's agent API (NEW): the conversation side of a human takeover. Router `/v1/agent`,
// mounted only when AGENT_API_ENABLED=true, `Authorization: Bearer <AGENT_API_TOKEN>`. Only the
// web-backoffice BFF calls it; the token never reaches a browser.
//
// The masked transcript comes from here. Messages an agent writes are masked with the same masker
// before they are stored, so the transcript never holds raw PII.

import { z } from "zod";
import {
  AgentRefSchema,
  ClientMessageIdSchema,
  ConversationIdSchema,
  HandoffRefSchema,
  IsoDateTimeSchema,
  MessageTextSchema,
  SessionRefSchema,
} from "./common";
import { RawBlocksSchema } from "./blocks";
import { ConversationParamsSchema, TranscriptResponseSchema } from "./orchestrator-chat";
import { defineRoute } from "./route";

/** Who holds the conversation. Unlike the customer view it names the agent. */
export const AgentTakeoverStateSchema = z.object({
  active: z.boolean(),
  since: IsoDateTimeSchema.nullable(),
  agent_ref: z.string().min(1).nullable(),
});
export type AgentTakeoverState = z.infer<typeof AgentTakeoverStateSchema>;

// --- GET /v1/agent/sessions/{session_ref}/conversation -----------------------------------------------------

/** `session_ref` is the banking-core session id, which is what `ops.handoff.session_ref` stores. 404 when unknown. */
export const SessionParamsSchema = z.object({ session_ref: SessionRefSchema });

export const SessionConversationResponseSchema = z.object({
  conversation_id: ConversationIdSchema,
});
export type SessionConversationResponse = z.infer<typeof SessionConversationResponseSchema>;

// --- GET /v1/agent/conversations/{id} ------------------------------------------------------------------------

/** The transcript shape of the chat API, with the takeover naming the agent. */
export const AgentTranscriptResponseSchema = TranscriptResponseSchema.extend({
  takeover: AgentTakeoverStateSchema,
});
export type AgentTranscriptResponse = z.infer<typeof AgentTranscriptResponseSchema>;

// --- POST /v1/agent/conversations/{id}/takeover ---------------------------------------------------------------

export const TakeoverRequestSchema = z.strictObject({
  agent_ref: AgentRefSchema,
  handoff_ref: HandoffRefSchema,
});
export type TakeoverRequest = z.infer<typeof TakeoverRequestSchema>;

/** Idempotent for the same agent. */
export const TakeoverResponseSchema = z.object({
  conversation_id: ConversationIdSchema,
  takeover: z.object({
    active: z.literal(true),
    since: IsoDateTimeSchema,
    agent_ref: z.string().min(1),
  }),
});
export type TakeoverResponse = z.infer<typeof TakeoverResponseSchema>;

// --- POST /v1/agent/conversations/{id}/messages ---------------------------------------------------------------

export const AgentMessageRequestSchema = z.strictObject({
  text: MessageTextSchema,
  /** A repeated id returns the stored message. */
  client_message_id: ClientMessageIdSchema,
});
export type AgentMessageRequest = z.infer<typeof AgentMessageRequestSchema>;

export const AgentMessageSchema = z.object({
  role: z.literal("agent"),
  /** Masked text, as stored. */
  content: z.string(),
  blocks: RawBlocksSchema,
  created_at: IsoDateTimeSchema,
});
export type AgentMessage = z.infer<typeof AgentMessageSchema>;

export const AgentMessageResponseSchema = z.object({ message: AgentMessageSchema });
export type AgentMessageResponse = z.infer<typeof AgentMessageResponseSchema>;

// --- Routes --------------------------------------------------------------------------------------------------

/**
 * Errors: 401 bad token; 404 unknown conversation or session; 409 `taken_over_by_another_agent` (takeover)
 * or `no_active_takeover` (messages). The messages route also needs the `X-Agent-Ref` header
 * (`AGENT_REF_HEADER`), set by the BFF from the session.
 */
export const orchestratorAgentRoutes = {
  conversationForSession: defineRoute({
    method: "GET",
    pattern: "/v1/agent/sessions/:session_ref/conversation",
    successStatus: 200,
    params: SessionParamsSchema,
    response: SessionConversationResponseSchema,
  }),
  getConversation: defineRoute({
    method: "GET",
    pattern: "/v1/agent/conversations/:id",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: AgentTranscriptResponseSchema,
  }),
  takeover: defineRoute({
    method: "POST",
    pattern: "/v1/agent/conversations/:id/takeover",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: TakeoverRequestSchema,
    response: TakeoverResponseSchema,
  }),
  sendMessage: defineRoute({
    method: "POST",
    pattern: "/v1/agent/conversations/:id/messages",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: AgentMessageRequestSchema,
    response: AgentMessageResponseSchema,
  }),
} as const;
