# OtpInboxNotice

The simulated email delivery of the one-time code in the demo: a toast that announces the new message and an inbox panel that shows the masked destination, the six digits and a countdown.

## Consumer provides

`maskedEmail` (`d***@example.com`), the six digits from the demo delivery channel, `expiresAt`, and the open/dismiss handlers. Delivery is simulated: no email is sent. The panel says so in the visible note, always.

## Parts

| Class | Notes |
| --- | --- |
| `pb-toast` (`role="status"`) | Violet icon block with a mail glyph, title, one line, close button, and "Abrir bandeja" as a `pb-action` in `pb-toast__actions` (own line, right-aligned). `shadow-float`. |
| `pb-card pb-inbox` | Panel: `pb-inbox__bar` (title plus `DEMO` tag), `pb-kv` for De / Para / Asunto, the instruction, the code, the countdown, the simulation note. |
| `pb-code` with `pb-code__d` | Six chamfered digit cells in `mono-code`. Put `role="img"` and an `aria-label` with spaced digits on the wrapper and `aria-hidden` on the cells. |
| `pb-expiry` | `label` "Vence en", `role="timer"` time in `mono`, and a `pb-gauge--sm` of 24 segments that turns `alert` under 60 seconds. |
| `pb-inbox__note` | `info` glyph on `surface-200`: "Entrega simulada para la demo". |

## Rules

- Never claim a real delivery. The words "simulada" and "demo" stay visible in the panel; in production this component is not rendered.
- The code is shown in this panel only. When the customer types it in the chat, echo it as `••••••`; the orchestrator masks it before anything reaches the LLM. Never log it.
- The countdown updates the text every second but has no live region (`role="timer"` is silent); announce expiry once with a `role="status"` message.
- Security copy: "Pattern Blue nunca te pedirá este código por teléfono ni por correo."
