// Structure of src/tokens.json, the design-system artifact's token file.
//
// The file is copied by hand from the artifact (README, "Syncing from the artifact"), so the build
// checks its shape and stops with a readable message when the artifact starts using something this
// package does not know how to emit. Top-level families are strict for that reason: a new family
// should fail the build, not be dropped silently.

import { z } from "zod";

/** Token, family and style names end up in CSS custom properties, class names and TS keys. */
const NAME = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;

/** A reference to another color token: "{pattern}". */
export const ALIAS = /^\{([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\}$/;

/**
 * A plain CSS value. The file is content written outside this repository, so values that could end
 * a declaration or a block, open a comment or break out of an HTML comment are rejected.
 */
const cssValue = z
  .string()
  .min(1)
  .refine((value) => !/[;{}<>\r\n]|\/\*|\*\//.test(value), {
    message: "must be a plain CSS value: no ; { } < > line breaks or comments",
  });

const tokenName = z.string().regex(NAME, "must be lowercase words joined by hyphens");

const usage = z.string().optional();

const perTheme = z.strictObject({ light: cssValue, dark: cssValue });

const colorToken = z.object({
  name: tokenName,
  value: z.union([z.string().regex(ALIAS, 'an alias is written "{token-name}"'), perTheme]),
  usage,
});

const shadowToken = z.object({ name: tokenName, value: perTheme, usage });

const simpleToken = z.object({ name: tokenName, value: cssValue, usage });

const typeStyle = z.object({
  name: tokenName,
  fontSize: cssValue,
  lineHeight: cssValue,
  fontWeight: z.number().int().min(1).max(1000),
  letterSpacing: cssValue.optional(),
  sample: z.string().optional(),
  usage,
});

const typeGroup = z.object({
  name: cssValue,
  family: tokenName,
  note: z.string().optional(),
  styles: z.array(typeStyle).min(1),
});

export const tokensSchema = z.strictObject({
  name: z.string(),
  version: z.number().int(),
  color: z.strictObject({
    themes: z.array(z.strictObject({ id: tokenName, name: z.string() })).min(1),
    note: z.string().optional(),
    tokens: z.array(colorToken).min(1),
  }),
  type: z.strictObject({
    fonts: z
      .array(z.unknown())
      .length(
        0,
        "type.fonts must be empty: the build has no font files to emit, fonts come from Google Fonts",
      ),
    families: z.record(tokenName, cssValue),
    groups: z.array(typeGroup).min(1),
  }),
  spacing: z.strictObject({ note: z.string().optional(), tokens: z.array(simpleToken).min(1) }),
  radius: z.strictObject({ note: z.string().optional(), tokens: z.array(simpleToken).min(1) }),
  shadow: z.strictObject({ note: z.string().optional(), tokens: z.array(shadowToken).min(1) }),
  motion: z.strictObject({ note: z.string().optional(), tokens: z.array(simpleToken).min(1) }),
  stroke: z.strictObject({ note: z.string().optional(), tokens: z.array(simpleToken).min(1) }),
});

export type Tokens = z.infer<typeof tokensSchema>;

/** Validate an already parsed tokens.json. Throws one Error listing every problem. */
export function parseTokens(input: unknown): Tokens {
  const result = tokensSchema.safeParse(input);
  if (!result.success) {
    throw new Error(`src/tokens.json does not match the expected structure:\n${z.prettifyError(result.error)}`);
  }
  return result.data;
}
