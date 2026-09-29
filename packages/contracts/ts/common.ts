// Primitives shared by every HTTP shape: timestamps, opaque references, error bodies.
//
// Two rules run through this package:
//   * Request schemas are strict. A BFF forwards only what the contract names, so an unknown key is
//     an error, never a silent pass-through (ADR-0004).
//   * Response schemas strip what they do not know. A consumer parses with them and passes on only the
//     parsed value, so a field the contract does not name (an agent identity in the customer view, the
//     `eval` block of a debug orchestrator) does not reach the browser.

import { z } from "zod";

/**
 * ISO 8601 with an explicit offset. The orchestrator writes `Z`; a value read back from the database
 * may carry `+00:00` or another offset. Times are UTC by contract; the offset is accepted so a valid
 * instant never fails a page.
 */
export const IsoDateTimeSchema = z.iso.datetime({ offset: true });
export type IsoDateTime = z.infer<typeof IsoDateTimeSchema>;

/**
 * An opaque token that is safe to put in a URL path: letters, digits, `_` and `-`. The consumers check
 * this before they build an upstream path, so a crafted id cannot walk out of its route.
 */
const opaqueRef = (max: number) => z.string().regex(new RegExp(`^[A-Za-z0-9_-]{1,${max}}$`));

/**
 * The orchestrator's conversation id. Today it is `conv_` plus 32 hex digits (`ConversationState` in
 * `apps/orchestrator/src/orchestrator/session/models.py`); the client must treat it as opaque, so the
 * schema checks only that it is path-safe. It is not a UUID.
 */
export const ConversationIdSchema = opaqueRef(64);
export type ConversationId = z.infer<typeof ConversationIdSchema>;

/** A banking-core handoff reference: `hnd_` plus 16 lowercase letters today; opaque, path-safe. */
export const HandoffRefSchema = opaqueRef(64);
export type HandoffRef = z.infer<typeof HandoffRefSchema>;

/** A banking-core session id (`sess_` plus 32 hex digits today); what `ops.handoff.session_ref` stores. */
export const SessionRefSchema = opaqueRef(128);
export type SessionRef = z.infer<typeof SessionRefSchema>;

/**
 * The back-office agent, identified by e-mail (3 to 128 characters, the width of `ops.audit_log.actor_ref`). The check is deliberately the
 * shape only (`something@something`, no whitespace): the value also travels in the `X-Agent-Ref`
 * header and in an audit row, and it must never carry a line break.
 */
export const AgentRefSchema = z
  .string()
  .min(3)
  .max(128)
  .regex(/^[^\s@]+@[^\s@]+$/);
export type AgentRef = z.infer<typeof AgentRefSchema>;

/** The client message id: the retry handle. Unique per message, repeated unchanged on a retry. */
export const ClientMessageIdSchema = z
  .string()
  .min(8)
  .max(64)
  .regex(/^[A-Za-z0-9_-]+$/);
export type ClientMessageId = z.infer<typeof ClientMessageIdSchema>;

/** Text a person types, as the orchestrator accepts it: 1 to 2000 characters. */
export const MessageTextSchema = z.string().min(1).max(2000);

/** A non-negative count. */
export const CountSchema = z.number().int().min(0);

/** Header the web-backoffice BFF sets from its session, so the orchestrator knows which agent acts. */
export const AGENT_REF_HEADER = "X-Agent-Ref";

// --- Errors ------------------------------------------------------------------------------------------

/** One entry of FastAPI's own 422 body, and of the tool-policy refusal, which copies its shape. */
export const ValidationIssueSchema = z.looseObject({
  loc: z.array(z.union([z.string(), z.number()])),
  msg: z.string(),
  type: z.string(),
});
export type ValidationIssue = z.infer<typeof ValidationIssueSchema>;

/** FastAPI's error body: `detail` is a code or message, or a list of validation issues (422). */
export const ApiErrorSchema = z.object({
  detail: z.union([z.string(), z.array(ValidationIssueSchema)]),
});
export type ApiError = z.infer<typeof ApiErrorSchema>;

/** The `detail` codes the contract fixes. Anything else in `detail` is a free-text message. */
export const ERROR_DETAIL = {
  /** Replay mode has no recording for this turn (orchestrator, 503). */
  replayMiss: "replay_miss",
  /** A BFF could not reach its upstream (503). */
  unavailable: "unavailable",
  /** Another agent already holds the conversation (orchestrator agent API, 409). */
  takenOverByAnotherAgent: "taken_over_by_another_agent",
  /** The agent posted a message without holding the takeover (orchestrator agent API, 409). */
  noActiveTakeover: "no_active_takeover",
  /** Another agent already holds the handoff (banking-core admin API, 409). */
  claimedByAnotherAgent: "claimed_by_another_agent",
  /** A customer turn holds the conversation's lock past the wait (orchestrator agent API, 503 with Retry-After). Retrying is safe. */
  turnInProgress: "turn_in_progress",
  /** The claim succeeded and the takeover failed; retrying the same call is safe (back-office BFF, 502). */
  claimedButTakeoverFailed: "claimed_but_takeover_failed",
} as const;
export type ErrorDetailCode = (typeof ERROR_DETAIL)[keyof typeof ERROR_DETAIL];
