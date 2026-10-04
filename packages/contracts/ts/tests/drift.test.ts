// Drift between the Zod contracts and the JSON Schemas that `export_schemas.py` writes and Python's own
// test pins byte for byte (packages/contracts/schemas). If a Python model changes, the schemas are
// regenerated (see README, "Regenerating"), and this file fails until the Zod side follows.
//
// It reads the committed JSON files; it never parses Python.

import { describe, expect, test } from "bun:test";
import { z } from "zod";
import * as blocks from "../blocks";
import * as enums from "../enums";
import * as trace from "../trace";
import {
  compareSchemas,
  enumDefs,
  readAllSchemaFiles,
  readSchemaFile,
  type JsonSchema,
} from "./json-schema";

/** Any Zod enum: only its values matter here. */
type EnumSchema = { readonly options: readonly (string | number)[] };

const zodSchema = (schema: z.ZodType): JsonSchema =>
  z.toJSONSchema(schema, { io: "input" }) as unknown as JsonSchema;

const python = await readSchemaFile("blocks/message_block.json");
const files = await readAllSchemaFiles();

describe("message blocks against blocks/message_block.json", () => {
  // Each block definition Python exports, and the Zod schema that mirrors it.
  const models: Record<string, z.ZodType> = {
    TextBlock: blocks.TextBlockSchema,
    ReceiptBlock: blocks.ReceiptBlockSchema,
    HandoffBlock: blocks.HandoffBlockSchema,
  };

  for (const [name, schema] of Object.entries(models)) {
    test(`${name}: field names, required fields, enums and limits agree`, () => {
      const zod = zodSchema(schema);
      expect(compareSchemas({ $ref: `#/$defs/${name}` }, python, zod, zod, name)).toEqual([]);
    });
  }

  test("the union is discriminated on `type` with the same members", () => {
    expect(python.discriminator?.propertyName).toBe("type");
    const mapping = python.discriminator?.mapping ?? {};
    expect(Object.keys(mapping).sort()).toEqual([...blocks.BLOCK_TYPES].sort());
    // Each discriminator value points at the model whose `type` const is that value, and the Zod
    // model with that `type` is the one compared above.
    for (const [type, ref] of Object.entries(mapping)) {
      const name = ref.replace("#/$defs/", "");
      expect(python.$defs?.[name]?.properties?.type?.const).toBe(type);
      expect(models[name]).toBeDefined();
      const option = blocks.MessageBlockSchema.options.find((candidate) => candidate.shape.type.value === type);
      expect(option).toBe(models[name] as never);
    }
  });

  test("every definition Python exports has a Zod counterpart", () => {
    const covered = new Set<string>([
      ...Object.keys(models),
      // Nested models: compared by recursion through the blocks that contain them.
      "Receipt",
      "HandoffSummary",
      "HandoffOpenQuestion",
      // A recursive JSON value: Zod's JsonValueSchema, exercised by the blocks tests.
      "JsonScalar",
      "JsonValue",
      // Enums: compared below.
      ...enumDefs(python).keys(),
    ]);
    expect(Object.keys(python.$defs ?? {}).filter((name) => !covered.has(name))).toEqual([]);
  });

  test("the Receipt definition agrees on its own", () => {
    const zod = zodSchema(blocks.ReceiptSchema);
    expect(compareSchemas({ $ref: "#/$defs/Receipt" }, python, zod, zod, "Receipt")).toEqual([]);
  });

  test("the HandoffSummary definition agrees on its own", () => {
    const zod = zodSchema(blocks.HandoffSummarySchema);
    expect(compareSchemas({ $ref: "#/$defs/HandoffSummary" }, python, zod, zod, "HandoffSummary")).toEqual([]);
  });

  test("the masked-target pattern is the one Python exports", () => {
    expect(python.$defs?.Receipt?.properties?.target_masked?.pattern).toBe(blocks.TARGET_MASKED_PATTERN);
  });

  test("the comparison would notice a difference", () => {
    const zod = zodSchema(blocks.TextBlockSchema);
    const drifted = structuredClone(zod);
    (drifted.properties as Record<string, JsonSchema>).extra = { type: "string" };
    (drifted.properties as Record<string, JsonSchema>).text = { type: "string", minLength: 1, maxLength: 3999 };
    drifted.required = ["type"];
    const problems = compareSchemas({ $ref: "#/$defs/TextBlock" }, python, drifted, drifted, "TextBlock");
    expect(problems).toContain('TextBlock: field "extra" is in Zod and missing in Python');
    expect(problems.some((problem) => problem.includes("maxLength"))).toBe(true);
    expect(problems.some((problem) => problem.includes("TextBlock.text: required in Python and optional in Zod"))).toBe(true);
  });
});

const pythonTrace = await readSchemaFile("trace/turn_trace.json");

describe("the detective-mode trace against trace/turn_trace.json", () => {
  // Each definition Python exports, and the Zod schema that mirrors it.
  const models: Record<string, z.ZodType> = {
    TraceCount: trace.TraceCountSchema,
    TraceDecisionPoint: trace.TraceDecisionPointSchema,
    EncoderDetail: trace.EncoderDetailSchema,
    MaskingDetail: trace.MaskingDetailSchema,
    TraceDecision: trace.TraceDecisionSchema,
    TraceEffect: trace.TraceEffectSchema,
    DecisionsDetail: trace.DecisionsDetailSchema,
    TraceMessage: trace.TraceMessageSchema,
    TraceToolRequest: trace.TraceToolRequestSchema,
    LlmCallDetail: trace.LlmCallDetailSchema,
    ToolCallDetail: trace.ToolCallDetailSchema,
    BlocksDetail: trace.BlocksDetailSchema,
    TraceEvent: trace.TraceEventSchema,
  };

  test("TurnTrace, the root: field names, required fields, enums and limits agree", () => {
    const zod = zodSchema(trace.TurnTraceSchema);
    expect(compareSchemas(pythonTrace, pythonTrace, zod, zod, "TurnTrace")).toEqual([]);
  });

  for (const [name, schema] of Object.entries(models)) {
    test(`${name}: field names, required fields, enums and limits agree`, () => {
      const zod = zodSchema(schema);
      expect(compareSchemas({ $ref: `#/$defs/${name}` }, pythonTrace, zod, zod, name)).toEqual([]);
    });
  }

  test("every definition Python exports has a Zod counterpart", () => {
    const covered = new Set<string>([...Object.keys(models), ...enumDefs(pythonTrace).keys()]);
    expect(Object.keys(pythonTrace.$defs ?? {}).filter((name) => !covered.has(name))).toEqual([]);
  });
});

describe("enums against every exported schema that defines them", () => {
  // Zod enum -> the Python class it mirrors (the name pydantic gives the definition).
  const mirrored: Record<string, EnumSchema> = {
    VerificationState: enums.VerificationStateSchema,
    ToolResultStatus: enums.ToolResultStatusSchema,
    ReasonCode: enums.ReasonCodeSchema,
    ResourceState: enums.ResourceStateSchema,
    HandoffReason: enums.HandoffReasonSchema,
    HandoffPriority: enums.HandoffPrioritySchema,
    Department: enums.DepartmentSchema,
    HandoffStatus: enums.HandoffStatusSchema,
    TraceEventKind: enums.TraceEventKindSchema,
    TraceEventStatus: enums.TraceEventStatusSchema,
  };

  for (const [pythonName, schema] of Object.entries(mirrored)) {
    test(`${pythonName}`, () => {
      const occurrences = [...files.entries()].flatMap(([file, root]) => {
        const values = enumDefs(root).get(pythonName);
        return values === undefined ? [] : [{ file, values }];
      });
      // At least one exported schema defines it, and every one that does agrees with Zod.
      expect(occurrences.length).toBeGreaterThan(0);
      for (const { file, values } of occurrences) {
        expect({ file, values: [...values].sort() }).toEqual({ file, values: schema.options.map(String).sort() });
      }
    });
  }

  test("every enum exported from enums.ts is checked above", () => {
    const exported = Object.values(enums as Record<string, unknown>).filter((value) => value instanceof z.ZodEnum);
    expect(exported.length).toBeGreaterThan(0);
    for (const schema of exported) {
      expect(Object.values(mirrored)).toContain(schema as EnumSchema);
    }
  });

  test("the enums the block schema defines are all mirrored", () => {
    // A new enum in a block field must get a Zod enum, or the block comparison above cannot check it.
    expect([...enumDefs(python).keys()].filter((name) => mirrored[name] === undefined)).toEqual([]);
  });

  test("the queue order is a permutation of the priorities", () => {
    expect([...enums.HANDOFF_PRIORITY_ORDER].sort()).toEqual([...enums.HandoffPrioritySchema.options].sort());
  });
});
