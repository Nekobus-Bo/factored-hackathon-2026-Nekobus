# Encoder Package

Specialized decision and extraction models (intent classification, slot extraction, PII) running locally on CPU.

- `encoder.adapters.TFIDFLRAdapter`: lexical baseline (TF-IDF + logistic regression). Needs only scikit-learn.
- `encoder.adapters.GLiNERAdapter`: GLiNER2 zero-shot intents and slots. Needs the `gliner` extra (PyTorch, transformers); it is imported lazily, so the baseline never loads PyTorch.
- `encoder.regex_slots.extract_regex_slots`: conservative regex slots for the baseline (email, card number, card last 4, OTP, amount, currency, transaction and birth dates).

The encoder service (`apps/encoder`) selects one of them with `ENCODER_BACKEND`; see `.env.example`.
