# S2PromoCard

A decorative promo in the customer app for S² (ticker S2), Pattern Blue's fictional demo asset: "liquidity without limit". Nothing sits behind it.

## Consumer provides

Nothing dynamic. Copy is fixed; the card has no price, balance, chart, link or button. It is safe to render on any customer screen.

## Parts

| Class | Notes |
| --- | --- |
| `pb-s2` | `field` face with a `field-accent` edge; `on-field` text. Always dark, in both themes. |
| `pb-hexfield` (first child) | The absolute-field texture at 16% opacity, `on-field` ink. |
| `pb-s2__top`, `pb-s2__demo` | Brand line and the "Solo demo" tag. Required. |
| `pb-s2__mark` | The `S²` glyph in `display` 900 (aria-hidden) and the `S2` ticker in `mono`. |
| `pb-s2__title` | Title card: two stacked lines ("Liquidez / sin límite"). |
| `pb-s2__reactor` with `pb-gauge--sm` | Full 24-segment bar in `field-accent`: the infinite-energy motif. Decorative, `aria-hidden`. |
| `pb-s2__legal` | Small print in `on-field-muted`: "Activo digital ficticio de demostración. No es una inversión ni un producto real." Required. |

## Rules

- S² is a fictional demo asset, not a real one. Never show prices, returns, market data, wallets or any call to action, and never describe it as an investment.
- The "Solo demo" tag and the small print are part of the component. Keep them in every language (Solo demo, Somente demo, Demo only).
- Use once per screen, below the primary task, never in the chat, receipts or the back office.
- The green on this card is `field-accent`, valid on `field` only. Do not copy it to light surfaces.
