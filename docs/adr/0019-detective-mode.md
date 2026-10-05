# ADR-0019: detective mode, each turn's masked timeline in the customer chat

**Status:** Accepted · **Date:** 2026-10-04 · **Amended:** 2026-10-04 (the view takes the chat's place, the choice is not remembered), 2026-10-04 (beside the chat again, in the panel the demo guide shares), 2026-10-05 (with no room the chat takes the screen and the demo panel replaces it, with its two tabs; see the last section) · **Deciders:** TODO (team)

## Context

Judges and the team want to see what happens under the hood of a conversation: what the encoder predicted and how fast, what was masked, what each LLM call was sent and answered, what banking-core allowed or refused, and what was kept of the reply. Today that lives in logs, in the eval hook (`EVAL_EXPOSE_TURN`, eval runs only, refused in production) and in the audit log. None of it is visible from the chat, where the demo happens.

## Options

- **(a) Read the logs.** Nothing to build, nothing anyone outside the team can follow.
- **(b) Widen the eval hook.** It is refused under `APP_ENV=production` on purpose, and its shape is pinned by the eval runner and llmbench.
- **(c) A separate, typed trace per turn, returned with the turn where an environment offers it, shown by a switch in the chat (chosen).**

## Decision

**Each customer turn can return a `TurnTrace`** (`packages/contracts/src/contracts/trace.py`, mirrored in `ts/trace.ts`, drift-tested): one timed event per step, encoder, masking, each LLM call, each tool call (and the handoff the engine creates itself), the reply's blocks and the decision records, each with the detail named after its kind.

- **Masked values only.** The engine's recorder reads the values it already computed for the provider: the masked text, the masked messages, the masked tool arguments, the feedback string the model receives. It never sees the placeholder map's values, the rehydrated tool arguments or a raw tool result. Slot values are left out (types only). A test sweeps a traced turn for the raw document number.
- **Passive.** What the provider and banking-core receive, and the LLM recording keys, are identical with the trace on or off (tested). A defect in the recorder drops an event, never the turn.
- **Availability is per environment** (`DETECTIVE_MODE`, off in code): on in the local compose, off in the production overlay unless set, and the Terraform variable `detective_mode` on Cloud Run (`presentation.tfvars` sets it). Unlike the eval hook it is allowed under `APP_ENV=production`.
- **Runtime switch in the back office.** The Guardrails screen turns it off and on for every conversation at once, through the agent API (`GET/PUT /v1/agent/detective`); the state is one key on redis-edge. It cannot go beyond what `DETECTIVE_MODE` offers (409).
- **The chat asks** `GET /v1/capabilities` when it opens and after every turn, and only then shows the detective tab and an action under each reply that came with a trace ("Ver detective" and the turn's time). The viewer's choice is not remembered: every visit starts with the panel closed. The view covers the earlier turns too.
- **Where the view lives: see the amendments below (the third, of 2026-10-05, is the one in force).** The demo menu button in the header opens the panel; the action under a reply opens that turn; the header button opens the newest, and the view follows the newest turn until another is picked. Two views of the same steps: a list where each step opens in place, and a timeline of bars on the turn's clock. A stepper ("Turno n de total") moves between turns, skipping the replies that came without a trace. Numbers and the system's own names, few words: a status shows only when a step went wrong, a step's detail is one line plus the masked values, and the prompt, the tools offered and what the LLM got back fold. The chat is 520px wide beside the panel and the screen when there is no room for it.

## Consequences

- **On a public URL, anyone using the chat sees the system prompt, the tools offered, the policy outcomes and the masked conversation.** The data is synthetic and masked, but the prompt and the policy behaviour are an easier target to probe. That is the price of showing judges the inside; the back office can turn it off at once.
- Responses are larger (the first LLM call of a turn lists its messages in full, later calls only the new ones).
- Not covered: a turn that fails (LLM error, replay miss) returns no trace; traces are not stored, so a reload shows none; the back office does not show them; retrieval internals (keyword vs embedding scores) and policy internals stay inside banking-core ([limitations](../limitations.md)).

## Amendment 2026-10-04: in place of the chat, and not remembered

- **What it said:** a panel opened left of the chat when a switch was on, a strip under each reply picked the turn, the panel covered the chat below 900px, and the switch was remembered in the browser (`pb-detective`).
- **What it says now:** the view replaces the chat inside the same panel (decision above). The panel beside the chat, its strip, the `matchMedia` cover below 900px and the remembered switch are gone. The chat is 520px wide (it was 420px) so the view has room for the steps and the bars.
- **Why:** the beside-panel needed room for two panels at once, so on a narrow window it covered the page, and below 900px it needed a second set of rules to cover the chat. One panel at one width works at every window size, and the view is drawn with the design system (a hexagon marks a step, bars are rows of hexagon cells, two tones, a 44px stepper; card `DetectiveMode` in `packages/design-tokens/reference/`).
- **Not remembered:** a remembered "on" would reopen the view after a reload with no turns to show (traces are not stored), a chat with no composer. Every visit starts on the chat.
- **What did not change:** the trace, its contract, the availability rules, the back-office switch and every consequence below.

## Second amendment 2026-10-04: beside the chat again, in the panel the demo guide shares

*The rules for a window with no room (the end of "What it says now" below) are replaced by the third amendment.*

- **What the first amendment said:** the view replaces the chat inside the same panel, at every width, and there is no second panel.
- **What it says now:** on a window of 920px or more the view is the "Detective" tab of one panel at the left of the chat, as tall as the chat, which the demo guide (ScriptChoice) shares as its "Guion" tab. One header button with text, "Menú demo", opens and closes the panel (it opens on the tab last used in the visit, the guide the first time); the tabs inside the panel switch. (Until the same day the header had two icon buttons, one per tab; the owner asked for one.) The detective tab exists only where the environment offers the mode; otherwise the panel is the guide alone. The chat and its composer stay in sight and usable. The panel is `min(520px, calc(100% - 580px))` wide: 340px at 920px, 520px from 1100px. **Only below 920px does the view replace the chat** (the first amendment's behaviour, with its button back to the chat), because there is no room for the panel; the guide is not offered there and the same header button exists only where the mode is offered, opening the view in place of the chat. When the back office turns the mode off, the panel goes to the guide (beside the chat) or the chat is back (in place of it).
- **Why:** the owner saw the replacement in a preview: it hides the conversation the trace is about, and the demo needs both in sight. The panel is the one the guide already needed, so there is still one extra panel and not two.
- **The control under a reply** is now an explicit action of the system ("Ver detective" and the turn's time, with the icon and an arrow; the name "Modo detective" is the mode's, and it did not fit an action that opens one turn), because the bare icon and time did not say what it opens. It opens the panel on that turn (the view replacing the chat, on a narrow window).
- **Not remembered:** unchanged. Whether the panel is open, its tab and the turn picked are local to the chat and every visit starts with it closed.
- **What did not change:** the trace, its contract, the availability rules, the back-office switch, the design of the view itself and every consequence above.

## Third amendment 2026-10-05: with no room, the chat takes the screen and the demo panel replaces it

- **What the second amendment said:** below 920px only the detective view replaces the chat; the guide is not offered there; the header button exists only where the mode is offered; turning the mode off returns the chat; the chat takes the whole screen only on phones (480px or less).
- **What it says now:** "no room" means a window under 920px wide or under 500px tall. With no room the chat takes the whole screen and the demo panel, the same one with its two tabs (guide and detective; the guide alone, with its "Solo demo" tag, where the environment does not offer the mode), replaces the chat inside the bubble. The header button "Menú demo" exists always, at every size. The chat and its composer stay mounted and hidden while the panel is in place, so the scroll and the draft survive. Escape or "Volver al chat" returns to the chat. Picking a script, sending one of its lines or copying one into the composer returns to the chat by itself, because the visitor is going to read or edit it there. Turning the mode off leaves the guide, in both places (beside the chat or in place of it); it no longer returns the chat. A resize or a rotation between wide and narrow keeps what was open: the panel, its tab, the turn picked, the script and the draft.
- **Why:** the guide was missing on phones, and a phone in landscape (852x393) got a 245px-high chat window, which is neither a chat nor room for anything else. The demo is run on phones too.
- **Not changed:** the trace and its contract, the availability rules, the back-office switch, the design of the view itself, and that nothing is remembered: every visit starts with the panel closed.

### Note 2026-10-05 (same day): the next line also over the composer

- **What it adds:** where the demo panel is not showing beside the chat (a phone with the menu closed, or a wide window with the panel closed), a band over the composer offers the running script's next message: a label, the line as written (three lines at most) and the same two icon buttons as the guide's next line, send and "Copiar al chat" (the card itself is text, not a button). It disappears at the code step, with the code field, when the script is complete or stopped, and while the panel beside the chat shows the same card; after a send it moves to the next line by itself. **Why:** on a phone the guide is behind "Menú demo" and a visitor who has just sent step 1 has no obvious way to step 2.
- **Also in this note:** the hero's button with the chat already open puts the focus in the composer (the visible one) instead of doing nothing.
- **The rule it amends:** the guide's rule was that nothing of it is inside the conversation. The band sits between the log and the composer, outside the `role="log"` element, so it is not announced and it is not a message; the intent of the rule holds (the conversation the customer reads stays as the customer sees it, and the notice that the script stopped lives only in the panel).
