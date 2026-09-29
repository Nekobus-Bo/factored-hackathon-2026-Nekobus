// Enums that have a Python source in packages/contracts/src/contracts/. Every enum in this file is
// checked against the committed JSON Schemas by tests/drift.test.ts; a new export here without a
// source there fails that test. Enums with no exported schema live beside the API that uses them.

import { z } from "zod";

/** contracts.envelope.VerificationState: the finite-state machine of the identity flow. */
export const VerificationStateSchema = z.enum([
  "ANONYMOUS",
  "IDENTIFIED",
  "OTP_PENDING",
  "VERIFIED",
  "LOCKED",
  "HANDED_OFF",
]);
export type VerificationState = z.infer<typeof VerificationStateSchema>;

/** contracts.envelope.ToolResultStatus. */
export const ToolResultStatusSchema = z.enum(["ok", "refused", "error"]);
export type ToolResultStatus = z.infer<typeof ToolResultStatusSchema>;

/** contracts.envelope.ReasonCode: why a tool call was refused or failed. */
export const ReasonCodeSchema = z.enum([
  "STATE_NOT_ALLOWED",
  "POLICY_BLOCKED",
  "POLICY_FLAGGED",
  "RATE_LIMITED",
  "NOT_MATCHED",
  "NOT_IMPLEMENTED",
  "SESSION_BUSY",
  "INVALID_ARGUMENTS",
  "CODE_FLOOR_VIOLATION",
  "CONFIRMATION_REQUIRED",
  "INTERNAL_ERROR",
]);
export type ReasonCode = z.infer<typeof ReasonCodeSchema>;

/** contracts.envelope.ResourceState: the state of a resource before and after a write. */
export const ResourceStateSchema = z.enum([
  "NONE",
  "ACTIVE",
  "BLOCKED",
  "FROZEN",
  "ISSUED",
  "PENDING",
  "VERIFIED",
  "EXPIRED",
  "LOCKED",
  "QUEUED",
  "ASSIGNED",
  "RESOLVED",
  "ANONYMOUS",
  "IDENTIFIED",
  "OTP_PENDING",
  "HANDED_OFF",
]);
export type ResourceState = z.infer<typeof ResourceStateSchema>;

/** contracts.tools.handoff_create.HandoffReason. */
export const HandoffReasonSchema = z.enum([
  "SUSPECTED_FRAUD",
  "DISPUTE_CLAIM",
  "CUSTOMER_LOCKED",
  "UNRECOGNIZED_TRANSACTION",
  "CUSTOMER_REQUEST",
  "VERIFICATION_FAILED",
]);
export type HandoffReason = z.infer<typeof HandoffReasonSchema>;

/** contracts.tools.handoff_create.HandoffPriority, in the Python order (lowest first). */
export const HandoffPrioritySchema = z.enum(["LOW", "NORMAL", "HIGH", "URGENT"]);
export type HandoffPriority = z.infer<typeof HandoffPrioritySchema>;

/** The order the queue is served in: most urgent first (`GET /v1/admin/handoffs`). */
export const HANDOFF_PRIORITY_ORDER: readonly HandoffPriority[] = ["URGENT", "HIGH", "NORMAL", "LOW"];

/** contracts.tools.handoff_create.Department. */
export const DepartmentSchema = z.enum(["FRAUD_OPERATIONS", "CUSTOMER_SUPPORT", "DISPUTES"]);
export type Department = z.infer<typeof DepartmentSchema>;

/** contracts.tools.handoff_create.HandoffStatus. */
export const HandoffStatusSchema = z.enum(["QUEUED", "ASSIGNED", "PENDING"]);
export type HandoffStatus = z.infer<typeof HandoffStatusSchema>;
