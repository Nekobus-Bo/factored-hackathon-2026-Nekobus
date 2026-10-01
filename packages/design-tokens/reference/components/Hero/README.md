# Hero

The landing's first screen: a stacked title-card headline, a subhead that says what the assistant really does, two calls to action, the hex field and a card visual.

## Consumer provides

The copy in each language and the handler that opens the chat (`data-open-chat` on the primary button; the launcher opens the same panel). The secondary button scrolls to `HowItWorks`.

| Language | Headline (3 lines) | Primary call to action |
| --- | --- | --- |
| es | Tu tarjeta / bloqueada / con comprobante | Hablar con el asistente |
| pt | Seu cartão / bloqueado / com comprovante | Falar com o assistente |
| en | Your card / blocked / with a receipt | Talk to the assistant |

## Parts

| Class | Notes |
| --- | --- |
| `pb-hero` | Full-bleed band on `surface-000`, `overflow: hidden`, with `pb-hexfield` as its first child (ink `line`). |
| `pb-hero__inner` | Max 1200px; one column, two from 960px. |
| `pb-hero__kicker` | `label` with a `hex` glyph. |
| `pb-hero__title` | The title card: `display` 900, uppercase, `font-stretch: 62.5%`, three stacked `<span>`s; the middle one has `pb-accent` (`wordmark`). Fluid: about 30–46px on phones, up to 68px on desktop. Leading is 1.06. |
| `pb-hero__sub` | 17–18px body, max 52 characters wide. |
| `pb-hero__cta` | A primary `pb-btn` and a secondary `pb-btn`. |
| `pb-hero__facts` | Three checked lines of real product facts. |
| `pb-hero__visual` | `aria-hidden` art: `CardVisual` (BLOCKED), a `pb-stamp` and two color slabs (`violet`, `pattern`). |

## Rules

- **Say what the assistant really does**: verifies identity with a code, blocks a compromised card, shows the receipt, hands disputes to a person with the facts already verified. Nothing else.
- **No invented numbers.** No user counts, ratings, uptime or speed claims ("al instante" is not a fact). A number may appear only if it is a product fact: a 6-digit code, 5 minutes of validity, the per-currency amount threshold.
- One title card per landing hero. The headline never exceeds three lines; if a line wraps, shorten the copy, do not shrink the type below the fluid range.
- The hex field stays behind the copy at line-color ink; never raise its opacity.
- The visual is decorative. If it must carry meaning, give `CardVisual` `role="img"` and a label.
