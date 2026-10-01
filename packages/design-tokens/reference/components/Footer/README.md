# Footer

The landing's foot: brand, link groups, the demo note, the legal small print and a compact language and theme control.

## Consumer provides

Link groups (Producto: Funciones · Cómo funciona · S² · Ayuda; Seguridad; Legal), the language and theme handlers, and the legal copy. Link labels match their targets: the page has features, a flow, the S² promo and help, and no accounts or cards pages. The links are placeholders in the demo: they scroll to sections or to the small print; there are no legal pages.

## Parts

| Class | Notes |
| --- | --- |
| `pb-footer`, `pb-footer__inner` | `surface-100` band with a `line-strong` top rule; one column on phones. |
| `pb-footer__brand`, `__wordmark`, `__tag` | The wordmark in type and one line: "Atención bancaria con IA: nada se da por hecho hasta que se verifica." |
| `pb-footer__cols`, `__group`, `__link` | Link groups with `label` headings; links are 44px targets, underlined on hover. |
| `pb-footer__demo` | The note, always present, in `mono` on `surface-200`: "Demo · Factored AI & Data Hackathon 2026 · datos sintéticos". |
| `pb-footer__legal` | Small print: a demonstration project, not a bank or financial entity, no real accounts, cards or money, S² is fictional. |
| `pb-footer__controls` | The same `pb-lang` and `pb-theme` as the Navbar, repeated. |

## Rules

- The demo note and the small print are part of the component and appear in every language.
- No copyright, license or regulator claims that suggest a real bank. The line is "© 2026 Pattern Blue (demo)".
- Keep the language and theme controls in sync with the Navbar's.
