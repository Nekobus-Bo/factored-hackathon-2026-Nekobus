# @pattern-blue/design-tokens

The look of Pattern Blue for both front ends (`apps/web-client`, `apps/web-backoffice`): design tokens as CSS custom properties and TypeScript, plus the `pb-*` component stylesheet. It is imported, never deployed ([ADR-0009](../../docs/adr/0009-monorepo-structure.md)).

**The design system is not authored here.** It is a published claude.ai Artifact, and this package is a checked, generated copy of two of its files:

| | |
|---|---|
| Source of truth | [Pattern Blue design system](https://claude.ai/artifact/SCciz5Vfoa9s7sSY4KT2NV) (Artifact type "Design System") |
| Synced version | `1790655197-4dbb`, 2026-09-29 |
| Copied files | `project/tokens.json` to `src/tokens.json`, `project/components/bundle.css` to `src/components.css` |
| Not copied | The artifact's `README.md` (brand book, voice, accessibility rules): read it in the artifact. Its Google Fonts link is the one constant kept by hand, in `scripts/generate.ts` |

## Layout

```
packages/design-tokens/
  index.css              imports dist/tokens.css, then src/components.css, then local.css (the required order)
  src/tokens.json        copied verbatim from the artifact
  src/components.css     copied verbatim from the artifact, behind a header comment naming the source and version
  local.css              written here: changes not in the artifact yet (see below)
  scripts/               build.ts (CLI), generate.ts (pure generators), schema.ts (Zod schema of tokens.json)
  dist/tokens.css        GENERATED, committed: every token as a custom property, both themes, type-style classes
  dist/tokens.ts         GENERATED, committed: typed token names and values per theme
  dist/fonts.html        GENERATED, committed: the Google Fonts <link>
  reference/             copied verbatim from the artifact: its README.md (the rules) and components/<Name>/{README.md,preview.html}
  tests/                 bun test
```

`src/` and `reference/` are copied by hand and never edited here. `reference/` is the design system's documentation, the markup and rules of every component, kept in the repository so the front ends can be built without access to the artifact (which is private to its owner until shared). Its previews expect the artifact viewer to inject the tokens and `components.css`; to open one locally, add `<link rel="stylesheet" href="../../../index.css">` to its `<head>`. It is not imported by any app and no check reads it.

`src/` is copied by hand and never edited here. `dist/` is written by `make design-tokens` and never edited by hand. It is committed so apps and CI need no build step; `make design-tokens-check` fails when it drifts from `src/`.

## Using it from an app

1. Depend on it. An app is a workspace member as soon as it has a `package.json`:
   ```json
   { "dependencies": { "@pattern-blue/design-tokens": "workspace:*" } }
   ```
2. Paste the fonts link from `dist/fonts.html` into the `<head>` of the app's `index.html`. The fonts come from Google Fonts; there are no font files. Offline, the fallback stacks in `--font-*` apply.
3. Import the styles **once, at the app root**:
   ```ts
   import "@pattern-blue/design-tokens/index.css";
   ```
   Bun's bundler follows the `@import`s. If you import the pieces separately, keep the order: `tokens.css`, then `components.css`. Bun writes a few `--buncss-*` custom properties next to `color-scheme` in its output; nothing reads them.
4. Use tokens in TypeScript when a value has to follow the theme from code (XState guards, inline styles, charts):
   ```ts
   import { colors, cssVar, type ColorTokenName } from "@pattern-blue/design-tokens/tokens";

   <div style={{ color: cssVar("ink-muted") }} />   // "var(--ink-muted)": follows the theme
   colors.violet.dark                                 // "#b39bff": the resolved value
   ```

| Export | File |
|---|---|
| `@pattern-blue/design-tokens/index.css` | `index.css` |
| `@pattern-blue/design-tokens/tokens.css` | `dist/tokens.css` |
| `@pattern-blue/design-tokens/components.css` | `src/components.css` |
| `@pattern-blue/design-tokens/tokens` | `dist/tokens.ts` |
| `@pattern-blue/design-tokens/tokens.json` | `src/tokens.json` |
| `@pattern-blue/design-tokens/fonts.html` | `dist/fonts.html` |

`dist/tokens.ts` exports `themes`, `ThemeId`, `defaultTheme`, `themeAttribute`, `isThemeId`, the value tables `colors`, `colorAliases`, `shadows`, `spacing`, `radius`, `motion`, `stroke`, `fontFamilies`, `typeStyles`, the name unions (`ColorTokenName`, `TokenName`, ...), `cssVar` and `googleFontsHref`.

## Themes

Two themes, `light` (the base and the fallback) and `dark`. Everything that differs between them (all colors, the shadows and the sync glow) is declared three times in `tokens.css`, with the same declarations in each dark block:

| Selector | When it applies |
|---|---|
| `:root` | Always: light values, plus every theme-independent token (type families, spacing, radius, motion, stroke) |
| `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` | The system prefers dark and the page has not pinned light |
| `:root[data-theme="dark"]` | The page pinned dark |

Each block also sets `color-scheme`, so native controls and scrollbars follow. Aliases such as `--link` or `--state-verified` stay `var(--pattern)` and `var(--sync)` references in every block.

The theme attribute goes on `<html>` and nowhere else:

| `<html>` | Result |
|---|---|
| no `data-theme` | Follows the system, light if the browser cannot say |
| `data-theme="light"` | Light, whatever the system says |
| `data-theme="dark"` | Dark, whatever the system says |

The apps differ on purpose: the customer app follows the system (no attribute), the back office remembers the agent's choice. Toggling is the app's job and belongs in its global XState machine (context `theme: ThemeId | "system"`); the package ships the vocabulary, not the machine:

```ts
import { isThemeId, themeAttribute, type ThemeId } from "@pattern-blue/design-tokens/tokens";

export type ThemeChoice = ThemeId | "system";

export function applyTheme(choice: ThemeChoice, root = document.documentElement): void {
  if (choice === "system") root.removeAttribute(themeAttribute);
  else root.setAttribute(themeAttribute, choice);
}

// A remembered choice is untrusted input: check it, and expect storage to throw.
export function readStoredTheme(key: string): ThemeChoice {
  try {
    const stored = localStorage.getItem(key);
    return isThemeId(stored) ? stored : "system";
  } catch {
    return "system";
  }
}
```

Apply the remembered choice from an inline script in `<head>` (before the stylesheet paints) to avoid a flash of the wrong theme.

## Type styles

Every style in `tokens.json` (`title-card`, `h1`, `h2`, `h3`, `body`, `body-strong`, `small`, `label`, `label-lg`, `mono-data`, `mono-code`, `case-id`) is a class of the same name in `tokens.css` with family, size, line height, weight and letter spacing. `mono-*` and `case-id` also get tabular figures. Uppercase and `font-stretch` are added by `components.css`, because the token grammar cannot express them. `components.css` also has the `pb-t-*` utilities with the same values.

## Local changes not yet in the artifact

`local.css` holds styles written in this repository that the artifact does not have yet. It loads after `src/components.css` and uses only tokens and `pb-` classes (a test checks both). The customer chat's rules are scoped to `.pb-dock`; the back office's conversation rules to `.pb-convo`. They come from the two declutter reviews of 2026-10-02: the customer chat and the landing, then the back office (ADR-0018 for the decisions). The artifact belongs to another claude.ai account, so they could not be published there.

They change these design-system rules. Whoever updates the artifact should change the rule, move the CSS into `components/bundle.css`, sync, and delete it from `local.css`.

| Rule in the artifact | What the customer app does now |
|---|---|
| ChatBubble: the panel is a 360px column | 520 × 680 on desktop, capped by the window height; full screen on phones |
| ChatBubble: the launcher is a 60px glyph | The glyph and the word "Asistente" (`pb-launcher--label`) |
| ChatBubble: `pb-msg__meta` carries sender and time on every message | The sender is a `pb-sr` label and the time sits after the last word (`pb-msg__time`). A human agent's message keeps a sender line, in sentence case |
| README: case ids are `case-id` (stencil) | In the customer chat, case and receipt references are mono |
| ChatMessage 2: a receipt shows kicker, state transition, key-values and footer | `pb-proof`: the result and the receipt reference. The transition and "Verificado contra la base de datos" open from the reference. `otp.verify` is a verified system line with its reference |
| ChatMessage 2 and 4: the `otp.send` receipt and the OTP notice are two messages | One `pb-proof` with the countdown and "Abrir bandeja" |
| OtpInboxNotice: the inbox is a card in the log with De / Para / Asunto | A sheet over the messages (`pb-sheet`), without the key-value rows |
| ChatMessage 3: the handoff shows priority, status, queue position and a list of what the agent knows | The department, the case reference and one closing sentence that keeps "Desde aquí el asistente deja de actuar" |
| ChatMessage 5: system lines use the `label` style | 13px sentence case, with an optional receipt reference (`pb-sys__ref`) |
| ChatMessage 6b and 6c: a failed message adds a caution card; a rate limit is a caution card | One `pb-unsent` line under the failed message; `pb-strip` for 429 and 404 |
| ChatMessage: the list of content types | A new one: feedback after a handoff (`pb-rate`) |
| ChatMessage: assistant text is plain text | Money in assistant text is mono and never breaks from its currency (`pb-amount`); a dash list of amounts (recent transactions, balances) is a ledger of date, label and amount (`pb-ledger`). Presentation only: the figures are the model's words, and a list it does not recognise stays plain text |
| Hero: say only what the assistant does | The landing is a fictional bank's home page; the hero names its products and what the chat does |
| Landing: a section header is a kicker and a title card of two or three lines | The title alone, on one line |
| FeatureGrid: the assistant's features, a fact line on each card | The bank's products, no fact line |
| Navbar: a login button and a two-button theme radio group | No button for the chat (it opens from the hero and the launcher), and the theme as two radios, a sun and a moon (`pb-navtool`, `pb-lang__btn`; see below) |
| Footer: link columns and its own language and theme controls | The wordmark, the demo note and the small print (`pb-footer__inner--compact`) |

And in the back office:

| Rule in the artifact | What the back office does now |
|---|---|
| StatusChip: the back office shows the raw enum (`OTP_PENDING`) | Chips speak the agent's language; the raw enum is the chip's `title` |
| README: case ids are `case-id` (stencil) | Lowercase mono in groups of four (`pb-caseref`); copying gives the plain id |
| QueueRow: id, priority, department, language, wait, customer; the id is the anchor; the row is not focusable | Priority, the case in words (reason, department, amount, id), who holds it, the wait, and a chevron (`pb-cases`, `pb-crow`). The title is the link, so the whole row opens the case |
| QueueRow: nothing opens over the queue | A summary card under the row (`pb-peek`) with the case facts and the decisions |
| HandoffCard: `pb-caseid`, priority and HANDED_OFF chips in the header; facts as `pb-kv`; actions as `pb-steps`; open questions numbered in stencil | The page header holds the case (`pb-casehead`). The card is a summary in sentence-case sections (`pb-sum`): the customer's ask as an unverified quote (`pb-said`), the charge (`pb-txn`), facts as sentences (`pb-facts`), the writes, the customer's feedback, and the full log on demand (`pb-more`, `pb-audit`) |
| HandoffCard: `pb-handoff__actions` holds Tomar caso and Reasignar | Tomar caso, Aprobar, Rechazar and Escalar in the header, with one confirmation (`pb-decide`, `pb-confirm`, `pb-choices`, `pb-done`) |
| ChatBubble and ChatMessage: the customer is right-aligned in violet; `pb-msg__meta` on every message; receipts as `pb-cmsg` | Inside `.pb-convo` the customer is on the left and the bank on the right, names once per run (`pb-convo__who`), the time in the bubble, receipts and the handoff as `pb-sys` lines |
| PolicyControl: one `pb-navtool` block per tool with its `pb-cells` row | One table, the states named once in the header (`pb-mx`) |
| Navbar: the language radio group and the theme in the bar | The theme as two radios (no visible label), and the agent's menu (`pb-menu`: a button of the system, a panel with Sesión, Idioma and Salir; see below); a count on Cola (`pb-nav__count`) |
| No metrics components | Four numbers with their change (`pb-kpis`, `pb-kpi`, `pb-delta`), two short lists (`pb-list`), the tables on demand (`pb-details`, `pb-mtable`) |

`pb-live`, `pb-tabs`, `pb-linkbtn` and `pb-empty` are new parts that change no rule.

`pb-s2--band` (S² as a band from 720px) and `pb-hero__fact` are new layouts that change no rule.

The demo's message options (ScriptChoice, approved 2026-10-04) add parts that change no rule, in one section at the end of `local.css`: the band `pb-say` with `pb-say__head`, `pb-say__title` and `pb-say__hint`, and the options it offers, `pb-say__list` and `pb-say__opt` (a `<button>` that also carries `pb-cut`), with `pb-say__body`, `pb-say__label`, `pb-say__text`, `pb-say__note`, `pb-say__side` and `pb-say__go`. An option is the outlined twin of the bubble it becomes (violet edge, no fill, the rule of `pb-qr`); `pb-dock` and `pb-convo` give it the sender's cut and size. The back office uses it for the suggested reply over the composer (`.bo-composer-wrap`); the customer app's demo panel (`pb-side`, in its guide tab) uses the same options. The panel is one chamfered card at the left of the chat, as tall as it (`pb-cut pb-side pb-dock__side`, `min(520px, calc(100% - 580px))` wide: 340px at a 920px window, 520px from 1100px), shared by the guide and detective mode as two tabs (`pb-tabs`, `pb-tab` with `role="tab"` and `aria-selected`) in its head (`pb-side__head`, content in `pb-side__content`). It is closed by default and opened from one button with text in the chat header (`pb-demo-toggle`, a `pb-btn` with the `menu` icon and "Menú demo"); below 920px the panel is `display: none` and the button opens the detective view in the chat's place. The guide's parts are `pb-guide__body`, `pb-guide__title`, `pb-guide__hint`, `pb-guide__steps`, `pb-guide__step` (`data-state="done" | "current" | "next"`) and `pb-guide__foot`. The panel's display would win over the `hidden` attribute, so `.pb-side[hidden]` hides it. The card is in `reference/components/ScriptChoice/` (README and preview, literal copies of the approved design of 2026-10-04, written in `local.css` and not yet in the artifact's `bundle.css`). **Both cards describe the earlier design:** the guide as a panel of its own (`pb-guide`, `pb-dock__guide`, 340px) and detective mode in place of the chat. What ships is the shared panel above; the cards have not been updated yet.

Detective mode (ADR-0019) adds parts that change no rule: the view, a tab of the demo panel beside the chat and, under 920px, in place of the chat (`pb-trace pb-trace--inpanel`), its turn stepper (`pb-trace__nav`, `pb-trace__stepper`) and totals (`pb-trace__totals`), the action under a reply (`pb-action pb-trace-open`: the icon, "Ver detective", the time and an arrow), the step list, timeline and step detail (`pb-trace-*`), and a hexagonal magnifier icon (`pb-ico--detective`) drawn like the rest of the set (in the action under a reply, in the title of the view that takes the chat's place and nowhere in the header). The card is in `reference/components/DetectiveMode/`: it is the approved design of 2026-10-04, written in `local.css` and not yet in the artifact's `bundle.css`; the card's preview carries its own copy of the old rules (its section 1), which `local.css` no longer has.

The composer while a one-time code is pending adds parts that change no rule, in `local.css`: `pb-code-entry` (on the `pb-chat__composer` form), with `pb-code-entry__field` (a `pb-t-label` label over the boxes), `pb-code-entry__cells` (a `pb-code` row of six `pb-code__d pb-t-code pb-code-entry__cell` boxes, `data-active` on the one to type in, `data-disabled` while off), `pb-code-entry__input` (the one real input, transparent, over the boxes; the group takes the system's focus ring), `pb-code-entry__cancel` (a `pb-btn--ghost`), `pb-code-entry__note` (the "code expired" line) and `pb-code-entry__error` (a `pb-unsent` line under the boxes). No send button. No card in `reference/components/` describes it yet.

**One rule of the system changes: the typing indicator is no longer the only loop.** Two controls call for attention in a loop, in the same mechanical movement (the face swaps between its rest and its hover, `violet-soft`, in system steps: ten `--motion-step` long, `--ease-step`; no glow, shadow or gradient; `pb-nudge` in `local.css`). Each is bounded: the chat header's "Menú demo" button (`pb-demo-toggle`) until the panel has been open once in the visit (`data-seen`) and never while it is open; and the option of the guide's current step while it can be used (not disabled). Both stop, showing the hover face, under the pointer or the keyboard focus, and neither runs under `prefers-reduced-motion: reduce`. The artifact's README should say "the typing indicator, and these two bounded calls" when it takes the rule.

**One more rule of the system changes: how a field shows the focus.** The artifact outlines a `pb-field` that has the focus (`.pb-field:focus-within`, a 2px ring 3px outside). `local.css` takes that outline away and turns the field's own chamfered edge to the focus colour, 2px thick, while it has the cursor (`--edge: var(--focus); --bw: 2px`, winning over the hover edge; an invalid field keeps its red edge). The focus stays always visible, in the shape of the field and not outside it. The one-time code's boxes show it in the box to type in, only while the field has the focus, with no ring around the group. A checkbox (`.pb-check input`) gets the system's ring, only for the keyboard. The rings of buttons, links, tabs and the other controls are unchanged. `src/components.css` is still the artifact's copy: the artifact's README should say the field's focus is in its edge when it takes the rule.

**The header tools change shape in both apps.** The artifact's theme control is two square buttons (`pb-theme`, `pb-theme__btn`, one of them a single square toggle in the apps) and the agent's menu was a plain box (`pb-menu__btn`); neither matched the rest of the system, and the landing's two unlabelled groups ("ES PT" and "MX AR CO") were taken for language and currency. Now each tool is a `pb-navtool`: a visible label (`pb-navtool__label`, the `label` style, `ink-muted`; the theme has none and is named for assistive technology) followed by its options as radios drawn like the language switch (`pb-lang`, `pb-lang__btn`), with **no lines anywhere** (`pb-lang--fill`: the options in the full ink and heavier than the muted label, the one checked a block filled with `violet-soft` and its text in violet instead of the underline; groups told apart by room, not by a rule), so the label and the options do not read alike, the groups told apart by room, with no rule. The landing has Idioma (ES, PT), País (MX, AR, CO: the market) and the theme group; the back office has the theme group and, in the agent's menu, Idioma. **The theme is two radios, a sun and a moon, named "Claro" and "Oscuro"** (`pb-ico--sun`, `pb-ico--moon`), in place of the square toggle; it is the same machine and the same storage as ever. The agent's menu button is a button of the system (`pb-btn pb-btn--ghost pb-btn--sm pb-menu__btn`) with the user icon, the e-mail in the data type (`pb-menu__agent`, cut with an ellipsis) and the chevron; its panel has labelled sections (Sesión with the e-mail in `pb-t-mono`, Idioma) and, after a rule, "Salir" as a `pb-btn--secondary`. The system folds the bar at 800px; with three labelled groups and with the theme group unlabelled and the options with no borders about 1085px, so `local.css` folds it up to **1140px** (the same rules as the system's fold, and the groups stack with their labels in the menu). The artifact's own README and `pb-nav` rules would take this when it adopts the change.

**The wordmark changes in the bar and the footer of both apps.** The system sets the brand's name in one colour, `wordmark` or `ink`. Here it is drawn in capitals (`text-transform: uppercase`; the text stays "Pattern Blue", and so does the accessible name) with "Pattern" in the main ink (`pb-wordmark__ink`, white in the dark theme) and "Blue" in the brand's blue (`pb-wordmark__blue`), in the title type the bar and the footer already use. The drawn card of the hero is not touched. **A name to avoid:** `pb-tool` is the policy control's row in `src/components.css`, so the bar's tools are `pb-navtool`; a test fails if `local.css` defines `pb-tool` again and lists the base classes it restyles over the system's own.

In "Si pierdes tu tarjeta" (`pb-flow`) the four steps share a row from 960px up and their text takes two or three lines, so the state chips (`pb-flow__state`) sat at different heights. `local.css` makes each step a flex column (the row gives it its height) with the chip pushed to its foot (`margin-top: auto`), so the four chips share one line; stacked on a narrow screen nothing is aligned.

## Class-naming rules (from the design system)

- Component classes are prefixed `pb-`. Elements use `__` (`pb-msg__meta`), variants `--` (`pb-btn--ghost`, `pb-ico--lock`). The only unprefixed classes are the type styles above.
- State and tone come from attributes, not classes: `data-state` (`pb-chip[data-state="verified"]`, checked switches and buttons), `data-tone`, `data-disabled`, `aria-checked`, `aria-pressed`, `aria-disabled`. That is what Zag.js and Ark UI emit, so put the classes on their parts. Derive a chip's state from the machine value: `data-state={value.toLowerCase().replace(/_/g, "-")}`.
- Read colors, spacing and type through the tokens (`var(--violet)`, `var(--space-4)`); never paste a hex value. Text on a solid fill uses its `on-*` token.
- Custom properties like `--tone`, `--c-tl`, `--face` and `--edge` belong to the components; do not set them from app code. The exception is the gauge, whose instance sets `--n` (segments), `--on` (lit segments) and `--tau` (the threshold, 0 to 1).
- Never put `clip-path` on a component itself: the chamfer is built from two clipped layers so borders and focus outlines follow it.
- Set `font-stretch: 62.5%` on any new display rule yourself; the `font` shorthand resets it.

## Syncing from the artifact

When the design system changes:

1. Read the artifact's current `project/tokens.json` and `project/components/bundle.css` (in Claude Code: the Artifact tool, `action: "read"`, with the file as `path`; or download them from claude.ai).
2. Replace `src/tokens.json` with `tokens.json`, byte for byte.
3. Replace `src/components.css` with the header comment (update the version and date, they come from the read's "version" line) followed by `bundle.css`, byte for byte.
   Replace `reference/` with the artifact's `project/README.md` and `project/components/` (every `README.md` and `preview.html`, not `bundle.css`).
4. Run `make design-tokens`, then `make design-tokens-check`.
5. Delete from `local.css` whatever the artifact now has.
6. Commit `src/` and `dist/` together: `feat(design-tokens): sync from the design-system artifact <version>`. Update the version in the table at the top of this file.

`make design-tokens-check` is designed to fail on the changes a sync can bring:

| Change in the artifact | What fails |
|---|---|
| A component reads a variable no token defines | `components.css only reads variables that exist` |
| A new token family, an unknown field, a value that is not plain CSS | The Zod schema, with the path of the problem |
| An alias that points nowhere or loops, or a name defined twice | The model check in `generate.ts` |
| A new non-`pb-` class in `components.css` that `tokens.css` does not generate | `every non-pb class it uses is a type style` |
| A new font family that the Google Fonts link does not load | `the Google Fonts link covers the first font of every family`: update `GOOGLE_FONTS_HREF` in `scripts/generate.ts` from the artifact's README |
| Anything at all, if `dist/` was not regenerated | `dist/ does not match src/tokens.json` |

What it cannot check: contrast, or whether a token is used well. Those are the artifact's job.

## Commands

From the repository root (`make` is the single entry point):

```bash
make design-tokens         # bun install --frozen-lockfile, then regenerate dist/
make design-tokens-check   # dist/ matches src/, tsc --noEmit, bun test: what CI runs
```

Both fail with an explicit message when Bun is not installed (1.3 or later; `BUN=/path/to/bun` overrides). Inside the package: `bun run build`, `bun run check`, `bun run typecheck`, `bun test`.

## Known limits

- The fonts load from Google Fonts. Without a network the fallback stacks apply, so the title card is set in a system serif. Listed in [limitations](../../docs/limitations.md).
- Only the `light` and `dark` themes are generated; a third theme in `tokens.json` stops the build.
- The sync is manual. There is no script that reads the artifact.
