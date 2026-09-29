// Pure generators: tokens.json in, file contents out. No clock, no filesystem, no randomness, so the
// same input always produces the same bytes (the drift check and the tests rely on it).
// scripts/build.ts is the only caller that touches disk.

import { ALIAS, parseTokens, type Tokens } from "./schema";

/**
 * The stylesheet link the design system prescribes (its README, "Type: four voices and a stencil").
 * It cannot be derived from tokens.json, which names the families but not their weights; a test
 * checks that every family in tokens.json is covered by this link.
 */
export const GOOGLE_FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Big+Shoulders+Stencil+Display:wght@700;800;900&family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Noto+Serif+Display:wdth,wght@62.5..100,100..900&display=swap";

/** Light is the base (`:root`) and the fallback; dark is layered on top. */
export const THEME_IDS = ["light", "dark"] as const;
export type ThemeId = (typeof THEME_IDS)[number];
export type PerTheme = Record<ThemeId, string>;

/** Families whose type styles get tabular figures (tokens.json asks for it in the usage text). */
const TABULAR_FAMILIES = new Set(["mono", "stencil"]);

export interface ColorEntry {
  name: string;
  /** Concrete value per theme; an alias carries the value of the token it points at. */
  values: PerTheme;
  /** Name of the token this one is an alias of, when it is one. */
  alias?: string;
}

export interface PlainEntry {
  name: string;
  value: string;
}

export interface ThemedEntry {
  name: string;
  values: PerTheme;
}

export interface TypeStyleEntry {
  name: string;
  family: string;
  fontSize: string;
  lineHeight: string;
  fontWeight: number;
  letterSpacing?: string;
}

export interface TypeGroupEntry {
  name: string;
  family: string;
  styles: TypeStyleEntry[];
}

export interface Model {
  themes: { id: ThemeId; name: string }[];
  fonts: PlainEntry[];
  spacing: PlainEntry[];
  radius: PlainEntry[];
  motion: PlainEntry[];
  stroke: PlainEntry[];
  colors: ColorEntry[];
  shadows: ThemedEntry[];
  typeGroups: TypeGroupEntry[];
}

/** Relative path inside dist/ to file contents. */
export type Outputs = Record<string, string>;

const isThemeId = (id: string): id is ThemeId => (THEME_IDS as readonly string[]).includes(id);

function resolveColors(tokens: Tokens["color"]["tokens"]): ColorEntry[] {
  const byName = new Map(tokens.map((token) => [token.name, token]));
  const cache = new Map<string, PerTheme>();

  const resolve = (name: string, trail: string[]): PerTheme => {
    if (trail.includes(name)) {
      throw new Error(`color aliases form a cycle: ${[...trail, name].join(" -> ")}`);
    }
    const cached = cache.get(name);
    if (cached) return cached;
    const token = byName.get(name);
    if (!token) {
      const from = trail[trail.length - 1] ?? name;
      throw new Error(`color token "${from}" is an alias of "{${name}}", which is not a color token`);
    }
    let values: PerTheme;
    if (typeof token.value === "string") {
      const target = ALIAS.exec(token.value)?.[1];
      if (!target) throw new Error(`color token "${name}": "${token.value}" is not a valid alias`);
      values = resolve(target, [...trail, name]);
    } else {
      values = { light: token.value.light, dark: token.value.dark };
    }
    cache.set(name, values);
    return values;
  };

  return tokens.map((token) => {
    const entry: ColorEntry = { name: token.name, values: resolve(token.name, []) };
    if (typeof token.value === "string") {
      const target = ALIAS.exec(token.value)?.[1];
      if (target) entry.alias = target;
    }
    return entry;
  });
}

/** Turn a validated tokens.json into the model the renderers work from, checking cross references. */
export function buildModel(tokens: Tokens): Model {
  const ids = tokens.color.themes.map((theme) => theme.id);
  if (ids.length !== THEME_IDS.length || ids.some((id, index) => id !== THEME_IDS[index])) {
    throw new Error(
      `color.themes must be exactly [${THEME_IDS.join(", ")}] in that order, got [${ids.join(", ")}]: ` +
        "the generated CSS has a light base and one dark override",
    );
  }
  const themes = tokens.color.themes.flatMap((theme) =>
    isThemeId(theme.id) ? [{ id: theme.id, name: theme.name }] : [],
  );

  const fonts = Object.entries(tokens.type.families).map(([family, value]) => ({
    name: `font-${family}`,
    value,
  }));
  const plain = (list: { name: string; value: string }[]): PlainEntry[] =>
    list.map(({ name, value }) => ({ name, value }));

  const model: Model = {
    themes,
    fonts,
    spacing: plain(tokens.spacing.tokens),
    radius: plain(tokens.radius.tokens),
    motion: plain(tokens.motion.tokens),
    stroke: plain(tokens.stroke.tokens),
    colors: resolveColors(tokens.color.tokens),
    shadows: tokens.shadow.tokens.map(({ name, value }) => ({
      name,
      values: { light: value.light, dark: value.dark },
    })),
    typeGroups: tokens.type.groups.map((group) => ({
      name: group.name,
      family: group.family,
      styles: group.styles.map((style) => {
        const entry: TypeStyleEntry = {
          name: style.name,
          family: group.family,
          fontSize: style.fontSize,
          lineHeight: style.lineHeight,
          fontWeight: style.fontWeight,
        };
        if (style.letterSpacing !== undefined) entry.letterSpacing = style.letterSpacing;
        return entry;
      }),
    })),
  };

  // Every custom property shares one namespace, and every type style becomes a class.
  const seen = new Map<string, string>();
  const claim = (kind: string, list: { name: string }[]) => {
    for (const { name } of list) {
      const previous = seen.get(name);
      if (previous) throw new Error(`"${name}" is defined twice: as ${previous} and as ${kind}`);
      seen.set(name, kind);
    }
  };
  claim("a font family", model.fonts);
  claim("a spacing token", model.spacing);
  claim("a radius token", model.radius);
  claim("a motion token", model.motion);
  claim("a stroke token", model.stroke);
  claim("a color token", model.colors);
  claim("a shadow token", model.shadows);

  const styleNames = new Set<string>();
  for (const group of model.typeGroups) {
    if (!(group.family in tokens.type.families)) {
      throw new Error(`type group "${group.name}" uses the family "${group.family}", which type.families does not define`);
    }
    for (const style of group.styles) {
      if (styleNames.has(style.name)) throw new Error(`type style "${style.name}" is defined twice`);
      styleNames.add(style.name);
    }
  }
  return model;
}

// ---------------------------------------------------------------------------------------------
// tokens.css

const decl = (name: string, value: string) => `  --${name}: ${value};`;

/** Color and shadow declarations for one theme. Aliases stay `var()` references in every block. */
function themedDeclarations(model: Model, theme: ThemeId): string[] {
  const lines = ["  /* color */"];
  for (const color of model.colors) {
    lines.push(decl(color.name, color.alias ? `var(--${color.alias})` : color.values[theme]));
  }
  lines.push("", "  /* shadow */");
  for (const shadow of model.shadows) lines.push(decl(shadow.name, shadow.values[theme]));
  return lines;
}

function typeClasses(model: Model): string[] {
  const lines: string[] = [];
  for (const group of model.typeGroups) {
    lines.push(`/* ${group.name} */`);
    for (const style of group.styles) {
      lines.push(
        `.${style.name} {`,
        `  font-family: var(--font-${style.family});`,
        `  font-size: ${style.fontSize};`,
        `  line-height: ${style.lineHeight};`,
        `  font-weight: ${style.fontWeight};`,
      );
      if (style.letterSpacing !== undefined) lines.push(`  letter-spacing: ${style.letterSpacing};`);
      if (TABULAR_FAMILIES.has(style.family)) lines.push("  font-variant-numeric: tabular-nums;");
      lines.push("}");
    }
    lines.push("");
  }
  lines.pop();
  return lines;
}

export function renderCss(model: Model): string {
  const dark = themedDeclarations(model, "dark");
  const group = (title: string, list: PlainEntry[]) => ["", `  /* ${title} */`, ...list.map((e) => decl(e.name, e.value))];
  const lines = [
    "/* Pattern Blue design tokens.",
    "   Generated by packages/design-tokens/scripts/build.ts from src/tokens.json. Do not edit:",
    "   change the design-system artifact, sync src/, then run `make design-tokens`.",
    "   Load order: the Google Fonts link (fonts.html), this file, then components.css. */",
    "",
    "/* Light is the base and the fallback. Type, spacing, radius, motion and stroke do not change with the theme. */",
    ":root {",
    "  color-scheme: light;",
    ...group("font families", model.fonts),
    ...group("spacing", model.spacing),
    ...group("radius", model.radius),
    ...group("motion", model.motion),
    ...group("stroke", model.stroke),
    "",
    ...themedDeclarations(model, "light"),
    "}",
    "",
    "/* Dark follows the system preference unless the page pins light with data-theme=\"light\" on <html>. */",
    "@media (prefers-color-scheme: dark) {",
    "  :root:not([data-theme=\"light\"]) {",
    "    color-scheme: dark;",
    ...dark.map((line) => (line ? `  ${line}` : line)),
    "  }",
    "}",
    "",
    "/* Dark pinned with data-theme=\"dark\" on <html>. Same declarations as the block above. */",
    ":root[data-theme=\"dark\"] {",
    "  color-scheme: dark;",
    ...dark,
    "}",
    "",
    "/* Type styles as classes. Uppercase and font-stretch are added by components.css, which the token",
    "   grammar cannot express. */",
    ...typeClasses(model),
  ];
  return `${lines.join("\n")}\n`;
}

// ---------------------------------------------------------------------------------------------
// tokens.ts

const q = (value: string | number) => JSON.stringify(value);

function tsMap(entries: [string, string][], indent = "  "): string[] {
  return entries.map(([key, value]) => `${indent}${q(key)}: ${value},`);
}

const themedLiteral = (values: PerTheme) => `{ light: ${q(values.light)}, dark: ${q(values.dark)} }`;

function typeStyleLiteral(style: TypeStyleEntry): string {
  const parts = [
    `family: ${q(style.family)}`,
    `fontSize: ${q(style.fontSize)}`,
    `lineHeight: ${q(style.lineHeight)}`,
    `fontWeight: ${style.fontWeight}`,
  ];
  if (style.letterSpacing !== undefined) parts.push(`letterSpacing: ${q(style.letterSpacing)}`);
  return `{ ${parts.join(", ")} }`;
}

export function renderTs(model: Model): string {
  const plainMap = (name: string, list: PlainEntry[], doc: string) => [
    "",
    `/** ${doc} */`,
    `export const ${name} = {`,
    ...tsMap(list.map((e) => [e.name, q(e.value)])),
    "} as const;",
    `export type ${name[0]?.toUpperCase()}${name.slice(1)}TokenName = keyof typeof ${name};`,
  ];
  const aliases = model.colors.flatMap((c): [string, string][] => (c.alias ? [[c.name, q(c.alias)]] : []));

  const lines = [
    "// Pattern Blue design tokens for TypeScript.",
    "// Generated by packages/design-tokens/scripts/build.ts from src/tokens.json. Do not edit:",
    "// change the design-system artifact, sync src/, then run `make design-tokens`.",
    "",
    "/** Themes in the order tokens.json lists them: the first is the base and the fallback. */",
    "export const themes = [",
    ...model.themes.map((t) => `  { id: ${q(t.id)}, name: ${q(t.name)} },`),
    "] as const;",
    "",
    'export type ThemeId = (typeof themes)[number]["id"];',
    "",
    `export const defaultTheme: ThemeId = ${q(model.themes[0]?.id ?? "light")};`,
    "",
    "/** Attribute on <html> that pins a theme. Without it the page follows the system preference. */",
    'export const themeAttribute = "data-theme";',
    "",
    "export function isThemeId(value: unknown): value is ThemeId {",
    "  return themes.some((theme) => theme.id === value);",
    "}",
    "",
    "/** Value per theme, aliases resolved. The CSS variable of the same name follows the active theme. */",
    "export const colors = {",
    ...tsMap(model.colors.map((c) => [c.name, themedLiteral(c.values)])),
    "} as const;",
    "export type ColorTokenName = keyof typeof colors;",
    "",
    "/** Alias tokens and the token each one points at. The CSS emits `var(--target)` for them. */",
    "export const colorAliases = {",
    ...tsMap(aliases),
    "} as const satisfies Partial<Record<ColorTokenName, ColorTokenName>>;",
    "",
    "/** Shadows per theme. */",
    "export const shadows = {",
    ...tsMap(model.shadows.map((s) => [s.name, themedLiteral(s.values)])),
    "} as const;",
    "export type ShadowTokenName = keyof typeof shadows;",
    ...plainMap("spacing", model.spacing, "Spacing scale: 4px base, 8px rhythm."),
    ...plainMap("radius", model.radius, "Radii and chamfer sizes."),
    ...plainMap("motion", model.motion, "Durations and the stepped easing."),
    ...plainMap("stroke", model.stroke, "Line weights and tick length."),
    "",
    "/** Font stacks, by family name. The CSS variable is `--font-<family>`. */",
    "export const fontFamilies = {",
    ...tsMap(model.fonts.map((f) => [f.name.replace(/^font-/, ""), q(f.value)])),
    "} as const;",
    "export type FontFamilyName = keyof typeof fontFamilies;",
    "",
    "/** Type styles. Each is also a CSS class of the same name. */",
    "export const typeStyles = {",
    ...tsMap(model.typeGroups.flatMap((g) => g.styles.map((s): [string, string] => [s.name, typeStyleLiteral(s)]))),
    "} as const;",
    "export type TypeStyleName = keyof typeof typeStyles;",
    "",
    "/** Every name that exists as a CSS custom property. */",
    "export type TokenName =",
    "  | ColorTokenName",
    "  | ShadowTokenName",
    "  | SpacingTokenName",
    "  | RadiusTokenName",
    "  | MotionTokenName",
    "  | StrokeTokenName",
    "  | `font-${FontFamilyName}`;",
    "",
    "export type CssVar<Name extends TokenName = TokenName> = `var(--${Name})`;",
    "",
    "/** `cssVar(\"violet\")` is `\"var(--violet)\"`: for inline styles that must follow the theme. */",
    "export function cssVar<Name extends TokenName>(name: Name): CssVar<Name> {",
    "  return `var(--${name})`;",
    "}",
    "",
    "/** Stylesheet that loads the font families. Also in fonts.html. */",
    `export const googleFontsHref = ${q(GOOGLE_FONTS_HREF)};`,
  ];
  return `${lines.join("\n")}\n`;
}

// ---------------------------------------------------------------------------------------------
// fonts.html

export function renderFontsHtml(): string {
  return [
    "<!-- Generated by packages/design-tokens/scripts/build.ts. Do not edit.",
    "     Paste into the <head> of the app's index.html, before the stylesheet that imports the tokens. -->",
    `<link rel="stylesheet" href="${GOOGLE_FONTS_HREF}">`,
    "",
  ].join("\n");
}

// ---------------------------------------------------------------------------------------------

/** Everything build.ts writes into dist/, keyed by file name. */
export function generate(input: unknown): Outputs {
  const model = buildModel(parseTokens(input));
  return {
    "fonts.html": renderFontsHtml(),
    "tokens.css": renderCss(model),
    "tokens.ts": renderTs(model),
  };
}
