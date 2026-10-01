// Message blocks: what the orchestrator returns to the chat client. Mirrors, field by field,
// packages/contracts/src/contracts/blocks.py (and envelope.py's Receipt, handoff_create.py's summary).
// tests/drift.test.ts compares these schemas with the committed JSON Schema
// packages/contracts/schemas/blocks/message_block.json: field names, required fields, enum values and
// the length/pattern limits. Change the Python model, regenerate the schemas, then change this file.
//
// Objects strip unknown keys instead of rejecting them (Python's models forbid extras, but a server
// never sends one; a consumer that strips is safe by construction, since it renders only what it
// parsed). What this file never does is crash on a block it does not know: see parseBlocks.

import { z } from "zod";
import { IsoDateTimeSchema } from "./common";
import {
  DepartmentSchema,
  HandoffPrioritySchema,
  HandoffStatusSchema,
  ResourceStateSchema,
} from "./enums";

// --- JSON values ---------------------------------------------------------------------------------------

/** contracts.tools.handoff_create.JsonValue. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export const JsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([z.string(), z.number(), z.boolean(), z.null(), z.array(JsonValueSchema), z.record(z.string(), JsonValueSchema)]),
);

// --- Receipt -------------------------------------------------------------------------------------------

/**
 * contracts.envelope.TARGET_MASKED_PATTERN: a masked card number, e-mail or phone, or an opaque
 * reference. The drift test compares this source string with the one in the exported schema.
 */
export const TARGET_MASKED_PATTERN =
  String.raw`^((\*{4}[\s-]?\*{4}[\s-]?\*{4}[\s-]?\d{4}|\*{4,12}\d{4})|[a-zA-Z0-9]\*+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|(\+?\d{1,3}[-\s]?)?(\d{1,4}[-\s]?)?(\*+[-\s]?)+\d{2,4}|(card|hnd|otp|chal|ticket|handoff)[_-][A-Za-z0-9*_-]{6,50})$`;

const OPAQUE_PREFIXES = ["card", "hnd", "otp", "chal", "ticket", "handoff"] as const;

/** Receipt.validate_pan_guard: an opaque reference never carries 12 or more digits. */
function passesPanGuard(target: string): boolean {
  for (const prefix of OPAQUE_PREFIXES) {
    if (target.startsWith(`${prefix}_`) || target.startsWith(`${prefix}-`)) {
      const digits = [...target.slice(prefix.length + 1)].filter((char) => char >= "0" && char <= "9").length;
      return digits < 12;
    }
  }
  return true;
}

/** contracts.envelope.Receipt: a write re-read from the database. */
export const ReceiptSchema = z.object({
  action: z.string().min(3).max(64),
  target_masked: z
    .string()
    .min(6)
    .max(64)
    .regex(new RegExp(TARGET_MASKED_PATTERN))
    .refine(passesPanGuard, "an opaque reference cannot contain 12 or more digits"),
  state_before: ResourceStateSchema,
  state_after: ResourceStateSchema,
  verified_at: IsoDateTimeSchema,
  audit_id: z.string().min(8).max(128),
});
export type Receipt = z.infer<typeof ReceiptSchema>;

// --- Handoff summary -----------------------------------------------------------------------------------

/** contracts.tools.handoff_create.HandoffOpenQuestion. */
export const HandoffOpenQuestionSchema = z.object({
  source: z.string(),
  text: z.string(),
});
export type HandoffOpenQuestion = z.infer<typeof HandoffOpenQuestionSchema>;

/** contracts.tools.handoff_create.HandoffSummary: the server-built context stored with a handoff. */
export const HandoffSummarySchema = z.object({
  verified_facts: z.record(z.string(), JsonValueSchema),
  actions_taken: z.array(z.union([z.string(), z.record(z.string(), JsonValueSchema)])),
  verification_method: z.string(),
  open_questions: z.array(HandoffOpenQuestionSchema),
});
export type HandoffSummary = z.infer<typeof HandoffSummarySchema>;

// --- Blocks --------------------------------------------------------------------------------------------

/** contracts.blocks.TextBlock. `type` is required on the wire even though Python defaults it. */
export const TextBlockSchema = z.object({
  type: z.literal("text"),
  text: z.string().min(1).max(4000),
});
export type TextBlock = z.infer<typeof TextBlockSchema>;

/** contracts.blocks.ReceiptBlock. */
export const ReceiptBlockSchema = z.object({
  type: z.literal("receipt"),
  receipt: ReceiptSchema,
});
export type ReceiptBlock = z.infer<typeof ReceiptBlockSchema>;

/** contracts.blocks.HandoffBlock. `queue_position` is null when the position is not known. */
export const HandoffBlockSchema = z.object({
  type: z.literal("handoff"),
  handoff_id: z.string().min(8).max(64),
  status: HandoffStatusSchema,
  department: DepartmentSchema,
  priority: HandoffPrioritySchema,
  queue_position: z.number().int().min(1).nullable().default(null),
  summary: HandoffSummarySchema,
  receipt: ReceiptSchema,
});
export type HandoffBlock = z.infer<typeof HandoffBlockSchema>;

/** contracts.blocks.MessageBlock: a union discriminated on `type`. */
export const MessageBlockSchema = z.discriminatedUnion("type", [
  TextBlockSchema,
  ReceiptBlockSchema,
  HandoffBlockSchema,
]);
export type MessageBlock = z.infer<typeof MessageBlockSchema>;

/** contracts.blocks.BLOCK_TYPES, derived from the union so the two cannot disagree. */
export const BLOCK_TYPES = MessageBlockSchema.options.map((option) => option.shape.type.value);
export type BlockType = MessageBlock["type"];

export function isKnownBlockType(type: string): type is BlockType {
  return (BLOCK_TYPES as readonly string[]).includes(type);
}

// --- The wire form -------------------------------------------------------------------------------------

/**
 * A block as it travels: the orchestrator declares `blocks` as a list of dicts, and a newer server may
 * send a type this build does not know. The HTTP schemas keep blocks in this form; a consumer turns
 * them into `MessageBlock`s with `parseBlocks`.
 */
export const RawBlockSchema = z.record(z.string(), z.unknown());
export type RawBlock = z.infer<typeof RawBlockSchema>;

export const RawBlocksSchema = z.array(RawBlockSchema);

// --- parseBlocks ---------------------------------------------------------------------------------------

export type UnknownBlockReason =
  /** `type` is a string this build does not know: a newer server, or a block only another client renders. */
  | "unknown_type"
  /** No usable `type`, or a known type whose fields do not satisfy its schema. */
  | "invalid";

/** A block `parseBlocks` set aside. */
export interface UnknownBlock {
  /** Position in the input list; -1 when the input was not a list at all. */
  index: number;
  /** The block's `type` when it has one. */
  type: string | null;
  reason: UnknownBlockReason;
  /** One line per problem, `path: message`; empty for an unknown type. */
  issues: string[];
  /** The value as received, for a log or a "cannot show this" placeholder. */
  raw: unknown;
}

export interface ParsedBlocks {
  /** The blocks that parsed, in the order received. */
  blocks: MessageBlock[];
  /** Everything else, each with the reason it was set aside. */
  unknown: UnknownBlock[];
}

/**
 * Parse the `blocks` of a response or of a transcript message. It never throws: a block of a type this
 * build does not know, or a known one that fails its schema, is reported in `unknown` and the rest are
 * kept, so a new block type on the server degrades one message and does not blank the chat.
 */
export function parseBlocks(input: unknown): ParsedBlocks {
  if (!Array.isArray(input)) {
    return {
      blocks: [],
      unknown: [{ index: -1, type: null, reason: "invalid", issues: ["blocks is not a list"], raw: input }],
    };
  }

  const result: ParsedBlocks = { blocks: [], unknown: [] };
  input.forEach((raw: unknown, index) => {
    const type = typeof raw === "object" && raw !== null && "type" in raw && typeof raw.type === "string" ? raw.type : null;
    if (type !== null && !isKnownBlockType(type)) {
      result.unknown.push({ index, type, reason: "unknown_type", issues: [], raw });
      return;
    }
    const parsed = MessageBlockSchema.safeParse(raw);
    if (parsed.success) {
      result.blocks.push(parsed.data);
      return;
    }
    result.unknown.push({
      index,
      type,
      reason: "invalid",
      issues: parsed.error.issues.map((issue) => `${issue.path.join(".") || "(block)"}: ${issue.message}`),
      raw,
    });
  });
  return result;
}
