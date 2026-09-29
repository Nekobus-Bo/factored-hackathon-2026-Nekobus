# ChatMessage

Every content type the customer chat can show, each in the chat's own visual language (chamfers, tokens, condensed labels), with the backend source that feeds it and whether it exists today.

`ChatBubble` is the shell (launcher, panel, header, log, composer, typing indicator); `ChatMessage` is what goes inside `pb-chat__log`. Render messages in order; structured messages (`pb-cmsg`) and system lines (`pb-sys`) take the full width of the log, bubbles (`pb-msg`) do not.

## Content types

| # | Type | Markup | Source | Status |
| --- | --- | --- | --- | --- |
| 1 | Assistant and customer text | `pb-msg pb-msg--assistant`, `pb-msg pb-msg--customer` | `text` block (the only block the model may emit); customer input | Exists |
| 2 | Receipt | `pb-cmsg[data-tone="receipt"]` | `receipt` block: the engine builds it from a successful tool result (`action`, `target_masked`, `state_before`, `state_after`, `verified_at`). Shown for `card.block`, `otp.send`, `otp.verify` | Exists |
| 3 | Handoff, customer view | `pb-cmsg[data-tone="handoff"]` | `handoff` block: `department`, `priority`, `status`, `queue_position`. Never `summary` | Exists |
| 3b | Human agent text | `pb-msg pb-msg--agent` plus a `pb-sys[data-tone="joined"]` line | The blocks contract carries no sender today; telling a person's text from the assistant's needs one | Style ahead, needs a sender field |
| 4 | OTP sent notice | `pb-cmsg pb-cmsg--notice` with a `pb-action` to `OtpInboxNotice` | Derived by the client from the `otp.send` receipt plus `GET /v1/conversations/{id}/inbox` (destination, expiry) | Exists (client-derived) |
| 5 | System lines: date, identity verified, session locked, agent joined | `pb-sys[data-tone="verified" \| "locked" \| "joined"]` | Client, from FSM state changes and conversation events | Exists (client-derived) |
| 6a | Masking fallback | `pb-cmsg[data-tone="info"]` | The orchestrator's masking layer refused to process the message | Exists |
| 6b | Service unavailable | `pb-msg--customer[data-status="failed"]` plus `pb-cmsg[data-tone="caution"]` with a retry `pb-action` | HTTP 503 from the chat API. Retry resends the same `client_message_id` | Exists |
| 6c | Rate limited | `pb-cmsg[data-tone="caution"]` | HTTP 429; the copy carries the wait in minutes | Exists |
| 7 | Confirmation with quick replies | `pb-msg--assistant` followed by `pb-quick` with two `pb-qr` | ADR-0012 confirm gate (`confirm_gate`). Each quick reply sends a canonical text string as the customer message; the gate classifies it. The gate is not in the backend yet | In design (shadow) |
| 8 | Card picker, transaction picker | `pb-cmsg` with `pb-pick` and `role="radio"` rows | Would need a new engine-built block from `card.list` and `transaction.list_recent` (masked card, brand, type, status chip; merchant, amount, date, dispute-eligible marker) | Pending: new block |
| 9 | Account summary | `pb-cmsg` with `pb-lines` | Would need a new engine-built block from `account.get_summary` (one masked line per account with its balance) | Pending: new block |

Types 8 and 9 do not exist in the contracts. The "Pendiente" chip in the preview marks them as designed ahead; do not render that chip in the product. Do not build any of them from model text.

## Rules

- **The model only writes `text`.** Receipts, handoffs, notices, system lines and errors are engine-built or client-derived, with fixed strings per language (es, pt, en). Never show a receipt, a handoff or a "verified" line because the model said so.
- **Customer-facing handoff is plain.** Show the department in words ("Disputas"), the priority in words (URGENT is Urgente, HIGH Alta, NORMAL Normal, LOW Baja), the queue position, a case reference and a fixed list of what the agent already knows. Never `summary.verified_facts`, `actions_taken`, internal ids or audit ids other than the case reference. End with "Desde aquí el asistente deja de actuar".
- **A human's message is not the assistant's.** `pb-msg--agent` has a `violet-soft` face, a `user` glyph and "Agente humano · <first name>" in the meta line. It always follows a "se unió" system line.
- **The OTP is never echoed.** When the customer types the code, the transcript shows `Código: ••••••`. The notice carries only the masked destination and the time left.
- **Degraded states are calm.** No hazard stripe in the chat. State what happened and what to do; 503 is `role="alert"`, the rest `role="status"`. A message the API did not accept stays in the log as `data-status="failed"` with "No enviado" and a retry action.
- **Quick replies are equal in weight** (two outlined `pb-qr`, never one filled): the gate is a question, not a nudge. After a choice, disable the group and show the chosen text as a customer bubble. The composer stays available.
- **Pickers ask for a pointer, not a decision.** Rows are `role="radio"` in a `role="radiogroup"`; a row the flow cannot use (a BLOCKED card, a non-disputable charge) is `aria-disabled` and states why in a chip, not only in gray.
- **Chips speak the customer's language.** State chips inside the chat and in pickers use the customer wording of the message's language (es Activa, Bloqueada, Identificado, Código pendiente, Verificado; en Code pending, Verified), never the raw enum; the enum belongs to the back office. Stamps and footers are localized the same way.
- **Mask everything** the way the contract does: `•••• 4821`, `d***@example.com`, account numbers `•••• 3302`. Amounts put the currency first: `USD 139.99`.
- Each structured message has an accessible name (`aria-label`) and a kicker in `label`. The log itself is `role="log"` (`aria-live="polite"`); do not add live regions to individual messages except for 503.
- Set `lang` on a message whose language differs from the page (pt, en); the copy of engine-built blocks is localized as a whole.

## Parts

`pb-cmsg` with `__head`, `__kicker`, `__eyebrow`, `__title`, `__text`, `__note`, `__list`, `__actions`, `__foot`, `__icon`; `pb-kv` (compact inside `pb-cmsg`); `pb-transition` for state before and after; `pb-lines` (`__name`, `__sub`, `__amt`); `pb-sys` (`__text`); `pb-quick`, `pb-qr`; `pb-pick` (`__row`, `__main`, `__sub`, `__side`, `__amt`, `__tick`); `pb-action` for in-message actions.
