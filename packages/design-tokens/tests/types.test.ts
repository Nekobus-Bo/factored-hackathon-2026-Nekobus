// Type-level checks: `bun test` runs them as plain assertions, `tsc --noEmit` (make design-tokens-check)
// is what makes the @ts-expect-error lines meaningful.

import { expect, test } from "bun:test";
import {
  colors,
  cssVar,
  spacing,
  themes,
  type ColorTokenName,
  type CssVar,
  type ThemeId,
  type TokenName,
} from "../dist/tokens";

test("cssVar returns the var() reference with a literal type", () => {
  const violet: "var(--violet)" = cssVar("violet");
  const gap: CssVar<"space-4"> = cssVar("space-4");
  const font: "var(--font-mono)" = cssVar("font-mono");
  expect([violet, gap, font]).toEqual(["var(--violet)", "var(--space-4)", "var(--font-mono)"]);
});

test("token names are closed unions", () => {
  // @ts-expect-error not a token
  cssVar("not-a-token");
  // @ts-expect-error a type style is a class, not a custom property
  cssVar("h1");
  const name: TokenName = "cut-md";
  expect(cssVar(name)).toBe("var(--cut-md)");
});

test("values are indexed by theme", () => {
  const theme: ThemeId = themes[1].id;
  const key: ColorTokenName = "surface-000";
  expect(colors[key][theme]).toBe("#08070f");
  expect(spacing["space-4"]).toBe("16px");
  // @ts-expect-error there are only two themes
  colors[key].sepia;
});
