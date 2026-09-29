# Button

The chamfered action control: one primary per view, with secondary, danger and ghost for everything else.

## Consumer provides

A visible text label (Spanish, Portuguese or English, sentence case in source; the class uppercases it) and, for icon-only buttons, an `aria-label`. Native `<button>` or `<a>`; no wrapper needed.

## Classes and attributes

| Class / attribute | Effect |
| --- | --- |
| `pb-btn pb-btn--primary` | `violet` fill, `on-violet` label. Hover `violet-hover`. One per view. |
| `pb-btn--secondary` | `surface-100` face, `violet` edge and label. Hover `violet-soft`. |
| `pb-btn--danger` | `crimson` fill, `on-crimson` label. Only for actions that block, cancel or delete. |
| `pb-btn--ghost` | No edge or fill, `ink` label. Hover `surface-200`. Cancel, dismiss, tertiary. |
| `pb-btn--sm` | 32px tall, `cut-sm`. Back-office density. Default is 44px, the customer touch target. |
| `pb-btn--icon` | Square, no padding; add `aria-label`. |
| `pb-btn--block` | Full width. Use on mobile forms. |
| `disabled`, `aria-disabled`, `data-disabled` | `surface-200` face, `ink-muted` label. |
| `aria-checked="true"`, `aria-pressed="true"`, `data-state="checked"` | Primary appearance; use with `role="radio"` for segmented choices. |

```tsx
<button className="pb-btn pb-btn--danger" type="button">
  <i className="pb-ico pb-ico--card-blocked" aria-hidden="true" />Bloquear tarjeta
</button>
```

## Button, action or link

- `pb-btn` (with `pb-btn--ghost` for a quiet one) is a command in a button row or a form: Cancelar, Descartar, Guardar.
- `pb-action` is a follow-up action embedded in a toast, card, banner or chat message: "Abrir bandeja", "Ver comprobante", "Reintentar". Condensed uppercase in `violet`, a trailing `arrow` (or `retry`), no underline at rest; on hover a 2px bar and the arrow step forward, on focus the same plus a `focus` outline. The hit area is 44px tall while the visible box hugs the text. Use it on its own line, usually right-aligned. Never as the primary action of a view.
- `pb-link` is a reference inside running text: `link` color, a 1px `line-strong` underline offset 4px, 2px on hover. It navigates; it does not do anything. Never a bare `<a>` with browser defaults.

```tsx
<a className="pb-action" href="#bandeja">Abrir bandeja<i className="pb-ico pb-ico--arrow" aria-hidden="true" /></a>
```

## Rules

- Label in `label-lg` (Barlow Condensed 15px, 0.1em tracking), uppercase by class. Never type capitals in source.
- Icon leading only, `pb-ico` 16px, `aria-hidden`. The label always stays.
- Focus is a 2px `focus` outline with a 3px offset on the button itself; do not remove it and do not put `clip-path` on the button (the outline and shadow would be cut).
- Danger is not a warning: use it after the customer or agent has understood the consequence; pair with a confirmation, never as a default.
- Do not stack two primaries. Do not use `hazard` colors on a button.
