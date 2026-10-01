# AlertBanner

A chamfered notice for something the reader must act on or know: informational, success, caution (with hazard stripe) and critical (with hazard stripe).

## Consumer provides

`tone` (`info`, `success`, `caution`, `critical`), an eyebrow word, one sentence that says what happened, an optional second line that says what to do, and an optional action button. Critical uses `role="alert"`, everything else `role="status"`.

## Parts

| Class / attribute | Notes |
| --- | --- |
| `pb-alert` with `data-tone` | Ground is the tone's `*-soft`, edge and glyph the tone color. Default tone is `info`. |
| `pb-alert--stripe` and a first-child `<span class="pb-hazard">` | Caution and critical only. |
| `pb-alert__eyebrow` | One word in `label`, in the tone color: Política, Crítico, Idioma, Verificado. |
| `pb-alert__text` and `small` | Sentence in `body` weight 500; `small` for the next step, in `ink-muted`. |
| trailing `pb-btn--sm` or `pb-action` | Secondary button for caution, danger for critical retry, a ghost icon button to dismiss info, or a `pb-action` for a follow-up such as "Ver comprobante". |

## Rules

- Say what happened, then what to do. "No se pudo confirmar el bloqueo: la tarjeta •••• 4821 sigue ACTIVE. No informes al cliente hasta tener un comprobante." Never "Algo salió mal".
- Hazard stripe only when the reader must stop or change course: an amount above its threshold requires a priority handoff, an attempt to widen a tool beyond the code floor was refused, a write was not confirmed. Not for info, success, marketing, empty states or errors the reader cannot act on. One striped banner per screen region.
- Body text is `ink` on the soft ground (14:1 or better); the tone color is only for the eyebrow, glyph and edge.
- Critical stays until resolved; caution can be dismissed only if it will not matter later.
