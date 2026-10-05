# DetectiveMode

Detective mode shown inside the chat panel, in place of the conversation, and drawn with the system. **In design (2026-10-04): a proposed change to what ships today** (ADR-0019, a panel beside the chat). Nothing here is in `components/bundle.css`; the new rules are section 3 of this card's preview, and sections 1 and 2 are the repository's local styles as they ship.

## What changes

| Today | Proposed |
| --- | --- |
| A panel opens left of the chat | The view takes the chat's place, inside the same chamfered panel. A button in the header goes back to the chat |
| A strip with a bar under each reply, only while the mode is on | One quiet control under each reply, always there while the mode is offered: the icon and the turn's time. It opens that turn |
| A magnifier | A hexagonal magnifier, `pb-ico--detective` |
| Square dots, flat bars | A hexagon marks a step; a bar is a row of hexagon cells |
| Four hues, one per kind of step, with sync green and alert orange among them | Two tones: pattern blue (information) for the LLM, muted ink for every other step. Green, orange and red keep their meaning |
| A row of 28px numbered squares for the turns | One stepper, "Turno 2 de 5", with 44px targets |
| The conversation total as a boxed table in the header | Two lines of label and data: the turn, the conversation |
| `$0.00016` | `USD 0.00016`: the currency code first |
| Mono at 11px and 12px, labels at 11px | `small` for names, `mono-data` for figures, `label` for labels |

## The icon

`pb-ico--detective`: a hexagonal magnifier, chosen 2026-10-04. The lens is the system's hexagon (pointy top, R = 4 on the 16px grid, centre 6,7.5). The handle leaves the lower-right vertex on the line from the centre through that vertex, at 30 degrees: it is the third edge of the honeycomb at that vertex, 5 long. Same stroke, caps and joins as the rest of the set.

## Rules

- **The conversation stays the customer's.** The chat shows one small control per reply and one button in the header; everything else is in the view.
- **Every value is masked**, as the LLM saw it (ADR-0019). Placeholders are marked (`[DOC_1]`).
- **A hexagon is a system glyph, not a status.** Status is a chip with a word, and only when a step went wrong.
- **Bars show time, never a score.** The segmented gauge stays for a calibrated confidence against its threshold (the encoder's detail).
- Targets are 44px, as in the rest of the customer app.

## Parts

Existing, restyled: `pb-trace`, `pb-trace__head`, `pb-trace__body`, `pb-trace-steps`, `pb-trace-step`, `pb-trace-dot`, `pb-trace-spark`, `pb-trace-wf` (`__axis`, `__row`, `__track`, `__bar`, `__detail`, `__head`), `pb-trace-detail`, `pb-trace-code`, `pb-trace-ph`, `pb-trace-more`. New: `pb-trace--inpanel`, `pb-trace__nav`, `pb-trace__stepper`, `pb-trace__totals`, `pb-trace-open`, and the icon `pb-ico--detective`.

## Open

- The figures in the preview are sample values.
- At 520px the Time view has about 25 cells for the bars; a step shorter than one cell still shows one.
