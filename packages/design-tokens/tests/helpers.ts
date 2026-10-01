import { join, resolve } from "node:path";
import { parseTokens, type Tokens } from "../scripts/schema";

export const PACKAGE_ROOT = resolve(import.meta.dir, "..");

export const readText = (relative: string): Promise<string> => Bun.file(join(PACKAGE_ROOT, relative)).text();

export async function readTokens(): Promise<Tokens> {
  return parseTokens(JSON.parse(await readText("src/tokens.json")));
}

/** The raw JSON, for tests that break it on purpose. */
export async function readTokensJson(): Promise<Record<string, any>> {
  return JSON.parse(await readText("src/tokens.json"));
}

export const stripComments = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, "");

export interface Rule {
  selector: string;
  declarations: Map<string, string>;
  /** Rules nested in an at-rule such as @media. */
  rules: Rule[];
}

/**
 * Just enough CSS parsing for the generated tokens.css: rules, one level of at-rule nesting and
 * plain declarations. It is not a general parser (no strings containing braces or semicolons).
 */
export function parseCss(css: string): Rule[] {
  const source = stripComments(css);
  const rules: Rule[] = [];
  let index = 0;
  while (index < source.length) {
    const open = source.indexOf("{", index);
    if (open === -1) break;
    const selector = source.slice(index, open).trim();
    let depth = 1;
    let cursor = open + 1;
    while (depth > 0 && cursor < source.length) {
      if (source[cursor] === "{") depth++;
      else if (source[cursor] === "}") depth--;
      cursor++;
    }
    if (depth !== 0) throw new Error(`unbalanced braces after "${selector}"`);
    const body = source.slice(open + 1, cursor - 1);
    const rule: Rule = { selector, declarations: new Map(), rules: [] };
    if (body.includes("{")) {
      rule.rules = parseCss(body);
    } else {
      for (const part of body.split(";")) {
        const colon = part.indexOf(":");
        if (colon === -1) continue;
        rule.declarations.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim());
      }
    }
    rules.push(rule);
    index = cursor;
  }
  return rules;
}

export interface ThemeBlocks {
  light: Rule;
  darkSystem: Rule;
  darkPinned: Rule;
}

/** The three blocks that carry theme values in tokens.css. Throws if one is missing. */
export function themeBlocks(tokensCss: string): ThemeBlocks {
  const rules = parseCss(tokensCss);
  const light = rules.find((rule) => rule.selector === ":root");
  const media = rules.find((rule) => rule.selector === "@media (prefers-color-scheme: dark)");
  const darkSystem = media?.rules.find((rule) => rule.selector === ':root:not([data-theme="light"])');
  const darkPinned = rules.find((rule) => rule.selector === ':root[data-theme="dark"]');
  if (!light || !darkSystem || !darkPinned) {
    throw new Error("tokens.css must have :root, a prefers-color-scheme dark block and :root[data-theme=\"dark\"]");
  }
  return { light, darkSystem, darkPinned };
}

/** Custom property names (without the leading dashes) declared in a rule. */
export const variableNames = (rule: Rule): string[] =>
  [...rule.declarations.keys()].filter((name) => name.startsWith("--")).map((name) => name.slice(2));

/**
 * Custom properties a component stylesheet reads with var() but neither defines itself nor gets from
 * the tokens. A component-local property, like --tone or --c-tl, is declared inside components.css.
 */
export function undefinedVariables(componentsCss: string, tokenVariables: ReadonlySet<string>): string[] {
  // Data URIs carry no variables, and comments may mention them.
  const css = stripComments(componentsCss).replace(/url\((?:"[^"]*"|'[^']*'|[^)]*)\)/g, "url()");
  const used = new Set([...css.matchAll(/var\(\s*--([a-z0-9-]+)/gi)].map((match) => match[1] as string));
  const declaredHere = new Set([...css.matchAll(/(?<![\w-])--([a-z0-9-]+)\s*:/gi)].map((match) => match[1] as string));
  return [...used].filter((name) => !tokenVariables.has(name) && !declaredHere.has(name)).sort();
}

/** Class names a component stylesheet uses that are not pb-prefixed: they must come from tokens.css. */
export function unprefixedClasses(componentsCss: string): string[] {
  const css = stripComments(componentsCss)
    .replace(/url\((?:"[^"]*"|'[^']*'|[^)]*)\)/g, "url()")
    .replace(/"[^"]*"|'[^']*'/g, '""');
  const names = new Set([...css.matchAll(/\.([a-z][a-z0-9_-]*)/gi)].map((match) => match[1] as string));
  return [...names].filter((name) => !name.startsWith("pb-")).sort();
}
