# FaqAccordion

Frequently asked questions as an accordion, built to take Zag and Ark UI accordion attributes.

## Consumer provides

Question and answer pairs. The five today:

1. ¿Qué pasa si pierdo mi tarjeta? The assistant verifies you with a 6-digit code and blocks the card; it confirms only when the receipt was re-read from the database.
2. ¿El asistente puede resolver una disputa? No. It gathers the verified facts and hands the case to a person on the Disputes team.
3. ¿Por qué me pide un código? To check it is you before blocking anything; 6 digits, valid 5 minutes; never requested by phone or email; the email is simulated in the demo.
4. ¿En qué idiomas atiende? Spanish, Portuguese and English.
5. ¿Esto es un banco real? No: a demo of the Factored AI & Data Hackathon 2026 with synthetic data; S² is fictional.

## Parts and attributes

| Part | Class | Zag / Ark attributes it reads |
| --- | --- | --- |
| Root | `pb-faq` | `data-scope="accordion" data-part="root"` |
| Item | `pb-faq__item` | `data-part="item"`, `data-state="open \| closed"` |
| Heading | `pb-faq__heading` | An `<h3>` around the trigger. |
| Trigger | `pb-faq__trigger` | `data-part="item-trigger"`, `data-state`, `aria-expanded`, `aria-controls` |
| Indicator | `pb-faq__indicator` | `data-part="item-indicator"`; holds a `plus` and a `minus` icon, one shown per state |
| Content | `pb-faq__content` | `data-part="item-content"`, `data-state`, `hidden`, `role="region"`, `aria-labelledby` |

The CSS opens on `aria-expanded="true"` or `data-state="open"` and hides content with `hidden` or `data-state="closed"`, so it works with Ark's `Accordion.Item`, `ItemTrigger`, `ItemIndicator` and `ItemContent` given these class names, or with plain markup and your own toggle.

## Rules

- Answers state what the system does, no more. Disputes are resolved by people; say so plainly.
- One item open at a time, collapsible; the first can start open.
- The trigger is a full-width 64px target; its focus outline is drawn inside (`outline-offset: -2px`).
- Motion is a step, not a slide: content appears at once.
