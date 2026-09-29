# CardVisual

A Pattern Blue payment card mockup in the brand's armor language: a chamfered `field` plate with the hex texture, a stencil last-four, a masked holder and a status chip (ACTIVE or BLOCKED).

## Consumer provides

`state` (`active` or `blocked`, as `data-state`) and the language. The chip word is customer-facing and localized: es Activa / Bloqueada, pt Ativo / Bloqueado, en Active / Blocked (never the raw ACTIVE or BLOCKED on the landing); the holder and expiry labels follow (Titular / Vence, Titular / Validade, Holder / Expires). Every value on the plate is already masked and fixed for the demo: `••••` + `4821`, `D*** M***`, `••/••`. Never render a real number, holder or expiry.

## Parts

| Class | Notes |
| --- | --- |
| `pb-cardvis` | 1.586 aspect ratio, max 380px, `field` face, `field-accent` edge (`crimson` when blocked), `shadow-float`. |
| `pb-hexfield` | First child; `on-field` ink at 14%. |
| `pb-cardvis__top`, `__brand`, `pb-chip` | "Pattern Blue" in `display` and the `active` or `blocked` chip. |
| `pb-cardvis__mid`, `__chip`, `__pan` | A chamfered chip plate and the masked number: bullets in `mono`, the last four in `stencil`. |
| `pb-cardvis__bottom`, `__label` | Holder and expiry in `mono`, labels in `label`. |

## Rules

- Decorative art: `aria-hidden="true"`. If it stands for a real card in a status message, use `role="img"` and an `aria-label` such as "Tarjeta Pattern Blue terminada en 4821".
- No payment-network marks, no real brand logos, no fake full numbers.
- The plate is always dark (`field`) in both themes, so its text is `on-field` or `on-field-muted`. The chip has its own ground, so it stays legible on top.
- Use it as the Hero's visual and next to card actions; do not tile it into grids.
