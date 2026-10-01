# QueueRow

One row of the back-office handoff queue: case id, priority, department, language, waiting time and masked customer.

## Consumer provides

The handoff list sorted by priority then wait, the selected case id, and the SLA limit for the late marker. Rows are links into the case (`pb-caseid` is the anchor); the row itself is not focusable.

## Parts

| Class / attribute | Notes |
| --- | --- |
| `pb-queue` with `role="table"` | Hairline frame, no chamfer: tables stay square. |
| `pb-queue__head` | Column labels in `label` on `surface-200`; hidden under 720px. |
| `pb-qrow` with `role="row"`, cells `data-col="id|pri|dept|lang|wait|cust"` | Six-column grid; under 720px it becomes two lines per row. |
| `aria-current="true"` | Selected case: `surface-300` and a 2px `violet` inset frame. |
| `data-late` on the `wait` cell | Past SLA: `crimson` text, bold, with a `warning` glyph and a `pb-sr` "SLA excedido". |
| `pb-tag` | Language code (ES, PT, EN) as text; no flags. |

## Rules

- The stencil `pb-caseid` is for ids only. Priority is a `StatusChip` (word plus glyph); department is `mono-data`; wait is `mm:ss` in tabular figures.
- Sort order and the late threshold come from configuration, never from row code.
- Mask the customer to initials plus asterisks. Full identity is behind the case.
- Row height is 52px on desktop; do not shrink below 44px on touch devices.
