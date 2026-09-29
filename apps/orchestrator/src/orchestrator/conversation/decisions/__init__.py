"""Decision points in the turn engine (ADR-0012).

A decision point (DP) is a calibrated local decision (`confirm_gate`,
`block_reason`, ...) served by the encoder. This package is the engine side: it
loads the effects file that says which DP drives which effect, keeps the small
state the effects need between turns, and applies them.

- `config`: the effects file, validated at startup (fail loud).
- `state`: `DecisionState`, persisted with the conversation. No text.
- `records`: what a turn records about each decision. No text.
- `catalog`: the DP ids the encoder serves, cached.
- `effects`: `record`, `select` and `gate`, and the per-turn hooks the engine calls.

The modules do not import each other's heavy parts on purpose: `state` and
`records` are leaves, so the session and conversation models can use them.
"""
