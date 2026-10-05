# ScriptChoice

The demo guide: a panel beside the customer chat that offers the team's six walkthrough scripts and, once one is chosen, its next message; and the suggested reply over the agent's composer in the back office. **Approved 2026-10-04, not in the product and not in `components/bundle.css` yet.** The new rules are section 3 of this card's preview; sections 1 and 2 are the repository's local styles as they ship.

It exists so a person trying the demo can run a script with clicks instead of typing it, without the conversation changing for someone who sees the product for the first time.

## Where it shows

| Surface | When | What choosing does |
| --- | --- | --- |
| Customer chat, a panel at its left | The button in the chat header (`menu` glyph) opens it. Closed by default; not offered below 900px | Nothing until a script is chosen |
| The panel, no script yet | Six scripts | Sends the script's first message as the customer's and switches the chat to the script's market |
| The panel, a script running | The script's lines: sent, next, and what comes after | Sends the next line as written |
| The panel, code step | The assistant asked for the one-time code | Nothing to send: a pointer to "Abrir bandeja" and "Mostrar código". The code is real |
| Back office, case taken over | The masked transcript matches a script that has an agent line | Puts the text in the composer. It is never sent by the click |

## Rules

- **Nothing of the guide is inside the conversation.** The chat stays as the customer sees it; the guide is a panel beside it, like the chat's other demo tool.
- **It is a demo guide, never a bank feature.** The panel always carries the "Solo demo" tag.
- **The script is chosen once.** From then on the panel offers exactly one message, the next line of that script. "Cambiar de guion" starts over.
- **Off script, it stops.** If the customer or the agent sends anything that is not the script's line, the guide stops offering messages for that conversation. The composer never changes.
- **The market follows the script, and the interface follows the market.** Choosing a pt-BR script sets the market to pt-BR: the page, the chat and the guide itself switch to Portuguese, and amounts are in that market's currency (BRL). An es-CO script reads in Spanish with COP. The script's own lines are never translated: they are the test.
- **A suggestion, not a nudge.** Options are outlined, never filled (the rule of `pb-qr`). An option is the outlined twin of the bubble it becomes.
- **The customer sends, the agent reviews.** In the guide the click sends. In the back office the click fills the composer, because the message is recorded with the agent's email and the customer reads it as written.
- **A script that depends on a back-office policy says so**, in a note that names the guardrail. The chat cannot change the policy.
- **The agent side matches masked text.** The agent's transcript stores the customer's messages masked (`[DOC_1]`, `[OTP_1]`); the match compares the script's lines with those markers in place of the personal data, and recognises the script from the first customer message.
- The customer panel is 520px wide (it was 420px).

## Parts

`pb-guide` (with `pb-cut`), `pb-dock__guide`, `pb-guide-toggle`, `pb-guide__head`, `pb-guide__body`, `pb-guide__title`, `pb-guide__hint`, `pb-guide__steps`, `pb-guide__step` (`data-state="done" | "current" | "next"`), `pb-guide__foot`; the options: `pb-say__list`, `pb-say__opt` (a `<button>`, with `pb-cut`), `pb-say__body`, `pb-say__label`, `pb-say__text`, `pb-say__note`, `pb-say__side`, `pb-say__go`; in the back office the band `pb-say` with `pb-say__head`, `pb-say__title`, `pb-say__hint`. Reused: `pb-tag`, `pb-ico`, `pb-action`, `pb-t-mono`.

## Open

- The team's scripts carry no agent lines. The suggested reply in the back-office example is a draft and needs the real text.
- Scripts 2 and 3 share a customer and a charge, and scripts 1 and 6 share a customer: the demo data has to be seeded again between them.
- The Spanish demo customer's account is in COP whatever the Spanish market, and there is no MXN threshold: in es-MX amounts still read in COP.
