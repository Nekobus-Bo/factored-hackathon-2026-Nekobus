# StatusChip

A small chamfered label that names a state with a word, a glyph and a color: the six FSM states, the two card statuses and the handoff priority.

## Consumer provides

The state, as `data-state` (kebab-case of the FSM value) or, for priority and generic tones, `data-tone`; a visible word; and one `pb-ico`. Customer-facing screens use the friendly wording (Sin identificar, Código pendiente, Verificado); the back office shows the raw enum (`OTP_PENDING`).

| FSM value | `data-state` | Tokens (text and edge / ground) | Glyph |
| --- | --- | --- | --- |
| ANONYMOUS | `anonymous` | `state-anonymous` / `state-anonymous-bg` | `user-dashed` |
| IDENTIFIED | `identified` | `state-identified` / `state-identified-bg` | `user` |
| OTP_PENDING | `otp-pending` | `state-otp-pending` / `state-otp-pending-bg` | `clock` |
| VERIFIED | `verified` | `state-verified` / `state-verified-bg` | `shield-check` |
| LOCKED | `locked` | `state-locked` / `state-locked-bg` | `lock` |
| HANDED_OFF | `handed-off` | `state-handed-off` / `state-handed-off-bg` | `handoff` |
| card ACTIVE | `active` | `state-active` / `state-active-bg` | `card` |
| card BLOCKED | `blocked` | `state-blocked` / `state-blocked-bg` | `card-blocked` |

Priority uses `data-tone`: URGENT `danger` + `chev2`, HIGH `warning` + `chev1`, NORMAL `neutral` + `minus`. Other tones: `info`, `success`.

```tsx
const chipState = (v: string) => v.toLowerCase().replace(/_/g, "-"); // XState value -> data-state
<span className="pb-chip" data-state={chipState(state)}><i className="pb-ico pb-ico--lock" aria-hidden="true" />LOCKED</span>
```

## Rules

- Color is never the only signal: every chip has a word and a glyph. In the light theme `sync` and `crimson` are close in lightness, so the glyph and word are what tell VERIFIED from LOCKED apart.
- Text is 12px `label` on its own ground; every pair holds 4.5:1 in both themes.
- `pb-chip--live` adds the faint `glow-sync`; use it on VERIFIED while the session is live, nowhere else.
- One chip per fact. Do not use a chip as a button; it is not interactive.
