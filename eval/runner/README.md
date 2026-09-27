# evalrunner

Evaluation runner core for Pattern Blue conversational scenarios.

Loads scenarios from `eval/scenarios`, executes them against a pluggable `SystemUnderTest` (baseline, proposed, or test fake), checks expectations and safety outcome hooks (U1–U8), and generates Markdown reports per `docs/evaluation.md`.
