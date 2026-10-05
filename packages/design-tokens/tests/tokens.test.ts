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
  stripComments,
  themeBlocks,
  undefinedVariables,
  unprefixedClasses,
  variableNames,
} from "./helpers";

const tokens = await readTokens();
const tokensCss = await readText("dist/tokens.css");
const componentsCss = await readText("src/components.css");
const localCss = await readText("local.css");
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

describe("local.css", () => {
  const defined = new Set(variableNames(blocks.light));

  test("reads only tokens and the variables the component stylesheets declare", () => {
    expect(undefinedVariables(`${componentsCss}\n${localCss}`, defined)).toEqual([]);
  });

  test("styles only pb- classes", () => {
    expect(unprefixedClasses(localCss)).toEqual([]);
  });

  test("says it is not in the design-system artifact yet", () => {
    expect(localCss).toContain("not in the design-system artifact yet");
  });
});

describe("local.css: detective mode (ADR-0019): a tab of the demo panel, and in place of the chat on a narrow window", () => {
  /** The declarations of the first rule whose selector is exactly `selector`, comments removed. */
  const declarationsOf = (selector: string, css = localCss): string | undefined =>
    stripComments(css)
      .split("}")
      .map((chunk) => chunk.split("{"))
      .find(([sel]) => sel?.trim() === selector)?.[1]
      ?.trim();

  test("case 13: the panel is 520px wide, or the window minus 32px, and a phone gets the whole screen", () => {
    expect(declarationsOf(".pb-dock__panel")).toBe("bottom: 84px; width: min(520px, calc(100% - 32px));");
    expect(localCss).not.toContain("420px");
    expect(localCss).toMatch(/@media \(max-width: 480px\) \{\s*\.pb-dock__panel \{ position: fixed; inset: 0;/);
  });

  test("nothing of the earlier detective panel, its strip, its own pane switch or the old magnifier is left: the panel beside the chat is the shared demo panel", () => {
    for (const gone of ["pb-dock__trace", "pb-trace-strip", "pb-trace__total ", "pb-trace__turn", "pb-trace__back", "pb-ico--search", "data-pane"]) {
      expect(localCss, gone).not.toContain(gone);
    }
    expect(localCss).toContain(".pb-ico--detective {");
  });

  test("the log and the composer can be hidden while they stay mounted: their display must not beat the attribute", () => {
    expect(declarationsOf(".pb-chat__body[hidden], .pb-chat__composer[hidden]")).toBe("display: none;");
  });

  test("case 10: two tones only, pattern blue for the LLM and the muted ink for every other step", () => {
    expect(declarationsOf(".pb-trace--inpanel [data-kind]")).toBe("--pb-trace-k: var(--ink-muted);");
    expect(declarationsOf('.pb-trace--inpanel [data-kind="llm_call"]')).toBe("--pb-trace-k: var(--pattern);");
    expect([...localCss.matchAll(/--pb-trace-k: var\(--([a-z-]+)\)/g)].map((match) => match[1]).sort()).toEqual(["ink-muted", "pattern"]);
    // the messages of an LLM call keep to the same two: no green or orange (they keep their meaning), no red
    const roles = [...stripComments(localCss).matchAll(/\.pb-trace-msg\[data-role[^{]*\{([^}]*)\}/g)].map((match) => match[1]!);
    expect(roles.length).toBeGreaterThan(0);
    for (const declarations of roles) expect(declarations).not.toMatch(/--(sync|alert|crimson|violet|hazard)/);
    expect(localCss).not.toMatch(/\.pb-trace[^{]*\{[^}]*var\(--(sync|alert|crimson)/);
  });

  test("the view has no leftovers: nothing of a frame of its own, and the tabs' rule is not overridden by a dead one", () => {
    expect(declarationsOf(".pb-trace")).toBe("display: grid; grid-template-rows: auto minmax(0, 1fr); color: var(--ink);");
    expect(declarationsOf(".pb-trace--inpanel")).toBe("flex: 1; min-height: 0;");
    expect(declarationsOf(".pb-trace__views")).toBeUndefined();
  });

  test("case 11: bars are quantized to hexagon cells only where round() exists, a bar is at least one cell, and the fallback is a smooth bar", () => {
    const supports = localCss.slice(localCss.indexOf("@supports (width: round("));
    expect(supports.startsWith("@supports (width: round(nearest, 50%, 10px))")).toBe(true);
    expect(supports).toContain("width: min(round(nearest, var(--w), 10px), calc(100% - var(--l))); min-width: 10px;");
    expect(supports).toContain("mask: var(--pb-hexcell) 0 50% / 10px 10px repeat-x");
    // outside @supports the track has no mask, so the edge of a bar never cuts a cell
    const outside = localCss.slice(0, localCss.indexOf("@supports (width: round("));
    expect(outside).not.toContain("repeat-x");
  });

  test("the bars: the track is a whole number of cells, a bar that starts at the end keeps a cell inside it, and the summary tiles the turn on cell boundaries", () => {
    const supports = stripComments(localCss.slice(localCss.indexOf("@supports (width: round(")));
    // the last cell of the track is never cut
    expect(supports).toMatch(/\.pb-trace--inpanel \.pb-trace-spark,\s*\.pb-trace--inpanel \.pb-trace-wf__track \{ width: round\(down, 100%, 10px\);/);
    // a timeline bar: left on a cell and at most one cell short of the end, wide to the end at most
    expect(supports).toContain("--l: min(round(down, var(--x), 10px), calc(100% - 10px)); left: var(--l);");
    // the summary: each segment runs from one cell boundary to the next, so no sum exceeds the bar and none is cut
    expect(supports).toContain("left: round(down, var(--x), 10px); width: calc(round(down, var(--x2), 10px) - round(down, var(--x), 10px)); min-width: 0;");
    // the fallback (no round()): smooth bars that start no later than their minimum width before the end
    expect(declarationsOf(".pb-trace-spark > span, .pb-trace-wf__bar")).toContain("left: min(var(--x), calc(100% - 3px));");
    expect(declarationsOf(".pb-trace-spark > span, .pb-trace-wf__bar")).toContain("position: absolute;");
    expect(declarationsOf(".pb-trace-spark, .pb-trace-wf__track")).toContain("position: relative;");
    expect(declarationsOf(".pb-trace-spark, .pb-trace-wf__track")).toContain("overflow: hidden;");
  });

  test("case 4: the stepper's buttons and the tabs and rows of the view have 44px targets", () => {
    expect(declarationsOf(".pb-trace__views .pb-tab")).toContain("min-height: 44px");
    expect(declarationsOf(".pb-trace-step")).toContain("min-height: 44px");
    expect(declarationsOf(".pb-trace-wf__row")).toContain("min-height: 44px");
  });
});

/** Base classes that local.css restyles on purpose, over the system's own rule of the same name. */
const CLASHES_THAT_OVERRIDE_THE_SYSTEM: string[] = ["pb-chat__composer", "pb-dock__panel"];

describe("local.css: the demo panel, shared by the guide and detective mode (ScriptChoice, ADR-0019)", () => {
  /** The declarations of the first rule whose selector is exactly `selector`, comments removed. */
  const declarationsOf = (selector: string): string | undefined =>
    stripComments(localCss)
      .split("}")
      .map((chunk) => chunk.split("{"))
      .find(([sel]) => sel?.trim() === selector)?.[1]
      ?.trim();

  test("case 16: below 920px the panel is not offered, with CSS alone (the header button stays for the detective view in place of the chat)", () => {
    expect(stripComments(localCss)).toMatch(/@media \(max-width: 919px\) \{\s*\.pb-dock__side \{ display: none; \}\s*\}/);
    expect(localCss).not.toContain("pb-guide-toggle");
    expect(localCss).not.toContain("pb-trace-toggle");
  });

  test("the panel sits at the left of the 520px chat and is as tall as it; it is 340px at 920px and 520px from 1100px; the attribute hides it", () => {
    const placed = declarationsOf(".pb-dock__side") ?? "";
    expect(placed).toContain("position: absolute; bottom: 84px; right: calc(48px + min(520px, 100% - 32px)); width: min(520px, calc(100% - 580px));");
    expect(placed).toContain("height: min(680px, calc(100dvh - 148px));");
    expect(declarationsOf(".pb-side[hidden]")).toBe("display: none;");
    // 100% - 580px is 340px at 920px and 520px at 1100px; the chat's own 520px plus the 48px offset leave a 12px margin
    expect(920 - 580).toBe(340);
    expect(Math.min(520, 1100 - 580)).toBe(520);
    expect(920 - (48 + 520) - (920 - 580)).toBe(12);
  });

  test("it is a chamfered card with a head, the tabs on the head's rule and a content area; the guide's parts and the options of pb-say are not redefined", () => {
    expect(declarationsOf(".pb-side")).toContain("--c-tl: var(--cut-lg); --c-br: var(--cut-lg);");
    for (const part of ["pb-side__head", "pb-side__content", "pb-guide__body", "pb-guide__title", "pb-guide__hint", "pb-guide__steps", "pb-guide__step", "pb-guide__foot"]) {
      expect(localCss, part).toContain(`.${part} {`);
    }
    expect(localCss).not.toContain("pb-guide__head");
    expect(localCss).not.toContain("pb-dock__guide");
    expect(declarationsOf(".pb-side__head .pb-tabs")).toContain("border-bottom: 0;");
    expect(declarationsOf(".pb-side__head .pb-tab")).toContain("min-height: 44px;");
    expect(localCss).toContain('.pb-side__head .pb-tab[aria-selected="true"]');
    // the base rules of the options are written once
    expect(localCss.match(/^\.pb-say__opt \{/gm)).toHaveLength(1);
    expect(localCss.match(/^\.pb-say__list > li \{/gm)).toHaveLength(1);
    expect(declarationsOf(".pb-guide__body .pb-say__list > li")).toBe("justify-self: stretch; max-width: none;");
  });

  test("the guide's track: two-figure numerals in the stencil face, a rail, the label style, a card that is not a button, no text below 14px", () => {
    expect(declarationsOf(".pb-guide__step::before")).toContain("counter(gstep, decimal-leading-zero)");
    expect(declarationsOf(".pb-guide__step::before")).toContain("var(--font-stencil)");
    expect(declarationsOf(".pb-guide__step::after")).toContain("width: 1px; background: var(--line-strong);");
    expect(declarationsOf(".pb-guide__steps")).toContain("counter-reset: gstep;");
    expect(declarationsOf(".pb-guide__label")).toContain("font: 600 12px/16px var(--font-condensed); letter-spacing: 0.14em; text-transform: uppercase;");
    const card = declarationsOf(".pb-guide__card") ?? "";
    expect(card).toContain("border: 1px solid var(--line-strong)");
    expect(card).toContain("color: var(--ink)");
    expect(card).toContain("font: 400 14px/20px");
    expect(declarationsOf(".pb-guide__sent")).toContain("font: 400 14px/20px");
    // a card is not a control: no hover, no pointer
    expect(localCss).not.toContain(".pb-guide__card:hover");
    expect(card).not.toContain("cursor");
    expect(declarationsOf('.pb-guide__step[data-state="current"] .pb-guide__label')).toBe("color: var(--violet);");
  });

  test("two calls for attention in a loop: the header button until first use, the current step's option while enabled; both in steps, neither with reduced motion", () => {
    const css = stripComments(localCss);
    const keyframes = /@keyframes pb-nudge \{([^@]*?)\n\}/.exec(css)?.[1] ?? "";
    // rest and hover face, nothing else: no glow, no shadow, no gradient
    expect(keyframes).toContain("--face: var(--surface-100);");
    expect(keyframes).toContain("--face: var(--violet-soft);");
    expect(keyframes).not.toMatch(/shadow|glow|gradient|filter/);
    // the header button: from the missing `data-seen`, not while the panel is open, in the system's step timing, ten steps long
    expect(css).toContain('.pb-demo-toggle:not([data-seen]):not([aria-pressed="true"]) { animation: pb-nudge calc(var(--motion-step) * 10) var(--ease-step) infinite; }');
    // paused under the pointer or the focus, showing the hover face
    expect(css).toMatch(/\.pb-demo-toggle:not\(\[data-seen\]\):not\(\[aria-pressed="true"\]\):hover,\s*\.pb-demo-toggle:not\(\[data-seen\]\):not\(\[aria-pressed="true"\]\):focus-visible \{ animation: none; --face: var\(--violet-soft\); \}/);
    // the option: only the current step's, only while enabled, paused under the pointer, the focus and the press
    expect(css).toContain('.pb-guide__step[data-state="current"] .pb-say__opt:not(:disabled) { animation: pb-nudge calc(var(--motion-step) * 10) var(--ease-step) infinite; }');
    expect(css).toMatch(/\.pb-say__opt:not\(:disabled\):hover,[^{]*:focus-visible,[^{]*:active \{ animation: none; \}/);
    // nothing else animates with it: the list of six and the "Sigue" cards have no such rule
    expect([...css.matchAll(/animation: pb-nudge/g)]).toHaveLength(2);
    expect(css).not.toMatch(/\.pb-guide__card[^{]*\{[^}]*animation/);
    // reduced motion turns both off
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.pb-demo-toggle, \.pb-guide__step\[data-state="current"\] \.pb-say__opt \{ animation: none; \}\s*\}/);
  });

  test("the code field: the boxes fit their own width, so the input over them covers exactly the six boxes", () => {
    const cells = declarationsOf(".pb-code-entry__cells") ?? "";
    expect(cells).toContain("width: fit-content;");
    expect(cells).toContain("max-width: 100%;");
    expect(cells).toContain("repeat(6, minmax(0, 40px))");
    expect(declarationsOf(".pb-code-entry__input")).toContain("position: absolute; inset: 0;");
    expect(localCss).not.toContain(".pb-guide__hint b");
  });

  test("fields show the focus in their edge, not in a ring: no outline on a focused field, the edge turns to the focus colour, 2px; the code box and the checkbox follow", () => {
    // the artifact's ring on a focused field is taken away (and its copy is left as it is)
    expect(declarationsOf(".pb-field:focus-within")).toBe("outline: 0; --edge: var(--focus); --bw: 2px;");
    expect(componentsCss).toMatch(/\.pb-field:focus-within \{ outline:/);
    expect(declarationsOf('.pb-field[data-invalid]:focus-within')).toBe("--edge: var(--crimson);");
    // no other rule of local.css puts an outline on something that merely has the focus inside it
    expect(stripComments(localCss)).not.toMatch(/:focus-within[^{]*\{[^}]*outline: 2px/);
    // it loads after the artifact, so it wins over the hover edge of the same weight
    expect(localCss.indexOf(".pb-field:focus-within {")).toBeGreaterThan(-1);
    // the code field: no ring around the group, the box to type in shows the focus, and only while the field has it
    expect(declarationsOf(".pb-code-entry__cells:focus-within")).toBeUndefined();
    expect(declarationsOf('.pb-code-entry__cells:focus-within .pb-code-entry__cell[data-active="true"]')).toBe("--edge: var(--focus); --bw: 2px;");
    expect(declarationsOf('.pb-code-entry__cell[data-active="true"]')).toBeUndefined();
    // the checkbox of the escalate dialog: the system's ring, for the keyboard only
    expect(declarationsOf(".pb-check input:focus-visible")).toBe("outline: 2px solid var(--focus); outline-offset: 3px;");
    expect(declarationsOf(".pb-check input:focus")).toBeUndefined();
  });

  test("a class of the header tools never reuses a name the system already has: `pb-tool` is the policy control's row, the bar's tools are `pb-navtool`", () => {
    // the system's `.pb-tool` (a grid row with a rule above it) belongs to the policy control; local.css must not define it again
    expect(componentsCss).toMatch(/^\.pb-tool \{ display: grid;/m);
    expect(stripComments(localCss)).not.toMatch(/\.pb-tool(?![-\w])/);
    expect(componentsCss).not.toMatch(/\.pb-navtool/);
    // and, more widely, a base class that local.css defines at the start of a line and the system defines too is a deliberate override of
    // the system's own rule, listed here: a new clash with another purpose has to be looked at before it is added
    const baseClasses = (css: string) => new Set([...stripComments(css).matchAll(/^\.(pb-[a-z0-9_-]+) \{/gm)].map((match) => match[1]!));
    const system = baseClasses(componentsCss);
    const clashes = [...baseClasses(localCss)].filter((name) => system.has(name)).sort();
    expect(clashes).toEqual(CLASHES_THAT_OVERRIDE_THE_SYSTEM);
  });

  test("the four steps of 'Si pierdes tu tarjeta': from the system's 960px row on, each step is a column of the row's height and its state chip sits at its foot, so the chips are on one line", () => {
    const css = stripComments(localCss);
    const block = /@media \(min-width: 960px\) \{([^@]*?)\n\}/.exec(css.slice(css.indexOf("the state chips")))?.[1] ?? /@media \(min-width: 960px\) \{\s*\.pb-flow__item \{ display: flex;[^@]*?\n\}/.exec(css)?.[0] ?? "";
    expect(block).toContain(".pb-flow__item { display: flex; flex-direction: column;");
    expect(block).toContain(".pb-flow__state { margin-top: auto;");
    // the same breakpoint as the system's row of four, so it never applies to the stacked layout
    expect(componentsCss).toMatch(/@media \(min-width: 960px\) \{\s*\.pb-flow \{ grid-template-columns: repeat\(4,/);
    // and nothing outside that media query restyles the item's layout
    expect(css.replace(block, "")).not.toMatch(/\.pb-flow__item \{ display: flex/);
  });

  test("the wordmark: capitals in the bar and the footer, \"Pattern\" in the ink and \"Blue\" in the brand blue, the type they already use", () => {
    expect(declarationsOf(".pb-nav__brand, .pb-footer__wordmark")).toBe("text-transform: uppercase;");
    expect(declarationsOf(".pb-wordmark__ink")).toBe("color: var(--ink);");
    expect(declarationsOf(".pb-wordmark__blue")).toBe("color: var(--wordmark);");
    // the type is the system's (title type, in the wordmark colour), untouched
    expect(componentsCss).toMatch(/\.pb-nav__brand \{[^}]*color: var\(--wordmark\)[^}]*font: 900 30px/);
    expect(localCss).not.toMatch(/\.pb-nav__brand \{/);
  });

  test("the header tools: a label in the label style and its radios, groups told apart by room, stacked in the folded menu", () => {
    expect(declarationsOf(".pb-navtool__label")).toBe("font: 600 12px/16px var(--font-condensed); letter-spacing: 0.14em; text-transform: uppercase; color: var(--ink-muted);");
    // groups are told apart by room only: a margin, no line
    expect(declarationsOf(".pb-navtool + .pb-navtool, .pb-navtool + .pb-menu")).toBe("margin-left: var(--space-4);");
    // the old square toggle's one-button rule is gone, and the agent's button is a button of the system, not a plain box
    expect(localCss).not.toContain("pb-theme--single");
    expect(localCss).not.toMatch(/^\.pb-menu__btn \{/m);
    expect(declarationsOf(".pb-menu__agent")).toContain("font: 500 13px/20px var(--font-mono);");
    expect(declarationsOf(".pb-menu__agent")).toContain("text-transform: none;");
    // the folded menu stacks the groups with their labels
    const css = stripComments(localCss);
    expect(css).toMatch(/@media \(max-width: 1140px\) \{\s*\.pb-nav__tools \{ flex-direction: column;/);
    expect(css).toContain(".pb-nav__tools > .pb-navtool { justify-content: space-between;");
  });

  test("the header tools have no lines at all; the label and the options differ by type, the one checked is a filled block", () => {
    const css = stripComments(localCss);
    const section = css.slice(css.indexOf(".pb-navtool {"), css.indexOf("@media (min-width: 801px) and (max-width: 1140px)"));
    expect(section).not.toMatch(/border-(top|bottom|right)|border:/);
    // the only `border-left` of the tools zeroes the one the system draws between options
    expect([...section.matchAll(/border-left: ([^;]*);/g)].map((match) => match[1])).toEqual(["0"]);
    expect(declarationsOf(".pb-lang--fill .pb-lang__btn")).toBe("border-left: 0; color: var(--ink); font-weight: 700; font-size: 14px;");
    expect(declarationsOf(".pb-lang--fill .pb-lang__btn::after")).toBe("display: none;");
    expect(declarationsOf(".pb-lang--fill .pb-lang__btn:hover")).toBe("background: var(--surface-200);");
    expect(declarationsOf('.pb-lang--fill .pb-lang__btn[aria-checked="true"]')).toBe("background: var(--violet-soft); color: var(--violet);");
    // the label is muted text in the label style, lighter than the options
    expect(declarationsOf(".pb-navtool__label")).toContain("font: 600 12px/16px var(--font-condensed);");
    expect(declarationsOf(".pb-navtool__label")).toContain("color: var(--ink-muted);");
    // the artifact's own option is muted, so the override is what makes the options plain ink
    expect(componentsCss).toMatch(/\.pb-lang__btn \{[^}]*color: var\(--ink-muted\)/);
  });

  test("the bar folds at 1140px, not at the system's 800px: the wordmark, the links and the groups do not fit before", () => {
    const css = stripComments(localCss);
    const block = /@media \(min-width: 801px\) and \(max-width: 1140px\) \{([^@]*?)\n\}/.exec(css)?.[1] ?? "";
    // the same rules as the system's own fold, from 801px up
    const system = /@media \(max-width: 800px\) \{([^@]*?)\n\}/.exec(stripComments(componentsCss))?.[1] ?? "";
    for (const rule of [".pb-nav__menu { display: inline-flex; }", ".pb-nav[data-open=\"true\"] .pb-nav__collapse { display: flex; }", ".pb-nav__links { flex-direction: column; gap: 0; }"]) {
      expect(system, rule).toContain(rule);
      expect(block, rule).toContain(rule);
    }
    expect(block).toContain(".pb-nav__collapse { display: none; position: absolute;");
    // a rough width of the unfolded bar (wordmark, the four links, the language and currency groups with their labels,
    // the theme group with none, gaps and padding) stays under the fold, with a margin for the real width of the type
    // (no borders: a group is its options and 2px between them; groups are told apart by 16px of margin on top of the 16px gap)
    const unfolded = 140 + 385 + (57 + 4 + 88) + (38 + 4 + 132) + 88 + 4 + 2 * 16 + 2 * 16 + 2 * 24 + 32;
    expect(unfolded).toBe(1084);
    expect(unfolded * 1.05).toBeLessThanOrEqual(1140);
  });

  test("the action under a reply is a pb-action: only its placement and its time are written here, and the leading icon does not step on hover", () => {
    expect(declarationsOf(".pb-trace-open")).toContain("align-self: flex-start;");
    expect(declarationsOf(".pb-action.pb-trace-open .pb-ico--detective")).toBe("transform: none;");
    expect(declarationsOf(".pb-trace-open__time")).toContain("text-transform: none;");
    expect(declarationsOf(".pb-trace-open")).not.toContain("min-height");
    expect(localCss).not.toContain(".pb-trace-open:hover");
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
      ["./components.css", "./fonts.html", "./index.css", "./local.css", "./tokens", "./tokens.css", "./tokens.json"],
    );
    for (const target of Object.values(manifest.exports)) expect(existsSync(join(PACKAGE_ROOT, target)), target).toBe(true);
  });

  test("index.css imports the tokens, then the components, then the local changes", async () => {
    const index = await readText("index.css");
    const imports = [...index.matchAll(/@import "([^"]+)";/g)].map((match) => match[1]);
    expect(imports).toEqual(["./dist/tokens.css", "./src/components.css", "./local.css"]);
    expect(manifest.exports["./tokens.css"]).toBe("./dist/tokens.css");
    expect(manifest.exports["./components.css"]).toBe("./src/components.css");
  });

  test("bundling index.css puts the tokens before the components, and the local changes last", async () => {
    const result = await Bun.build({ entrypoints: [join(PACKAGE_ROOT, "index.css")] });
    expect(result.success).toBe(true);
    const css = await result.outputs[0]!.text();
    const firstToken = css.indexOf("--surface-000:");
    const firstComponent = css.indexOf(".pb-btn");
    expect(firstToken).toBeGreaterThan(-1);
    expect(firstComponent).toBeGreaterThan(firstToken);
    expect(css.indexOf(".pb-proof")).toBeGreaterThan(css.indexOf(".pb-cmsg"));
    expect(css).toContain(':root[data-theme="dark"]');
  });

  test("components.css names its source artifact and version", () => {
    expect(componentsCss.startsWith("/* Source: claude.ai Artifact")).toBe(true);
    expect(componentsCss).toContain("https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV");
    expect(componentsCss).toMatch(/version \d+-[0-9a-f]+ \(\d{4}-\d{2}-\d{2}\)/);
  });
});
