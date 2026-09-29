import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { findDrift, generateFromDisk } from "../scripts/build";
import { buildModel, generate, GOOGLE_FONTS_HREF } from "../scripts/generate";
import { parseTokens } from "../scripts/schema";
import * as ts from "../dist/tokens";
import {
  PACKAGE_ROOT,
  readText,
  readTokens,
  readTokensJson,
  themeBlocks,
  undefinedVariables,
  unprefixedClasses,
  variableNames,
} from "./helpers";

const tokens = await readTokens();
const tokensCss = await readText("dist/tokens.css");
const componentsCss = await readText("src/components.css");
const blocks = themeBlocks(tokensCss);

const colorNames = tokens.color.tokens.map((token) => token.name);
const shadowNames = tokens.shadow.tokens.map((token) => token.name);
const themedNames = [...colorNames, ...shadowNames];

describe("components.css only reads variables that exist", () => {
  const defined = new Set(variableNames(blocks.light));

  test("every var(--x) is a token or is declared by the stylesheet itself", () => {
    expect(undefinedVariables(componentsCss, defined)).toEqual([]);
  });

  test("the check does catch a missing variable", () => {
    const css = `${componentsCss}\n.pb-broken { color: var(--not-a-token); background: var(--surface-000); }`;
    expect(undefinedVariables(css, defined)).toEqual(["not-a-token"]);
  });

  test("the tokens the stylesheet relies on are really read (the check is not vacuous)", () => {
    const used = new Set([...componentsCss.matchAll(/var\(--([a-z0-9-]+)/g)].map((match) => match[1]));
    for (const name of ["surface-000", "violet", "space-4", "cut-md", "font-display", "shadow-card", "motion-step", "ease-step"]) {
      expect(used.has(name)).toBe(true);
      expect(defined.has(name)).toBe(true);
    }
  });

  test("every non-pb class it uses is a type style generated into tokens.css", () => {
    const styleNames = tokens.type.groups.flatMap((group) => group.styles.map((style) => style.name));
    const classes = unprefixedClasses(componentsCss);
    expect(classes.length).toBeGreaterThan(0);
    for (const name of classes) expect(styleNames).toContain(name);
    for (const name of styleNames) expect(tokensCss).toContain(`.${name} {`);
  });
});

describe("themes", () => {
  test("the light block defines every token and the color scheme", () => {
    expect(blocks.light.declarations.get("color-scheme")).toBe("light");
    const defined = new Set(variableNames(blocks.light));
    const expected = [
      ...Object.keys(tokens.type.families).map((family) => `font-${family}`),
      ...tokens.spacing.tokens.map((token) => token.name),
      ...tokens.radius.tokens.map((token) => token.name),
      ...tokens.motion.tokens.map((token) => token.name),
      ...tokens.stroke.tokens.map((token) => token.name),
      ...themedNames,
    ];
    expect([...defined].sort()).toEqual([...expected].sort());
  });

  test("both dark blocks define the same variables as the themed part of the light block", () => {
    for (const dark of [blocks.darkSystem, blocks.darkPinned]) {
      expect(dark.declarations.get("color-scheme")).toBe("dark");
      expect(variableNames(dark).sort()).toEqual([...themedNames].sort());
    }
  });

  test("the two dark blocks are declaration for declaration identical", () => {
    expect([...blocks.darkSystem.declarations]).toEqual([...blocks.darkPinned.declarations]);
  });

  test("theme-independent tokens are not redeclared in dark", () => {
    const themed = new Set(themedNames);
    for (const name of variableNames(blocks.darkPinned)) expect(themed.has(name)).toBe(true);
  });

  test("concrete values match tokens.json in each theme", () => {
    for (const token of tokens.color.tokens) {
      if (typeof token.value === "string") continue;
      expect(blocks.light.declarations.get(`--${token.name}`)).toBe(token.value.light);
      expect(blocks.darkSystem.declarations.get(`--${token.name}`)).toBe(token.value.dark);
      expect(blocks.darkPinned.declarations.get(`--${token.name}`)).toBe(token.value.dark);
    }
    for (const token of tokens.shadow.tokens) {
      expect(blocks.light.declarations.get(`--${token.name}`)).toBe(token.value.light);
      expect(blocks.darkPinned.declarations.get(`--${token.name}`)).toBe(token.value.dark);
    }
  });

  test("the system dark block is skipped when the page pins light", () => {
    expect(tokensCss).toContain('@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {');
  });

  test("the TypeScript themes list matches tokens.json", () => {
    expect<string[]>(ts.themes.map((theme) => theme.id)).toEqual(tokens.color.themes.map((theme) => theme.id));
    expect(ts.defaultTheme).toBe("light");
    expect(ts.isThemeId("dark")).toBe(true);
    expect(ts.isThemeId("sepia")).toBe(false);
    expect(ts.themeAttribute).toBe("data-theme");
  });
});

describe("aliases", () => {
  const aliases = tokens.color.tokens.flatMap((token) =>
    typeof token.value === "string" ? [{ name: token.name, target: token.value.slice(1, -1) }] : [],
  );

  test("there are aliases to test", () => {
    expect(aliases.length).toBeGreaterThan(10);
  });

  test("each is emitted as var() of an existing token, in every theme block", () => {
    for (const { name, target } of aliases) {
      expect(colorNames).toContain(target);
      for (const block of [blocks.light, blocks.darkSystem, blocks.darkPinned]) {
        expect(block.declarations.get(`--${name}`)).toBe(`var(--${target})`);
      }
    }
  });

  test("the TypeScript export resolves each alias to its target's values", () => {
    for (const { name, target } of aliases) {
      expect(ts.colors[name as ts.ColorTokenName]).toEqual(ts.colors[target as ts.ColorTokenName]);
      expect<string>(ts.colorAliases[name as keyof typeof ts.colorAliases]).toBe(target);
    }
  });

  test("an alias of an alias resolves to the final value", async () => {
    const json = await readTokensJson();
    json.color.tokens.push({ name: "brand", value: "{wordmark}" });
    const model = buildModel(parseTokens(json));
    const brand = model.colors.find((color) => color.name === "brand");
    const pattern = model.colors.find((color) => color.name === "pattern");
    expect(brand?.values).toEqual(pattern?.values);
  });

  test("a dangling alias, a cycle and a duplicate name stop the build", async () => {
    const dangling = await readTokensJson();
    dangling.color.tokens.push({ name: "brand", value: "{nope}" });
    expect(() => generate(dangling)).toThrow(/"brand" is an alias of "\{nope\}"/);

    const cycle = await readTokensJson();
    cycle.color.tokens.push({ name: "a", value: "{b}" }, { name: "b", value: "{a}" });
    expect(() => generate(cycle)).toThrow(/cycle: a -> b -> a/);

    const duplicate = await readTokensJson();
    duplicate.spacing.tokens.push({ name: "violet", value: "1px" });
    expect(() => generate(duplicate)).toThrow(/"violet" is defined twice/);
  });
});

describe("input validation", () => {
  test("the committed tokens.json has the expected structure", () => {
    expect(() => parseTokens(JSON.parse(JSON.stringify(tokens)))).not.toThrow();
  });

  test("a family this build does not know is an error, not silently dropped", async () => {
    const json = await readTokensJson();
    json.zindex = { tokens: [{ name: "z-modal", value: "10" }] };
    expect(() => generate(json)).toThrow(/does not match the expected structure/);
  });

  test("a token missing its dark value is an error that names the token", async () => {
    const json = await readTokensJson();
    delete json.color.tokens[0].value.dark;
    expect(() => generate(json)).toThrow(/color[\s\S]*tokens[\s\S]*0[\s\S]*value/);
  });

  test("a value that would end the declaration or the block is rejected", async () => {
    const json = await readTokensJson();
    json.spacing.tokens[0].value = "4px; } body { display: none";
    expect(() => generate(json)).toThrow(/plain CSS value/);
  });

  test("themes other than light then dark are rejected", async () => {
    const json = await readTokensJson();
    json.color.themes.reverse();
    expect(() => generate(json)).toThrow(/color\.themes must be exactly \[light, dark\]/);
  });

  test("a type group with an unknown family is rejected", async () => {
    const json = await readTokensJson();
    json.type.groups[0].family = "serif";
    expect(() => generate(json)).toThrow(/family "serif"/);
  });
});

describe("determinism and drift", () => {
  test("the same input gives the same bytes", async () => {
    const json = await readTokensJson();
    expect(generate(json)).toEqual(generate(structuredClone(json)));
    expect(Object.keys(generate(json))).toEqual(["fonts.html", "tokens.css", "tokens.ts"]);
  });

  test("nothing volatile is written into the output", async () => {
    for (const [name, content] of Object.entries(generate(await readTokensJson()))) {
      expect(content, name).not.toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(content, name).not.toContain("\r");
      expect(content.endsWith("\n"), name).toBe(true);
    }
  });

  test("the committed dist/ is what the build writes", async () => {
    expect(await findDrift(await generateFromDisk())).toEqual([]);
  });

  test("drift is reported for a stale file and for a file that is not generated any more", async () => {
    const outputs = await generateFromDisk();
    const stale = { ...outputs, "tokens.css": `${outputs["tokens.css"]}/* edited */\n` };
    expect((await findDrift(stale)).join("\n")).toMatch(/dist\/tokens\.css is out of date \(line \d+/);
    const { "fonts.html": _removed, ...fewer } = outputs;
    expect(await findDrift(fewer)).toContain("dist/fonts.html is not generated any more");
  });
});

describe("fonts", () => {
  test("the Google Fonts link covers the first font of every family", () => {
    for (const [family, stack] of Object.entries(tokens.type.families)) {
      const first = /^"([^"]+)"/.exec(stack)?.[1];
      expect(first, `first font of ${family}`).toBeDefined();
      expect(GOOGLE_FONTS_HREF, first).toContain(`family=${(first ?? "").replaceAll(" ", "+")}`);
    }
  });

  test("fonts.html and the TypeScript export carry the same link", async () => {
    expect(await readText("dist/fonts.html")).toContain(`href="${GOOGLE_FONTS_HREF}"`);
    expect(ts.googleFontsHref).toBe(GOOGLE_FONTS_HREF);
  });

  test("every family has a CSS variable and a TypeScript entry", () => {
    for (const [family, stack] of Object.entries(tokens.type.families)) {
      expect(blocks.light.declarations.get(`--font-${family}`)).toBe(stack);
      expect<string>(ts.fontFamilies[family as ts.FontFamilyName]).toBe(stack);
    }
  });
});

describe("type styles", () => {
  test("each style is a class with the values from tokens.json", () => {
    for (const group of tokens.type.groups) {
      for (const style of group.styles) {
        const block = new RegExp(`\\.${style.name} \\{([^}]*)\\}`).exec(tokensCss)?.[1] ?? "";
        expect(block, style.name).toContain(`font-family: var(--font-${group.family});`);
        expect(block, style.name).toContain(`font-size: ${style.fontSize};`);
        expect(block, style.name).toContain(`line-height: ${style.lineHeight};`);
        expect(block, style.name).toContain(`font-weight: ${style.fontWeight};`);
        if (style.letterSpacing) expect(block, style.name).toContain(`letter-spacing: ${style.letterSpacing};`);
        expect<string>(ts.typeStyles[style.name as ts.TypeStyleName].fontSize).toBe(style.fontSize);
      }
    }
  });

  test("data and stencil styles use tabular figures, the others do not", () => {
    expect(/\.mono-data \{[^}]*tabular-nums/.test(tokensCss)).toBe(true);
    expect(/\.case-id \{[^}]*tabular-nums/.test(tokensCss)).toBe(true);
    expect(/\.body \{[^}]*tabular-nums/.test(tokensCss)).toBe(false);
  });
});

const manifest = JSON.parse(await readText("package.json")) as { exports: Record<string, string> };

describe("package", () => {
  test("every export points at a file that exists", () => {
    expect(Object.keys(manifest.exports).sort()).toEqual(
      ["./components.css", "./fonts.html", "./index.css", "./tokens", "./tokens.css", "./tokens.json"],
    );
    for (const target of Object.values(manifest.exports)) expect(existsSync(join(PACKAGE_ROOT, target)), target).toBe(true);
  });

  test("index.css imports the tokens before the components", async () => {
    const index = await readText("index.css");
    const imports = [...index.matchAll(/@import "([^"]+)";/g)].map((match) => match[1]);
    expect(imports).toEqual(["./dist/tokens.css", "./src/components.css"]);
    expect(manifest.exports["./tokens.css"]).toBe("./dist/tokens.css");
    expect(manifest.exports["./components.css"]).toBe("./src/components.css");
  });

  test("bundling index.css puts the tokens before the components", async () => {
    const result = await Bun.build({ entrypoints: [join(PACKAGE_ROOT, "index.css")] });
    expect(result.success).toBe(true);
    const css = await result.outputs[0]!.text();
    const firstToken = css.indexOf("--surface-000:");
    const firstComponent = css.indexOf(".pb-btn");
    expect(firstToken).toBeGreaterThan(-1);
    expect(firstComponent).toBeGreaterThan(firstToken);
    expect(css).toContain(':root[data-theme="dark"]');
  });

  test("components.css names its source artifact and version", () => {
    expect(componentsCss.startsWith("/* Source: claude.ai Artifact")).toBe(true);
    expect(componentsCss).toContain("https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV");
    expect(componentsCss).toMatch(/version \d+-[0-9a-f]+ \(\d{4}-\d{2}-\d{2}\)/);
  });
});
