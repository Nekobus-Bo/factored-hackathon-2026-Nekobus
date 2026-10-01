# Navbar

The landing's top bar: the wordmark set in type, four links, a language switch, a theme toggle and a login button, collapsing into a menu on mobile.

## Consumer provides

The current language (`es`, `pt`, `en`) and theme, the link labels and targets, and handlers for language and theme changes. The login is **decorative in the demo**: there is no authentication, account or session behind it.

| Language | Links | Login |
| --- | --- | --- |
| es | Funciones · Cómo funciona · S² · Ayuda | Ingresar |
| pt | Recursos · Como funciona · S² · Ajuda | Entrar |
| en | Features · How it works · S² · Help | Log in |

## Parts

| Class / attribute | Notes |
| --- | --- |
| `pb-nav` | Sticky `surface-100` bar with a `line-strong` bottom rule. `data-open="true"` opens the collapsed menu. |
| `pb-nav__bar` | 64px row, max 1200px. |
| `pb-nav__brand` | The wordmark "Pattern Blue" in `display` (weight 900, `font-stretch: 62.5%`), color `wordmark`. Type only: there is no symbol. |
| `pb-nav__collapse` | Wraps the links and tools; on desktop it is the rest of the bar, when collapsed it drops below the bar. |
| `pb-nav__link` | Condensed uppercase; a 2px `violet` bar steps in on hover and stays under `aria-current="page"`. |
| `pb-lang` with `pb-lang__btn[role="radio"]` | ES · PT · EN, `aria-checked`, `lang` on each button. |
| `pb-theme` with `pb-theme__btn[role="radio"]` | Sun and moon; sets `data-theme` on `<html>`. |
| `pb-btn pb-btn--secondary` | The login. |
| `pb-nav__menu` | Menu button (`aria-expanded`, `aria-controls`); shown only when collapsed. |
| `pb-nav--compact` | Forces the collapsed layout (previews, narrow containers). Below 800px it applies by itself. |

## Rules

- The theme toggle sets `data-theme` and remembers the choice per viewer (`localStorage`, wrapped in try/catch); without a stored choice it follows `prefers-color-scheme`.
- The language switch changes the page copy and the language the assistant answers in.
- Targets are 44px. The collapsed menu closes when a link is tapped.
- One `<nav>` landmark with a label; the language and theme controls are radio groups with labels.
