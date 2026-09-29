# PolicyControl

The back-office control panel for a workflow's policy: amount threshold per currency, handoff mode, and the tool-by-state matrix, where the code fixes a floor that configuration can only restrict.

## Consumer provides

The current policy configuration from `banking-core`: `amount_mode` (`flag` or `block`), `thresholds_minor` per currency (minor units; show them in major units), the seed value of each threshold (from `.env`), and for each tool the states the code permits (its floor) and the states currently enabled. Saving sends `amount_mode` and `thresholds_minor` to `PUT /v1/admin/policy-config`. Validation belongs to the backend; this component shows its answer.

## Parts

| Class | Notes |
| --- | --- |
| `pb-card pb-policy`, `pb-policy__sec` | Panel of hairline-separated sections; each with an `h3` and one line of help. |
| `pb-thr` | Threshold row: currency code, `pb-field pb-field--mono` input, and a side column with `pb-thr__seed` (the seed value, plus an `info` chip "Editado" when it differs). |
| `pb-thr__demo` with `pb-gauge--sm` | Optional: the demo charge against the threshold (USD 139.99 vs USD 100.00, `data-state="caution"` when above). Scale is fixed and written under the bar. |
| `pb-modes` with `role="radiogroup"` and two `pb-btn--sm[role="radio"]` | "Handoff recomendado" (`flag`) and "Handoff obligatorio" (`block`), with the effect written under them. |
| `pb-tool` | One tool: `pb-tool__name` (mono), `pb-tool__meta` (the code floor and where it is active), `pb-tool__note`, a master `pb-switch` with its state word. |
| `pb-cells` with `pb-btn pb-btn--sm pb-btn--secondary[role="switch"]` | One cell per FSM state, with `data-fsm`. `aria-checked="true"` is filled (enabled), `false` is outlined (allowed by the code, off), and `aria-disabled="true"` with an `x` glyph is gray (outside the floor). |
| `pb-alert pb-alert--stripe` (caution) | Shown when a widen attempt is refused. |

## Rules

- **Amount thresholds have no code floor.** They are per currency, accept any non-negative value, and are stored in minor units and shown in major units. Show the seed next to the current value (`Semilla USD 500.00`) and mark an edited row. Seeds: USD 500.00, COP 2,000,000, BRL 2,500.00, EUR 500.00.
- **Mode.** Stored values are `flag` and `block`, labeled Handoff recomendado / Handoff obligatorio (Handoff recommended / Handoff required). `block` does not block the card: above the threshold it requires a priority handoff. Say so under the switch.
- **The code floor exists only for tools.** The state-by-tool matrix is set in code; configuration can only restrict a tool below the states the code permits, never widen it. Each row shows the floor and where the tool is active. A cell outside the floor cannot be enabled: clicking it shows the refusal (the API answers 422 to any attempt to widen) in a caution banner with the hazard stripe. The master switch turns the tool off in every state, or back on within its floor.
- The code floor, per tool:

| Tool | Allowed states (floor) |
| --- | --- |
| `card.block`, `card.list`, `transaction.list_recent`, `account.get_summary` | VERIFIED |
| `customer.match` | ANONYMOUS, IDENTIFIED |
| `otp.send` | IDENTIFIED, OTP_PENDING |
| `otp.verify` | OTP_PENDING |
| `handoff.create`, `kb.search` | every state |

- `account.get_summary` (the second workflow, account inquiries) starts disabled and is enabled live from this panel, within VERIFIED.
- Every toggle shows its state in words as well as position or fill. Never rely on fill alone: the master switch carries "Activa" or "Apagada".
- `.env` values are only the initial seed; this panel edits the live configuration and the code floor stays in code.
