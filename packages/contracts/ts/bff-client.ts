// The web-client BFF (apps/web-client, port 5173), same origin as the page under `/api`.
//
// It maps 1:1 to the orchestrator's six chat routes, so it speaks the same shapes: validate the
// request with the route's schemas, forward, validate the response, answer with the parsed value.
// Status codes and `Retry-After` pass through; an upstream that cannot be reached is a 503
// `{"detail": "unavailable"}` (ERROR_DETAIL.unavailable). It holds no tokens, sets `X-Forwarded-For`
// to the client address, and also serves `GET /healthz`.

import {
  CapabilitiesResponseSchema,
  ConversationParamsSchema,
  CreateConversationRequestSchema,
  CreateConversationResponseSchema,
  FeedbackResponseSchema,
  InboxResponseSchema,
  SendFeedbackRequestSchema,
  SendMessageRequestSchema,
  SendMessageResponseSchema,
  TranscriptResponseSchema,
} from "./orchestrator-chat";
import { defineRoute } from "./route";

/** `:id` is a conversation id; it is checked before it becomes part of an upstream path. */
export const clientBffRoutes = {
  createConversation: defineRoute({
    method: "POST",
    pattern: "/api/conversations",
    successStatus: 201,
    body: CreateConversationRequestSchema,
    bodyOptional: true,
    response: CreateConversationResponseSchema,
  }),
  sendMessage: defineRoute({
    method: "POST",
    pattern: "/api/conversations/:id/messages",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: SendMessageRequestSchema,
    response: SendMessageResponseSchema,
  }),
  getTranscript: defineRoute({
    method: "GET",
    pattern: "/api/conversations/:id",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: TranscriptResponseSchema,
  }),
  getInbox: defineRoute({
    method: "GET",
    pattern: "/api/conversations/:id/inbox",
    successStatus: 200,
    params: ConversationParamsSchema,
    response: InboxResponseSchema,
  }),
  sendFeedback: defineRoute({
    method: "POST",
    pattern: "/api/conversations/:id/feedback",
    successStatus: 200,
    params: ConversationParamsSchema,
    body: SendFeedbackRequestSchema,
    response: FeedbackResponseSchema,
  }),
  getCapabilities: defineRoute({
    method: "GET",
    pattern: "/api/capabilities",
    successStatus: 200,
    response: CapabilitiesResponseSchema,
  }),
} as const;
