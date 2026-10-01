# ReceiptCard

The proof of a write: what was done, to what, from which state to which, with the audit id and the moment `banking-core` re-read it from the database.

## Consumer provides

A receipt object returned by the tool: `action`, `target` (already masked), `from` and `to` states, `auditId`, `idempotencyKey`, `verifiedAt` (ISO with zone). The card renders only when `verifiedAt` exists; before that, use the `data-state="pending"` variant.

## Parts

| Class / attribute | Notes |
| --- | --- |
| `pb-card pb-receipt` | `sync` edge and `glow-sync`. Add `pb-ticks` for the instrument corners. |
| `pb-receipt__head`, `__kicker`, `__title` | Kicker is `Recibo · <action>`; title is a plain-language result in `display` (Tarjeta bloqueada). |
| `pb-stamp` | "VERIFIED AGAINST DATABASE": 2px `sync` edge on `sync-soft`, `shield-check` glyph. Localize the words (VERIFICADO NA BASE DE DADOS, VERIFICADO CONTRA LA BASE DE DATOS); keep the meaning. |
| `pb-kv` | Definition list: `dt` in `label`, `dd` in `mono-data`. |
| `pb-transition` | Wraps `state-active` chip, an `arrow` icon and `state-blocked` chip, in customer wording (es Activa / Bloqueada, pt Ativo / Bloqueado, en Active / Blocked), not the raw ACTIVE and BLOCKED. |
| `data-state="pending"` | `alert` edge, no glow, stamp "AWAITING RECEIPT". The write was sent but not confirmed. |

## Rules

- No receipt, no confirmation: never show the green card, the stamp or a success message until the database re-read is in hand. Show the pending variant and tell the agent or the customer what happens next.
- Audit id and idempotency key are in `mono-data`; truncate the key in the middle (`7f3a91c2…5a10`), never the audit id.
- Time is ISO date, 24h time and zone abbreviation: `2026-09-29 10:42:18 COT`.
- Do not use the green edge or glow for anything that is not a verified write.
