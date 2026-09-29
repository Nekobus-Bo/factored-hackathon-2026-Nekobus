// What an `ApiError` means for the screens. The BFF's codes are the contract's (`ERROR_DETAIL`), so the
// classification lives in one place and the machines and components only ask for a category.

import { ERROR_DETAIL, type ValidationIssue } from "@pattern-blue/contracts";
import { isApiError } from "./client";

export type ErrorCategory =
  | "unauthorized"
  | "notFound"
  /** Another agent holds the handoff or its conversation. */
  | "heldByAnother"
  /** The claim succeeded, the takeover did not; repeating the call is safe. */
  | "claimedButTakeoverFailed"
  /** The conversation is not (or no longer) taken over by this agent. */
  | "noActiveTakeover"
  /** A customer turn holds the conversation; the same message can be retried. */
  | "turnInProgress"
  | "forbidden"
  /** The request was refused as invalid (422), with the issues the API gave. */
  | "validation"
  /** Nobody answered, or an upstream did not: retry later. */
  | "unavailable"
  | "other";

const TURN_IN_PROGRESS = "turn_in_progress";

export function categorize(error: unknown): ErrorCategory {
  if (!isApiError(error)) return "other";
  if (error.kind === "network") return "unavailable";
  if (error.kind === "invalid") return "other";
  const { status, detail } = error;
  if (status === 401) return "unauthorized";
  if (status === 404) return "notFound";
  if (status === 403) return "forbidden";
  if (status === 409) {
    if (detail === ERROR_DETAIL.noActiveTakeover) return "noActiveTakeover";
    return "heldByAnother";
  }
  if (status === 422) return "validation";
  if (status === 502 && detail === ERROR_DETAIL.claimedButTakeoverFailed) return "claimedButTakeoverFailed";
  if (status === 503 && detail === TURN_IN_PROGRESS) return "turnInProgress";
  if (status === 502 || status === 503) return "unavailable";
  return "other";
}

/** The messages of a 422, one per issue. */
export function validationMessages(error: unknown): string[] {
  if (!isApiError(error) || !Array.isArray(error.detail)) return [];
  return (error.detail as ValidationIssue[]).map((issue) => issue.msg);
}
