// The layout glue of the chat header (app.css): the cuts that keep the close button inside the panel. There is no
// browser here, so the rules themselves are pinned.

import { describe, expect, test } from "bun:test";
import { join } from "node:path";

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
