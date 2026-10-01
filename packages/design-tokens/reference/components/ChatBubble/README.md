# ChatBubble

The customer chat surface: a launcher button, an open panel with customer and assistant messages, a typing indicator and a composer, built for a 360px phone.

## Consumer provides

The message list (`role`, text, time, optional receipt id), the current FSM state for the header chip, the typing flag and the send handler. The panel is a fixed-width column (`max-width: 360px`); on a phone, make it fill the screen and put `scrim` behind it.

This component is the shell. The content types that go inside the log (receipts, handoff, notices, system lines, errors, quick replies, pickers, summaries) are in `ChatMessage`, with the backend source of each.

## Parts

| Class | Notes |
| --- | --- |
| `pb-launcher` | 60px chamfered `violet` square with a chat glyph; add `pb-launcher__live` (a `sync` square) when the assistant is online. `aria-label` states the action and the status. |
| `pb-chat`, `pb-chat__head`, `pb-chat__title` | Panel, header with the state chip on the right. |
| `pb-chat__log` | `role="log"` `aria-live="polite"`; `surface-200` ground. |
| `pb-msg pb-msg--assistant` | `surface-100` face, hairline edge, cut on top-left and bottom-right. |
| `pb-msg pb-msg--customer` | `violet` face, `on-violet` text, mirrored cut (top-right, bottom-left). |
| `pb-msg__meta` | Sender and time in `label`. |
| `pb-msg__receipt` | Sync-green line with the audit id under a confirmed action. |
| `pb-typing` | Three stepped squares; wrap in `role="status"` with a `pb-sr` text. Static under reduced motion. |
| `pb-chat__composer` | A `pb-field` plus a `pb-btn--icon` send button. |

## Rules

- The assistant confirms an action only alongside a `receipt` block (see `ChatMessage`) or, in text, the `pb-msg__receipt` line. Before that, use progressive wording ("Estoy bloqueando tu tarjeta") and no receipt line.
- Echo an OTP the customer typed as `••••••` in the transcript; it is masked before it reaches the LLM.
- Mask on the client too: `•••• 4821`, `d***@example.com`. Never render a full card number, even if the model returns it.
- Messages wrap with `overflow-wrap: anywhere`; do not truncate. Keep `max-width: 88%`.
- Set `lang` on a message whose language differs from the page (pt, en).
- Input font is 16px so iOS does not zoom.
