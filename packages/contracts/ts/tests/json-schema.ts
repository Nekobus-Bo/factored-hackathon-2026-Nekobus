// Just enough JSON Schema handling for the drift test: load the committed files, follow local `$ref`s,
// unwrap `nullable`, and compare a Python-generated schema with the one Zod generates. It is not a
// general validator; it understands the constructs pydantic and Zod actually emit for these contracts.

import { join, resolve } from "node:path";

/** packages/contracts/schemas: what `export_schemas.py` writes and the Python drift test pins. */
export const SCHEMAS_DIR = resolve(import.meta.dir, "../../schemas");

export interface JsonSchema {
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  type?: string;
  enum?: unknown[];
  const?: unknown;
  default?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  additionalProperties?: boolean | JsonSchema;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  format?: string;
  discriminator?: { propertyName: string; mapping: Record<string, string> };
}

export async function readSchemaFile(relative: string): Promise<JsonSchema> {
  return (await Bun.file(join(SCHEMAS_DIR, relative)).json()) as JsonSchema;
}

/** Every exported schema file, keyed by its path relative to `schemas/`. */
export async function readAllSchemaFiles(): Promise<Map<string, JsonSchema>> {
  const files = new Map<string, JsonSchema>();
  for await (const relative of new Bun.Glob("**/*.json").scan(SCHEMAS_DIR)) {
    files.set(relative, await readSchemaFile(relative));
  }
  return files;
}

/** Follows `#/$defs/Name` references against the root the schema came from. */
export function deref(schema: JsonSchema, root: JsonSchema): JsonSchema {
  let current = schema;
  const seen = new Set<string>();
  while (current.$ref !== undefined) {
    const ref = current.$ref;
    if (seen.has(ref)) throw new Error(`circular $ref ${ref}`);
    seen.add(ref);
    const match = /^#\/\$defs\/(.+)$/.exec(ref);
    const target = match?.[1] === undefined ? undefined : root.$defs?.[match[1]];
    if (target === undefined) throw new Error(`cannot resolve $ref ${ref}`);
    current = target;
  }
  return current;
}

/** The enum definitions of a schema, by name (pydantic puts each `Enum` class under `$defs`). */
export function enumDefs(root: JsonSchema): Map<string, string[]> {
  const defs = new Map<string, string[]>();
  for (const [name, def] of Object.entries(root.$defs ?? {})) {
    if (def.enum !== undefined) defs.set(name, def.enum.map(String));
  }
  return defs;
}

/** What a property is, reduced to the facts the two sides must agree on. */
export interface Leaf {
  nullable: boolean;
  kind: string;
  enum?: string[];
  const?: unknown;
  minLength?: number;
  maxLength?: number;
  format?: string;
  minimum?: number;
  maximum?: number;
  pattern?: string;
}

function isNull(schema: JsonSchema): boolean {
  return schema.type === "null";
}

/** Unwraps `X | null` and resolves references; the resolved schema is returned beside its description. */
export function leaf(schema: JsonSchema, root: JsonSchema): { leaf: Leaf; resolved: JsonSchema } {
  let resolved = deref(schema, root);
  let nullable = false;
  if (resolved.anyOf !== undefined) {
    const members = resolved.anyOf;
    const rest = members.filter((member) => !isNull(member));
    nullable = rest.length !== members.length;
    if (rest.length === 1) resolved = deref(rest[0] as JsonSchema, root);
    else {
      const kinds = rest.map((member) => leaf(member, root).leaf.kind).sort();
      return { leaf: { nullable, kind: `union(${kinds.join(",")})` }, resolved };
    }
  }
  const description: Leaf = { nullable, kind: resolved.type ?? "unknown" };
  if (resolved.enum !== undefined) description.enum = resolved.enum.map(String).sort();
  if (resolved.const !== undefined) description.const = resolved.const;
  for (const key of ["minLength", "maxLength", "format", "minimum", "maximum", "pattern"] as const) {
    if (resolved[key] !== undefined) (description as unknown as Record<string, unknown>)[key] = resolved[key];
  }
  return { leaf: description, resolved };
}

/** Facts stated on both sides must be equal, and a fact only Python states must also hold for Zod. */
const BOTH_WAYS = ["nullable", "kind", "enum", "const", "minLength", "maxLength", "format"] as const;
/**
 * Facts Python states must appear on the Zod side, but Zod may add its own: `maximum` (Zod bounds an
 * integer to the safe range) and `pattern` (Zod adds one to `date-time`).
 */
const PYTHON_ONLY = ["minimum", "maximum", "pattern"] as const;

/**
 * Compare the schema pydantic exported (`python`, resolved against `pythonRoot`) with the one Zod
 * generated (`zod`, against `zodRoot`). Returns one line per disagreement; empty means they agree on
 * field names, required fields, enum values and limits, recursing into nested objects and lists.
 */
export function compareSchemas(
  python: JsonSchema,
  pythonRoot: JsonSchema,
  zod: JsonSchema,
  zodRoot: JsonSchema,
  path: string,
): string[] {
  const problems: string[] = [];
  const { leaf: pyLeaf, resolved: pyResolved } = leaf(python, pythonRoot);
  const { leaf: zodLeaf, resolved: zodResolved } = leaf(zod, zodRoot);

  for (const key of BOTH_WAYS) {
    if (JSON.stringify(pyLeaf[key]) !== JSON.stringify(zodLeaf[key])) {
      problems.push(`${path}: ${key} is ${JSON.stringify(pyLeaf[key])} in Python and ${JSON.stringify(zodLeaf[key])} in Zod`);
    }
  }
  for (const key of PYTHON_ONLY) {
    if (pyLeaf[key] !== undefined && JSON.stringify(pyLeaf[key]) !== JSON.stringify(zodLeaf[key])) {
      problems.push(`${path}: ${key} is ${JSON.stringify(pyLeaf[key])} in Python and ${JSON.stringify(zodLeaf[key])} in Zod`);
    }
  }

  if (pyResolved.properties !== undefined || zodResolved.properties !== undefined) {
    const pyProps = pyResolved.properties ?? {};
    const zodProps = zodResolved.properties ?? {};
    const pyNames = Object.keys(pyProps).sort();
    const zodNames = Object.keys(zodProps).sort();
    for (const name of pyNames) if (!zodNames.includes(name)) problems.push(`${path}: field "${name}" is in Python and missing in Zod`);
    for (const name of zodNames) if (!pyNames.includes(name)) problems.push(`${path}: field "${name}" is in Zod and missing in Python`);

    const pyRequired = new Set(pyResolved.required ?? []);
    const zodRequired = new Set(zodResolved.required ?? []);
    for (const name of pyNames) {
      if (!zodNames.includes(name)) continue;
      // Python defaults the `type` of a block ("text"), so its schema does not require it. On the wire
      // it is always present, and Zod needs it to discriminate: the one accepted difference.
      const pyProp = pyProps[name] as JsonSchema;
      const isDiscriminator = name === "type" && pyProp.const !== undefined && pyProp.default === pyProp.const;
      if (pyRequired.has(name) !== zodRequired.has(name) && !(isDiscriminator && zodRequired.has(name))) {
        problems.push(
          `${path}.${name}: ${pyRequired.has(name) ? "required" : "optional"} in Python and ${zodRequired.has(name) ? "required" : "optional"} in Zod`,
        );
      }
      problems.push(...compareSchemas(pyProp, pythonRoot, zodProps[name] as JsonSchema, zodRoot, `${path}.${name}`));
    }
  }

  if (pyResolved.items !== undefined || zodResolved.items !== undefined) {
    if (pyResolved.items === undefined || zodResolved.items === undefined) {
      problems.push(`${path}: only one side describes the list items`);
    } else {
      problems.push(...compareSchemas(pyResolved.items, pythonRoot, zodResolved.items, zodRoot, `${path}[]`));
    }
  }
  return problems;
}
