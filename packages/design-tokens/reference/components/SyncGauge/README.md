# SyncGauge

A segmented bar that shows a model's calibrated confidence against its decision threshold τ, with the outcome spelled out as decided or abstained.

## Consumer provides

`name` (`head · label`, e.g. `turn_intent · report_lost_card`), `confidence` (calibrated, 0 to 1), `threshold` (τ from configuration, not from code), and `n` segments (default 20). Compute `--on = round(confidence × n)` and `--tau = threshold`; the outcome is `confidence ≥ threshold ? decided : abstained`.

```html
<div class="pb-gauge" data-state="decided" style="--n: 20; --on: 16; --tau: 0.37">
  <div class="pb-gauge__head"><span class="pb-gauge__name">turn_intent · report_lost_card</span><span class="pb-gauge__val">0.82 <small>/ τ 0.37</small></span></div>
  <div class="pb-gauge__track" role="meter" aria-valuemin="0" aria-valuemax="1" aria-valuenow="0.82" aria-valuetext="Confianza 0.82, umbral 0.37: decidido">
    <div class="pb-gauge__fill"></div>
    <span class="pb-gauge__tau"><span class="pb-gauge__taulab">τ 0.37</span></span>
  </div>
  <div class="pb-gauge__foot"><span class="pb-chip" data-tone="success">DECIDED</span></div>
</div>
```

## Variants

| Attribute / class | Effect |
| --- | --- |
| `data-state="decided"` | `sync` segments. |
| `data-state="abstained"` | `alert` segments. The assistant asks instead of acting. |
| `data-state="caution"` | Same `alert` segments, for a value above a limit (a demo charge against a threshold in `PolicyControl`). |
| `data-state="blocked"` | `crimson` segments: a value at a hard stop. Rare. |
| `pb-gauge--sm` | 8px bar, no threshold label; for lists, queues and the promo reactor. |

## Rules

- A decided gauge is a proposal by the model. `banking-core` (FSM and policy) authorizes the action; no caption may imply otherwise.
- Labels are the system's decision points and intents (`turn_intent`, `confirm_gate`, `block_reason`, `handoff_route`, `smalltalk_route` with a label from the intent schema); do not invent new ones for a sample.
- Only for calibrated scores. Never plot a raw softmax or an uncalibrated logit; a full bar would look like certainty.
- Always show the numbers (value and τ) and the outcome word with a glyph. Filled segments are `sync` or `alert` at 3:1 or better, but the words carry the meaning.
- The τ marker is `ink`, 2px, taller than the track. Its label sits above; keep τ between 0.1 and 0.9 so the label does not clip, or set it in the row instead.
- Not a progress bar. Use nothing segmented for loading.
- Thresholds shown here are configuration; the gauge never lets a viewer edit them. Editing is `PolicyControl`.
