# HowItWorks

The real flow as a numbered sequence, with stencil numerals: the order is information.

## Consumer provides

The four steps, in this order, each with a title, one sentence and the state chip the customer reaches:

| # | Step | Chip |
| --- | --- | --- |
| 01 | Cuéntale qué pasó: the customer reports the lost card or the charge and gives a document number | Identificado (`identified`) |
| 02 | Verifica tu identidad: a 6-digit code, valid 5 minutes | Verificado (`verified`) |
| 03 | Bloqueamos con comprobante: `card.block` and the receipt | Tarjeta bloqueada (`blocked`) |
| 04 | Una persona toma la disputa: handoff with the verified facts | Con un agente (`handed-off`) |

## Parts

| Class | Notes |
| --- | --- |
| `pb-flow` | `<ol role="list">`. The numerals come from a CSS counter (`01` to `04`) in `stencil`, `violet`. Vertical on phones with a hairline running down; four columns with a hairline between the numerals from 960px. |
| `pb-flow__item` | One step. |
| `pb-flow__title`, `__text`, `__state` | Title in `display`, body, and the state chip. |

## Rules

- Do not reorder, merge or add decorative steps. If the product flow changes, this component changes with it.
- The chips reuse the FSM state colors; the wording is the customer-facing one. A step without a state change gets no chip.
- Keep the `<ol>`: screen readers announce the order. The visual numerals are generated, so the markup carries no digits.
