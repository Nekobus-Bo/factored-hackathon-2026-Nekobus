# Landing

The whole simulated Pattern Blue fintech page, assembled from Navbar, Hero, FeatureGrid, HowItWorks, S2PromoCard, FaqAccordion and Footer, with the chat launcher docked at the bottom-right.

## Composition

| Order | Block | Notes |
| --- | --- | --- |
| 1 | `Navbar` (`<header>`) | Sticky. Links go to `#funciones`, `#como-funciona`, `#s2`, `#ayuda`. |
| 2 | `Hero` | `id="top"`. The primary call to action opens the chat. |
| 3 | `FeatureGrid` | `#funciones`. |
| 4 | `HowItWorks` | `#como-funciona`. |
| 5 | `S2PromoCard` | `id="s2"` sits on its `<section>`; the card is centered in a `pb-section__narrow` slot (max 420px). Once per page, between the flow and the FAQ. |
| 6 | `FaqAccordion` | `#ayuda`. |
| 7 | `Footer` | `<footer>`; the language and theme repeated. |
| 8 | Dock | `pb-dock` as the last child of `<body>`: the `pb-launcher` and, when open, a `pb-chat` panel. |

Wrap the sections between the header and the footer in `<main>`.

## The dock

`pb-dock` is a zero-height sticky container pinned to the bottom of the viewport. It holds `pb-dock__panel` (a `ChatBubble` panel, `hidden` until opened) and `pb-dock__launcher` (the `ChatBubble` launcher). The launcher toggles the panel and sets `aria-expanded`; the hero's `data-open-chat` button opens it; opening it moves focus to the composer input; Escape inside the panel closes it and returns focus to the launcher, as does the close button. On a phone the panel takes the width of the screen minus 32px.

## Rules

- **Title cards on the landing**: the hero headline and each section header (`pb-hero__title`, `pb-section__title`) are title cards: `display` 900, uppercase, two or three stacked lines, sized fluidly. Inside the customer app and the back office use `h1` and `h2` in sentence case instead; a title card there is at most one per screen, for a moment that deserves it.
- Hazard stripes never appear on the landing.
- Every number on the page is a product fact. No user counts, ratings, uptime or speed claims.
- The page follows the system theme and language on load; the toggles change them.
- Spacing between sections is `space-12` on phones and `space-16` from 720px. Widths: content max 1200px, 16px side gutters.
