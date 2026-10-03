// The orchestrator's customer chat API (apps/orchestrator/src/orchestrator/chat/routes.py), with the
// two additions of the takeover: the `agent` role and the `takeover` object of the transcript.
//
// The web-client BFF forwards exactly these five routes (see bff-client.ts), so the browser sees the
// same shapes. `blocks` stay in their wire form (`RawBlock[]`): pass them through `parseBlocks`.

import { z } from "zod";
import {
  ClientMessageIdSchema,
  ConversationIdSchema,
  IsoDateTimeSchema,
  MessageTextSchema,
} from "./common";
import { RawBlocksSchema } from "./blocks";
import { defineRoute } from "./route";

/** orchestrator.session.models.Lang. */
export const LangSchema = z.enum(["es", "pt", "en"]);
export type Lang = z.infer<typeof LangSchema>;

/** contracts.locale.Locale: the customer's market (ADR-0014). Its language is the part before "-". */
export const LocaleSchema = z.enum(["pt-BR", "es-MX", "es-AR", "es-CO", "en-US"]);
export type Locale = z.infer<typeof LocaleSchema>;

/**
 * The roles a transcript returns. `system` exists in the orchestrator but is never returned. `agent`
 * is NEW: a message a back-office agent wrote after taking the conversation over.
 */
export const TranscriptRoleSchema = z.enum(["user", "assistant", "agent"]);
export type TranscriptRole = z.infer<typeof TranscriptRoleSchema>;

// --- POST /v1/conversations ------------------------------------------------------------------------------

/** The body may be left out altogether; it then means `{}`. */
export const CreateConversationRequestSchema = z.strictObject({
  lang: LangSchema.optional(),
  /** Alone, it sets the language; with a `lang` that contradicts it, the orchestrator answers 422. */
  locale: LocaleSchema.optional(),
});
export type CreateConversationRequest = z.infer<typeof CreateConversationRequestSchema>;

export const CreateConversationResponseSchema = z.object({
  conversation_id: ConversationIdSchema,
  language: LangSchema,
  /** Null when the conversation has no market; optional for orchestrators that predate it. */
  locale: LocaleSchema.nullable().optional(),
});
export type CreateConversationResponse = z.infer<typeof CreateConversationResponseSchema>;

// --- POST /v1/conversations/{id}/messages -------------------------------------------------------------------

export const SendMessageRequestSchema = z.strictObject({
  text: MessageTextSchema,
  lang: LangSchema.optional(),
  client_message_id: ClientMessageIdSchema.optional(),
});
export type SendMessageRequest = z.infer<typeof SendMessageRequestSchema>;

/**
 * While a takeover is active the customer message is stored and `blocks` is `[]`: an empty list is a
 * normal answer, not a failure.
 */
export const SendMessageResponseSchema = z.object({
  conversation_id: ConversationIdSchema,
  blocks: RawBlocksSchema,
});
export type SendMessageResponse = z.infer<typeof SendMessageResponseSchema>;

// --- GET /v1/conversations/{id} -----------------------------------------------------------------------------

export const TranscriptMessageSchema = z.object({
  role: TranscriptRoleSchema,
  /** Masked text for customer and assistant messages; an agent message is the text as the agent wrote it. */
  content: z.string(),
  blocks: RawBlocksSchema,
  created_at: IsoDateTimeSchema,
});
export type TranscriptMessage = z.infer<typeof TranscriptMessageSchema>;

/**
 * The takeover as the customer sees it. There is deliberately no agent identity here: parsing with
 * this schema strips one if an upstream ever sent it.
 */
export const CustomerTakeoverSchema = z.object({
  active: z.boolean(),
  since: IsoDateTimeSchema.nullable(),
});
export type CustomerTakeover = z.infer<typeof CustomerTakeoverSchema>;

export const TranscriptResponseSchema = z.object({
  conversation_id: ConversationIdSchema,
  language: LangSchema,
  /** Dropped (null) when the customer switches to another language. */
  locale: LocaleSchema.nullable().optional(),
  messages: z.array(TranscriptMessageSchema),
  takeover: CustomerTakeoverSchema,
});
export type TranscriptResponse = z.infer<typeof TranscriptResponseSchema>;

// --- GET /v1/conversations/{id}/inbox -----------------------------------------------------------------------

/** One simulated OTP delivery. It carries the clear code by design (ADR-0007): show it, never store it. */
export const InboxMessageSchema = z.object({
  channel: z.string(),
  destination_masked: z.string(),
  code: z.string(),
  received_at: IsoDateTimeSchema,
  expires_at: IsoDateTimeSchema,
});
export type InboxMessage = z.infer<typeof InboxMessageSchema>;

export const InboxResponseSchema = z.object({
  messages: z.array(InboxMessageSchema),
});
export type InboxResponse = z.infer<typeof InboxResponseSchema>;

// --- POST /v1/conversations/{id}/feedback -------------------------------------------------------------------

/** The customer's answer to "did the assistant help?", once the conversation was handed off (ADR-0017). */
export const SendFeedbackRequestSchema = z.strictObject({ helpful: z.boolean() });
export type SendFeedbackRequest = z.infer<typeof SendFeedbackRequestSchema>;

/** The answer as banking-core stored it. The handoff it belongs to stays on the trusted side. */
export const FeedbackResponseSchema = z.object({
  helpful: z.boolean(),
  recorded_at: IsoDateTimeSchema,
});
export type FeedbackResponse = z.infer<typeof FeedbackResponseSchema>;

// --- Routes --------------------------------------------------------------------------------------------------

export const ConversationParamsSchema = z.object({ id: ConversationIdSchema });
export type ConversationParams = z.infer<typeof ConversationParamsSchema>;

/**
 * Errors: 404 unknown conversation, 409 a turn is already running (feedback: `no_handoff`,
 * `already_answered`), 429 with `Retry-After` (seconds), 502 no banking session could be opened,
 * 503 `replay_miss`, or the turn, the inbox or the feedback store is unavailable.
 */
export const orchestratorChatRoutes = {
  createConversation: defineRoute({
    method: "POST",
    pattern: "/v1/conversations",
    successStatus: 201,
    body: CreateConversationRequestSchema,
    bodyOptional: true,
    response: CreateConversationResponseSchema,
  }),
  sendMessage: defineRoute({
    method: "POST",
    pattern: "/v1/conversations/:id/messages",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: SendMessageRequestSchema,
    response: SendMessageResponseSchema,
  }),
  getTranscript: defineRoute({
    method: "GET",
    pattern: "/v1/conversations/:id",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: TranscriptResponseSchema,
  }),
  getInbox: defineRoute({
    method: "GET",
    pattern: "/v1/conversations/:id/inbox",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: InboxResponseSchema,
  }),
  sendFeedback: defineRoute({
    method: "POST",
    pattern: "/v1/conversations/:id/feedback",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: SendFeedbackRequestSchema,
    response: FeedbackResponseSchema,
  }),
} as const;
