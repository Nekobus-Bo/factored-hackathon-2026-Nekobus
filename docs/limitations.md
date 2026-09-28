# Known limits and future work

Written so that a reviewer knows exactly what we tested, what we did not, and what we would do with more time. Ten days are enough for an honest system, not a complete one; we would rather declare the gaps than have them discovered.

## 1. What works and is tested

**TODO at close.** One item per capability, with the number backing it and the scenario covering it.

- [ ] Compromised-card workflow, end to end, in Spanish, Portuguese and English
- [ ] Identity verification with OTP and state machine
- [ ] Card block with verified receipt and idempotency
- [ ] Structured handoff with all four elements
- [ ] Guardrails configurable from the back office
- [ ] Second workflow added through configuration only
- [ ] Evaluation suite with baseline comparison

## 2. What works with caveats

| Capability | Caveat |
|---|---|
| Document verification | Simulated provider; the interface is real, the verification is not ([ADR-0007](adr/0007-no-llm-biometrics.md)) |
| Outbound OTP channel | Open decision (email, Telegram, WhatsApp or SMS; chosen by feasibility / free tier); currently delivery is simulated in a panel. The model never chooses the channel. |
| Key management | Master key from the environment, not from a KMS ([ADR-0005](adr/0005-application-level-encryption.md)) |
| Second workflow | Added by configuration and covered by a smoke test, not the full suite |
| Multi-tenancy | Anticipated in the data model, not implemented |
| Scalability | Single instance; the scaling path is documented, not exercised ([ADR-0006](adr/0006-single-postgres-pgvector.md)) |
| Audit log external anchoring | Hash chain integrity is enforced append-only in Postgres with triggers and verified via `make verify-audit` (which reports row count and head hash); external anchoring of the head hash (e.g. to a timestamping authority, transparency log, or external store) to detect tail truncation is pending. |
| Outbound PII masking | Regex-based and fail-closed until the encoder's PII spans are wired in (3C). Known misses: names without an intro phrase ("hola, Carlos Gómez aquí"), written-out dates ("March 4, 1988"), digit groups split by spaces. Live mode depends on regex plus encoder spans; replay mode is unaffected |
| Knowledge retrieval evaluation | Measured on a **provisional synthetic** query set (120 validation queries per language, `data/eval/synthetic/retrieval/`), not a human-written one. Vector-only is the default backend (same-language Hit@1 0.494, cross-language 0.508, vs BM25 0.366 / 0.144; [ADR-0006](adr/0006-single-postgres-pgvector.md)). The in-memory `packages/retrieval` index is what was measured; pgvector ingestion and the `kb.search` tool wiring are pending |
| Bare OTP in customer text | While an OTP challenge is pending, any standalone 4-8 digit run in the customer text is masked as an OTP (a small amount typed at that moment is over-masked, on the safe side). Outside a pending challenge, a bare code without a cue ("123456") is not masked |
| Encoder signal in the turn engine | The orchestrator records the encoder's intent, confidence and abstention in the turn metadata only; it is not yet fed to the LLM or used for masking. The encoder receives the raw customer text over the edge network (local service, not a provider) |
| Decision test split | Provisional: `decision.test.provisional.jsonl` was written free-form by an AI agent, not by humans, and has no double labeling. Calibration reports on it carry a "provisional synthetic (not human)" banner. The human set per [labeling-rubric.md](labeling-rubric.md) replaces it |
| Encoder abstention calibration | Boots in uncalibrated mode when ABSTENTION_THRESHOLD is unset (/health 200, /ready and /v1/analyze 503 "uncalibrated"). Calibrated threshold tau is required before serving live traffic ([ADR-0010](adr/0010-model-selection-calibration-harness.md)). |
| Encoder backends | `tfidf_lr` (lexical baseline) returns intents plus regex slots (email, card number, card last 4, OTP, amount, currency, dates) and PII spans for the PII-typed ones (email, card number, OTP, birth date); names, phones, document numbers, document types and merchants need `gliner`. The regex rules were tuned on the synthetic train and validation splits, and the provisional test split has the same author as the rules, so regex slot scores on it are optimistic until the human test set exists. `gliner` refuses to start when the cgroup memory limit is below `ENCODER_GLINER_MIN_MEMORY_MB` (default 4096); an unreadable or unlimited cgroup starts with a warning. `gliner` maps PII-typed slots to PII spans. Measured with `make encoder-bench` on the synthetic validation split (450 messages, single thread, Apple M-series host, 2026-09-27): `tfidf_lr` build 0.15 s, p95 0.22 ms, +43 MB RSS; `gliner` (`fastino/gliner2.5-multi-v1`, fp32) build 18 s, p95 90 ms, peak RSS 3.45 GB. The default demo backend is `tfidf_lr`; `gliner` needs `ENCODER_MEMORY_LIMIT=4g` (the compose default stays 3g), and `ENCODER_QUANTIZED` is read by compose but not implemented. The GLiNER weights come from the Hugging Face cache by model id, without a pinned revision or hash yet (ADR-0010 §5), and on Linux PyTorch comes from the CPU-only index (`pytorch-cpu` in the root `pyproject.toml`; macOS keeps the default wheels for MPS training). The `gliner` image build has not been completed on the dev host yet (Docker disk full) |
| Policy configuration UI | Policy thresholds and tool matrices live in DB `config` schema tables (seeded from env on initial startup per ADR-0002) and support versioned updates; administrative editing via the back-office UI is pending. |
| Read tools vs contract | `account.get_summary` always returns balances: the contract requires both balance fields, so `include_balances=false` cannot omit them. `transaction.list_recent` lists card transactions only, because each item requires a `card_ref`. `card.list` returns `expiry_month`/`expiry_year` as null for synthetic cards (no source data) and derives `card_type` from the account (CREDIT_LINE → CREDIT, otherwise DEBIT) until stored values exist |
| Audit log tail truncation | Tail truncation with the owner disabling triggers is only detectable against an external count/head_hash checkpoint. |
| OTP dev sink and test hook | Outbound OTP delivery channel is an open decision; a delivery port with a dev sink stays in the trusted zone (never returned to the caller or logged in clear text). An explicit test/dev-only hook is exposed for evaluation but disabled by default. |
| `customer.match` timing | A miss spends one decrypt like a hit with birth date, but a miss still probes every equivalent document type (one extra indexed query in the pt market); no constant-time padding of DB round trips |
| U6 evidence in the proposed-system eval | Unmasked-PII-to-provider (U6) evidence comes from the orchestrator side: the masked outbound messages its eval hook exposes, and the replay recordings on disk. Neither is the trusted side; the report labels the provenance. Without the hook, U6 stays "needs human review" and a replay miss cannot be told apart from other turn failures, so it counts as a failure (only a 503 with detail "replay_miss" is reported as not run) |

## 3. What we did not do

| Not done | Why |
|---|---|
| Autonomous dispute resolution | A judgment call with monetary impact: our test case for not automating |
| Real biometrics | Requires a certified provider with liveness detection |
| Voice channel | A different problem (transcription, latency, barge-in); adds nothing to the chosen workflow |
| Onboarding and credit origination | Outside the workflow |
| Load testing | We prioritized correctness over performance in the available time |
| Per-IP rate limiting in banking-core | Banking-core cannot trust client IP relayed by untrusted orchestrator; per-IP limiting belongs at edge/proxy (pending) |

## 4. Known failure modes

**TODO at close.** The ones we already anticipate and must confirm or rule out with data:

- Degradation in Portuguese relative to Spanish in the classifier, if the labeled sample came out unbalanced
- Cross-language retrieval: question in one language, knowledge in another. Measured: vector-only Hit@1 0.508 (mean es/pt/en) against an index restricted to the other languages; BM25 0.144. Same-language search is the default, so this only matters when the KB lacks the customer's language
- Long conversations: context grows and so do cost and latency
- Ambiguity between neighboring intents: TODO, per the confusion matrix
- Unnecessary escalation on legitimate but unforeseen cases: a cost the design accepts ([ADR-0003](adr/0003-deterministic-vs-ai.md))

## 5. What we would do with four more weeks

1. **A real document verification provider**, with thresholds and retry policy.
2. **KMS or HSM** for the master key, with scheduled rotation.
3. **Human-in-the-loop learning**: every agent correction in the back office becomes a labeled example, with periodic retraining and drift monitoring.
4. **Continuous evaluation in production**: sampling real conversations for human review, not just a fixed suite.
5. **Load testing and a read replica** before exposing the system to real volume.
6. **Expand the adversarial suite**, with injection in fields we do not currently treat as hostile.
7. **Full multi-tenancy** on top of the schema separation already anticipated.

## 6. Where else this applies

The engine is not banking-specific. The same core — calibrated classification with abstention, verification state machine, policy engine, structured handoff and audit — applies to any customer service domain where an action has irreversible consequences: telecommunications, insurance, healthcare, logistics. What changes is the tool catalog; the control does not.
