# FeatureGrid

A grid of feature cards for the landing, one per capability the product actually has.

## Consumer provides

For each feature: an icon from the set, a title (sentence case, in `display`), one or two sentences, and one fact line in `mono` with its glyph. Only features that exist. The four today:

| Feature | Icon | Fact line |
| --- | --- | --- |
| Bloqueo con comprobante: the card is blocked and the receipt is re-read from the database | `card-blocked` | Verificado contra la base de datos |
| Identidad con código: a 6-digit code valid for 5 minutes (simulated email in the demo) | `mail` | 6 dígitos · 5 min de validez |
| Disputas con una persona: the assistant does not resolve disputes, a human does, with the facts verified | `handoff` | Resolución siempre humana |
| En tu idioma: Spanish, Portuguese and English | `chat` | ES · PT · EN |

## Parts

| Class | Notes |
| --- | --- |
| `pb-section`, `pb-section__head`, `__kicker`, `__title` | The section wrapper and its title-card header (two stacked lines, uppercase). |
| `pb-features` | `<ul>`; auto-fit columns from 216px, one column on phones, four on desktop. |
| `pb-feature` | `<li>` chamfered card (`cut-lg`). |
| `pb-feature__icon` | 44px `violet` plate with the icon in `on-violet`. |
| `pb-feature__title`, `__text`, `__fact` | Title, body, and the mono fact under a hairline. |

## Rules

- Three to four cards. Do not add a feature the product does not have, and never a number that is not a product fact (no user counts, ratings or uptime).
- The fact line is a product fact, never marketing. If the demo simulates something (the email), say so in the text.
- Icons come from the existing set; the icon plate is decorative (`aria-hidden`).
