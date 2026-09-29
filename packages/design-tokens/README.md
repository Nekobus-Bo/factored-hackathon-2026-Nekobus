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
  index.css              imports dist/tokens.css, then src/components.css (the required order)
  src/tokens.json        copied verbatim from the artifact
  src/components.css     copied verbatim from the artifact, behind a header comment naming the source and version
  scripts/               build.ts (CLI), generate.ts (pure generators), schema.ts (Zod schema of tokens.json)
  dist/tokens.css        GENERATED, committed: every token as a custom property, both themes, type-style classes
  dist/tokens.ts         GENERATED, committed: typed token names and values per theme
  dist/fonts.html        GENERATED, committed: the Google Fonts <link>
  tests/                 bun test
```

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
4. Run `make design-tokens`, then `make design-tokens-check`.
5. Commit `src/` and `dist/` together: `feat(design-tokens): sync from the design-system artifact <version>`. Update the version in the table at the top of this file.

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
