# Known limits and future work

Written so that a reviewer knows exactly what we tested, what we did not, and what we would do with more time. Ten days are enough for an honest system, not a complete one; we would rather declare the gaps than have them discovered.

## 1. What works and is tested

**TODO at close.** One item per capability, with the number backing it and the scenario covering it.

- [ ] Compromised-card workflow, end to end, in Spanish and Portuguese
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
| SMS | Shown in a simulated panel; email OTP is real |
| Key management | Master key from the environment, not from a KMS ([ADR-0005](adr/0005-application-level-encryption.md)) |
| Second workflow | Added by configuration and covered by a smoke test, not the full suite |
| Multi-tenancy | Anticipated in the data model, not implemented |
| Scalability | Single instance; the scaling path is documented, not exercised ([ADR-0006](adr/0006-single-postgres-pgvector.md)) |

## 3. What we did not do

| Not done | Why |
|---|---|
| Autonomous dispute resolution | A judgment call with monetary impact: our test case for not automating |
| Real biometrics | Requires a certified provider with liveness detection |
| Voice channel | A different problem (transcription, latency, barge-in); adds nothing to the chosen workflow |
| Onboarding and credit origination | Outside the workflow |
| Load testing | We prioritized correctness over performance in the available time |

## 4. Known failure modes

**TODO at close.** The ones we already anticipate and must confirm or rule out with data:

- Degradation in Portuguese relative to Spanish in the classifier, if the labeled sample came out unbalanced
- Cross-language retrieval: question in one language, knowledge in another
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
