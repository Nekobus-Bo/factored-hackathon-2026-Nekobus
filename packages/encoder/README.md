# Encoder Package

Specialized decision and extraction models (intent classification, slot extraction, PII) running locally on CPU.

- `encoder.adapters.TFIDFLRAdapter`: lexical baseline (TF-IDF + logistic regression). Needs only scikit-learn.
- `encoder.adapters.GLiNERAdapter`: GLiNER2 zero-shot intents and slots. Needs the `gliner` extra (PyTorch, transformers); it is imported lazily, so the baseline never loads PyTorch.
- `encoder.regex_slots.extract_regex_slots`: conservative regex slots for the baseline (email, card number, card last 4, OTP, amount, currency, transaction and birth dates).

The encoder service (`apps/encoder`) selects one of them with `ENCODER_BACKEND`; see `.env.example`.

## Decision points ([ADR-0012](../../docs/adr/0012-decision-points.md))

- `encoder.decision_points`: the calibration artifact (`calibration/decision_points.json`, schema next to it in `calibration/decision_points.schema.json`), its canonical id, a fail-loud loader, and `decide`, the pure function from a backend's probabilities to one outcome (`decided`, `abstained`, `infeasible`, `off`). No artifact ships yet: the service runs in legacy seed mode.
- `encoder.registry`: an artifact names a backend `kind` (`tfidf_lr`, `gliner`, `llm_sidecar`); `register(kind, lazy_loader)` adds one. A model that implements `DecisionAdapter` and declares `kind` and `probability_kind` is then usable by the service and the harness unchanged.
- `encoder.pinning`: a model is pinned by a full 40-hex hub commit and/or the SHA-256 of its weights file, verified against the local cache before it loads.
- To add a backend: implement `DecisionAdapter`, register it, add one entry to `BUILDERS` in `tests/test_adapter_conformance.py` and run `uv run pytest packages/encoder/tests/test_adapter_conformance.py -k <kind>`.
- `tests/fixtures/regenerate.py` rebuilds the test artifact (a fixture, not a calibration).
