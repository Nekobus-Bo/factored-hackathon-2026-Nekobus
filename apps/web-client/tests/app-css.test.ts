// The layout glue of the chat header (app.css): the cuts that keep the close button inside the panel. There is no
// browser here, so the rules themselves are pinned.

import { describe, expect, test } from "bun:test";
import { join } from "node:path";
import { SIDE_PANEL_QUERY } from "../src/app/hooks";

const css = (await Bun.file(join(import.meta.dir, "../src/app/app.css")).text()).replace(/\/\*[\s\S]*?\*\//g, "");

describe("the chat header", () => {
  test("the chat panel is the container, so the cut follows the panel and not the window", () => {
    expect(css).toContain(".pb-dock .pb-chat { container: pb-chat / inline-size; }");
    expect(css).not.toMatch(/@media \(max-width: 391px\)/);
  });

  test("a panel narrower than its 520px moves the chip to a row of its own and lets the header wrap, so the close button stays in", () => {
    const block = /@container pb-chat \(max-width: 519px\) \{([^@]*?)\n\}/.exec(css)?.[1] ?? "";
    expect(block).toContain(".pb-dock .pb-chat__head { flex-wrap: wrap;");
    expect(block).toContain(".pb-dock .chat-head-chip { order: 1; flex: 0 0 100%; margin: 0; }");
    expect(block).toContain(".pb-dock .chat-head-chip ~ .pb-demo-toggle { margin-left: auto; }");
  });

  test("the text button is a 44px target, and keeps its icon alone on a very narrow phone", () => {
    expect(css).toContain(".pb-chat__head .pb-demo-toggle:not(.pb-btn--icon) { min-height: 44px; }");
    expect(css).toMatch(/@media \(max-width: 340px\) \{\s*\.pb-demo-toggle:not\(\.pb-btn--icon\) \{ width: 44px;/);
    expect(css).toContain(".pb-demo-toggle__text { display: none; }");
  });

  test("the chip can shrink inside its row instead of pushing the close button out", () => {
    expect(css).toMatch(/\.chat-head-chip \{[^}]*min-width: 0;[^}]*overflow: hidden;/);
    expect(css).toMatch(/\.pb-chat__head \.pb-demo-toggle \{ flex: none;/);
  });
});

const localCss = (await Bun.file(join(import.meta.dir, "../../../packages/design-tokens/local.css")).text()).replace(/\/\*[\s\S]*?\*\//g, "");

/** Every `@media` block of local.css as its query and its body, braces matched. */
function mediaBlocks(source: string): { query: string; body: string }[] {
  const blocks: { query: string; body: string }[] = [];
  for (const match of source.matchAll(/@media ([^{]+)\{/g)) {
    let depth = 1;
    let end = match.index! + match[0].length;
    while (depth > 0 && end < source.length) {
      const char = source[end++];
      if (char === "{") depth++;
      else if (char === "}") depth--;
    }
    blocks.push({ query: match[1]!.trim(), body: source.slice(match.index! + match[0].length, end - 1) });
  }
  return blocks;
}

describe("the one definition of 'no room' for the demo panel beside the chat", () => {
  /** The queries the stylesheet puts a rule under, in the order they appear. */
  const queriesOf = (rule: string) => mediaBlocks(localCss).filter((block) => block.body.includes(rule)).map((block) => block.query);

  test("the full-screen chat and the hidden aside are under the same query: narrower than 920px or shorter than 500px", () => {
    expect(queriesOf(".pb-dock__panel { position: fixed")).toEqual(["(max-width: 919.98px), (max-height: 499.98px)"]);
    expect(queriesOf(".pb-dock__side { display: none; }")).toEqual(["(max-width: 919.98px), (max-height: 499.98px)"]);
  });

  test("the script's query is the complement of the stylesheet's, also at fractional sizes: the CSS bounds are the pixel before the script's, minus a hundredth", () => {
    const css = queriesOf(".pb-dock__panel { position: fixed")[0]!;
    const width = Number(/max-width: ([\d.]+)px/.exec(css)![1]);
    const height = Number(/max-height: ([\d.]+)px/.exec(css)![1]);
    expect(SIDE_PANEL_QUERY).toBe(`(min-width: ${Math.ceil(width)}px) and (min-height: ${Math.ceil(height)}px)`);
    // what each query says of a window (matchMedia's rules for min- and max- on a length)
    const cssHides = (w: number, h: number) => w <= width || h <= height;
    const scriptSees = (w: number, h: number) => w >= Math.ceil(width) && h >= Math.ceil(height);
    // a fractional size (a zoomed or scaled window) is on one side or the other: 919.5 is under 920 and the stylesheet hides the panel
    for (const [w, h] of [[919.5, 800], [800, 499.5], [919.97, 499.97], [920, 500], [920.5, 500.5], [919, 500], [920, 499]] as const) {
      expect(scriptSees(w, h), `${w}x${h}`).toBe(!cssHides(w, h));
    }
    // the only sizes that fall on neither side are the hundredth between 919.98 and 920 (or 499.98 and 500), which no device reports
    expect(scriptSees(919.99, 800) || cssHides(919.99, 800)).toBe(false);
  });
});
