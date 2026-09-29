Pattern Blue is an AI-first customer-service system for banking, presented as a futuristic fintech: a calm, precise machine that acts only when the bank's database has confirmed it. One brand serves two front ends: the **customer web client** (a simulated fintech app with a chat bubble, mobile-first) and the **back office** (handoff queue, case detail with verified facts, policy and tool controls; dense, desktop-first, often used in dark mode). The look borrows the colors, condensed type and cut-corner armor of mecha and plugsuit design, and none of its marks (see Inspiration and IP).

## Content fundamentals

**Voice: calm, precise, never alarmist.** Bank-grade clarity. Say what happened, what is true now, and what happens next. No exclamation marks, no emoji, no slang, no urgency theatre. Address the customer as "tú" in Spanish, "você" in Portuguese, "you" in English.

**The assistant never claims an action without a receipt.** Before the receipt exists, use progressive wording ("Estoy bloqueando tu tarjeta"). After the database re-read, state the result and the audit id in the same message.

| Language | Confirmed action |
| --- | --- |
| es | Bloqueé la tarjeta •••• 4821. Comprobante AUD-20481. |
| pt | Bloqueei o cartão •••• 4821. Comprovante AUD-20481. |
| en | Card •••• 4821 is now blocked. Receipt AUD-20481. |

**Errors say what happened and what to do.** "No pude confirmar el bloqueo. Tu tarjeta •••• 4821 sigue activa. Voy a pasar tu caso a un agente." Never "¡Ups! Algo salió mal."

**Casing and data.**
- Sentence case in source. Uppercase comes from the `label`, `label-lg` and `title-card` styles; never type capitals for style. Identifiers stay as they are: `card.block`, `OTP_PENDING`, `CASE-0427`.
- Mask on screen: `•••• 4821`, `d***@example.com`, `D*** M***`. Amounts: currency code first, `USD 139.99`. Dates ISO with 24h time and zone: `2026-09-29 10:42:18 COT`.
- Tool names, receipts, thresholds and ids are `mono-data`. Case ids are `case-id`.
- Customers are served in Spanish, Portuguese and English; set `lang` on any fragment that differs from the page. Documentation and code are English; sample UI copy here is Spanish, with pt and en beside it.

## Visual foundations

**Color: roles, not decoration.** Every token has a light and a dark value; light ("plugsuit white", cool) is primary, dark (deep near-black with a violet bias, "terminal") is first-class and the usual back-office setting. Put `data-theme="light"` or `"dark"` on `<html>`.

| Role | Tokens | Use |
| --- | --- | --- |
| Ground and surfaces | `surface-000` page, `surface-100` cards and inputs, `surface-200` wells and hover, `surface-300` selected and pressed | Layers, lightest to highest. |
| Text | `ink`, `ink-muted` | On every surface and every soft tint. |
| Lines | `line` (decorative), `line-strong` (control borders, edges, ticks; 3:1) | Never use `line` as the only boundary of a control. |
| Primary action | `violet`, `violet-hover`, `violet-soft`, `on-violet` | One primary per view; HANDED_OFF. |
| Pattern blue | `pattern`, `pattern-soft`, `on-pattern`; aliases `wordmark`, `link`, `focus`, `info` | Wordmark, links, focus ring, information, IDENTIFIED. |
| Sync green | `sync`, `sync-soft`, `on-sync`; alias `success` | Verified, synced, live. Darker on light, neon on dark. |
| Alert orange | `alert`, `alert-soft`, `on-alert`; alias `warning`; `hazard`, `hazard-ink` | Caution, OTP_PENDING, HIGH. `hazard` pair is the stripe only. |
| Crimson | `crimson`, `crimson-soft`, `on-crimson`; alias `danger` | Danger, critical, LOCKED, BLOCKED, URGENT. |
| Absolute field | `field`, `on-field`, `on-field-muted`, `field-accent` | The one always-dark surface: cover, S² promo, hero bands. |
| FSM and card states | `state-anonymous`, `state-identified`, `state-otp-pending`, `state-verified`, `state-locked`, `state-handed-off`, `state-active`, `state-blocked`, each with a `-bg` | Aliases onto the hues above. Use through `StatusChip`. |

- Text on a solid fill is its `on-*` token, never literal white or black: the dark theme lightens the fills and flips the text.
- A soft tint (`*-soft`) is the ground for text of the same hue; body copy on it stays `ink`.
- Green means verified or live, red means danger, orange means caution. Do not use them for decoration or to fill a chart.
- No gradients except the hazard stripe and the gauge segments. No blue-to-purple washes.

**Type: four voices and a stencil.** Load the fonts from Google Fonts (families are named in `type.families`, there are no font files):

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Big+Shoulders+Stencil+Display:wght@700;800;900&family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Noto+Serif+Display:wdth,wght@62.5..100,100..900&display=swap">
```

- **Title card** (`title-card`, `h1`, `h2`; `--font-display`): Noto Serif Display at weight 800–900 and `font-stretch: 62.5%`, its narrowest width. The narrow axis is what gives the heavy, tall, high-contrast serif of a title card; `components/bundle.css` sets it on those classes, and any new display rule must set `font-stretch: 62.5%` itself (the `font` shorthand resets it). Stack two or three short lines, uppercase for `title-card`. **Landing versus app:** on the landing the hero headline and every section header are title cards (`pb-hero__title`, `pb-section__title`, sized fluidly). Inside the customer app and the back office use `h1` and `h2` in sentence case, and allow at most one title card per screen, for a moment that deserves it (a confirmed action, an empty state); never in tables, forms or chat.
- **UI text** (`h3`, `body`, `body-strong`, `small`; `--font-sans`): IBM Plex Sans, 16/24 for body so mobile inputs do not zoom.
- **Telemetry** (`label`, `label-lg`; `--font-condensed`): Barlow Condensed, uppercase with wide tracking, for field labels, chips, table headers, gauge names and buttons.
- **Data** (`mono-data`, `mono-code`; `--font-mono`): JetBrains Mono, tabular figures, for tool names, receipts, thresholds, timestamps and the OTP.
- **Stencil** (`case-id`; `--font-stencil`): Big Shoulders Stencil Display, for case ids and list numerals only.

**Shape: the chamfer is the signature.** Components are rectangles with a 45-degree cut on the top-left and bottom-right corners: `cut-sm` (6px) for chips, inputs and switches, `cut-md` (8px) for buttons, alerts and messages, `cut-lg` (12px) for cards, panels and the launcher. A customer's chat message mirrors the cut (top-right, bottom-left). Everything else is square (`radius-none`): tables, tags, the queue frame. `radius-dot` is for status dots and the typing indicator only. The chamfer is built from two clipped layers so the border follows the diagonal; the focus outline and `filter: drop-shadow()` sit on the unclipped element. Never put `clip-path` on a component itself.

**Traits, and when not to use them.**
- **Hairline rules and corner ticks.** `line` for dividers; add `pb-ticks` to a card that should feel like an instrument (receipts, gauge panels). Not on every card.
- **Hex field.** `pb-hexfield`, a hexagonal grid texture for hero, cover and promo grounds, at most 16% opacity. Never behind body text on a light surface.
- **Segmented gauge.** `pb-gauge` for a calibrated confidence against its threshold τ. Never for raw scores, progress or loading.
- **Stencil numbering.** Case ids and question numerals (`01`, `02`), nothing else.
- **Hazard stripe.** `pb-hazard`, orange and ink diagonals, for caution and critical only: an amount above its threshold requires a priority handoff, an attempt to widen a tool beyond the code floor was refused, a write was not confirmed, an URGENT handoff. Do not use it for information, success, empty states, decoration, marketing, buttons, dividers or loading; not for an error the reader cannot act on; and not more than one striped surface in view.

**Actions and links.** `pb-btn` for commands (`pb-btn--ghost` for a quiet one in a button row). `pb-action` for a follow-up action inside a toast, card, banner or chat message ("Abrir bandeja", "Ver comprobante", "Reintentar"): condensed uppercase `violet` with a trailing `arrow` or `retry` glyph, a 2px bar and a stepped arrow on hover, a 44px hit area. `pb-link` only for a reference inside running text: `link` color, 1px `line-strong` underline offset 4px, 2px on hover. Never leave an `<a>` unstyled and never use `pb-link` for an action.

**Spacing and layout.** 4px base, 8px rhythm (`space-1` to `space-16`). Customer app: one column up to 480px, 16px gutters, 44px minimum touch targets. Back office: dense, 32px controls (`pb-btn--sm`), 52px table rows, 12 to 16px gaps.

**Elevation.** Cards use `shadow-card`, floating things `shadow-float`, both through `filter: drop-shadow()`. The only glow is `glow-sync`, for live and verified elements.

**Motion.** Short and mechanical: transitions use `ease-step` (`steps(4, end)`) over `motion-tick` (80ms) or `motion-step` (160ms); a one-shot reveal may take `motion-scan`. The typing indicator is the only loop. Everything is instant under `prefers-reduced-motion`.

**Focus.** A solid 2px `focus` outline with a 3px offset on the unclipped element, at least 3:1 on `surface-000` to `surface-300` in both themes (4.8:1 or better in light, 6.4:1 in dark). Never remove it.

## Iconography

Simple geometric line icons on a 16px grid: 1.5px stroke, square caps, mitered joins, with a hexagon for system glyphs. They ship as CSS masks in `components/bundle.css` and take the current text color:

```html
<i class="pb-ico pb-ico--lock" aria-hidden="true"></i>
```

Set: `check`, `arrow`, `retry`, `plus`, `menu`, `sun`, `moon`, `x`, `pause`, `lock`, `user`, `user-dashed`, `clock`, `handoff`, `card`, `card-blocked`, `mail`, `chat`, `warning`, `critical`, `info`, `shield-check`, `chev2`, `chev1`, `minus`, `send`, `db`, `infinity`, `hex`. `pb-ico--lg` is 24px. No emoji, no filled or duotone icons, no icon fonts. An icon never carries a status alone: it sits next to a word. New icons are drawn on the same grid.

There is no logo file. The wordmark is "Pattern Blue" set in `h1` or `title-card` in `wordmark` (pattern blue) or `ink`. Do not draw a symbol.

## S²: a fictional demo asset

S² (ticker S2) is Pattern Blue's own cryptocurrency, named after an infinite-energy engine: "liquidity without limit". It exists only as the decorative `S2PromoCard` in the customer app. It is a fictional demo asset, not a real one, and nothing sits behind it: no wallet, balance, price, chart or transaction. The card always carries the "Solo demo" tag and the small print. Do not add prices, yields, links or buttons.

## Inspiration and IP

The direction is inspired by the mechas and plugsuits of a Japanese science-fiction anime: its electric violet, sync green and alert orange, its heavy condensed serif title cards, its chamfered armor plates and hexagonal force fields. "Pattern Blue" is a nod to the franchise's detection code. It is inspiration, not copy. There are no logos or emblems of organizations from the show, no characters or likenesses, no franchise names in UI copy, token names or code, and no commercial typeface (the title font is Noto Serif Display, an open font). Keep it that way in new work.

## Accessibility

- Text is 4.5:1 or better on the grounds its token names, in both themes (3:1 for 24px and larger). Control borders, focus rings, icons and gauge fills are 3:1 or better. In the light theme `sync` and `crimson` are close in lightness, so status is always a word plus a glyph plus a color, never color alone.
- Targets: 44px on the customer app, 32px minimum in the back office.
- Live regions: chat log `role="log"`, typing `role="status"`, banners `role="status"` (critical: `role="alert"`), OTP countdown `role="timer"`.
- Gauges expose `role="meter"` with `aria-valuetext` that states the outcome.
- Motion respects `prefers-reduced-motion`. Every input has a label (visible or `pb-sr`).

## Using the system

- Load order: the Google Fonts link, `tokens.css`, `components/bundle.css`. Read colors, spacing and type through the tokens (`var(--violet)`, `var(--space-4)`, `var(--font-mono)`); never paste hex values.
- Component classes are prefixed `pb-`; each component's README lists its classes and attributes. There is no React bundle: the classes are plain CSS and work in Bun + React with `className`.
- Landing: `Landing` assembles `Navbar`, `Hero`, `FeatureGrid`, `HowItWorks`, `S2PromoCard`, `FaqAccordion` and `Footer` with the chat launcher docked bottom-right (`pb-dock`). Landing copy makes no invented claims: no user counts, ratings, uptime or speed; a number is allowed only if it is a product fact (a 6-digit code, 5 minutes of validity, the per-currency amount threshold). The login in the Navbar is decorative in the demo.
- Chat: `ChatBubble` is the shell and `ChatMessage` lists every content type that goes in its log, with the backend source of each (only `text`, `receipt` and `handoff` blocks exist today; the model may emit only `text`).
- XState: derive the chip from the machine value, `data-state={value.toLowerCase().replace(/_/g, "-")}`. Render a confirmation or a `ReceiptCard` only when the context holds a receipt.
- Zag and Ark UI: put the classes on the parts. The CSS already reads `data-state="checked"`, `data-disabled` and the `aria-*` attributes (switch: `pb-switch` on the control and `pb-switch__thumb` on the thumb; segmented choice: `pb-btn` with `role="radio"`).
- Theme: the customer app follows the system preference and falls back to light; the back office remembers the agent's choice (dark is common in long sessions).

## Components

- **Actions**: `Button` (with `pb-action` and `pb-link`).
- **Status and feedback**: `StatusChip`, `AlertBanner`, `SyncGauge`.
- **Customer app**: `ChatBubble` (shell), `ChatMessage` (content types), `ReceiptCard`, `OtpInboxNotice`, `S2PromoCard`.
- **Landing**: `Navbar`, `Hero`, `CardVisual`, `FeatureGrid`, `HowItWorks`, `FaqAccordion`, `Footer`, `Landing` (the assembled page).
- **Back office**: `HandoffCard`, `QueueRow`, `PolicyControl`.
