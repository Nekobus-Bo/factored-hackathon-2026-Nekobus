# Decision Points Calibration Report

> [!WARNING]
> The test split is **provisional synthetic (not human)**: written by an AI agent, 10 rows per intent and language, never double-labeled. It cannot certify a precision of 0.95 (or 0.90): 22 correct of 22 accepted has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted with zero errors.
> Validation shares its generating process with train, so a calibrator fitted on it is over-confident on real traffic. Thresholds here are chosen on validation only; nothing in this report is a guarantee on real customers.
> Every decision point stays in `shadow` until a separate reviewed diff flips it to `enforce` after the sign-off of ADR-0012, Appendix F.5.

- **Run id:** `6601ebbc444e`
- **Date:** 2026-10-01
- **Task:** `decision-points` (ADR-0012, Appendix F)
- **Decision points in this run:** `turn_intent`, `confirm_gate`, `block_reason`, `handoff_route`, `smalltalk_route`, `intent_hint`, `clarify_route`
- **Artifact:** `packages/encoder/calibration/decision_points.distilbert.json` -> `artifact_id` `7738f0b6047f` (official run: merged into the committed artifact)
- **Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, scikit-learn 1.9.1, 12 CPUs (host, single process; not measured under the container limits)

## Provenance and hashes

- **Configuration:** `tools/calibrate/configs/decision_points_distilbert.yaml` (`a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901`)
- **Data (per decision point):**
  - `data/staging/decision_pooled/decision.pooled.train.jsonl` (train): `7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f`
  - `data/staging/decision_pooled/decision.pooled.validation.jsonl` (validation): `c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7`
  - `data/staging/decision_pooled/decision.pooled.test.jsonl` (test): `ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c`
  - `data/eval/synthetic/decision.train.jsonl` (train): `a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984`
  - `data/eval/synthetic/decision.validation.jsonl` (validation): `50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699`
  - `data/eval/synthetic/decision.test.provisional.jsonl` (test): `06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7`
- **Test provenance:** synthetic-provisional
- **Backends:**
  - `gate_tfidf`: `tfidf_lr@map-38e4e1a6/train-sha256:a563c0c445d6`
  - `intent_distilbert`: `hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`

## Certification status

| Decision point | Status | Certified | Detail |
|---|---|:---:|---|
| `turn_intent` | calibrated | no | 8 of 49 scopes clear the Wilson bound |
| `confirm_gate` | calibrated | no | 0 of 6 scopes clear the Wilson bound |
| `block_reason` | calibrated | no | 0 of 15 scopes clear the Wilson bound |
| `handoff_route` | calibrated | no | 0 of 12 scopes clear the Wilson bound |
| `smalltalk_route` | calibrated | no | 0 of 14 scopes clear the Wilson bound |
| `intent_hint` | calibrated | no | 25 of 105 scopes clear the Wilson bound |
| `clarify_route` | calibrated | no | 8 of 49 scopes clear the Wilson bound |

## Findings

The threshold chosen on validation did not hold on the held-out test split for these acted labels: their precision is below the floor even by the point estimate.

| Decision point | Scope | Label | Correct / decided | Precision | Floor |
|---|---|---|---:|---:|---:|
| `turn_intent` | pt | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `turn_intent` | pt-BR | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `turn_intent` | es-CO | `report_stolen_card` | 49/55 | 0.89 | 0.90 |
| `turn_intent` | es | `report_suspicious_activity` | 146/183 | 0.80 | 0.90 |
| `turn_intent` | pt | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `turn_intent` | pt-BR | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `turn_intent` | es-MX | `report_suspicious_activity` | 50/61 | 0.82 | 0.90 |
| `turn_intent` | es-AR | `report_suspicious_activity` | 50/64 | 0.78 | 0.90 |
| `turn_intent` | es-CO | `report_suspicious_activity` | 46/58 | 0.79 | 0.90 |
| `confirm_gate` | es | `deny` | 9/11 | 0.82 | 0.90 |
| `confirm_gate` | pt | `deny` | 9/11 | 0.82 | 0.90 |
| `block_reason` | es | `LOST` | 132/181 | 0.73 | 0.90 |
| `block_reason` | pt | `LOST` | 48/58 | 0.83 | 0.90 |
| `block_reason` | pooled (en) | `LOST` | 4/13 | 0.31 | 0.90 |
| `block_reason` | es | `STOLEN` | 149/188 | 0.79 | 0.90 |
| `block_reason` | pt | `STOLEN` | 47/64 | 0.73 | 0.90 |
| `block_reason` | pooled (en) | `STOLEN` | 10/20 | 0.50 | 0.90 |
| `block_reason` | es | `UNRECOGNIZED_CHARGE` | 141/176 | 0.80 | 0.90 |
| `block_reason` | pt | `UNRECOGNIZED_CHARGE` | 44/68 | 0.65 | 0.90 |
| `block_reason` | pooled (en) | `UNRECOGNIZED_CHARGE` | 6/18 | 0.33 | 0.90 |
| `block_reason` | es | `SUSPICIOUS_ACTIVITY` | 148/191 | 0.77 | 0.90 |
| `block_reason` | pt | `SUSPICIOUS_ACTIVITY` | 48/63 | 0.76 | 0.90 |
| `block_reason` | pooled (en) | `SUSPICIOUS_ACTIVITY` | 10/19 | 0.53 | 0.90 |
| `block_reason` | es | `CUSTOMER_REQUEST` | 139/157 | 0.89 | 0.90 |
| `block_reason` | pt | `CUSTOMER_REQUEST` | 47/62 | 0.76 | 0.90 |
| `block_reason` | pooled (en) | `CUSTOMER_REQUEST` | 5/12 | 0.42 | 0.90 |
| `handoff_route` | es | `DISPUTE` | 138/185 | 0.75 | 0.90 |
| `handoff_route` | pt | `DISPUTE` | 44/67 | 0.66 | 0.90 |
| `handoff_route` | pooled (en) | `DISPUTE` | 6/10 | 0.60 | 0.90 |
| `handoff_route` | es | `FRAUD` | 298/382 | 0.78 | 0.90 |
| `handoff_route` | pt | `FRAUD` | 98/125 | 0.78 | 0.90 |
| `handoff_route` | pooled (en) | `FRAUD` | 20/37 | 0.54 | 0.90 |
| `handoff_route` | es | `UNRECOGNIZED` | 141/171 | 0.82 | 0.90 |
| `handoff_route` | pt | `UNRECOGNIZED` | 42/62 | 0.68 | 0.90 |
| `handoff_route` | pooled (en) | `UNRECOGNIZED` | 6/14 | 0.43 | 0.90 |
| `handoff_route` | es | `HUMAN_REQUEST` | 144/195 | 0.74 | 0.90 |
| `handoff_route` | pt | `HUMAN_REQUEST` | 48/62 | 0.77 | 0.90 |
| `handoff_route` | pooled (en) | `HUMAN_REQUEST` | 10/33 | 0.30 | 0.90 |
| `smalltalk_route` | es | `greeting` | 140/157 | 0.89 | 0.95 |
| `smalltalk_route` | pt | `greeting` | 44/51 | 0.86 | 0.95 |
| `smalltalk_route` | en | `greeting` | 6/7 | 0.86 | 0.95 |
| `smalltalk_route` | pt-BR | `greeting` | 44/51 | 0.86 | 0.95 |
| `smalltalk_route` | es-MX | `greeting` | 45/51 | 0.88 | 0.95 |
| `smalltalk_route` | es-AR | `greeting` | 45/51 | 0.88 | 0.95 |
| `smalltalk_route` | es-CO | `greeting` | 50/55 | 0.91 | 0.95 |
| `smalltalk_route` | es | `out_of_scope` | 123/165 | 0.75 | 0.95 |
| `smalltalk_route` | pt | `out_of_scope` | 30/38 | 0.79 | 0.95 |
| `smalltalk_route` | en | `out_of_scope` | 3/5 | 0.60 | 0.95 |
| `smalltalk_route` | pt-BR | `out_of_scope` | 30/38 | 0.79 | 0.95 |
| `smalltalk_route` | es-MX | `out_of_scope` | 41/57 | 0.72 | 0.95 |
| `smalltalk_route` | es-AR | `out_of_scope` | 43/56 | 0.77 | 0.95 |
| `smalltalk_route` | es-CO | `out_of_scope` | 39/51 | 0.76 | 0.95 |
| `intent_hint` | es | `confirm` | 141/164 | 0.86 | 0.90 |
| `intent_hint` | pt | `confirm` | 47/61 | 0.77 | 0.90 |
| `intent_hint` | pt-BR | `confirm` | 47/61 | 0.77 | 0.90 |
| `intent_hint` | es-MX | `confirm` | 48/57 | 0.84 | 0.90 |
| `intent_hint` | es-AR | `confirm` | 45/55 | 0.82 | 0.90 |
| `intent_hint` | pt | `deny` | 43/50 | 0.86 | 0.90 |
| `intent_hint` | pt-BR | `deny` | 43/50 | 0.86 | 0.90 |
| `intent_hint` | es | `greeting` | 140/159 | 0.88 | 0.90 |
| `intent_hint` | pt | `greeting` | 44/51 | 0.86 | 0.90 |
| `intent_hint` | pt-BR | `greeting` | 44/51 | 0.86 | 0.90 |
| `intent_hint` | es-MX | `greeting` | 45/51 | 0.88 | 0.90 |
| `intent_hint` | es-AR | `greeting` | 45/51 | 0.88 | 0.90 |
| `intent_hint` | es-CO | `greeting` | 50/56 | 0.89 | 0.90 |
| `intent_hint` | es | `out_of_scope` | 123/167 | 0.74 | 0.90 |
| `intent_hint` | pt | `out_of_scope` | 31/39 | 0.79 | 0.90 |
| `intent_hint` | pt-BR | `out_of_scope` | 31/39 | 0.79 | 0.90 |
| `intent_hint` | es-MX | `out_of_scope` | 41/58 | 0.71 | 0.90 |
| `intent_hint` | es-AR | `out_of_scope` | 43/56 | 0.77 | 0.90 |
| `intent_hint` | es-CO | `out_of_scope` | 39/52 | 0.75 | 0.90 |
| `intent_hint` | pt | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `intent_hint` | pt-BR | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `intent_hint` | es-CO | `report_stolen_card` | 49/55 | 0.89 | 0.90 |
| `intent_hint` | es | `report_suspicious_activity` | 146/183 | 0.80 | 0.90 |
| `intent_hint` | pt | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `intent_hint` | pt-BR | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `intent_hint` | es-MX | `report_suspicious_activity` | 50/61 | 0.82 | 0.90 |
| `intent_hint` | es-AR | `report_suspicious_activity` | 50/64 | 0.78 | 0.90 |
| `intent_hint` | es-CO | `report_suspicious_activity` | 46/58 | 0.79 | 0.90 |
| `clarify_route` | pt | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `clarify_route` | pt-BR | `report_stolen_card` | 47/54 | 0.87 | 0.90 |
| `clarify_route` | es-CO | `report_stolen_card` | 49/55 | 0.89 | 0.90 |
| `clarify_route` | es | `report_suspicious_activity` | 146/183 | 0.80 | 0.90 |
| `clarify_route` | pt | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `clarify_route` | pt-BR | `report_suspicious_activity` | 48/59 | 0.81 | 0.90 |
| `clarify_route` | es-MX | `report_suspicious_activity` | 50/61 | 0.82 | 0.90 |
| `clarify_route` | es-AR | `report_suspicious_activity` | 50/64 | 0.78 | 0.90 |
| `clarify_route` | es-CO | `report_suspicious_activity` | 46/58 | 0.79 | 0.90 |

- `turn_intent`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, es-CO, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `confirm_gate`: the constraint rejected nothing on validation in es/confirm, es/deny, pt/confirm, pt/deny, en/confirm, en/deny, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `smalltalk_route`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, es-CO, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `intent_hint`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, es-CO, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `clarify_route`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, es-CO, so those thresholds are only the lowest confidence seen (see each Thresholds table).

## Summary

| Decision point | Language | Status | tau | T | Coverage val | Coverage test | Acted coverage test | ECE pre -> post (test) | Certified |
|---|:---:|---|---|---:|---:|---:|---:|---|:---:|
| `turn_intent` | es | calibrated | 0.339856 | 0.914 | 100.0% | 100.0% | 46.9% | 0.047 -> 0.052 | no |
| `turn_intent` | pt | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 46.4% | 0.062 -> 0.061 | no |
| `turn_intent` | en | calibrated | 0.904958 | 1.667 | 34.0% | 27.3% | 5.3% | 0.219 -> 0.105 | no |
| `turn_intent` | pt-BR | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 46.4% | 0.062 -> 0.061 | no |
| `turn_intent` | es-MX | calibrated | 0.487000 | 0.894 | 100.0% | 99.7% | 46.9% | 0.051 -> 0.057 | no |
| `turn_intent` | es-AR | calibrated | 0.471282 | 0.888 | 100.0% | 99.5% | 46.1% | 0.052 -> 0.060 | no |
| `turn_intent` | es-CO | calibrated | 0.331145 | 0.950 | 100.0% | 100.0% | 47.5% | 0.042 -> 0.044 | no |
| `confirm_gate` | es | calibrated | confirm: 0.880956, deny: 0.742556, other: 0.000000 | 0.122 | 100.0% | 100.0% | 12.0% | 0.184 -> 0.041 | no |
| `confirm_gate` | pt | calibrated | confirm: 0.869226, deny: 0.805281, other: 0.000000 | 0.148 | 100.0% | 99.3% | 12.0% | 0.199 -> 0.039 | no |
| `confirm_gate` | en | calibrated | confirm: 0.987937, deny: 0.999998, other: 0.000000 | 0.116 | 100.0% | 97.3% | 7.3% | 0.210 -> 0.036 | no |
| `block_reason` | es | calibrated | LOST: 0.000459, STOLEN: 0.000302, UNRECOGNIZED_CHARGE: 0.005660, SUSPICIOUS_ACTIVITY: 0.178279, CUSTOMER_REQUEST: 0.000883 | 0.914 | 36.7% | 39.7% | 39.7% | 0.023 -> 0.023 | no |
| `block_reason` | pt | calibrated | LOST: 0.004535, STOLEN: 0.000609, UNRECOGNIZED_CHARGE: 0.001307, SUSPICIOUS_ACTIVITY: 0.412844, CUSTOMER_REQUEST: 0.001723 | 1.010 | 36.5% | 42.0% | 42.0% | 0.029 -> 0.028 | no |
| `block_reason` | en | calibrated | LOST: 0.002689, STOLEN: 0.000924, UNRECOGNIZED_CHARGE: 0.006524, SUSPICIOUS_ACTIVITY: 0.305145, CUSTOMER_REQUEST: 0.007881 | 1.667 | 48.7% | 54.7% | 54.7% | 0.078 -> 0.064 | no |
| `handoff_route` | es | calibrated | DISPUTE: 0.000841, FRAUD: 0.069169, UNRECOGNIZED: 0.001256, HUMAN_REQUEST: 0.000222 | 0.914 | 36.7% | 41.5% | 41.5% | 0.025 -> 0.025 | no |
| `handoff_route` | pt | calibrated | DISPUTE: 0.000860, FRAUD: 0.076438, UNRECOGNIZED: 0.001054, HUMAN_REQUEST: 0.001195 | 1.010 | 36.7% | 42.1% | 42.1% | 0.023 -> 0.023 | no |
| `handoff_route` | en | calibrated | DISPUTE: 0.001013, FRAUD: 0.153112, UNRECOGNIZED: 0.001955, HUMAN_REQUEST: 0.006383 | 1.667 | 52.7% | 62.7% | 62.7% | 0.079 -> 0.062 | no |
| `smalltalk_route` | es | calibrated | 0.502150 | 0.914 | 100.0% | 99.9% | 14.3% | 0.023 -> 0.027 | no |
| `smalltalk_route` | pt | calibrated | 0.562066 | 1.010 | 100.0% | 99.2% | 11.9% | 0.029 -> 0.028 | no |
| `smalltalk_route` | en | calibrated | 0.779321 | 1.667 | 77.3% | 74.0% | 8.0% | 0.135 -> 0.029 | no |
| `smalltalk_route` | pt-BR | calibrated | 0.562066 | 1.010 | 100.0% | 99.2% | 11.9% | 0.029 -> 0.028 | no |
| `smalltalk_route` | es-MX | calibrated | 0.512674 | 0.894 | 100.0% | 99.9% | 14.4% | 0.028 -> 0.033 | no |
| `smalltalk_route` | es-AR | calibrated | 0.538168 | 0.888 | 100.0% | 99.7% | 14.3% | 0.027 -> 0.029 | no |
| `smalltalk_route` | es-CO | calibrated | 0.502779 | 0.950 | 100.0% | 99.9% | 14.1% | 0.023 -> 0.024 | no |
| `intent_hint` | es | calibrated | 0.339856 | 0.914 | 100.0% | 100.0% | 100.0% | 0.047 -> 0.052 | no |
| `intent_hint` | pt | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 98.5% | 0.062 -> 0.061 | no |
| `intent_hint` | en | calibrated | 0.948382 | 1.667 | 0.7% | 0.0% | 0.0% | 0.219 -> 0.105 | no |
| `intent_hint` | pt-BR | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 98.5% | 0.062 -> 0.061 | no |
| `intent_hint` | es-MX | calibrated | 0.487000 | 0.894 | 100.0% | 99.7% | 99.7% | 0.051 -> 0.057 | no |
| `intent_hint` | es-AR | calibrated | 0.471282 | 0.888 | 100.0% | 99.5% | 99.5% | 0.052 -> 0.060 | no |
| `intent_hint` | es-CO | calibrated | 0.331145 | 0.950 | 100.0% | 100.0% | 100.0% | 0.042 -> 0.044 | no |
| `clarify_route` | es | calibrated | 0.339856 | 0.914 | 100.0% | 100.0% | 46.9% | 0.047 -> 0.052 | no |
| `clarify_route` | pt | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 46.4% | 0.062 -> 0.061 | no |
| `clarify_route` | en | calibrated | 0.904958 | 1.667 | 34.0% | 27.3% | 5.3% | 0.219 -> 0.105 | no |
| `clarify_route` | pt-BR | calibrated | 0.530052 | 1.010 | 100.0% | 98.5% | 46.4% | 0.062 -> 0.061 | no |
| `clarify_route` | es-MX | calibrated | 0.487000 | 0.894 | 100.0% | 99.7% | 46.9% | 0.051 -> 0.057 | no |
| `clarify_route` | es-AR | calibrated | 0.471282 | 0.888 | 100.0% | 99.5% | 46.1% | 0.052 -> 0.060 | no |
| `clarify_route` | es-CO | calibrated | 0.331145 | 0.950 | 100.0% | 100.0% | 47.5% | 0.042 -> 0.044 | no |

## `turn_intent`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (8 of 49 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |
| pt-BR | 750 | 1.0101 | 0.062 -> 0.062 |  |
| es-MX | 750 | 0.8942 | 0.033 -> 0.032 |  |
| es-AR | 750 | 0.8878 | 0.040 -> 0.039 |  |
| es-CO | 750 | 0.9503 | 0.055 -> 0.055 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.339856 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.904958 | language |  |
| pt-BR | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.487000 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.471282 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-CO | 0.331145 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 100.0% | 100.0% | 46.9% | 0.922 | 0.047 | 0.052 | yes |
| pt | 750 | 750 | 100.0% | 98.5% | 46.4% | 0.898 | 0.062 | 0.061 | yes |
| en | 150 | 150 | 34.0% | 27.3% | 5.3% | 0.649 | 0.219 | 0.105 | no |
| pt-BR | 750 | 750 | 100.0% | 98.5% | 46.4% | 0.898 | 0.062 | 0.061 | yes |
| es-MX | 750 | 750 | 100.0% | 99.7% | 46.9% | 0.921 | 0.051 | 0.057 | yes |
| es-AR | 750 | 750 | 100.0% | 99.5% | 46.1% | 0.920 | 0.052 | 0.060 | yes |
| es-CO | 750 | 750 | 100.0% | 100.0% | 47.5% | 0.926 | 0.042 | 0.044 | yes |
| all | 6150 | 6150 | 98.4% | 97.8% | 45.8% | 0.911 | 0.055 | 0.055 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `report_lost_card` | 150 | 138 | 132 | 0.957 | 0.908 | 0.880 | 0.90 |
| es | `report_stolen_card` | 150 | 163 | 149 | 0.914 | 0.861 | 0.993 | 0.90 |
| es | `report_suspicious_activity` | 150 | 183 | 146 | 0.798 | 0.734 | 0.973 | 0.90 |
| es | `report_unrecognized_charge` | 150 | 147 | 138 | 0.939 | 0.888 | 0.920 | 0.90 |
| es | `request_card_block` | 150 | 141 | 139 | 0.986 | 0.950 | 0.927 | 0.90 |
| es | `request_dispute` | 150 | 140 | 134 | 0.957 | 0.910 | 0.893 | 0.90 |
| es | `request_human_agent` | 150 | 144 | 141 | 0.979 | 0.941 | 0.940 | 0.90 |
| pt | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| en | `report_lost_card` | 10 | 1 | 1 | 1.000 | 0.207 | 0.100 | 0.90 |
| en | `report_stolen_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_suspicious_activity` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_human_agent` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt-BR | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt-BR | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 61 | 50 | 0.820 | 0.705 | 1.000 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 50 | 47 | 0.940 | 0.838 | 0.940 | 0.90 |
| es-MX | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-MX | `request_dispute` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `request_human_agent` | 50 | 48 | 47 | 0.979 | 0.891 | 0.940 | 0.90 |
| es-AR | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 64 | 50 | 0.781 | 0.666 | 1.000 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-AR | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-AR | `request_dispute` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-AR | `request_human_agent` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-CO | `report_lost_card` | 50 | 46 | 42 | 0.913 | 0.797 | 0.840 | 0.90 |
| es-CO | `report_stolen_card` | 50 | 55 | 49 | 0.891 | 0.782 | 0.980 | 0.90 |
| es-CO | `report_suspicious_activity` | 50 | 58 | 46 | 0.793 | 0.672 | 0.920 | 0.90 |
| es-CO | `report_unrecognized_charge` | 50 | 51 | 47 | 0.922 | 0.815 | 0.940 | 0.90 |
| es-CO | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| es-CO | `request_dispute` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-CO | `request_human_agent` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| all | `report_lost_card` | 410 | 379 | 361 | 0.953 | 0.926 | 0.880 | 0.90 |
| all | `report_stolen_card` | 410 | 434 | 392 | 0.903 | 0.872 | 0.956 | 0.90 |
| all | `report_suspicious_activity` | 410 | 488 | 392 | 0.803 | 0.766 | 0.956 | 0.90 |
| all | `report_unrecognized_charge` | 410 | 382 | 360 | 0.942 | 0.914 | 0.878 | 0.90 |
| all | `request_card_block` | 410 | 380 | 372 | 0.979 | 0.959 | 0.907 | 0.90 |
| all | `request_dispute` | 410 | 366 | 348 | 0.951 | 0.924 | 0.849 | 0.90 |
| all | `request_human_agent` | 410 | 385 | 379 | 0.984 | 0.966 | 0.924 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `check_balance` | 410 | 350 | 346 | 0.989 | 0.971 | 0.844 | not acted on |
| all | `check_recent_transactions` | 410 | 340 | 334 | 0.982 | 0.962 | 0.815 | not acted on |
| all | `confirm` | 410 | 455 | 381 | 0.837 | 0.801 | 0.929 | not acted on |
| all | `deny` | 410 | 400 | 373 | 0.932 | 0.904 | 0.910 | not acted on |
| all | `greeting` | 410 | 423 | 371 | 0.877 | 0.842 | 0.905 | not acted on |
| all | `out_of_scope` | 410 | 411 | 308 | 0.749 | 0.705 | 0.751 | not acted on |
| all | `provide_identity_data` | 410 | 407 | 401 | 0.985 | 0.968 | 0.978 | not acted on |
| all | `provide_otp_code` | 410 | 413 | 409 | 0.990 | 0.975 | 0.998 | not acted on |
| all | `report_lost_card` | 410 | 379 | 361 | 0.953 | 0.926 | 0.880 | 0.90 |
| all | `report_stolen_card` | 410 | 434 | 392 | 0.903 | 0.872 | 0.956 | 0.90 |
| all | `report_suspicious_activity` | 410 | 488 | 392 | 0.803 | 0.766 | 0.956 | 0.90 |
| all | `report_unrecognized_charge` | 410 | 382 | 360 | 0.942 | 0.914 | 0.878 | 0.90 |
| all | `request_card_block` | 410 | 380 | 372 | 0.979 | 0.959 | 0.907 | 0.90 |
| all | `request_dispute` | 410 | 366 | 348 | 0.951 | 0.924 | 0.849 | 0.90 |
| all | `request_human_agent` | 410 | 385 | 379 | 0.984 | 0.966 | 0.924 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `report_lost_card` | 132/138 | 0.908 | 0.90 | yes |  |
| pt | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| en | `report_lost_card` | 1/1 | 0.207 | 0.90 | no | 35 decided with zero errors (has 1/1) |
| pt-BR | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| es-MX | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-AR | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-CO | `report_lost_card` | 42/46 | 0.797 | 0.90 | no | 35 decided with zero errors (has 42/46) |
| es | `report_stolen_card` | 149/163 | 0.861 | 0.90 | no | 35 decided with zero errors (has 149/163) |
| pt | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| en | `report_stolen_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| es-MX | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-AR | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-CO | `report_stolen_card` | 49/55 | 0.782 | 0.90 | no | 35 decided with zero errors (has 49/55) |
| es | `report_suspicious_activity` | 146/183 | 0.734 | 0.90 | no | 35 decided with zero errors (has 146/183) |
| pt | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| en | `report_suspicious_activity` | 4/4 | 0.510 | 0.90 | no | 35 decided with zero errors (has 4/4) |
| pt-BR | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| es-MX | `report_suspicious_activity` | 50/61 | 0.705 | 0.90 | no | 35 decided with zero errors (has 50/61) |
| es-AR | `report_suspicious_activity` | 50/64 | 0.666 | 0.90 | no | 35 decided with zero errors (has 50/64) |
| es-CO | `report_suspicious_activity` | 46/58 | 0.672 | 0.90 | no | 35 decided with zero errors (has 46/58) |
| es | `report_unrecognized_charge` | 138/147 | 0.888 | 0.90 | no | 35 decided with zero errors (has 138/147) |
| pt | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| en | `report_unrecognized_charge` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| es-MX | `report_unrecognized_charge` | 47/50 | 0.838 | 0.90 | no | 35 decided with zero errors (has 47/50) |
| es-AR | `report_unrecognized_charge` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es-CO | `report_unrecognized_charge` | 47/51 | 0.815 | 0.90 | no | 35 decided with zero errors (has 47/51) |
| es | `request_card_block` | 139/141 | 0.950 | 0.90 | yes |  |
| pt | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es-MX | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-AR | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-CO | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es | `request_dispute` | 134/140 | 0.910 | 0.90 | yes |  |
| pt | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| en | `request_dispute` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| es-MX | `request_dispute` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-AR | `request_dispute` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_dispute` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es | `request_human_agent` | 141/144 | 0.941 | 0.90 | yes |  |
| pt | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| en | `request_human_agent` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| pt-BR | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| es-MX | `request_human_agent` | 47/48 | 0.891 | 0.90 | no | 35 decided with zero errors (has 47/48) |
| es-AR | `request_human_agent` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_human_agent` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc | es-CO: n, conf, acc |
|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 1, 0.27, 0.00 | 0 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.37, 0.00 | 1, 0.37, 0.00 | 9, 0.35, 0.33 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 2, 0.36, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.23 | 3, 0.47, 0.00 | 14, 0.45, 0.36 | 3, 0.47, 0.00 | 1, 0.42, 0.00 | 5, 0.46, 0.00 | 7, 0.45, 0.43 |
| 0.5-0.6 | 22, 0.55, 0.45 | 18, 0.55, 0.44 | 14, 0.55, 0.36 | 18, 0.55, 0.44 | 8, 0.55, 0.12 | 4, 0.58, 1.00 | 11, 0.55, 0.45 |
| 0.6-0.7 | 29, 0.65, 0.41 | 13, 0.64, 0.31 | 13, 0.65, 0.77 | 13, 0.64, 0.31 | 5, 0.67, 0.60 | 14, 0.65, 0.43 | 6, 0.64, 0.33 |
| 0.7-0.8 | 38, 0.76, 0.61 | 20, 0.74, 0.40 | 24, 0.75, 0.54 | 20, 0.74, 0.40 | 19, 0.76, 0.53 | 11, 0.76, 0.64 | 15, 0.77, 0.47 |
| 0.8-0.9 | 62, 0.85, 0.63 | 25, 0.86, 0.68 | 31, 0.86, 0.74 | 25, 0.86, 0.68 | 18, 0.85, 0.56 | 17, 0.85, 0.82 | 16, 0.85, 0.62 |
| 0.9-1.0 | 2082, 0.99, 0.95 | 670, 0.99, 0.95 | 44, 0.93, 0.95 | 670, 0.99, 0.95 | 698, 0.99, 0.95 | 698, 0.99, 0.94 | 693, 0.99, 0.96 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 346 | 4 | 13 | 0 | 0 | 25 | 0 | 0 | 4 | 0 | 0 | 2 | 0 | 2 | 0 | 14 |
| `check_recent_transactions` | 0 | 334 | 3 | 0 | 0 | 52 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 6 | 0 | 11 |
| `confirm` | 2 | 0 | 381 | 1 | 11 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 7 |
| `deny` | 0 | 0 | 28 | 373 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `greeting` | 2 | 0 | 14 | 6 | 371 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 4 | 9 |
| `out_of_scope` | 0 | 2 | 12 | 16 | 31 | 308 | 0 | 0 | 0 | 2 | 18 | 0 | 2 | 0 | 0 | 19 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 401 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 409 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 361 | 32 | 6 | 0 | 2 | 0 | 0 | 9 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 392 | 6 | 0 | 0 | 0 | 0 | 10 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 2 | 392 | 2 | 0 | 2 | 2 | 6 |
| `report_unrecognized_charge` | 0 | 0 | 0 | 2 | 0 | 10 | 0 | 0 | 2 | 2 | 20 | 360 | 0 | 4 | 0 | 10 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 24 | 0 | 372 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 8 | 6 | 0 | 0 | 0 | 10 | 18 | 4 | 348 | 0 | 16 |
| `request_human_agent` | 0 | 0 | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 2 | 379 | 9 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "turn_intent": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "es-AR": {
            "T": 0.88783
          },
          "es-CO": {
            "T": 0.950337
          },
          "es-MX": {
            "T": 0.894171
          },
          "pt": {
            "T": 1.010123
          },
          "pt-BR": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ],
        "metric": "precision",
        "n_min": 10,
        "p_min": 0.9
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.0533,
            "certified": false,
            "coverage_test": 0.2733,
            "coverage_val": 0.34,
            "ece_post": 0.1055,
            "ece_pre": 0.219,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                1,
                1,
                0.2065
              ],
              "report_stolen_card": [
                0,
                0,
                null
              ],
              "report_suspicious_activity": [
                4,
                4,
                0.5101
              ],
              "report_unrecognized_charge": [
                0,
                0,
                null
              ],
              "request_card_block": [
                0,
                0,
                null
              ],
              "request_dispute": [
                0,
                0,
                null
              ],
              "request_human_agent": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "report_lost_card": 0.1,
              "report_stolen_card": 0.0,
              "report_suspicious_activity": 0.4,
              "report_unrecognized_charge": 0.0,
              "request_card_block": 0.0,
              "request_dispute": 0.0,
              "request_human_agent": 0.3
            }
          },
          "es": {
            "acted_coverage_test": 0.4693,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0522,
            "ece_pre": 0.0473,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "report_lost_card": [
                132,
                138,
                0.9084
              ],
              "report_stolen_card": [
                149,
                163,
                0.861
              ],
              "report_suspicious_activity": [
                146,
                183,
                0.7338
              ],
              "report_unrecognized_charge": [
                138,
                147,
                0.8877
              ],
              "request_card_block": [
                139,
                141,
                0.9498
              ],
              "request_dispute": [
                134,
                140,
                0.9097
              ],
              "request_human_agent": [
                141,
                144,
                0.9405
              ]
            },
            "recall_test": {
              "report_lost_card": 0.88,
              "report_stolen_card": 0.9933,
              "report_suspicious_activity": 0.9733,
              "report_unrecognized_charge": 0.92,
              "request_card_block": 0.9267,
              "request_dispute": 0.8933,
              "request_human_agent": 0.94
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.4613,
            "certified": false,
            "coverage_test": 0.9947,
            "coverage_val": 1.0,
            "ece_post": 0.0604,
            "ece_pre": 0.0515,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                64,
                0.6657
              ],
              "report_unrecognized_charge": [
                44,
                46,
                0.8547
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                44,
                45,
                0.8843
              ],
              "request_human_agent": [
                44,
                45,
                0.8843
              ]
            },
            "recall_test": {
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.92,
              "request_dispute": 0.88,
              "request_human_agent": 0.88
            }
          },
          "es-CO": {
            "acted_coverage_test": 0.4747,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0444,
            "ece_pre": 0.0416,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                42,
                46,
                0.7968
              ],
              "report_stolen_card": [
                49,
                55,
                0.7817
              ],
              "report_suspicious_activity": [
                46,
                58,
                0.6723
              ],
              "report_unrecognized_charge": [
                47,
                51,
                0.815
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                44,
                46,
                0.8547
              ],
              "request_human_agent": [
                50,
                51,
                0.897
              ]
            },
            "recall_test": {
              "report_lost_card": 0.84,
              "report_stolen_card": 0.98,
              "report_suspicious_activity": 0.92,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.94,
              "request_dispute": 0.88,
              "request_human_agent": 1.0
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.4693,
            "certified": false,
            "coverage_test": 0.9973,
            "coverage_val": 1.0,
            "ece_post": 0.0567,
            "ece_pre": 0.0509,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                61,
                0.7053
              ],
              "report_unrecognized_charge": [
                47,
                50,
                0.8378
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                46,
                47,
                0.8889
              ],
              "request_human_agent": [
                47,
                48,
                0.891
              ]
            },
            "recall_test": {
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.92,
              "request_dispute": 0.92,
              "request_human_agent": 0.94
            }
          },
          "pt": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.904958,
        "es": 0.339856,
        "es-AR": 0.471282,
        "es-CO": 0.331145,
        "es-MX": 0.487,
        "pt": 0.530052,
        "pt-BR": 0.530052
      },
      "view": {
        "kind": "labels",
        "labels": [
          "check_balance",
          "check_recent_transactions",
          "confirm",
          "deny",
          "greeting",
          "out_of_scope",
          "provide_identity_data",
          "provide_otp_code",
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ]
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.es-AR.T: 1.075648 -> 0.88783`
- `+ calibrator.by_lang.es-CO.T = 0.950337`
- `~ calibrator.by_lang.es-MX.T: 0.994325 -> 0.894171`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ calibrator.by_lang.pt-BR.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.16 -> 0.0533`
- `~ evidence.per_lang.en.coverage_test: 0.4533 -> 0.2733`
- `~ evidence.per_lang.en.coverage_val: 0.5133 -> 0.34`
- `~ evidence.per_lang.en.ece_post: 0.112 -> 0.1055`
- `~ evidence.per_lang.en.ece_pre: 0.2056 -> 0.219`
- `~ evidence.per_lang.en.precision_test.report_lost_card: [0, 0, None] -> [1, 1, 0.2065]`
- `~ evidence.per_lang.en.precision_test.report_stolen_card: [3, 3, 0.4385] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.report_suspicious_activity: [6, 7, 0.4869] -> [4, 4, 0.5101]`
- `~ evidence.per_lang.en.precision_test.report_unrecognized_charge: [5, 5, 0.5655] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.request_dispute: [1, 1, 0.2065] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.request_human_agent: [8, 8, 0.6756] -> [3, 3, 0.4385]`
- `~ evidence.per_lang.en.recall_test.report_lost_card: 0.0 -> 0.1`
- `~ evidence.per_lang.en.recall_test.report_stolen_card: 0.3 -> 0.0`
- `~ evidence.per_lang.en.recall_test.report_suspicious_activity: 0.6 -> 0.4`
- `~ evidence.per_lang.en.recall_test.report_unrecognized_charge: 0.5 -> 0.0`
- `~ evidence.per_lang.en.recall_test.request_dispute: 0.1 -> 0.0`
- `~ evidence.per_lang.en.recall_test.request_human_agent: 0.8 -> 0.3`
- `~ evidence.per_lang.es.acted_coverage_test: 0.462 -> 0.4693`
- `~ evidence.per_lang.es.coverage_test: 0.9887 -> 1.0`
- `~ evidence.per_lang.es.ece_post: 0.0313 -> 0.0522`
- `~ evidence.per_lang.es.ece_pre: 0.0343 -> 0.0473`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.report_lost_card: [96, 100, 0.9016] -> [132, 138, 0.9084]`
- `~ evidence.per_lang.es.precision_test.report_stolen_card: [100, 108, 0.8606] -> [149, 163, 0.861]`
- `~ evidence.per_lang.es.precision_test.report_suspicious_activity: [90, 99, 0.8362] -> [146, 183, 0.7338]`
- `~ evidence.per_lang.es.precision_test.report_unrecognized_charge: [96, 109, 0.8066] -> [138, 147, 0.8877]`
- `~ evidence.per_lang.es.precision_test.request_card_block: [91, 91, 0.9595] -> [139, 141, 0.9498]`
- `~ evidence.per_lang.es.precision_test.request_dispute: [84, 85, 0.9363] -> [134, 140, 0.9097]`
- `~ evidence.per_lang.es.precision_test.request_human_agent: [95, 101, 0.8764] -> [141, 144, 0.9405]`
- `~ evidence.per_lang.es.recall_test.report_lost_card: 0.96 -> 0.88`
- `~ evidence.per_lang.es.recall_test.report_stolen_card: 1.0 -> 0.9933`
- `~ evidence.per_lang.es.recall_test.report_suspicious_activity: 0.9 -> 0.9733`
- `~ evidence.per_lang.es.recall_test.report_unrecognized_charge: 0.96 -> 0.92`
- `~ evidence.per_lang.es.recall_test.request_card_block: 0.91 -> 0.9267`
- `~ evidence.per_lang.es.recall_test.request_dispute: 0.84 -> 0.8933`
- `~ evidence.per_lang.es.recall_test.request_human_agent: 0.95 -> 0.94`
- `~ evidence.per_lang.es-AR.acted_coverage_test: 0.4587 -> 0.4613`
- `~ evidence.per_lang.es-AR.coverage_test: 0.9867 -> 0.9947`
- `~ evidence.per_lang.es-AR.ece_post: 0.0298 -> 0.0604`
- `~ evidence.per_lang.es-AR.ece_pre: 0.0365 -> 0.0515`
- `~ evidence.per_lang.es-AR.precision_test.report_lost_card: [48, 50, 0.8654] -> [45, 46, 0.8866]`
- `~ evidence.per_lang.es-AR.precision_test.report_stolen_card: [50, 55, 0.8042] -> [50, 54, 0.8245]`
- `~ evidence.per_lang.es-AR.precision_test.report_suspicious_activity: [45, 51, 0.7662] -> [50, 64, 0.6657]`
- `~ evidence.per_lang.es-AR.precision_test.report_unrecognized_charge: [48, 54, 0.7781] -> [44, 46, 0.8547]`
- `~ evidence.per_lang.es-AR.precision_test.request_card_block: [44, 44, 0.9197] -> [46, 46, 0.9229]`
- `~ evidence.per_lang.es-AR.precision_test.request_dispute: [41, 42, 0.8768] -> [44, 45, 0.8843]`
- `~ evidence.per_lang.es-AR.precision_test.request_human_agent: [45, 48, 0.8316] -> [44, 45, 0.8843]`
- `~ evidence.per_lang.es-AR.recall_test.report_lost_card: 0.96 -> 0.9`
- `~ evidence.per_lang.es-AR.recall_test.report_suspicious_activity: 0.9 -> 1.0`
- `~ evidence.per_lang.es-AR.recall_test.report_unrecognized_charge: 0.96 -> 0.88`
- `~ evidence.per_lang.es-AR.recall_test.request_card_block: 0.88 -> 0.92`
- `~ evidence.per_lang.es-AR.recall_test.request_dispute: 0.82 -> 0.88`
- `~ evidence.per_lang.es-AR.recall_test.request_human_agent: 0.9 -> 0.88`
- `+ evidence.per_lang.es-CO.acted_coverage_test = 0.4747`
- `+ evidence.per_lang.es-CO.certified = False`
- `+ evidence.per_lang.es-CO.coverage_test = 1.0`
- `+ evidence.per_lang.es-CO.coverage_val = 1.0`
- `+ evidence.per_lang.es-CO.ece_post = 0.0444`
- `+ evidence.per_lang.es-CO.ece_pre = 0.0416`
- `+ evidence.per_lang.es-CO.n_test = 750`
- `+ evidence.per_lang.es-CO.n_val = 750`
- `+ evidence.per_lang.es-CO.precision_test.report_lost_card = [42, 46, 0.7968]`
- `+ evidence.per_lang.es-CO.precision_test.report_stolen_card = [49, 55, 0.7817]`
- `+ evidence.per_lang.es-CO.precision_test.report_suspicious_activity = [46, 58, 0.6723]`
- `+ evidence.per_lang.es-CO.precision_test.report_unrecognized_charge = [47, 51, 0.815]`
- `+ evidence.per_lang.es-CO.precision_test.request_card_block = [47, 49, 0.8629]`
- `+ evidence.per_lang.es-CO.precision_test.request_dispute = [44, 46, 0.8547]`
- `+ evidence.per_lang.es-CO.precision_test.request_human_agent = [50, 51, 0.897]`
- `... and 65 more changed fields`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (8 of 49 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `confirm_gate`

- **View:** `confirm`, `deny`, `other` (labels)
- **Acted labels and precision floor:** `confirm` >= 0.95, `deny` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language_per_label`; **calibrator:** `temperature`
- **Backend:** `gate_tfidf` (`tfidf_lr@map-38e4e1a6/train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.17 ms, p95 0.18 ms (budget `timeout_ms` 200); RAM model+inference 5.6 MB
- **Status written:** `calibrated`; certified: **no** (0 of 6 scopes clear the Wilson bound)

### Candidate selection

'gate_tfidf' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 150 | 0.1224 | 0.189 -> 0.015 |  |
| pt | 150 | 0.1485 | 0.219 -> 0.017 |  |
| en | 150 | 0.1158 | 0.203 -> 0.007 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | confirm: 0.880956, deny: 0.742556, other: 0.000000 | language | `confirm`: not binding (every prediction accepted); `deny`: not binding (every prediction accepted) |
| pt | confirm: 0.869226, deny: 0.805281, other: 0.000000 | language | `confirm`: not binding (every prediction accepted); `deny`: not binding (every prediction accepted) |
| en | confirm: 0.987937, deny: 0.999998, other: 0.000000 | language | `confirm`: not binding (every prediction accepted); `deny`: not binding (every prediction accepted) |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 100.0% | 100.0% | 12.0% | 0.886 | 0.184 | 0.041 | yes |
| pt | 150 | 150 | 100.0% | 99.3% | 12.0% | 0.872 | 0.199 | 0.039 | yes |
| en | 150 | 150 | 100.0% | 97.3% | 7.3% | 0.898 | 0.210 | 0.036 | yes |
| all | 450 | 450 | 100.0% | 98.9% | 10.4% | 0.886 | 0.186 | 0.035 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `confirm` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.95 |
| es | `deny` | 10 | 11 | 9 | 0.818 | 0.523 | 0.900 | 0.90 |
| pt | `confirm` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.95 |
| pt | `deny` | 10 | 11 | 9 | 0.818 | 0.523 | 0.900 | 0.90 |
| en | `confirm` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.95 |
| en | `deny` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| all | `confirm` | 30 | 21 | 21 | 1.000 | 0.845 | 0.700 | 0.95 |
| all | `deny` | 30 | 26 | 22 | 0.846 | 0.665 | 0.733 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `confirm` | 30 | 21 | 21 | 1.000 | 0.845 | 0.700 | 0.95 |
| all | `deny` | 30 | 26 | 22 | 0.846 | 0.665 | 0.733 | 0.90 |
| all | `other` | 390 | 398 | 385 | 0.967 | 0.945 | 0.987 | not acted on |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `confirm` | 7/7 | 0.646 | 0.95 | no | 73 decided with zero errors (has 7/7) |
| pt | `confirm` | 7/7 | 0.646 | 0.95 | no | 73 decided with zero errors (has 7/7) |
| en | `confirm` | 7/7 | 0.646 | 0.95 | no | 73 decided with zero errors (has 7/7) |
| es | `deny` | 9/11 | 0.523 | 0.90 | no | 35 decided with zero errors (has 9/11) |
| pt | `deny` | 9/11 | 0.523 | 0.90 | no | 35 decided with zero errors (has 9/11) |
| en | `deny` | 4/4 | 0.510 | 0.90 | no | 35 decided with zero errors (has 4/4) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 0 |
| 0.3-0.4 | 0 | 0 | 0 |
| 0.4-0.5 | 0 | 0 | 0 |
| 0.5-0.6 | 0 | 0 | 0 |
| 0.6-0.7 | 0 | 1, 0.66, 0.00 | 0 |
| 0.7-0.8 | 1, 0.75, 1.00 | 1, 0.76, 0.00 | 2, 0.77, 1.00 |
| 0.8-0.9 | 1, 0.86, 0.00 | 2, 0.85, 0.00 | 0 |
| 0.9-1.0 | 148, 1.00, 0.97 | 146, 1.00, 0.98 | 148, 1.00, 0.97 |

### Confusion on test, languages pooled

| Truth \ decided | `confirm` | `deny` | `other` | `(abstained)` |
|---|---:|---:|---:|---:|
| `confirm` | 21 | 0 | 8 | 1 |
| `deny` | 0 | 22 | 5 | 3 |
| `other` | 0 | 4 | 385 | 1 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "gate_tfidf": {
      "cost_class": "low",
      "kind": "tfidf_lr",
      "labels": [
        "confirm",
        "deny",
        "other"
      ],
      "local_only": true,
      "model_id": "tfidf_lr@map-38e4e1a6/train-sha256:a563c0c445d6",
      "params": {},
      "probability_kind": "distribution",
      "timeout_ms": 200,
      "train": {
        "label_map": {
          "*": "other",
          "confirm": "confirm",
          "deny": "deny"
        },
        "path": "data/eval/synthetic/decision.train.jsonl",
        "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
      }
    }
  },
  "decision_points": {
    "confirm_gate": {
      "always_on": true,
      "backend": "gate_tfidf",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 0.115797
          },
          "es": {
            "T": 0.122404
          },
          "pt": {
            "T": 0.148454
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "confirm",
          "deny"
        ],
        "metric": "precision",
        "n_min": 10,
        "p_min": {
          "confirm": 0.95,
          "deny": 0.9
        }
      },
      "enabled": true,
      "evidence": {
        "candidate": "gate_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/eval/synthetic/decision.test.provisional.jsonl",
            "sha256": "06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7"
          },
          "train": {
            "path": "data/eval/synthetic/decision.train.jsonl",
            "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
          },
          "validation": {
            "path": "data/eval/synthetic/decision.validation.jsonl",
            "sha256": "50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.0733,
            "certified": false,
            "coverage_test": 0.9733,
            "coverage_val": 1.0,
            "ece_post": 0.0359,
            "ece_pre": 0.2096,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "confirm": [
                7,
                7,
                0.6457
              ],
              "deny": [
                4,
                4,
                0.5101
              ]
            },
            "recall_test": {
              "confirm": 0.7,
              "deny": 0.4
            }
          },
          "es": {
            "acted_coverage_test": 0.12,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0406,
            "ece_pre": 0.1845,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "confirm": [
                7,
                7,
                0.6457
              ],
              "deny": [
                9,
                11,
                0.523
              ]
            },
            "recall_test": {
              "confirm": 0.7,
              "deny": 0.9
            }
          },
          "pt": {
            "acted_coverage_test": 0.12,
            "certified": false,
            "coverage_test": 0.9933,
            "coverage_val": 1.0,
            "ece_post": 0.0394,
            "ece_pre": 0.1989,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "confirm": [
                7,
                7,
                0.6457
              ],
              "deny": [
                9,
                11,
                0.523
              ]
            },
            "recall_test": {
              "confirm": 0.7,
              "deny": 0.9
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": {
          "confirm": 0.987937,
          "deny": 0.999998,
          "other": 0.0
        },
        "es": {
          "confirm": 0.880956,
          "deny": 0.742556,
          "other": 0.0
        },
        "pt": {
          "confirm": 0.869226,
          "deny": 0.805281,
          "other": 0.0
        }
      },
      "view": {
        "kind": "labels",
        "labels": [
          "confirm",
          "deny",
          "other"
        ]
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 6 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 5.6 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `block_reason`

- **View:** `LOST`, `STOLEN`, `UNRECOGNIZED_CHARGE`, `SUSPICIOUS_ACTIVITY`, `CUSTOMER_REQUEST` (groups)
- **Acted labels and precision floor:** `LOST` >= 0.90, `STOLEN` >= 0.90, `UNRECOGNIZED_CHARGE` >= 0.90, `SUSPICIOUS_ACTIVITY` >= 0.90, `CUSTOMER_REQUEST` >= 0.90
- **Selection rule on validation:** `point` precision, at least 30 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_label_pooled`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (0 of 15 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | LOST: 0.000459, STOLEN: 0.000302, UNRECOGNIZED_CHARGE: 0.005660, SUSPICIOUS_ACTIVITY: 0.178279, CUSTOMER_REQUEST: 0.000883 | language |  |
| pt | LOST: 0.004535, STOLEN: 0.000609, UNRECOGNIZED_CHARGE: 0.001307, SUSPICIOUS_ACTIVITY: 0.412844, CUSTOMER_REQUEST: 0.001723 | language |  |
| en | LOST: 0.002689, STOLEN: 0.000924, UNRECOGNIZED_CHARGE: 0.006524, SUSPICIOUS_ACTIVITY: 0.305145, CUSTOMER_REQUEST: 0.007881 | pooled |  |
| * | LOST: 0.002689, STOLEN: 0.000924, UNRECOGNIZED_CHARGE: 0.006524, SUSPICIOUS_ACTIVITY: 0.305145, CUSTOMER_REQUEST: 0.007881 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 36.7% | 39.7% | 39.7% | 0.488 | 0.023 | 0.023 | yes |
| pt | 750 | 750 | 36.5% | 42.0% | 42.0% | 0.482 | 0.029 | 0.028 | yes |
| en | 150 | 150 | 48.7% | 54.7% | 54.7% | 0.378 | 0.078 | 0.064 | yes |
| all | 3150 | 3150 | 37.2% | 41.0% | 41.0% | 0.481 | 0.023 | 0.023 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `LOST` | 150 | 181 | 132 | 0.729 | 0.660 | 0.880 | 0.90 |
| es | `STOLEN` | 150 | 188 | 149 | 0.793 | 0.729 | 0.993 | 0.90 |
| es | `UNRECOGNIZED_CHARGE` | 150 | 176 | 141 | 0.801 | 0.736 | 0.940 | 0.90 |
| es | `SUSPICIOUS_ACTIVITY` | 150 | 191 | 148 | 0.775 | 0.711 | 0.987 | 0.90 |
| es | `CUSTOMER_REQUEST` | 150 | 157 | 139 | 0.885 | 0.826 | 0.927 | 0.90 |
| pt | `LOST` | 50 | 58 | 48 | 0.828 | 0.711 | 0.960 | 0.90 |
| pt | `STOLEN` | 50 | 64 | 47 | 0.734 | 0.615 | 0.940 | 0.90 |
| pt | `UNRECOGNIZED_CHARGE` | 50 | 68 | 44 | 0.647 | 0.528 | 0.880 | 0.90 |
| pt | `SUSPICIOUS_ACTIVITY` | 50 | 63 | 48 | 0.762 | 0.644 | 0.960 | 0.90 |
| pt | `CUSTOMER_REQUEST` | 50 | 62 | 47 | 0.758 | 0.638 | 0.940 | 0.90 |
| en | `LOST` | 10 | 13 | 4 | 0.308 | 0.127 | 0.400 | 0.90 |
| en | `STOLEN` | 10 | 20 | 10 | 0.500 | 0.299 | 1.000 | 0.90 |
| en | `UNRECOGNIZED_CHARGE` | 10 | 18 | 6 | 0.333 | 0.163 | 0.600 | 0.90 |
| en | `SUSPICIOUS_ACTIVITY` | 10 | 19 | 10 | 0.526 | 0.317 | 1.000 | 0.90 |
| en | `CUSTOMER_REQUEST` | 10 | 12 | 5 | 0.417 | 0.193 | 0.500 | 0.90 |
| all | `LOST` | 210 | 252 | 184 | 0.730 | 0.672 | 0.876 | 0.90 |
| all | `STOLEN` | 210 | 272 | 206 | 0.757 | 0.703 | 0.981 | 0.90 |
| all | `UNRECOGNIZED_CHARGE` | 210 | 262 | 191 | 0.729 | 0.672 | 0.910 | 0.90 |
| all | `SUSPICIOUS_ACTIVITY` | 210 | 273 | 206 | 0.755 | 0.700 | 0.981 | 0.90 |
| all | `CUSTOMER_REQUEST` | 210 | 231 | 191 | 0.827 | 0.773 | 0.910 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `LOST` | 132/181 | 0.660 | 0.90 | no | 35 decided with zero errors (has 132/181) |
| pt | `LOST` | 48/58 | 0.711 | 0.90 | no | 35 decided with zero errors (has 48/58) |
| pooled (en) | `LOST` | 4/13 | 0.127 | 0.90 | no | 35 decided with zero errors (has 4/13) |
| es | `STOLEN` | 149/188 | 0.729 | 0.90 | no | 35 decided with zero errors (has 149/188) |
| pt | `STOLEN` | 47/64 | 0.615 | 0.90 | no | 35 decided with zero errors (has 47/64) |
| pooled (en) | `STOLEN` | 10/20 | 0.299 | 0.90 | no | 35 decided with zero errors (has 10/20) |
| es | `UNRECOGNIZED_CHARGE` | 141/176 | 0.736 | 0.90 | no | 35 decided with zero errors (has 141/176) |
| pt | `UNRECOGNIZED_CHARGE` | 44/68 | 0.528 | 0.90 | no | 35 decided with zero errors (has 44/68) |
| pooled (en) | `UNRECOGNIZED_CHARGE` | 6/18 | 0.163 | 0.90 | no | 35 decided with zero errors (has 6/18) |
| es | `SUSPICIOUS_ACTIVITY` | 148/191 | 0.711 | 0.90 | no | 35 decided with zero errors (has 148/191) |
| pt | `SUSPICIOUS_ACTIVITY` | 48/63 | 0.644 | 0.90 | no | 35 decided with zero errors (has 48/63) |
| pooled (en) | `SUSPICIOUS_ACTIVITY` | 10/19 | 0.317 | 0.90 | no | 35 decided with zero errors (has 10/19) |
| es | `CUSTOMER_REQUEST` | 139/157 | 0.826 | 0.90 | no | 35 decided with zero errors (has 139/157) |
| pt | `CUSTOMER_REQUEST` | 47/62 | 0.638 | 0.90 | no | 35 decided with zero errors (has 47/62) |
| pooled (en) | `CUSTOMER_REQUEST` | 5/12 | 0.193 | 0.90 | no | 35 decided with zero errors (has 5/12) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 1448, 0.00, 0.00 | 480, 0.00, 0.00 | 100, 0.02, 0.01 |
| 0.1-0.2 | 16, 0.13, 0.06 | 6, 0.16, 0.50 | 6, 0.15, 0.50 |
| 0.2-0.3 | 7, 0.23, 0.29 | 1, 0.24, 0.00 | 4, 0.26, 0.25 |
| 0.3-0.4 | 5, 0.34, 0.20 | 1, 0.39, 0.00 | 4, 0.34, 0.25 |
| 0.4-0.5 | 7, 0.46, 0.29 | 2, 0.44, 0.00 | 4, 0.46, 0.75 |
| 0.5-0.6 | 8, 0.56, 0.38 | 5, 0.54, 0.20 | 4, 0.54, 0.75 |
| 0.6-0.7 | 14, 0.65, 0.36 | 7, 0.64, 0.14 | 4, 0.64, 1.00 |
| 0.7-0.8 | 13, 0.78, 0.46 | 12, 0.74, 0.17 | 8, 0.74, 0.50 |
| 0.8-0.9 | 14, 0.86, 0.64 | 8, 0.85, 0.75 | 10, 0.85, 0.90 |
| 0.9-1.0 | 718, 0.99, 0.95 | 228, 0.99, 0.97 | 6, 0.92, 1.00 |

### Confusion on test, languages pooled

| Truth \ decided | `LOST` | `STOLEN` | `UNRECOGNIZED_CHARGE` | `SUSPICIOUS_ACTIVITY` | `CUSTOMER_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|
| `LOST` | 184 | 16 | 1 | 5 | 1 | 3 |
| `STOLEN` | 0 | 206 | 0 | 3 | 0 | 1 |
| `UNRECOGNIZED_CHARGE` | 1 | 2 | 191 | 12 | 1 | 3 |
| `SUSPICIOUS_ACTIVITY` | 0 | 1 | 1 | 206 | 0 | 2 |
| `CUSTOMER_REQUEST` | 1 | 2 | 0 | 14 | 191 | 2 |
| `(outside the view)` | 66 | 45 | 69 | 33 | 38 | 1849 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "block_reason": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "pt": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "CUSTOMER_REQUEST",
          "LOST",
          "STOLEN",
          "SUSPICIOUS_ACTIVITY",
          "UNRECOGNIZED_CHARGE"
        ],
        "metric": "precision",
        "n_min": 30,
        "p_min": 0.9
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.5467,
            "certified": false,
            "coverage_test": 0.5467,
            "coverage_val": 0.4867,
            "ece_post": 0.0636,
            "ece_pre": 0.0778,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                5,
                12,
                0.1933
              ],
              "LOST": [
                4,
                13,
                0.1268
              ],
              "STOLEN": [
                10,
                20,
                0.2993
              ],
              "SUSPICIOUS_ACTIVITY": [
                10,
                19,
                0.3171
              ],
              "UNRECOGNIZED_CHARGE": [
                6,
                18,
                0.1628
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.5,
              "LOST": 0.4,
              "STOLEN": 1.0,
              "SUSPICIOUS_ACTIVITY": 1.0,
              "UNRECOGNIZED_CHARGE": 0.6
            }
          },
          "es": {
            "acted_coverage_test": 0.3969,
            "certified": false,
            "coverage_test": 0.3969,
            "coverage_val": 0.3667,
            "ece_post": 0.023,
            "ece_pre": 0.0227,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                139,
                157,
                0.8261
              ],
              "LOST": [
                132,
                181,
                0.6603
              ],
              "STOLEN": [
                149,
                188,
                0.729
              ],
              "SUSPICIOUS_ACTIVITY": [
                148,
                191,
                0.7106
              ],
              "UNRECOGNIZED_CHARGE": [
                141,
                176,
                0.736
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.9267,
              "LOST": 0.88,
              "STOLEN": 0.9933,
              "SUSPICIOUS_ACTIVITY": 0.9867,
              "UNRECOGNIZED_CHARGE": 0.94
            }
          },
          "pt": {
            "acted_coverage_test": 0.42,
            "certified": false,
            "coverage_test": 0.42,
            "coverage_val": 0.3653,
            "ece_post": 0.0285,
            "ece_pre": 0.0287,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                47,
                62,
                0.6385
              ],
              "LOST": [
                48,
                58,
                0.7109
              ],
              "STOLEN": [
                47,
                64,
                0.6152
              ],
              "SUSPICIOUS_ACTIVITY": [
                48,
                63,
                0.6436
              ],
              "UNRECOGNIZED_CHARGE": [
                44,
                68,
                0.5284
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.94,
              "LOST": 0.96,
              "STOLEN": 0.94,
              "SUSPICIOUS_ACTIVITY": 0.96,
              "UNRECOGNIZED_CHARGE": 0.88
            }
          }
        },
        "pooled_test": {
          "CUSTOMER_REQUEST": [
            5,
            12,
            0.1933,
            "pooled (en)"
          ],
          "LOST": [
            4,
            13,
            0.1268,
            "pooled (en)"
          ],
          "STOLEN": [
            10,
            20,
            0.2993,
            "pooled (en)"
          ],
          "SUSPICIOUS_ACTIVITY": [
            10,
            19,
            0.3171,
            "pooled (en)"
          ],
          "UNRECOGNIZED_CHARGE": [
            6,
            18,
            0.1628,
            "pooled (en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "CUSTOMER_REQUEST": 0.007881,
          "LOST": 0.002689,
          "STOLEN": 0.000924,
          "SUSPICIOUS_ACTIVITY": 0.305145,
          "UNRECOGNIZED_CHARGE": 0.006524
        },
        "en": {
          "CUSTOMER_REQUEST": 0.007881,
          "LOST": 0.002689,
          "STOLEN": 0.000924,
          "SUSPICIOUS_ACTIVITY": 0.305145,
          "UNRECOGNIZED_CHARGE": 0.006524
        },
        "es": {
          "CUSTOMER_REQUEST": 0.000883,
          "LOST": 0.000459,
          "STOLEN": 0.000302,
          "SUSPICIOUS_ACTIVITY": 0.178279,
          "UNRECOGNIZED_CHARGE": 0.00566
        },
        "pt": {
          "CUSTOMER_REQUEST": 0.001723,
          "LOST": 0.004535,
          "STOLEN": 0.000609,
          "SUSPICIOUS_ACTIVITY": 0.412844,
          "UNRECOGNIZED_CHARGE": 0.001307
        }
      },
      "view": {
        "groups": {
          "CUSTOMER_REQUEST": [
            "request_card_block"
          ],
          "LOST": [
            "report_lost_card"
          ],
          "STOLEN": [
            "report_stolen_card"
          ],
          "SUSPICIOUS_ACTIVITY": [
            "report_suspicious_activity"
          ],
          "UNRECOGNIZED_CHARGE": [
            "report_unrecognized_charge"
          ]
        },
        "kind": "groups"
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.4667 -> 0.5467`
- `~ evidence.per_lang.en.coverage_test: 0.4667 -> 0.5467`
- `~ evidence.per_lang.en.coverage_val: 0.48 -> 0.4867`
- `~ evidence.per_lang.en.ece_post: 0.049 -> 0.0636`
- `~ evidence.per_lang.en.ece_pre: 0.0872 -> 0.0778`
- `~ evidence.per_lang.en.precision_test.CUSTOMER_REQUEST: [5, 9, 0.2667] -> [5, 12, 0.1933]`
- `~ evidence.per_lang.en.precision_test.LOST: [4, 10, 0.1682] -> [4, 13, 0.1268]`
- `~ evidence.per_lang.en.precision_test.STOLEN: [5, 12, 0.1933] -> [10, 20, 0.2993]`
- `~ evidence.per_lang.en.precision_test.SUSPICIOUS_ACTIVITY: [9, 30, 0.1666] -> [10, 19, 0.3171]`
- `~ evidence.per_lang.en.precision_test.UNRECOGNIZED_CHARGE: [6, 9, 0.3542] -> [6, 18, 0.1628]`
- `~ evidence.per_lang.en.recall_test.STOLEN: 0.5 -> 1.0`
- `~ evidence.per_lang.en.recall_test.SUSPICIOUS_ACTIVITY: 0.9 -> 1.0`
- `~ evidence.per_lang.es.acted_coverage_test: 0.41 -> 0.3969`
- `~ evidence.per_lang.es.coverage_test: 0.41 -> 0.3969`
- `~ evidence.per_lang.es.coverage_val: 0.366 -> 0.3667`
- `~ evidence.per_lang.es.ece_post: 0.0171 -> 0.023`
- `~ evidence.per_lang.es.ece_pre: 0.0174 -> 0.0227`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.CUSTOMER_REQUEST: [92, 114, 0.7251] -> [139, 157, 0.8261]`
- `~ evidence.per_lang.es.precision_test.LOST: [96, 122, 0.706] -> [132, 181, 0.6603]`
- `~ evidence.per_lang.es.precision_test.STOLEN: [100, 115, 0.7959] -> [149, 188, 0.729]`
- `~ evidence.per_lang.es.precision_test.SUSPICIOUS_ACTIVITY: [95, 153, 0.542] -> [148, 191, 0.7106]`
- `~ evidence.per_lang.es.precision_test.UNRECOGNIZED_CHARGE: [96, 111, 0.789] -> [141, 176, 0.736]`
- `~ evidence.per_lang.es.recall_test.CUSTOMER_REQUEST: 0.92 -> 0.9267`
- `~ evidence.per_lang.es.recall_test.LOST: 0.96 -> 0.88`
- `~ evidence.per_lang.es.recall_test.STOLEN: 1.0 -> 0.9933`
- `~ evidence.per_lang.es.recall_test.SUSPICIOUS_ACTIVITY: 0.95 -> 0.9867`
- `~ evidence.per_lang.es.recall_test.UNRECOGNIZED_CHARGE: 0.96 -> 0.94`
- `~ evidence.per_lang.pt.acted_coverage_test: 0.3867 -> 0.42`
- `~ evidence.per_lang.pt.coverage_test: 0.3867 -> 0.42`
- `~ evidence.per_lang.pt.coverage_val: 0.3627 -> 0.3653`
- `~ evidence.per_lang.pt.ece_post: 0.0278 -> 0.0285`
- `~ evidence.per_lang.pt.ece_pre: 0.0293 -> 0.0287`
- `~ evidence.per_lang.pt.precision_test.CUSTOMER_REQUEST: [48, 67, 0.5991] -> [47, 62, 0.6385]`
- `~ evidence.per_lang.pt.precision_test.LOST: [46, 61, 0.6332] -> [48, 58, 0.7109]`
- `~ evidence.per_lang.pt.precision_test.STOLEN: [47, 56, 0.7219] -> [47, 64, 0.6152]`
- `~ evidence.per_lang.pt.precision_test.SUSPICIOUS_ACTIVITY: [41, 44, 0.8177] -> [48, 63, 0.6436]`
- `~ evidence.per_lang.pt.precision_test.UNRECOGNIZED_CHARGE: [45, 62, 0.6041] -> [44, 68, 0.5284]`
- `~ evidence.per_lang.pt.recall_test.CUSTOMER_REQUEST: 0.96 -> 0.94`
- `~ evidence.per_lang.pt.recall_test.LOST: 0.92 -> 0.96`
- `~ evidence.per_lang.pt.recall_test.SUSPICIOUS_ACTIVITY: 0.82 -> 0.96`
- `~ evidence.per_lang.pt.recall_test.UNRECOGNIZED_CHARGE: 0.9 -> 0.88`
- `~ evidence.pooled_test.CUSTOMER_REQUEST: [5, 9, 0.2667, 'pooled (en)'] -> [5, 12, 0.1933, 'pooled (en)']`
- `~ evidence.pooled_test.LOST: [4, 10, 0.1682, 'pooled (en)'] -> [4, 13, 0.1268, 'pooled (en)']`
- `~ evidence.pooled_test.STOLEN: [5, 12, 0.1933, 'pooled (en)'] -> [10, 20, 0.2993, 'pooled (en)']`
- `~ evidence.pooled_test.SUSPICIOUS_ACTIVITY: [9, 30, 0.1666, 'pooled (en)'] -> [10, 19, 0.3171, 'pooled (en)']`
- `~ evidence.pooled_test.UNRECOGNIZED_CHARGE: [6, 9, 0.3542, 'pooled (en)'] -> [6, 18, 0.1628, 'pooled (en)']`
- `~ thresholds.*.CUSTOMER_REQUEST: 0.029937 -> 0.007881`
- `~ thresholds.*.LOST: 0.01318 -> 0.002689`
- `~ thresholds.*.STOLEN: 0.00091 -> 0.000924`
- `~ thresholds.*.SUSPICIOUS_ACTIVITY: 0.0201 -> 0.305145`
- `~ thresholds.*.UNRECOGNIZED_CHARGE: 0.289093 -> 0.006524`
- `~ thresholds.en.CUSTOMER_REQUEST: 0.029937 -> 0.007881`
- `~ thresholds.en.LOST: 0.01318 -> 0.002689`
- `~ thresholds.en.STOLEN: 0.00091 -> 0.000924`
- `~ thresholds.en.SUSPICIOUS_ACTIVITY: 0.0201 -> 0.305145`
- `~ thresholds.en.UNRECOGNIZED_CHARGE: 0.289093 -> 0.006524`
- `~ thresholds.es.CUSTOMER_REQUEST: 0.005726 -> 0.000883`
- `~ thresholds.es.LOST: 0.004574 -> 0.000459`
- `~ thresholds.es.STOLEN: 0.000661 -> 0.000302`
- `~ thresholds.es.SUSPICIOUS_ACTIVITY: 0.001761 -> 0.178279`
- `~ thresholds.es.UNRECOGNIZED_CHARGE: 0.331689 -> 0.00566`
- `~ thresholds.pt.CUSTOMER_REQUEST: 0.008131 -> 0.001723`
- `~ thresholds.pt.LOST: 0.015591 -> 0.004535`
- `~ thresholds.pt.STOLEN: 0.000796 -> 0.000609`
- `~ thresholds.pt.SUSPICIOUS_ACTIVITY: 0.002756 -> 0.412844`
- `~ thresholds.pt.UNRECOGNIZED_CHARGE: 0.028379 -> 0.001307`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 15 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `handoff_route`

- **View:** `DISPUTE`, `FRAUD`, `UNRECOGNIZED`, `HUMAN_REQUEST` (groups)
- **Acted labels and precision floor:** `DISPUTE` >= 0.90, `FRAUD` >= 0.90, `UNRECOGNIZED` >= 0.90, `HUMAN_REQUEST` >= 0.90
- **Selection rule on validation:** `point` precision, at least 30 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_label_pooled`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (0 of 12 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | DISPUTE: 0.000841, FRAUD: 0.069169, UNRECOGNIZED: 0.001256, HUMAN_REQUEST: 0.000222 | language |  |
| pt | DISPUTE: 0.000860, FRAUD: 0.076438, UNRECOGNIZED: 0.001054, HUMAN_REQUEST: 0.001195 | language |  |
| en | DISPUTE: 0.001013, FRAUD: 0.153112, UNRECOGNIZED: 0.001955, HUMAN_REQUEST: 0.006383 | pooled |  |
| * | DISPUTE: 0.001013, FRAUD: 0.153112, UNRECOGNIZED: 0.001955, HUMAN_REQUEST: 0.006383 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 36.7% | 41.5% | 41.5% | 0.531 | 0.025 | 0.025 | yes |
| pt | 750 | 750 | 36.7% | 42.1% | 42.1% | 0.505 | 0.023 | 0.023 | yes |
| en | 150 | 150 | 52.7% | 62.7% | 62.7% | 0.478 | 0.079 | 0.062 | yes |
| all | 3150 | 3150 | 37.5% | 42.6% | 42.6% | 0.523 | 0.025 | 0.022 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `DISPUTE` | 150 | 185 | 138 | 0.746 | 0.679 | 0.920 | 0.90 |
| es | `FRAUD` | 300 | 382 | 298 | 0.780 | 0.736 | 0.993 | 0.90 |
| es | `UNRECOGNIZED` | 150 | 171 | 141 | 0.825 | 0.761 | 0.940 | 0.90 |
| es | `HUMAN_REQUEST` | 150 | 195 | 144 | 0.738 | 0.673 | 0.960 | 0.90 |
| pt | `DISPUTE` | 50 | 67 | 44 | 0.657 | 0.537 | 0.880 | 0.90 |
| pt | `FRAUD` | 100 | 125 | 98 | 0.784 | 0.704 | 0.980 | 0.90 |
| pt | `UNRECOGNIZED` | 50 | 62 | 42 | 0.677 | 0.554 | 0.840 | 0.90 |
| pt | `HUMAN_REQUEST` | 50 | 62 | 48 | 0.774 | 0.656 | 0.960 | 0.90 |
| en | `DISPUTE` | 10 | 10 | 6 | 0.600 | 0.313 | 0.600 | 0.90 |
| en | `FRAUD` | 20 | 37 | 20 | 0.541 | 0.384 | 1.000 | 0.90 |
| en | `UNRECOGNIZED` | 10 | 14 | 6 | 0.429 | 0.214 | 0.600 | 0.90 |
| en | `HUMAN_REQUEST` | 10 | 33 | 10 | 0.303 | 0.174 | 1.000 | 0.90 |
| all | `DISPUTE` | 210 | 262 | 188 | 0.718 | 0.660 | 0.895 | 0.90 |
| all | `FRAUD` | 420 | 544 | 416 | 0.765 | 0.727 | 0.990 | 0.90 |
| all | `UNRECOGNIZED` | 210 | 247 | 189 | 0.765 | 0.709 | 0.900 | 0.90 |
| all | `HUMAN_REQUEST` | 210 | 290 | 202 | 0.697 | 0.641 | 0.962 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `DISPUTE` | 138/185 | 0.679 | 0.90 | no | 35 decided with zero errors (has 138/185) |
| pt | `DISPUTE` | 44/67 | 0.537 | 0.90 | no | 35 decided with zero errors (has 44/67) |
| pooled (en) | `DISPUTE` | 6/10 | 0.313 | 0.90 | no | 35 decided with zero errors (has 6/10) |
| es | `FRAUD` | 298/382 | 0.736 | 0.90 | no | 35 decided with zero errors (has 298/382) |
| pt | `FRAUD` | 98/125 | 0.704 | 0.90 | no | 35 decided with zero errors (has 98/125) |
| pooled (en) | `FRAUD` | 20/37 | 0.384 | 0.90 | no | 35 decided with zero errors (has 20/37) |
| es | `UNRECOGNIZED` | 141/171 | 0.761 | 0.90 | no | 35 decided with zero errors (has 141/171) |
| pt | `UNRECOGNIZED` | 42/62 | 0.554 | 0.90 | no | 35 decided with zero errors (has 42/62) |
| pooled (en) | `UNRECOGNIZED` | 6/14 | 0.214 | 0.90 | no | 35 decided with zero errors (has 6/14) |
| es | `HUMAN_REQUEST` | 144/195 | 0.673 | 0.90 | no | 35 decided with zero errors (has 144/195) |
| pt | `HUMAN_REQUEST` | 48/62 | 0.656 | 0.90 | no | 35 decided with zero errors (has 48/62) |
| pooled (en) | `HUMAN_REQUEST` | 10/33 | 0.174 | 0.90 | no | 35 decided with zero errors (has 10/33) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 1434, 0.00, 0.00 | 484, 0.00, 0.00 | 91, 0.02, 0.03 |
| 0.1-0.2 | 16, 0.15, 0.06 | 5, 0.13, 0.00 | 6, 0.14, 0.17 |
| 0.2-0.3 | 12, 0.25, 0.42 | 4, 0.25, 0.00 | 5, 0.26, 0.00 |
| 0.3-0.4 | 7, 0.34, 0.29 | 0 | 5, 0.34, 0.60 |
| 0.4-0.5 | 8, 0.44, 0.12 | 3, 0.46, 0.67 | 4, 0.46, 0.50 |
| 0.5-0.6 | 6, 0.55, 0.50 | 7, 0.54, 0.43 | 1, 0.57, 1.00 |
| 0.6-0.7 | 8, 0.67, 0.00 | 4, 0.66, 0.25 | 3, 0.67, 1.00 |
| 0.7-0.8 | 11, 0.76, 0.45 | 8, 0.74, 0.25 | 7, 0.76, 0.43 |
| 0.8-0.9 | 13, 0.85, 0.62 | 12, 0.86, 0.58 | 18, 0.86, 0.94 |
| 0.9-1.0 | 735, 1.00, 0.94 | 223, 0.99, 0.97 | 10, 0.92, 0.90 |

### Confusion on test, languages pooled

| Truth \ decided | `DISPUTE` | `FRAUD` | `UNRECOGNIZED` | `HUMAN_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|
| `DISPUTE` | 188 | 10 | 9 | 0 | 3 |
| `FRAUD` | 1 | 416 | 1 | 1 | 1 |
| `UNRECOGNIZED` | 3 | 14 | 189 | 0 | 4 |
| `HUMAN_REQUEST` | 2 | 6 | 0 | 202 | 0 |
| `(outside the view)` | 68 | 98 | 48 | 87 | 1799 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "handoff_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "pt": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "DISPUTE",
          "FRAUD",
          "HUMAN_REQUEST",
          "UNRECOGNIZED"
        ],
        "metric": "precision",
        "n_min": 30,
        "p_min": 0.9
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.6267,
            "certified": false,
            "coverage_test": 0.6267,
            "coverage_val": 0.5267,
            "ece_post": 0.0623,
            "ece_pre": 0.0786,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "DISPUTE": [
                6,
                10,
                0.3127
              ],
              "FRAUD": [
                20,
                37,
                0.3838
              ],
              "HUMAN_REQUEST": [
                10,
                33,
                0.1738
              ],
              "UNRECOGNIZED": [
                6,
                14,
                0.2138
              ]
            },
            "recall_test": {
              "DISPUTE": 0.6,
              "FRAUD": 1.0,
              "HUMAN_REQUEST": 1.0,
              "UNRECOGNIZED": 0.6
            }
          },
          "es": {
            "acted_coverage_test": 0.4147,
            "certified": false,
            "coverage_test": 0.4147,
            "coverage_val": 0.3671,
            "ece_post": 0.0255,
            "ece_pre": 0.0255,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "DISPUTE": [
                138,
                185,
                0.6787
              ],
              "FRAUD": [
                298,
                382,
                0.7359
              ],
              "HUMAN_REQUEST": [
                144,
                195,
                0.6726
              ],
              "UNRECOGNIZED": [
                141,
                171,
                0.7606
              ]
            },
            "recall_test": {
              "DISPUTE": 0.92,
              "FRAUD": 0.9933,
              "HUMAN_REQUEST": 0.96,
              "UNRECOGNIZED": 0.94
            }
          },
          "pt": {
            "acted_coverage_test": 0.4213,
            "certified": false,
            "coverage_test": 0.4213,
            "coverage_val": 0.3667,
            "ece_post": 0.0231,
            "ece_pre": 0.0234,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "DISPUTE": [
                44,
                67,
                0.5373
              ],
              "FRAUD": [
                98,
                125,
                0.704
              ],
              "HUMAN_REQUEST": [
                48,
                62,
                0.6559
              ],
              "UNRECOGNIZED": [
                42,
                62,
                0.5537
              ]
            },
            "recall_test": {
              "DISPUTE": 0.88,
              "FRAUD": 0.98,
              "HUMAN_REQUEST": 0.96,
              "UNRECOGNIZED": 0.84
            }
          }
        },
        "pooled_test": {
          "DISPUTE": [
            6,
            10,
            0.3127,
            "pooled (en)"
          ],
          "FRAUD": [
            20,
            37,
            0.3838,
            "pooled (en)"
          ],
          "HUMAN_REQUEST": [
            10,
            33,
            0.1738,
            "pooled (en)"
          ],
          "UNRECOGNIZED": [
            6,
            14,
            0.2138,
            "pooled (en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "DISPUTE": 0.001013,
          "FRAUD": 0.153112,
          "HUMAN_REQUEST": 0.006383,
          "UNRECOGNIZED": 0.001955
        },
        "en": {
          "DISPUTE": 0.001013,
          "FRAUD": 0.153112,
          "HUMAN_REQUEST": 0.006383,
          "UNRECOGNIZED": 0.001955
        },
        "es": {
          "DISPUTE": 0.000841,
          "FRAUD": 0.069169,
          "HUMAN_REQUEST": 0.000222,
          "UNRECOGNIZED": 0.001256
        },
        "pt": {
          "DISPUTE": 0.00086,
          "FRAUD": 0.076438,
          "HUMAN_REQUEST": 0.001195,
          "UNRECOGNIZED": 0.001054
        }
      },
      "view": {
        "groups": {
          "DISPUTE": [
            "request_dispute"
          ],
          "FRAUD": [
            "report_stolen_card",
            "report_suspicious_activity"
          ],
          "HUMAN_REQUEST": [
            "request_human_agent"
          ],
          "UNRECOGNIZED": [
            "report_unrecognized_charge"
          ]
        },
        "kind": "groups"
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.5533 -> 0.6267`
- `~ evidence.per_lang.en.coverage_test: 0.5533 -> 0.6267`
- `~ evidence.per_lang.en.coverage_val: 0.58 -> 0.5267`
- `~ evidence.per_lang.en.ece_post: 0.0401 -> 0.0623`
- `~ evidence.per_lang.en.ece_pre: 0.0577 -> 0.0786`
- `~ evidence.per_lang.en.precision_test.DISPUTE: [7, 12, 0.3195] -> [6, 10, 0.3127]`
- `~ evidence.per_lang.en.precision_test.FRAUD: [19, 46, 0.2829] -> [20, 37, 0.3838]`
- `~ evidence.per_lang.en.precision_test.HUMAN_REQUEST: [10, 16, 0.3864] -> [10, 33, 0.1738]`
- `~ evidence.per_lang.en.precision_test.UNRECOGNIZED: [6, 9, 0.3542] -> [6, 14, 0.2138]`
- `~ evidence.per_lang.en.recall_test.DISPUTE: 0.7 -> 0.6`
- `~ evidence.per_lang.en.recall_test.FRAUD: 0.95 -> 1.0`
- `~ evidence.per_lang.es.acted_coverage_test: 0.4393 -> 0.4147`
- `~ evidence.per_lang.es.coverage_test: 0.4393 -> 0.4147`
- `~ evidence.per_lang.es.coverage_val: 0.364 -> 0.3671`
- `~ evidence.per_lang.es.ece_post: 0.0167 -> 0.0255`
- `~ evidence.per_lang.es.ece_pre: 0.0164 -> 0.0255`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.DISPUTE: [87, 115, 0.6706] -> [138, 185, 0.6787]`
- `~ evidence.per_lang.es.precision_test.FRAUD: [199, 264, 0.6984] -> [298, 382, 0.7359]`
- `~ evidence.per_lang.es.precision_test.HUMAN_REQUEST: [98, 169, 0.5045] -> [144, 195, 0.6726]`
- `~ evidence.per_lang.es.precision_test.UNRECOGNIZED: [96, 111, 0.789] -> [141, 171, 0.7606]`
- `~ evidence.per_lang.es.recall_test.DISPUTE: 0.87 -> 0.92`
- `~ evidence.per_lang.es.recall_test.FRAUD: 0.995 -> 0.9933`
- `~ evidence.per_lang.es.recall_test.HUMAN_REQUEST: 0.98 -> 0.96`
- `~ evidence.per_lang.es.recall_test.UNRECOGNIZED: 0.96 -> 0.94`
- `~ evidence.per_lang.pt.acted_coverage_test: 0.38 -> 0.4213`
- `~ evidence.per_lang.pt.coverage_test: 0.38 -> 0.4213`
- `~ evidence.per_lang.pt.coverage_val: 0.3627 -> 0.3667`
- `~ evidence.per_lang.pt.ece_post: 0.0237 -> 0.0231`
- `~ evidence.per_lang.pt.ece_pre: 0.0255 -> 0.0234`
- `~ evidence.per_lang.pt.precision_test.DISPUTE: [45, 52, 0.7473] -> [44, 67, 0.5373]`
- `~ evidence.per_lang.pt.precision_test.FRAUD: [95, 122, 0.6972] -> [98, 125, 0.704]`
- `~ evidence.per_lang.pt.precision_test.HUMAN_REQUEST: [47, 49, 0.8629] -> [48, 62, 0.6559]`
- `~ evidence.per_lang.pt.precision_test.UNRECOGNIZED: [46, 62, 0.6212] -> [42, 62, 0.5537]`
- `~ evidence.per_lang.pt.recall_test.DISPUTE: 0.9 -> 0.88`
- `~ evidence.per_lang.pt.recall_test.FRAUD: 0.95 -> 0.98`
- `~ evidence.per_lang.pt.recall_test.HUMAN_REQUEST: 0.94 -> 0.96`
- `~ evidence.per_lang.pt.recall_test.UNRECOGNIZED: 0.92 -> 0.84`
- `~ evidence.pooled_test.DISPUTE: [7, 12, 0.3195, 'pooled (en)'] -> [6, 10, 0.3127, 'pooled (en)']`
- `~ evidence.pooled_test.FRAUD: [19, 46, 0.2829, 'pooled (en)'] -> [20, 37, 0.3838, 'pooled (en)']`
- `~ evidence.pooled_test.HUMAN_REQUEST: [10, 16, 0.3864, 'pooled (en)'] -> [10, 33, 0.1738, 'pooled (en)']`
- `~ evidence.pooled_test.UNRECOGNIZED: [6, 9, 0.3542, 'pooled (en)'] -> [6, 14, 0.2138, 'pooled (en)']`
- `~ thresholds.*.DISPUTE: 0.023572 -> 0.001013`
- `~ thresholds.*.FRAUD: 0.015406 -> 0.153112`
- `~ thresholds.*.HUMAN_REQUEST: 0.058411 -> 0.006383`
- `~ thresholds.*.UNRECOGNIZED: 0.246887 -> 0.001955`
- `~ thresholds.en.DISPUTE: 0.023572 -> 0.001013`
- `~ thresholds.en.FRAUD: 0.015406 -> 0.153112`
- `~ thresholds.en.HUMAN_REQUEST: 0.058411 -> 0.006383`
- `~ thresholds.en.UNRECOGNIZED: 0.246887 -> 0.001955`
- `~ thresholds.es.DISPUTE: 0.001697 -> 0.000841`
- `~ thresholds.es.FRAUD: 0.004285 -> 0.069169`
- `~ thresholds.es.HUMAN_REQUEST: 0.002508 -> 0.000222`
- `~ thresholds.es.UNRECOGNIZED: 0.289093 -> 0.001256`
- `~ thresholds.pt.DISPUTE: 0.051414 -> 0.00086`
- `~ thresholds.pt.FRAUD: 0.003069 -> 0.076438`
- `~ thresholds.pt.HUMAN_REQUEST: 0.15497 -> 0.001195`
- `~ thresholds.pt.UNRECOGNIZED: 0.028379 -> 0.001054`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 12 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `smalltalk_route`

- **View:** `greeting`, `out_of_scope`, `other` (groups)
- **Acted labels and precision floor:** `greeting` >= 0.95, `out_of_scope` >= 0.95
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (0 of 14 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |
| pt-BR | 750 | 1.0101 | 0.062 -> 0.062 |  |
| es-MX | 750 | 0.8942 | 0.033 -> 0.032 |  |
| es-AR | 750 | 0.8878 | 0.040 -> 0.039 |  |
| es-CO | 750 | 0.9503 | 0.055 -> 0.055 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.502150 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.562066 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.779321 | language |  |
| pt-BR | 0.562066 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.512674 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.538168 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-CO | 0.502779 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 100.0% | 99.9% | 14.3% | 0.891 | 0.023 | 0.027 | yes |
| pt | 750 | 750 | 100.0% | 99.2% | 11.9% | 0.845 | 0.029 | 0.028 | yes |
| en | 150 | 150 | 77.3% | 74.0% | 8.0% | 0.699 | 0.135 | 0.029 | yes |
| pt-BR | 750 | 750 | 100.0% | 99.2% | 11.9% | 0.845 | 0.029 | 0.028 | yes |
| es-MX | 750 | 750 | 100.0% | 99.9% | 14.4% | 0.876 | 0.028 | 0.033 | yes |
| es-AR | 750 | 750 | 100.0% | 99.7% | 14.3% | 0.894 | 0.027 | 0.029 | yes |
| es-CO | 750 | 750 | 100.0% | 99.9% | 14.1% | 0.904 | 0.023 | 0.024 | yes |
| all | 6150 | 6150 | 99.4% | 99.1% | 13.5% | 0.875 | 0.026 | 0.026 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `greeting` | 150 | 157 | 140 | 0.892 | 0.833 | 0.933 | 0.95 |
| es | `out_of_scope` | 150 | 165 | 123 | 0.745 | 0.674 | 0.820 | 0.95 |
| pt | `greeting` | 50 | 51 | 44 | 0.863 | 0.743 | 0.880 | 0.95 |
| pt | `out_of_scope` | 50 | 38 | 30 | 0.789 | 0.637 | 0.600 | 0.95 |
| en | `greeting` | 10 | 7 | 6 | 0.857 | 0.487 | 0.600 | 0.95 |
| en | `out_of_scope` | 10 | 5 | 3 | 0.600 | 0.231 | 0.300 | 0.95 |
| pt-BR | `greeting` | 50 | 51 | 44 | 0.863 | 0.743 | 0.880 | 0.95 |
| pt-BR | `out_of_scope` | 50 | 38 | 30 | 0.789 | 0.637 | 0.600 | 0.95 |
| es-MX | `greeting` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.95 |
| es-MX | `out_of_scope` | 50 | 57 | 41 | 0.719 | 0.592 | 0.820 | 0.95 |
| es-AR | `greeting` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.95 |
| es-AR | `out_of_scope` | 50 | 56 | 43 | 0.768 | 0.642 | 0.860 | 0.95 |
| es-CO | `greeting` | 50 | 55 | 50 | 0.909 | 0.804 | 1.000 | 0.95 |
| es-CO | `out_of_scope` | 50 | 51 | 39 | 0.765 | 0.632 | 0.780 | 0.95 |
| all | `greeting` | 410 | 423 | 374 | 0.884 | 0.850 | 0.912 | 0.95 |
| all | `out_of_scope` | 410 | 410 | 309 | 0.754 | 0.710 | 0.754 | 0.95 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `greeting` | 410 | 423 | 374 | 0.884 | 0.850 | 0.912 | 0.95 |
| all | `out_of_scope` | 410 | 410 | 309 | 0.754 | 0.710 | 0.754 | 0.95 |
| all | `other` | 5330 | 5260 | 5171 | 0.983 | 0.979 | 0.970 | not acted on |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `greeting` | 140/157 | 0.833 | 0.95 | no | 73 decided with zero errors (has 140/157) |
| pt | `greeting` | 44/51 | 0.743 | 0.95 | no | 73 decided with zero errors (has 44/51) |
| en | `greeting` | 6/7 | 0.487 | 0.95 | no | 73 decided with zero errors (has 6/7) |
| pt-BR | `greeting` | 44/51 | 0.743 | 0.95 | no | 73 decided with zero errors (has 44/51) |
| es-MX | `greeting` | 45/51 | 0.766 | 0.95 | no | 73 decided with zero errors (has 45/51) |
| es-AR | `greeting` | 45/51 | 0.766 | 0.95 | no | 73 decided with zero errors (has 45/51) |
| es-CO | `greeting` | 50/55 | 0.804 | 0.95 | no | 73 decided with zero errors (has 50/55) |
| es | `out_of_scope` | 123/165 | 0.674 | 0.95 | no | 73 decided with zero errors (has 123/165) |
| pt | `out_of_scope` | 30/38 | 0.637 | 0.95 | no | 73 decided with zero errors (has 30/38) |
| en | `out_of_scope` | 3/5 | 0.231 | 0.95 | no | 73 decided with zero errors (has 3/5) |
| pt-BR | `out_of_scope` | 30/38 | 0.637 | 0.95 | no | 73 decided with zero errors (has 30/38) |
| es-MX | `out_of_scope` | 41/57 | 0.592 | 0.95 | no | 73 decided with zero errors (has 41/57) |
| es-AR | `out_of_scope` | 43/56 | 0.642 | 0.95 | no | 73 decided with zero errors (has 43/56) |
| es-CO | `out_of_scope` | 39/51 | 0.632 | 0.95 | no | 73 decided with zero errors (has 39/51) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc | es-CO: n, conf, acc |
|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.3-0.4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.4-0.5 | 2, 0.49, 1.00 | 0 | 1, 0.47, 0.00 | 0 | 0 | 1, 0.49, 1.00 | 0 |
| 0.5-0.6 | 12, 0.55, 0.50 | 11, 0.55, 0.45 | 15, 0.55, 0.53 | 11, 0.55, 0.45 | 6, 0.56, 0.17 | 3, 0.55, 1.00 | 4, 0.52, 0.75 |
| 0.6-0.7 | 14, 0.65, 0.79 | 7, 0.66, 0.57 | 11, 0.65, 0.73 | 7, 0.66, 0.57 | 2, 0.63, 1.00 | 7, 0.67, 0.57 | 5, 0.64, 1.00 |
| 0.7-0.8 | 19, 0.76, 0.58 | 11, 0.75, 0.64 | 15, 0.75, 0.67 | 11, 0.75, 0.64 | 10, 0.77, 0.40 | 4, 0.75, 0.75 | 7, 0.77, 0.43 |
| 0.8-0.9 | 52, 0.85, 0.63 | 18, 0.86, 0.78 | 11, 0.86, 0.82 | 18, 0.86, 0.78 | 16, 0.85, 0.56 | 14, 0.86, 0.86 | 15, 0.84, 0.73 |
| 0.9-1.0 | 2151, 1.00, 0.98 | 703, 1.00, 0.97 | 97, 0.97, 0.96 | 703, 1.00, 0.97 | 716, 1.00, 0.98 | 721, 1.00, 0.97 | 719, 1.00, 0.98 |

### Confusion on test, languages pooled

| Truth \ decided | `greeting` | `out_of_scope` | `other` | `(abstained)` |
|---|---:|---:|---:|---:|
| `greeting` | 374 | 2 | 33 | 1 |
| `out_of_scope` | 31 | 309 | 56 | 14 |
| `other` | 18 | 99 | 5171 | 42 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "smalltalk_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "es-AR": {
            "T": 0.88783
          },
          "es-CO": {
            "T": 0.950337
          },
          "es-MX": {
            "T": 0.894171
          },
          "pt": {
            "T": 1.010123
          },
          "pt-BR": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "greeting",
          "out_of_scope"
        ],
        "metric": "precision",
        "n_min": 10,
        "p_min": 0.95
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.08,
            "certified": false,
            "coverage_test": 0.74,
            "coverage_val": 0.7733,
            "ece_post": 0.0292,
            "ece_pre": 0.1348,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "greeting": [
                6,
                7,
                0.4869
              ],
              "out_of_scope": [
                3,
                5,
                0.2307
              ]
            },
            "recall_test": {
              "greeting": 0.6,
              "out_of_scope": 0.3
            }
          },
          "es": {
            "acted_coverage_test": 0.1431,
            "certified": false,
            "coverage_test": 0.9991,
            "coverage_val": 1.0,
            "ece_post": 0.0266,
            "ece_pre": 0.0232,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "greeting": [
                140,
                157,
                0.8334
              ],
              "out_of_scope": [
                123,
                165,
                0.6739
              ]
            },
            "recall_test": {
              "greeting": 0.9333,
              "out_of_scope": 0.82
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.1427,
            "certified": false,
            "coverage_test": 0.9973,
            "coverage_val": 1.0,
            "ece_post": 0.0294,
            "ece_pre": 0.0271,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                45,
                51,
                0.7662
              ],
              "out_of_scope": [
                43,
                56,
                0.6423
              ]
            },
            "recall_test": {
              "greeting": 0.9,
              "out_of_scope": 0.86
            }
          },
          "es-CO": {
            "acted_coverage_test": 0.1413,
            "certified": false,
            "coverage_test": 0.9987,
            "coverage_val": 1.0,
            "ece_post": 0.0242,
            "ece_pre": 0.023,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                50,
                55,
                0.8042
              ],
              "out_of_scope": [
                39,
                51,
                0.6324
              ]
            },
            "recall_test": {
              "greeting": 1.0,
              "out_of_scope": 0.78
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.144,
            "certified": false,
            "coverage_test": 0.9987,
            "coverage_val": 1.0,
            "ece_post": 0.0328,
            "ece_pre": 0.0282,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                45,
                51,
                0.7662
              ],
              "out_of_scope": [
                41,
                57,
                0.5917
              ]
            },
            "recall_test": {
              "greeting": 0.9,
              "out_of_scope": 0.82
            }
          },
          "pt": {
            "acted_coverage_test": 0.1187,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0283,
            "ece_pre": 0.0285,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                44,
                51,
                0.7428
              ],
              "out_of_scope": [
                30,
                38,
                0.6365
              ]
            },
            "recall_test": {
              "greeting": 0.88,
              "out_of_scope": 0.6
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.1187,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0283,
            "ece_pre": 0.0285,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                44,
                51,
                0.7428
              ],
              "out_of_scope": [
                30,
                38,
                0.6365
              ]
            },
            "recall_test": {
              "greeting": 0.88,
              "out_of_scope": 0.6
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.779321,
        "es": 0.50215,
        "es-AR": 0.538168,
        "es-CO": 0.502779,
        "es-MX": 0.512674,
        "pt": 0.562066,
        "pt-BR": 0.562066
      },
      "view": {
        "groups": {
          "greeting": [
            "greeting"
          ],
          "other": [
            "check_balance",
            "check_recent_transactions",
            "confirm",
            "deny",
            "provide_identity_data",
            "provide_otp_code",
            "report_lost_card",
            "report_stolen_card",
            "report_suspicious_activity",
            "report_unrecognized_charge",
            "request_card_block",
            "request_dispute",
            "request_human_agent"
          ],
          "out_of_scope": [
            "out_of_scope"
          ]
        },
        "kind": "groups"
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.es-AR.T: 1.075648 -> 0.88783`
- `+ calibrator.by_lang.es-CO.T = 0.950337`
- `~ calibrator.by_lang.es-MX.T: 0.994325 -> 0.894171`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ calibrator.by_lang.pt-BR.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.0867 -> 0.08`
- `~ evidence.per_lang.en.coverage_test: 0.7867 -> 0.74`
- `~ evidence.per_lang.en.coverage_val: 0.84 -> 0.7733`
- `~ evidence.per_lang.en.ece_post: 0.0645 -> 0.0292`
- `~ evidence.per_lang.en.ece_pre: 0.1209 -> 0.1348`
- `~ evidence.per_lang.en.precision_test.greeting: [4, 4, 0.5101] -> [6, 7, 0.4869]`
- `~ evidence.per_lang.en.precision_test.out_of_scope: [4, 9, 0.1888] -> [3, 5, 0.2307]`
- `~ evidence.per_lang.en.recall_test.greeting: 0.4 -> 0.6`
- `~ evidence.per_lang.en.recall_test.out_of_scope: 0.4 -> 0.3`
- `~ evidence.per_lang.es.acted_coverage_test: 0.1407 -> 0.1431`
- `~ evidence.per_lang.es.coverage_test: 0.998 -> 0.9991`
- `~ evidence.per_lang.es.ece_post: 0.0216 -> 0.0266`
- `~ evidence.per_lang.es.ece_pre: 0.0218 -> 0.0232`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.greeting: [88, 92, 0.8935] -> [140, 157, 0.8334]`
- `~ evidence.per_lang.es.precision_test.out_of_scope: [88, 119, 0.654] -> [123, 165, 0.6739]`
- `~ evidence.per_lang.es.recall_test.greeting: 0.88 -> 0.9333`
- `~ evidence.per_lang.es.recall_test.out_of_scope: 0.88 -> 0.82`
- `~ evidence.per_lang.es-AR.coverage_test: 0.9987 -> 0.9973`
- `~ evidence.per_lang.es-AR.coverage_val: 0.9987 -> 1.0`
- `~ evidence.per_lang.es-AR.ece_post: 0.0199 -> 0.0294`
- `~ evidence.per_lang.es-AR.ece_pre: 0.0225 -> 0.0271`
- `~ evidence.per_lang.es-AR.precision_test.greeting: [45, 47, 0.8575] -> [45, 51, 0.7662]`
- `~ evidence.per_lang.es-AR.precision_test.out_of_scope: [44, 60, 0.6099] -> [43, 56, 0.6423]`
- `~ evidence.per_lang.es-AR.recall_test.out_of_scope: 0.88 -> 0.86`
- `+ evidence.per_lang.es-CO.acted_coverage_test = 0.1413`
- `+ evidence.per_lang.es-CO.certified = False`
- `+ evidence.per_lang.es-CO.coverage_test = 0.9987`
- `+ evidence.per_lang.es-CO.coverage_val = 1.0`
- `+ evidence.per_lang.es-CO.ece_post = 0.0242`
- `+ evidence.per_lang.es-CO.ece_pre = 0.023`
- `+ evidence.per_lang.es-CO.n_test = 750`
- `+ evidence.per_lang.es-CO.n_val = 750`
- `+ evidence.per_lang.es-CO.precision_test.greeting = [50, 55, 0.8042]`
- `+ evidence.per_lang.es-CO.precision_test.out_of_scope = [39, 51, 0.6324]`
- `+ evidence.per_lang.es-CO.recall_test.greeting = 1.0`
- `+ evidence.per_lang.es-CO.recall_test.out_of_scope = 0.78`
- `~ evidence.per_lang.es-MX.acted_coverage_test: 0.1387 -> 0.144`
- `~ evidence.per_lang.es-MX.coverage_test: 0.9973 -> 0.9987`
- `~ evidence.per_lang.es-MX.ece_post: 0.0219 -> 0.0328`
- `~ evidence.per_lang.es-MX.ece_pre: 0.0218 -> 0.0282`
- `~ evidence.per_lang.es-MX.precision_test.greeting: [43, 45, 0.8517] -> [45, 51, 0.7662]`
- `~ evidence.per_lang.es-MX.precision_test.out_of_scope: [44, 59, 0.622] -> [41, 57, 0.5917]`
- `~ evidence.per_lang.es-MX.recall_test.greeting: 0.86 -> 0.9`
- `~ evidence.per_lang.es-MX.recall_test.out_of_scope: 0.88 -> 0.82`
- `~ evidence.per_lang.pt.acted_coverage_test: 0.1147 -> 0.1187`
- `~ evidence.per_lang.pt.coverage_test: 0.964 -> 0.992`
- `~ evidence.per_lang.pt.coverage_val: 0.9947 -> 1.0`
- `~ evidence.per_lang.pt.ece_post: 0.0274 -> 0.0283`
- `~ evidence.per_lang.pt.ece_pre: 0.0282 -> 0.0285`
- `~ evidence.per_lang.pt.precision_test.greeting: [35, 37, 0.823] -> [44, 51, 0.7428]`
- `~ evidence.per_lang.pt.precision_test.out_of_scope: [38, 49, 0.6412] -> [30, 38, 0.6365]`
- `~ evidence.per_lang.pt.recall_test.greeting: 0.7 -> 0.88`
- `~ evidence.per_lang.pt.recall_test.out_of_scope: 0.76 -> 0.6`
- `~ evidence.per_lang.pt-BR.acted_coverage_test: 0.1147 -> 0.1187`
- `~ evidence.per_lang.pt-BR.coverage_test: 0.964 -> 0.992`
- `~ evidence.per_lang.pt-BR.coverage_val: 0.9947 -> 1.0`
- `~ evidence.per_lang.pt-BR.ece_post: 0.0274 -> 0.0283`
- `~ evidence.per_lang.pt-BR.ece_pre: 0.0282 -> 0.0285`
- `~ evidence.per_lang.pt-BR.precision_test.greeting: [35, 37, 0.823] -> [44, 51, 0.7428]`
- `~ evidence.per_lang.pt-BR.precision_test.out_of_scope: [38, 49, 0.6412] -> [30, 38, 0.6365]`
- `~ evidence.per_lang.pt-BR.recall_test.greeting: 0.7 -> 0.88`
- `~ evidence.per_lang.pt-BR.recall_test.out_of_scope: 0.76 -> 0.6`
- `~ thresholds.en: 0.78318 -> 0.779321`
- `~ thresholds.es: 0.502214 -> 0.50215`
- `~ thresholds.es-AR: 0.531993 -> 0.538168`
- `+ thresholds.es-CO = 0.502779`
- `~ thresholds.es-MX: 0.509892 -> 0.512674`
- `... and 2 more changed fields`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 14 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `intent_hint`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `check_balance` >= 0.90, `check_recent_transactions` >= 0.90, `confirm` >= 0.90, `deny` >= 0.90, `greeting` >= 0.90, `out_of_scope` >= 0.90, `provide_identity_data` >= 0.90, `provide_otp_code` >= 0.90, `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (25 of 105 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |
| pt-BR | 750 | 1.0101 | 0.062 -> 0.062 |  |
| es-MX | 750 | 0.8942 | 0.033 -> 0.032 |  |
| es-AR | 750 | 0.8878 | 0.040 -> 0.039 |  |
| es-CO | 750 | 0.9503 | 0.055 -> 0.055 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.339856 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.948382 | language |  |
| pt-BR | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.487000 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.471282 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-CO | 0.331145 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 100.0% | 100.0% | 100.0% | 0.922 | 0.047 | 0.052 | yes |
| pt | 750 | 750 | 100.0% | 98.5% | 98.5% | 0.898 | 0.062 | 0.061 | yes |
| en | 150 | 150 | 0.7% | 0.0% | 0.0% | 0.649 | 0.219 | 0.105 | no |
| pt-BR | 750 | 750 | 100.0% | 98.5% | 98.5% | 0.898 | 0.062 | 0.061 | yes |
| es-MX | 750 | 750 | 100.0% | 99.7% | 99.7% | 0.921 | 0.051 | 0.057 | yes |
| es-AR | 750 | 750 | 100.0% | 99.5% | 99.5% | 0.920 | 0.052 | 0.060 | yes |
| es-CO | 750 | 750 | 100.0% | 100.0% | 100.0% | 0.926 | 0.042 | 0.044 | yes |
| all | 6150 | 6150 | 97.6% | 97.1% | 97.1% | 0.911 | 0.055 | 0.055 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `check_balance` | 150 | 131 | 131 | 1.000 | 0.972 | 0.873 | 0.90 |
| es | `check_recent_transactions` | 150 | 124 | 122 | 0.984 | 0.943 | 0.813 | 0.90 |
| es | `confirm` | 150 | 164 | 141 | 0.860 | 0.798 | 0.940 | 0.90 |
| es | `deny` | 150 | 146 | 139 | 0.952 | 0.904 | 0.927 | 0.90 |
| es | `greeting` | 150 | 159 | 140 | 0.881 | 0.821 | 0.933 | 0.90 |
| es | `out_of_scope` | 150 | 167 | 123 | 0.737 | 0.665 | 0.820 | 0.90 |
| es | `provide_identity_data` | 150 | 151 | 148 | 0.980 | 0.943 | 0.987 | 0.90 |
| es | `provide_otp_code` | 150 | 152 | 150 | 0.987 | 0.953 | 1.000 | 0.90 |
| es | `report_lost_card` | 150 | 138 | 132 | 0.957 | 0.908 | 0.880 | 0.90 |
| es | `report_stolen_card` | 150 | 163 | 149 | 0.914 | 0.861 | 0.993 | 0.90 |
| es | `report_suspicious_activity` | 150 | 183 | 146 | 0.798 | 0.734 | 0.973 | 0.90 |
| es | `report_unrecognized_charge` | 150 | 147 | 138 | 0.939 | 0.888 | 0.920 | 0.90 |
| es | `request_card_block` | 150 | 141 | 139 | 0.986 | 0.950 | 0.927 | 0.90 |
| es | `request_dispute` | 150 | 140 | 134 | 0.957 | 0.910 | 0.893 | 0.90 |
| es | `request_human_agent` | 150 | 144 | 141 | 0.979 | 0.941 | 0.940 | 0.90 |
| pt | `check_balance` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt | `check_recent_transactions` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| pt | `confirm` | 50 | 61 | 47 | 0.770 | 0.651 | 0.940 | 0.90 |
| pt | `deny` | 50 | 50 | 43 | 0.860 | 0.738 | 0.860 | 0.90 |
| pt | `greeting` | 50 | 51 | 44 | 0.863 | 0.743 | 0.880 | 0.90 |
| pt | `out_of_scope` | 50 | 39 | 31 | 0.795 | 0.645 | 0.620 | 0.90 |
| pt | `provide_identity_data` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| en | `check_balance` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `check_recent_transactions` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `confirm` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `deny` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `greeting` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `out_of_scope` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `provide_identity_data` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `provide_otp_code` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_lost_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_stolen_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_suspicious_activity` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_human_agent` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| pt-BR | `check_balance` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt-BR | `check_recent_transactions` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| pt-BR | `confirm` | 50 | 61 | 47 | 0.770 | 0.651 | 0.940 | 0.90 |
| pt-BR | `deny` | 50 | 50 | 43 | 0.860 | 0.738 | 0.860 | 0.90 |
| pt-BR | `greeting` | 50 | 51 | 44 | 0.863 | 0.743 | 0.880 | 0.90 |
| pt-BR | `out_of_scope` | 50 | 39 | 31 | 0.795 | 0.645 | 0.620 | 0.90 |
| pt-BR | `provide_identity_data` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt-BR | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt-BR | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt-BR | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `check_balance` | 50 | 43 | 43 | 1.000 | 0.918 | 0.860 | 0.90 |
| es-MX | `check_recent_transactions` | 50 | 38 | 37 | 0.974 | 0.865 | 0.740 | 0.90 |
| es-MX | `confirm` | 50 | 57 | 48 | 0.842 | 0.726 | 0.960 | 0.90 |
| es-MX | `deny` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| es-MX | `greeting` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.90 |
| es-MX | `out_of_scope` | 50 | 58 | 41 | 0.707 | 0.580 | 0.820 | 0.90 |
| es-MX | `provide_identity_data` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| es-MX | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-MX | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 61 | 50 | 0.820 | 0.705 | 1.000 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 50 | 47 | 0.940 | 0.838 | 0.940 | 0.90 |
| es-MX | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-MX | `request_dispute` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `request_human_agent` | 50 | 48 | 47 | 0.979 | 0.891 | 0.940 | 0.90 |
| es-AR | `check_balance` | 50 | 43 | 43 | 1.000 | 0.918 | 0.860 | 0.90 |
| es-AR | `check_recent_transactions` | 50 | 44 | 44 | 1.000 | 0.920 | 0.880 | 0.90 |
| es-AR | `confirm` | 50 | 55 | 45 | 0.818 | 0.697 | 0.900 | 0.90 |
| es-AR | `deny` | 50 | 49 | 46 | 0.939 | 0.835 | 0.920 | 0.90 |
| es-AR | `greeting` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.90 |
| es-AR | `out_of_scope` | 50 | 56 | 43 | 0.768 | 0.642 | 0.860 | 0.90 |
| es-AR | `provide_identity_data` | 50 | 52 | 50 | 0.962 | 0.870 | 1.000 | 0.90 |
| es-AR | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-AR | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 64 | 50 | 0.781 | 0.666 | 1.000 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-AR | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-AR | `request_dispute` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-AR | `request_human_agent` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-CO | `check_balance` | 50 | 45 | 45 | 1.000 | 0.921 | 0.900 | 0.90 |
| es-CO | `check_recent_transactions` | 50 | 42 | 41 | 0.976 | 0.877 | 0.820 | 0.90 |
| es-CO | `confirm` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| es-CO | `deny` | 50 | 48 | 48 | 1.000 | 0.926 | 0.960 | 0.90 |
| es-CO | `greeting` | 50 | 56 | 50 | 0.893 | 0.785 | 1.000 | 0.90 |
| es-CO | `out_of_scope` | 50 | 52 | 39 | 0.750 | 0.618 | 0.780 | 0.90 |
| es-CO | `provide_identity_data` | 50 | 48 | 48 | 1.000 | 0.926 | 0.960 | 0.90 |
| es-CO | `provide_otp_code` | 50 | 52 | 50 | 0.962 | 0.870 | 1.000 | 0.90 |
| es-CO | `report_lost_card` | 50 | 46 | 42 | 0.913 | 0.797 | 0.840 | 0.90 |
| es-CO | `report_stolen_card` | 50 | 55 | 49 | 0.891 | 0.782 | 0.980 | 0.90 |
| es-CO | `report_suspicious_activity` | 50 | 58 | 46 | 0.793 | 0.672 | 0.920 | 0.90 |
| es-CO | `report_unrecognized_charge` | 50 | 51 | 47 | 0.922 | 0.815 | 0.940 | 0.90 |
| es-CO | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| es-CO | `request_dispute` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-CO | `request_human_agent` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| all | `check_balance` | 410 | 350 | 346 | 0.989 | 0.971 | 0.844 | 0.90 |
| all | `check_recent_transactions` | 410 | 340 | 334 | 0.982 | 0.962 | 0.815 | 0.90 |
| all | `confirm` | 410 | 449 | 376 | 0.837 | 0.800 | 0.917 | 0.90 |
| all | `deny` | 410 | 391 | 364 | 0.931 | 0.901 | 0.888 | 0.90 |
| all | `greeting` | 410 | 419 | 368 | 0.878 | 0.843 | 0.898 | 0.90 |
| all | `out_of_scope` | 410 | 411 | 308 | 0.749 | 0.705 | 0.751 | 0.90 |
| all | `provide_identity_data` | 410 | 402 | 396 | 0.985 | 0.968 | 0.966 | 0.90 |
| all | `provide_otp_code` | 410 | 404 | 400 | 0.990 | 0.975 | 0.976 | 0.90 |
| all | `report_lost_card` | 410 | 378 | 360 | 0.952 | 0.926 | 0.878 | 0.90 |
| all | `report_stolen_card` | 410 | 434 | 392 | 0.903 | 0.872 | 0.956 | 0.90 |
| all | `report_suspicious_activity` | 410 | 484 | 388 | 0.802 | 0.764 | 0.946 | 0.90 |
| all | `report_unrecognized_charge` | 410 | 382 | 360 | 0.942 | 0.914 | 0.878 | 0.90 |
| all | `request_card_block` | 410 | 380 | 372 | 0.979 | 0.959 | 0.907 | 0.90 |
| all | `request_dispute` | 410 | 366 | 348 | 0.951 | 0.924 | 0.849 | 0.90 |
| all | `request_human_agent` | 410 | 382 | 376 | 0.984 | 0.966 | 0.917 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `check_balance` | 131/131 | 0.972 | 0.90 | yes |  |
| pt | `check_balance` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| en | `check_balance` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `check_balance` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| es-MX | `check_balance` | 43/43 | 0.918 | 0.90 | yes |  |
| es-AR | `check_balance` | 43/43 | 0.918 | 0.90 | yes |  |
| es-CO | `check_balance` | 45/45 | 0.921 | 0.90 | yes |  |
| es | `check_recent_transactions` | 122/124 | 0.943 | 0.90 | yes |  |
| pt | `check_recent_transactions` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| en | `check_recent_transactions` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `check_recent_transactions` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-MX | `check_recent_transactions` | 37/38 | 0.865 | 0.90 | no | 35 decided with zero errors (has 37/38) |
| es-AR | `check_recent_transactions` | 44/44 | 0.920 | 0.90 | yes |  |
| es-CO | `check_recent_transactions` | 41/42 | 0.877 | 0.90 | no | 35 decided with zero errors (has 41/42) |
| es | `confirm` | 141/164 | 0.798 | 0.90 | no | 35 decided with zero errors (has 141/164) |
| pt | `confirm` | 47/61 | 0.651 | 0.90 | no | 35 decided with zero errors (has 47/61) |
| en | `confirm` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `confirm` | 47/61 | 0.651 | 0.90 | no | 35 decided with zero errors (has 47/61) |
| es-MX | `confirm` | 48/57 | 0.726 | 0.90 | no | 35 decided with zero errors (has 48/57) |
| es-AR | `confirm` | 45/55 | 0.697 | 0.90 | no | 35 decided with zero errors (has 45/55) |
| es-CO | `confirm` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| es | `deny` | 139/146 | 0.904 | 0.90 | yes |  |
| pt | `deny` | 43/50 | 0.738 | 0.90 | no | 35 decided with zero errors (has 43/50) |
| en | `deny` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `deny` | 43/50 | 0.738 | 0.90 | no | 35 decided with zero errors (has 43/50) |
| es-MX | `deny` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-AR | `deny` | 46/49 | 0.835 | 0.90 | no | 35 decided with zero errors (has 46/49) |
| es-CO | `deny` | 48/48 | 0.926 | 0.90 | yes |  |
| es | `greeting` | 140/159 | 0.821 | 0.90 | no | 35 decided with zero errors (has 140/159) |
| pt | `greeting` | 44/51 | 0.743 | 0.90 | no | 35 decided with zero errors (has 44/51) |
| en | `greeting` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `greeting` | 44/51 | 0.743 | 0.90 | no | 35 decided with zero errors (has 44/51) |
| es-MX | `greeting` | 45/51 | 0.766 | 0.90 | no | 35 decided with zero errors (has 45/51) |
| es-AR | `greeting` | 45/51 | 0.766 | 0.90 | no | 35 decided with zero errors (has 45/51) |
| es-CO | `greeting` | 50/56 | 0.785 | 0.90 | no | 35 decided with zero errors (has 50/56) |
| es | `out_of_scope` | 123/167 | 0.665 | 0.90 | no | 35 decided with zero errors (has 123/167) |
| pt | `out_of_scope` | 31/39 | 0.645 | 0.90 | no | 35 decided with zero errors (has 31/39) |
| en | `out_of_scope` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `out_of_scope` | 31/39 | 0.645 | 0.90 | no | 35 decided with zero errors (has 31/39) |
| es-MX | `out_of_scope` | 41/58 | 0.580 | 0.90 | no | 35 decided with zero errors (has 41/58) |
| es-AR | `out_of_scope` | 43/56 | 0.642 | 0.90 | no | 35 decided with zero errors (has 43/56) |
| es-CO | `out_of_scope` | 39/52 | 0.618 | 0.90 | no | 35 decided with zero errors (has 39/52) |
| es | `provide_identity_data` | 148/151 | 0.943 | 0.90 | yes |  |
| pt | `provide_identity_data` | 50/50 | 0.929 | 0.90 | yes |  |
| en | `provide_identity_data` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `provide_identity_data` | 50/50 | 0.929 | 0.90 | yes |  |
| es-MX | `provide_identity_data` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |
| es-AR | `provide_identity_data` | 50/52 | 0.870 | 0.90 | no | 35 decided with zero errors (has 50/52) |
| es-CO | `provide_identity_data` | 48/48 | 0.926 | 0.90 | yes |  |
| es | `provide_otp_code` | 150/152 | 0.953 | 0.90 | yes |  |
| pt | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| en | `provide_otp_code` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es-MX | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es-AR | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es-CO | `provide_otp_code` | 50/52 | 0.870 | 0.90 | no | 35 decided with zero errors (has 50/52) |
| es | `report_lost_card` | 132/138 | 0.908 | 0.90 | yes |  |
| pt | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| en | `report_lost_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| es-MX | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-AR | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-CO | `report_lost_card` | 42/46 | 0.797 | 0.90 | no | 35 decided with zero errors (has 42/46) |
| es | `report_stolen_card` | 149/163 | 0.861 | 0.90 | no | 35 decided with zero errors (has 149/163) |
| pt | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| en | `report_stolen_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| es-MX | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-AR | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-CO | `report_stolen_card` | 49/55 | 0.782 | 0.90 | no | 35 decided with zero errors (has 49/55) |
| es | `report_suspicious_activity` | 146/183 | 0.734 | 0.90 | no | 35 decided with zero errors (has 146/183) |
| pt | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| en | `report_suspicious_activity` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| es-MX | `report_suspicious_activity` | 50/61 | 0.705 | 0.90 | no | 35 decided with zero errors (has 50/61) |
| es-AR | `report_suspicious_activity` | 50/64 | 0.666 | 0.90 | no | 35 decided with zero errors (has 50/64) |
| es-CO | `report_suspicious_activity` | 46/58 | 0.672 | 0.90 | no | 35 decided with zero errors (has 46/58) |
| es | `report_unrecognized_charge` | 138/147 | 0.888 | 0.90 | no | 35 decided with zero errors (has 138/147) |
| pt | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| en | `report_unrecognized_charge` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| es-MX | `report_unrecognized_charge` | 47/50 | 0.838 | 0.90 | no | 35 decided with zero errors (has 47/50) |
| es-AR | `report_unrecognized_charge` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es-CO | `report_unrecognized_charge` | 47/51 | 0.815 | 0.90 | no | 35 decided with zero errors (has 47/51) |
| es | `request_card_block` | 139/141 | 0.950 | 0.90 | yes |  |
| pt | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es-MX | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-AR | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-CO | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es | `request_dispute` | 134/140 | 0.910 | 0.90 | yes |  |
| pt | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| en | `request_dispute` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| es-MX | `request_dispute` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-AR | `request_dispute` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_dispute` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es | `request_human_agent` | 141/144 | 0.941 | 0.90 | yes |  |
| pt | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| en | `request_human_agent` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| es-MX | `request_human_agent` | 47/48 | 0.891 | 0.90 | no | 35 decided with zero errors (has 47/48) |
| es-AR | `request_human_agent` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_human_agent` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc | es-CO: n, conf, acc |
|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 1, 0.27, 0.00 | 0 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.37, 0.00 | 1, 0.37, 0.00 | 9, 0.35, 0.33 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 2, 0.36, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.23 | 3, 0.47, 0.00 | 14, 0.45, 0.36 | 3, 0.47, 0.00 | 1, 0.42, 0.00 | 5, 0.46, 0.00 | 7, 0.45, 0.43 |
| 0.5-0.6 | 22, 0.55, 0.45 | 18, 0.55, 0.44 | 14, 0.55, 0.36 | 18, 0.55, 0.44 | 8, 0.55, 0.12 | 4, 0.58, 1.00 | 11, 0.55, 0.45 |
| 0.6-0.7 | 29, 0.65, 0.41 | 13, 0.64, 0.31 | 13, 0.65, 0.77 | 13, 0.64, 0.31 | 5, 0.67, 0.60 | 14, 0.65, 0.43 | 6, 0.64, 0.33 |
| 0.7-0.8 | 38, 0.76, 0.61 | 20, 0.74, 0.40 | 24, 0.75, 0.54 | 20, 0.74, 0.40 | 19, 0.76, 0.53 | 11, 0.76, 0.64 | 15, 0.77, 0.47 |
| 0.8-0.9 | 62, 0.85, 0.63 | 25, 0.86, 0.68 | 31, 0.86, 0.74 | 25, 0.86, 0.68 | 18, 0.85, 0.56 | 17, 0.85, 0.82 | 16, 0.85, 0.62 |
| 0.9-1.0 | 2082, 0.99, 0.95 | 670, 0.99, 0.95 | 44, 0.93, 0.95 | 670, 0.99, 0.95 | 698, 0.99, 0.95 | 698, 0.99, 0.94 | 693, 0.99, 0.96 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 346 | 4 | 12 | 0 | 0 | 25 | 0 | 0 | 4 | 0 | 0 | 2 | 0 | 2 | 0 | 15 |
| `check_recent_transactions` | 0 | 334 | 3 | 0 | 0 | 52 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 6 | 0 | 11 |
| `confirm` | 2 | 0 | 376 | 1 | 11 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| `deny` | 0 | 0 | 28 | 364 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `greeting` | 2 | 0 | 14 | 6 | 368 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 4 | 12 |
| `out_of_scope` | 0 | 2 | 12 | 16 | 30 | 308 | 0 | 0 | 0 | 2 | 18 | 0 | 2 | 0 | 0 | 20 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 396 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 400 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 360 | 32 | 6 | 0 | 2 | 0 | 0 | 10 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 392 | 6 | 0 | 0 | 0 | 0 | 10 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 2 | 388 | 2 | 0 | 2 | 2 | 10 |
| `report_unrecognized_charge` | 0 | 0 | 0 | 2 | 0 | 10 | 0 | 0 | 2 | 2 | 20 | 360 | 0 | 4 | 0 | 10 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 24 | 0 | 372 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 8 | 6 | 0 | 0 | 0 | 10 | 18 | 4 | 348 | 0 | 16 |
| `request_human_agent` | 0 | 0 | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 2 | 376 | 12 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "intent_hint": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "es-AR": {
            "T": 0.88783
          },
          "es-CO": {
            "T": 0.950337
          },
          "es-MX": {
            "T": 0.894171
          },
          "pt": {
            "T": 1.010123
          },
          "pt-BR": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "check_balance",
          "check_recent_transactions",
          "confirm",
          "deny",
          "greeting",
          "out_of_scope",
          "provide_identity_data",
          "provide_otp_code",
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ],
        "metric": "precision",
        "n_min": 10,
        "p_min": 0.9
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.0,
            "certified": false,
            "coverage_test": 0.0,
            "coverage_val": 0.0067,
            "ece_post": 0.1055,
            "ece_pre": 0.219,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "check_balance": [
                0,
                0,
                null
              ],
              "check_recent_transactions": [
                0,
                0,
                null
              ],
              "confirm": [
                0,
                0,
                null
              ],
              "deny": [
                0,
                0,
                null
              ],
              "greeting": [
                0,
                0,
                null
              ],
              "out_of_scope": [
                0,
                0,
                null
              ],
              "provide_identity_data": [
                0,
                0,
                null
              ],
              "provide_otp_code": [
                0,
                0,
                null
              ],
              "report_lost_card": [
                0,
                0,
                null
              ],
              "report_stolen_card": [
                0,
                0,
                null
              ],
              "report_suspicious_activity": [
                0,
                0,
                null
              ],
              "report_unrecognized_charge": [
                0,
                0,
                null
              ],
              "request_card_block": [
                0,
                0,
                null
              ],
              "request_dispute": [
                0,
                0,
                null
              ],
              "request_human_agent": [
                0,
                0,
                null
              ]
            },
            "recall_test": {
              "check_balance": 0.0,
              "check_recent_transactions": 0.0,
              "confirm": 0.0,
              "deny": 0.0,
              "greeting": 0.0,
              "out_of_scope": 0.0,
              "provide_identity_data": 0.0,
              "provide_otp_code": 0.0,
              "report_lost_card": 0.0,
              "report_stolen_card": 0.0,
              "report_suspicious_activity": 0.0,
              "report_unrecognized_charge": 0.0,
              "request_card_block": 0.0,
              "request_dispute": 0.0,
              "request_human_agent": 0.0
            }
          },
          "es": {
            "acted_coverage_test": 1.0,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0522,
            "ece_pre": 0.0473,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "check_balance": [
                131,
                131,
                0.9715
              ],
              "check_recent_transactions": [
                122,
                124,
                0.9431
              ],
              "confirm": [
                141,
                164,
                0.7983
              ],
              "deny": [
                139,
                146,
                0.9043
              ],
              "greeting": [
                140,
                159,
                0.8209
              ],
              "out_of_scope": [
                123,
                167,
                0.6649
              ],
              "provide_identity_data": [
                148,
                151,
                0.9432
              ],
              "provide_otp_code": [
                150,
                152,
                0.9533
              ],
              "report_lost_card": [
                132,
                138,
                0.9084
              ],
              "report_stolen_card": [
                149,
                163,
                0.861
              ],
              "report_suspicious_activity": [
                146,
                183,
                0.7338
              ],
              "report_unrecognized_charge": [
                138,
                147,
                0.8877
              ],
              "request_card_block": [
                139,
                141,
                0.9498
              ],
              "request_dispute": [
                134,
                140,
                0.9097
              ],
              "request_human_agent": [
                141,
                144,
                0.9405
              ]
            },
            "recall_test": {
              "check_balance": 0.8733,
              "check_recent_transactions": 0.8133,
              "confirm": 0.94,
              "deny": 0.9267,
              "greeting": 0.9333,
              "out_of_scope": 0.82,
              "provide_identity_data": 0.9867,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.88,
              "report_stolen_card": 0.9933,
              "report_suspicious_activity": 0.9733,
              "report_unrecognized_charge": 0.92,
              "request_card_block": 0.9267,
              "request_dispute": 0.8933,
              "request_human_agent": 0.94
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.9947,
            "certified": false,
            "coverage_test": 0.9947,
            "coverage_val": 1.0,
            "ece_post": 0.0604,
            "ece_pre": 0.0515,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                43,
                43,
                0.918
              ],
              "check_recent_transactions": [
                44,
                44,
                0.9197
              ],
              "confirm": [
                45,
                55,
                0.6967
              ],
              "deny": [
                46,
                49,
                0.8348
              ],
              "greeting": [
                45,
                51,
                0.7662
              ],
              "out_of_scope": [
                43,
                56,
                0.6423
              ],
              "provide_identity_data": [
                50,
                52,
                0.8702
              ],
              "provide_otp_code": [
                50,
                50,
                0.9287
              ],
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                64,
                0.6657
              ],
              "report_unrecognized_charge": [
                44,
                46,
                0.8547
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                44,
                45,
                0.8843
              ],
              "request_human_agent": [
                44,
                45,
                0.8843
              ]
            },
            "recall_test": {
              "check_balance": 0.86,
              "check_recent_transactions": 0.88,
              "confirm": 0.9,
              "deny": 0.92,
              "greeting": 0.9,
              "out_of_scope": 0.86,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.92,
              "request_dispute": 0.88,
              "request_human_agent": 0.88
            }
          },
          "es-CO": {
            "acted_coverage_test": 1.0,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0444,
            "ece_pre": 0.0416,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                45,
                45,
                0.9213
              ],
              "check_recent_transactions": [
                41,
                42,
                0.8768
              ],
              "confirm": [
                48,
                51,
                0.8408
              ],
              "deny": [
                48,
                48,
                0.9259
              ],
              "greeting": [
                50,
                56,
                0.7853
              ],
              "out_of_scope": [
                39,
                52,
                0.6179
              ],
              "provide_identity_data": [
                48,
                48,
                0.9259
              ],
              "provide_otp_code": [
                50,
                52,
                0.8702
              ],
              "report_lost_card": [
                42,
                46,
                0.7968
              ],
              "report_stolen_card": [
                49,
                55,
                0.7817
              ],
              "report_suspicious_activity": [
                46,
                58,
                0.6723
              ],
              "report_unrecognized_charge": [
                47,
                51,
                0.815
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                44,
                46,
                0.8547
              ],
              "request_human_agent": [
                50,
                51,
                0.897
              ]
            },
            "recall_test": {
              "check_balance": 0.9,
              "check_recent_transactions": 0.82,
              "confirm": 0.96,
              "deny": 0.96,
              "greeting": 1.0,
              "out_of_scope": 0.78,
              "provide_identity_data": 0.96,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.84,
              "report_stolen_card": 0.98,
              "report_suspicious_activity": 0.92,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.94,
              "request_dispute": 0.88,
              "request_human_agent": 1.0
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.9973,
            "certified": false,
            "coverage_test": 0.9973,
            "coverage_val": 1.0,
            "ece_post": 0.0567,
            "ece_pre": 0.0509,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                43,
                43,
                0.918
              ],
              "check_recent_transactions": [
                37,
                38,
                0.8651
              ],
              "confirm": [
                48,
                57,
                0.7264
              ],
              "deny": [
                45,
                48,
                0.8316
              ],
              "greeting": [
                45,
                51,
                0.7662
              ],
              "out_of_scope": [
                41,
                58,
                0.5799
              ],
              "provide_identity_data": [
                50,
                51,
                0.897
              ],
              "provide_otp_code": [
                50,
                50,
                0.9287
              ],
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                61,
                0.7053
              ],
              "report_unrecognized_charge": [
                47,
                50,
                0.8378
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                46,
                47,
                0.8889
              ],
              "request_human_agent": [
                47,
                48,
                0.891
              ]
            },
            "recall_test": {
              "check_balance": 0.86,
              "check_recent_transactions": 0.74,
              "confirm": 0.96,
              "deny": 0.9,
              "greeting": 0.9,
              "out_of_scope": 0.82,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.92,
              "request_dispute": 0.92,
              "request_human_agent": 0.94
            }
          },
          "pt": {
            "acted_coverage_test": 0.9853,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                42,
                44,
                0.8487
              ],
              "check_recent_transactions": [
                45,
                46,
                0.8866
              ],
              "confirm": [
                47,
                61,
                0.6509
              ],
              "deny": [
                43,
                50,
                0.7381
              ],
              "greeting": [
                44,
                51,
                0.7428
              ],
              "out_of_scope": [
                31,
                39,
                0.6447
              ],
              "provide_identity_data": [
                50,
                50,
                0.9287
              ],
              "provide_otp_code": [
                50,
                50,
                0.9287
              ],
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "check_balance": 0.84,
              "check_recent_transactions": 0.9,
              "confirm": 0.94,
              "deny": 0.86,
              "greeting": 0.88,
              "out_of_scope": 0.62,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.9853,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                42,
                44,
                0.8487
              ],
              "check_recent_transactions": [
                45,
                46,
                0.8866
              ],
              "confirm": [
                47,
                61,
                0.6509
              ],
              "deny": [
                43,
                50,
                0.7381
              ],
              "greeting": [
                44,
                51,
                0.7428
              ],
              "out_of_scope": [
                31,
                39,
                0.6447
              ],
              "provide_identity_data": [
                50,
                50,
                0.9287
              ],
              "provide_otp_code": [
                50,
                50,
                0.9287
              ],
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "check_balance": 0.84,
              "check_recent_transactions": 0.9,
              "confirm": 0.94,
              "deny": 0.86,
              "greeting": 0.88,
              "out_of_scope": 0.62,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.948382,
        "es": 0.339856,
        "es-AR": 0.471282,
        "es-CO": 0.331145,
        "es-MX": 0.487,
        "pt": 0.530052,
        "pt-BR": 0.530052
      },
      "view": {
        "kind": "labels",
        "labels": [
          "check_balance",
          "check_recent_transactions",
          "confirm",
          "deny",
          "greeting",
          "out_of_scope",
          "provide_identity_data",
          "provide_otp_code",
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ]
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.es-AR.T: 1.075648 -> 0.88783`
- `+ calibrator.by_lang.es-CO.T = 0.950337`
- `~ calibrator.by_lang.es-MX.T: 0.994325 -> 0.894171`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ calibrator.by_lang.pt-BR.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.24 -> 0.0`
- `~ evidence.per_lang.en.coverage_test: 0.24 -> 0.0`
- `~ evidence.per_lang.en.coverage_val: 0.2267 -> 0.0067`
- `~ evidence.per_lang.en.ece_post: 0.112 -> 0.1055`
- `~ evidence.per_lang.en.ece_pre: 0.2056 -> 0.219`
- `~ evidence.per_lang.en.precision_test.confirm: [4, 4, 0.5101] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.deny: [5, 5, 0.5655] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.greeting: [3, 3, 0.4385] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.provide_identity_data: [7, 7, 0.6457] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.provide_otp_code: [10, 10, 0.7225] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.report_stolen_card: [1, 1, 0.2065] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.request_human_agent: [6, 6, 0.6097] -> [0, 0, None]`
- `~ evidence.per_lang.en.recall_test.confirm: 0.4 -> 0.0`
- `~ evidence.per_lang.en.recall_test.deny: 0.5 -> 0.0`
- `~ evidence.per_lang.en.recall_test.greeting: 0.3 -> 0.0`
- `~ evidence.per_lang.en.recall_test.provide_identity_data: 0.7 -> 0.0`
- `~ evidence.per_lang.en.recall_test.provide_otp_code: 1.0 -> 0.0`
- `~ evidence.per_lang.en.recall_test.report_stolen_card: 0.1 -> 0.0`
- `~ evidence.per_lang.en.recall_test.request_human_agent: 0.6 -> 0.0`
- `~ evidence.per_lang.es.acted_coverage_test: 0.9887 -> 1.0`
- `~ evidence.per_lang.es.coverage_test: 0.9887 -> 1.0`
- `~ evidence.per_lang.es.ece_post: 0.0313 -> 0.0522`
- `~ evidence.per_lang.es.ece_pre: 0.0343 -> 0.0473`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.check_balance: [96, 101, 0.8893] -> [131, 131, 0.9715]`
- `~ evidence.per_lang.es.precision_test.check_recent_transactions: [84, 88, 0.8889] -> [122, 124, 0.9431]`
- `~ evidence.per_lang.es.precision_test.confirm: [91, 95, 0.8967] -> [141, 164, 0.7983]`
- `~ evidence.per_lang.es.precision_test.deny: [91, 95, 0.8967] -> [139, 146, 0.9043]`
- `~ evidence.per_lang.es.precision_test.greeting: [88, 92, 0.8935] -> [140, 159, 0.8209]`
- `~ evidence.per_lang.es.precision_test.out_of_scope: [88, 119, 0.654] -> [123, 167, 0.6649]`
- `~ evidence.per_lang.es.precision_test.provide_identity_data: [100, 100, 0.963] -> [148, 151, 0.9432]`
- `~ evidence.per_lang.es.precision_test.provide_otp_code: [100, 100, 0.963] -> [150, 152, 0.9533]`
- `~ evidence.per_lang.es.precision_test.report_lost_card: [96, 100, 0.9016] -> [132, 138, 0.9084]`
- `~ evidence.per_lang.es.precision_test.report_stolen_card: [100, 108, 0.8606] -> [149, 163, 0.861]`
- `~ evidence.per_lang.es.precision_test.report_suspicious_activity: [90, 99, 0.8362] -> [146, 183, 0.7338]`
- `~ evidence.per_lang.es.precision_test.report_unrecognized_charge: [96, 109, 0.8066] -> [138, 147, 0.8877]`
- `~ evidence.per_lang.es.precision_test.request_card_block: [91, 91, 0.9595] -> [139, 141, 0.9498]`
- `~ evidence.per_lang.es.precision_test.request_dispute: [84, 85, 0.9363] -> [134, 140, 0.9097]`
- `~ evidence.per_lang.es.precision_test.request_human_agent: [95, 101, 0.8764] -> [141, 144, 0.9405]`
- `~ evidence.per_lang.es.recall_test.check_balance: 0.96 -> 0.8733`
- `~ evidence.per_lang.es.recall_test.check_recent_transactions: 0.84 -> 0.8133`
- `~ evidence.per_lang.es.recall_test.confirm: 0.91 -> 0.94`
- `~ evidence.per_lang.es.recall_test.deny: 0.91 -> 0.9267`
- `~ evidence.per_lang.es.recall_test.greeting: 0.88 -> 0.9333`
- `~ evidence.per_lang.es.recall_test.out_of_scope: 0.88 -> 0.82`
- `~ evidence.per_lang.es.recall_test.provide_identity_data: 1.0 -> 0.9867`
- `~ evidence.per_lang.es.recall_test.report_lost_card: 0.96 -> 0.88`
- `~ evidence.per_lang.es.recall_test.report_stolen_card: 1.0 -> 0.9933`
- `~ evidence.per_lang.es.recall_test.report_suspicious_activity: 0.9 -> 0.9733`
- `~ evidence.per_lang.es.recall_test.report_unrecognized_charge: 0.96 -> 0.92`
- `~ evidence.per_lang.es.recall_test.request_card_block: 0.91 -> 0.9267`
- `~ evidence.per_lang.es.recall_test.request_dispute: 0.84 -> 0.8933`
- `~ evidence.per_lang.es.recall_test.request_human_agent: 0.95 -> 0.94`
- `~ evidence.per_lang.es-AR.acted_coverage_test: 0.9867 -> 0.9947`
- `~ evidence.per_lang.es-AR.coverage_test: 0.9867 -> 0.9947`
- `~ evidence.per_lang.es-AR.ece_post: 0.0298 -> 0.0604`
- `~ evidence.per_lang.es-AR.ece_pre: 0.0365 -> 0.0515`
- `~ evidence.per_lang.es-AR.precision_test.check_balance: [48, 49, 0.8931] -> [43, 43, 0.918]`
- `~ evidence.per_lang.es-AR.precision_test.check_recent_transactions: [44, 46, 0.8547] -> [44, 44, 0.9197]`
- `~ evidence.per_lang.es-AR.precision_test.confirm: [45, 46, 0.8866] -> [45, 55, 0.6967]`
- `~ evidence.per_lang.es-AR.precision_test.deny: [46, 48, 0.8602] -> [46, 49, 0.8348]`
- `~ evidence.per_lang.es-AR.precision_test.greeting: [45, 47, 0.8575] -> [45, 51, 0.7662]`
- `~ evidence.per_lang.es-AR.precision_test.out_of_scope: [44, 60, 0.6099] -> [43, 56, 0.6423]`
- `~ evidence.per_lang.es-AR.precision_test.provide_identity_data: [50, 50, 0.9287] -> [50, 52, 0.8702]`
- `~ evidence.per_lang.es-AR.precision_test.report_lost_card: [48, 50, 0.8654] -> [45, 46, 0.8866]`
- `~ evidence.per_lang.es-AR.precision_test.report_stolen_card: [50, 55, 0.8042] -> [50, 54, 0.8245]`
- `~ evidence.per_lang.es-AR.precision_test.report_suspicious_activity: [45, 51, 0.7662] -> [50, 64, 0.6657]`
- `~ evidence.per_lang.es-AR.precision_test.report_unrecognized_charge: [48, 54, 0.7781] -> [44, 46, 0.8547]`
- `... and 145 more changed fields`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (25 of 105 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## `clarify_route`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.90 ms, p95 9.57 ms (budget `timeout_ms` 1000); RAM model+inference 590.5 MB
- **Status written:** `calibrated`; certified: **no** (8 of 49 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 2250 | 0.9138 | 0.043 -> 0.042 |  |
| pt | 750 | 1.0101 | 0.062 -> 0.062 |  |
| en | 150 | 1.6670 | 1.319 -> 1.100 |  |
| pt-BR | 750 | 1.0101 | 0.062 -> 0.062 |  |
| es-MX | 750 | 0.8942 | 0.033 -> 0.032 |  |
| es-AR | 750 | 0.8878 | 0.040 -> 0.039 |  |
| es-CO | 750 | 0.9503 | 0.055 -> 0.055 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.339856 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.904958 | language |  |
| pt-BR | 0.530052 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.487000 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.471282 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-CO | 0.331145 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 2250 | 2250 | 100.0% | 100.0% | 46.9% | 0.922 | 0.047 | 0.052 | yes |
| pt | 750 | 750 | 100.0% | 98.5% | 46.4% | 0.898 | 0.062 | 0.061 | yes |
| en | 150 | 150 | 34.0% | 27.3% | 5.3% | 0.649 | 0.219 | 0.105 | no |
| pt-BR | 750 | 750 | 100.0% | 98.5% | 46.4% | 0.898 | 0.062 | 0.061 | yes |
| es-MX | 750 | 750 | 100.0% | 99.7% | 46.9% | 0.921 | 0.051 | 0.057 | yes |
| es-AR | 750 | 750 | 100.0% | 99.5% | 46.1% | 0.920 | 0.052 | 0.060 | yes |
| es-CO | 750 | 750 | 100.0% | 100.0% | 47.5% | 0.926 | 0.042 | 0.044 | yes |
| all | 6150 | 6150 | 98.4% | 97.8% | 45.8% | 0.911 | 0.055 | 0.055 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `report_lost_card` | 150 | 138 | 132 | 0.957 | 0.908 | 0.880 | 0.90 |
| es | `report_stolen_card` | 150 | 163 | 149 | 0.914 | 0.861 | 0.993 | 0.90 |
| es | `report_suspicious_activity` | 150 | 183 | 146 | 0.798 | 0.734 | 0.973 | 0.90 |
| es | `report_unrecognized_charge` | 150 | 147 | 138 | 0.939 | 0.888 | 0.920 | 0.90 |
| es | `request_card_block` | 150 | 141 | 139 | 0.986 | 0.950 | 0.927 | 0.90 |
| es | `request_dispute` | 150 | 140 | 134 | 0.957 | 0.910 | 0.893 | 0.90 |
| es | `request_human_agent` | 150 | 144 | 141 | 0.979 | 0.941 | 0.940 | 0.90 |
| pt | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| en | `report_lost_card` | 10 | 1 | 1 | 1.000 | 0.207 | 0.100 | 0.90 |
| en | `report_stolen_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_suspicious_activity` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_human_agent` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 51 | 48 | 0.941 | 0.841 | 0.960 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 54 | 47 | 0.870 | 0.756 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 59 | 48 | 0.814 | 0.696 | 0.960 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 44 | 42 | 0.955 | 0.849 | 0.840 | 0.90 |
| pt-BR | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| pt-BR | `request_dispute` | 50 | 44 | 40 | 0.909 | 0.788 | 0.800 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 61 | 50 | 0.820 | 0.705 | 1.000 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 50 | 47 | 0.940 | 0.838 | 0.940 | 0.90 |
| es-MX | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-MX | `request_dispute` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `request_human_agent` | 50 | 48 | 47 | 0.979 | 0.891 | 0.940 | 0.90 |
| es-AR | `report_lost_card` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 54 | 50 | 0.926 | 0.824 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 64 | 50 | 0.781 | 0.666 | 1.000 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-AR | `request_card_block` | 50 | 46 | 46 | 1.000 | 0.923 | 0.920 | 0.90 |
| es-AR | `request_dispute` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-AR | `request_human_agent` | 50 | 45 | 44 | 0.978 | 0.884 | 0.880 | 0.90 |
| es-CO | `report_lost_card` | 50 | 46 | 42 | 0.913 | 0.797 | 0.840 | 0.90 |
| es-CO | `report_stolen_card` | 50 | 55 | 49 | 0.891 | 0.782 | 0.980 | 0.90 |
| es-CO | `report_suspicious_activity` | 50 | 58 | 46 | 0.793 | 0.672 | 0.920 | 0.90 |
| es-CO | `report_unrecognized_charge` | 50 | 51 | 47 | 0.922 | 0.815 | 0.940 | 0.90 |
| es-CO | `request_card_block` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| es-CO | `request_dispute` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-CO | `request_human_agent` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| all | `report_lost_card` | 410 | 379 | 361 | 0.953 | 0.926 | 0.880 | 0.90 |
| all | `report_stolen_card` | 410 | 434 | 392 | 0.903 | 0.872 | 0.956 | 0.90 |
| all | `report_suspicious_activity` | 410 | 488 | 392 | 0.803 | 0.766 | 0.956 | 0.90 |
| all | `report_unrecognized_charge` | 410 | 382 | 360 | 0.942 | 0.914 | 0.878 | 0.90 |
| all | `request_card_block` | 410 | 380 | 372 | 0.979 | 0.959 | 0.907 | 0.90 |
| all | `request_dispute` | 410 | 366 | 348 | 0.951 | 0.924 | 0.849 | 0.90 |
| all | `request_human_agent` | 410 | 385 | 379 | 0.984 | 0.966 | 0.924 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `check_balance` | 410 | 350 | 346 | 0.989 | 0.971 | 0.844 | not acted on |
| all | `check_recent_transactions` | 410 | 340 | 334 | 0.982 | 0.962 | 0.815 | not acted on |
| all | `confirm` | 410 | 455 | 381 | 0.837 | 0.801 | 0.929 | not acted on |
| all | `deny` | 410 | 400 | 373 | 0.932 | 0.904 | 0.910 | not acted on |
| all | `greeting` | 410 | 423 | 371 | 0.877 | 0.842 | 0.905 | not acted on |
| all | `out_of_scope` | 410 | 411 | 308 | 0.749 | 0.705 | 0.751 | not acted on |
| all | `provide_identity_data` | 410 | 407 | 401 | 0.985 | 0.968 | 0.978 | not acted on |
| all | `provide_otp_code` | 410 | 413 | 409 | 0.990 | 0.975 | 0.998 | not acted on |
| all | `report_lost_card` | 410 | 379 | 361 | 0.953 | 0.926 | 0.880 | 0.90 |
| all | `report_stolen_card` | 410 | 434 | 392 | 0.903 | 0.872 | 0.956 | 0.90 |
| all | `report_suspicious_activity` | 410 | 488 | 392 | 0.803 | 0.766 | 0.956 | 0.90 |
| all | `report_unrecognized_charge` | 410 | 382 | 360 | 0.942 | 0.914 | 0.878 | 0.90 |
| all | `request_card_block` | 410 | 380 | 372 | 0.979 | 0.959 | 0.907 | 0.90 |
| all | `request_dispute` | 410 | 366 | 348 | 0.951 | 0.924 | 0.849 | 0.90 |
| all | `request_human_agent` | 410 | 385 | 379 | 0.984 | 0.966 | 0.924 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `report_lost_card` | 132/138 | 0.908 | 0.90 | yes |  |
| pt | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| en | `report_lost_card` | 1/1 | 0.207 | 0.90 | no | 35 decided with zero errors (has 1/1) |
| pt-BR | `report_lost_card` | 48/51 | 0.841 | 0.90 | no | 35 decided with zero errors (has 48/51) |
| es-MX | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-AR | `report_lost_card` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es-CO | `report_lost_card` | 42/46 | 0.797 | 0.90 | no | 35 decided with zero errors (has 42/46) |
| es | `report_stolen_card` | 149/163 | 0.861 | 0.90 | no | 35 decided with zero errors (has 149/163) |
| pt | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| en | `report_stolen_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_stolen_card` | 47/54 | 0.756 | 0.90 | no | 35 decided with zero errors (has 47/54) |
| es-MX | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-AR | `report_stolen_card` | 50/54 | 0.824 | 0.90 | no | 35 decided with zero errors (has 50/54) |
| es-CO | `report_stolen_card` | 49/55 | 0.782 | 0.90 | no | 35 decided with zero errors (has 49/55) |
| es | `report_suspicious_activity` | 146/183 | 0.734 | 0.90 | no | 35 decided with zero errors (has 146/183) |
| pt | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| en | `report_suspicious_activity` | 4/4 | 0.510 | 0.90 | no | 35 decided with zero errors (has 4/4) |
| pt-BR | `report_suspicious_activity` | 48/59 | 0.696 | 0.90 | no | 35 decided with zero errors (has 48/59) |
| es-MX | `report_suspicious_activity` | 50/61 | 0.705 | 0.90 | no | 35 decided with zero errors (has 50/61) |
| es-AR | `report_suspicious_activity` | 50/64 | 0.666 | 0.90 | no | 35 decided with zero errors (has 50/64) |
| es-CO | `report_suspicious_activity` | 46/58 | 0.672 | 0.90 | no | 35 decided with zero errors (has 46/58) |
| es | `report_unrecognized_charge` | 138/147 | 0.888 | 0.90 | no | 35 decided with zero errors (has 138/147) |
| pt | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| en | `report_unrecognized_charge` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_unrecognized_charge` | 42/44 | 0.849 | 0.90 | no | 35 decided with zero errors (has 42/44) |
| es-MX | `report_unrecognized_charge` | 47/50 | 0.838 | 0.90 | no | 35 decided with zero errors (has 47/50) |
| es-AR | `report_unrecognized_charge` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es-CO | `report_unrecognized_charge` | 47/51 | 0.815 | 0.90 | no | 35 decided with zero errors (has 47/51) |
| es | `request_card_block` | 139/141 | 0.950 | 0.90 | yes |  |
| pt | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es-MX | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-AR | `request_card_block` | 46/46 | 0.923 | 0.90 | yes |  |
| es-CO | `request_card_block` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| es | `request_dispute` | 134/140 | 0.910 | 0.90 | yes |  |
| pt | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| en | `request_dispute` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_dispute` | 40/44 | 0.788 | 0.90 | no | 35 decided with zero errors (has 40/44) |
| es-MX | `request_dispute` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-AR | `request_dispute` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_dispute` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es | `request_human_agent` | 141/144 | 0.941 | 0.90 | yes |  |
| pt | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| en | `request_human_agent` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| pt-BR | `request_human_agent` | 47/47 | 0.924 | 0.90 | yes |  |
| es-MX | `request_human_agent` | 47/48 | 0.891 | 0.90 | no | 35 decided with zero errors (has 47/48) |
| es-AR | `request_human_agent` | 44/45 | 0.884 | 0.90 | no | 35 decided with zero errors (has 44/45) |
| es-CO | `request_human_agent` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc | es-CO: n, conf, acc |
|---|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 1, 0.27, 0.00 | 0 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.37, 0.00 | 1, 0.37, 0.00 | 9, 0.35, 0.33 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 1, 0.37, 0.00 | 2, 0.36, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.23 | 3, 0.47, 0.00 | 14, 0.45, 0.36 | 3, 0.47, 0.00 | 1, 0.42, 0.00 | 5, 0.46, 0.00 | 7, 0.45, 0.43 |
| 0.5-0.6 | 22, 0.55, 0.45 | 18, 0.55, 0.44 | 14, 0.55, 0.36 | 18, 0.55, 0.44 | 8, 0.55, 0.12 | 4, 0.58, 1.00 | 11, 0.55, 0.45 |
| 0.6-0.7 | 29, 0.65, 0.41 | 13, 0.64, 0.31 | 13, 0.65, 0.77 | 13, 0.64, 0.31 | 5, 0.67, 0.60 | 14, 0.65, 0.43 | 6, 0.64, 0.33 |
| 0.7-0.8 | 38, 0.76, 0.61 | 20, 0.74, 0.40 | 24, 0.75, 0.54 | 20, 0.74, 0.40 | 19, 0.76, 0.53 | 11, 0.76, 0.64 | 15, 0.77, 0.47 |
| 0.8-0.9 | 62, 0.85, 0.63 | 25, 0.86, 0.68 | 31, 0.86, 0.74 | 25, 0.86, 0.68 | 18, 0.85, 0.56 | 17, 0.85, 0.82 | 16, 0.85, 0.62 |
| 0.9-1.0 | 2082, 0.99, 0.95 | 670, 0.99, 0.95 | 44, 0.93, 0.95 | 670, 0.99, 0.95 | 698, 0.99, 0.95 | 698, 0.99, 0.94 | 693, 0.99, 0.96 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 346 | 4 | 13 | 0 | 0 | 25 | 0 | 0 | 4 | 0 | 0 | 2 | 0 | 2 | 0 | 14 |
| `check_recent_transactions` | 0 | 334 | 3 | 0 | 0 | 52 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 6 | 0 | 11 |
| `confirm` | 2 | 0 | 381 | 1 | 11 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 7 |
| `deny` | 0 | 0 | 28 | 373 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `greeting` | 2 | 0 | 14 | 6 | 371 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 4 | 9 |
| `out_of_scope` | 0 | 2 | 12 | 16 | 31 | 308 | 0 | 0 | 0 | 2 | 18 | 0 | 2 | 0 | 0 | 19 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 401 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 409 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 361 | 32 | 6 | 0 | 2 | 0 | 0 | 9 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 392 | 6 | 0 | 0 | 0 | 0 | 10 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 2 | 392 | 2 | 0 | 2 | 2 | 6 |
| `report_unrecognized_charge` | 0 | 0 | 0 | 2 | 0 | 10 | 0 | 0 | 2 | 2 | 20 | 360 | 0 | 4 | 0 | 10 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 24 | 0 | 372 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 8 | 6 | 0 | 0 | 0 | 10 | 18 | 4 | 348 | 0 | 16 |
| `request_human_agent` | 0 | 0 | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 2 | 379 | 9 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_distilbert": {
      "cost_class": "low",
      "kind": "hf_seqcls",
      "labels": [
        "report_unrecognized_charge",
        "report_lost_card",
        "report_stolen_card",
        "report_suspicious_activity",
        "request_card_block",
        "request_dispute",
        "request_human_agent",
        "provide_identity_data",
        "provide_otp_code",
        "confirm",
        "deny",
        "check_balance",
        "check_recent_transactions",
        "greeting",
        "out_of_scope"
      ],
      "local_only": true,
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:56b52ec70460",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:7fd8bff09544",
      "timeout_ms": 1000,
      "weights_sha256": "56b52ec704608093974f0389147dcee6b29a5b54744d40ef116963d587512cc2"
    }
  },
  "decision_points": {
    "clarify_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.666988
          },
          "es": {
            "T": 0.91377
          },
          "es-AR": {
            "T": 0.88783
          },
          "es-CO": {
            "T": 0.950337
          },
          "es-MX": {
            "T": 0.894171
          },
          "pt": {
            "T": 1.010123
          },
          "pt-BR": {
            "T": 1.010123
          }
        },
        "kind": "temperature"
      },
      "constraint": {
        "calibration_split": "validation",
        "ci": "point",
        "labels": [
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ],
        "metric": "precision",
        "n_min": 10,
        "p_min": 0.9
      },
      "enabled": true,
      "evidence": {
        "candidate": "intent_distilbert",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points_distilbert.yaml",
          "sha256": "a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.0533,
            "certified": false,
            "coverage_test": 0.2733,
            "coverage_val": 0.34,
            "ece_post": 0.1055,
            "ece_pre": 0.219,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                1,
                1,
                0.2065
              ],
              "report_stolen_card": [
                0,
                0,
                null
              ],
              "report_suspicious_activity": [
                4,
                4,
                0.5101
              ],
              "report_unrecognized_charge": [
                0,
                0,
                null
              ],
              "request_card_block": [
                0,
                0,
                null
              ],
              "request_dispute": [
                0,
                0,
                null
              ],
              "request_human_agent": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "report_lost_card": 0.1,
              "report_stolen_card": 0.0,
              "report_suspicious_activity": 0.4,
              "report_unrecognized_charge": 0.0,
              "request_card_block": 0.0,
              "request_dispute": 0.0,
              "request_human_agent": 0.3
            }
          },
          "es": {
            "acted_coverage_test": 0.4693,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0522,
            "ece_pre": 0.0473,
            "n_test": 2250,
            "n_val": 2250,
            "precision_test": {
              "report_lost_card": [
                132,
                138,
                0.9084
              ],
              "report_stolen_card": [
                149,
                163,
                0.861
              ],
              "report_suspicious_activity": [
                146,
                183,
                0.7338
              ],
              "report_unrecognized_charge": [
                138,
                147,
                0.8877
              ],
              "request_card_block": [
                139,
                141,
                0.9498
              ],
              "request_dispute": [
                134,
                140,
                0.9097
              ],
              "request_human_agent": [
                141,
                144,
                0.9405
              ]
            },
            "recall_test": {
              "report_lost_card": 0.88,
              "report_stolen_card": 0.9933,
              "report_suspicious_activity": 0.9733,
              "report_unrecognized_charge": 0.92,
              "request_card_block": 0.9267,
              "request_dispute": 0.8933,
              "request_human_agent": 0.94
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.4613,
            "certified": false,
            "coverage_test": 0.9947,
            "coverage_val": 1.0,
            "ece_post": 0.0604,
            "ece_pre": 0.0515,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                64,
                0.6657
              ],
              "report_unrecognized_charge": [
                44,
                46,
                0.8547
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                44,
                45,
                0.8843
              ],
              "request_human_agent": [
                44,
                45,
                0.8843
              ]
            },
            "recall_test": {
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.92,
              "request_dispute": 0.88,
              "request_human_agent": 0.88
            }
          },
          "es-CO": {
            "acted_coverage_test": 0.4747,
            "certified": false,
            "coverage_test": 1.0,
            "coverage_val": 1.0,
            "ece_post": 0.0444,
            "ece_pre": 0.0416,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                42,
                46,
                0.7968
              ],
              "report_stolen_card": [
                49,
                55,
                0.7817
              ],
              "report_suspicious_activity": [
                46,
                58,
                0.6723
              ],
              "report_unrecognized_charge": [
                47,
                51,
                0.815
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                44,
                46,
                0.8547
              ],
              "request_human_agent": [
                50,
                51,
                0.897
              ]
            },
            "recall_test": {
              "report_lost_card": 0.84,
              "report_stolen_card": 0.98,
              "report_suspicious_activity": 0.92,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.94,
              "request_dispute": 0.88,
              "request_human_agent": 1.0
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.4693,
            "certified": false,
            "coverage_test": 0.9973,
            "coverage_val": 1.0,
            "ece_post": 0.0567,
            "ece_pre": 0.0509,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                45,
                46,
                0.8866
              ],
              "report_stolen_card": [
                50,
                54,
                0.8245
              ],
              "report_suspicious_activity": [
                50,
                61,
                0.7053
              ],
              "report_unrecognized_charge": [
                47,
                50,
                0.8378
              ],
              "request_card_block": [
                46,
                46,
                0.9229
              ],
              "request_dispute": [
                46,
                47,
                0.8889
              ],
              "request_human_agent": [
                47,
                48,
                0.891
              ]
            },
            "recall_test": {
              "report_lost_card": 0.9,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 1.0,
              "report_unrecognized_charge": 0.94,
              "request_card_block": 0.92,
              "request_dispute": 0.92,
              "request_human_agent": 0.94
            }
          },
          "pt": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.9853,
            "coverage_val": 1.0,
            "ece_post": 0.0613,
            "ece_pre": 0.0621,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                51,
                0.8408
              ],
              "report_stolen_card": [
                47,
                54,
                0.7558
              ],
              "report_suspicious_activity": [
                48,
                59,
                0.6962
              ],
              "report_unrecognized_charge": [
                42,
                44,
                0.8487
              ],
              "request_card_block": [
                47,
                49,
                0.8629
              ],
              "request_dispute": [
                40,
                44,
                0.7884
              ],
              "request_human_agent": [
                47,
                47,
                0.9244
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.96,
              "report_unrecognized_charge": 0.84,
              "request_card_block": 0.94,
              "request_dispute": 0.8,
              "request_human_agent": 0.94
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-10-01-distilbert.md",
        "run_id": "6601ebbc444e",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.904958,
        "es": 0.339856,
        "es-AR": 0.471282,
        "es-CO": 0.331145,
        "es-MX": 0.487,
        "pt": 0.530052,
        "pt-BR": 0.530052
      },
      "view": {
        "kind": "labels",
        "labels": [
          "check_balance",
          "check_recent_transactions",
          "confirm",
          "deny",
          "greeting",
          "out_of_scope",
          "provide_identity_data",
          "provide_otp_code",
          "report_lost_card",
          "report_stolen_card",
          "report_suspicious_activity",
          "report_unrecognized_charge",
          "request_card_block",
          "request_dispute",
          "request_human_agent"
        ]
      }
    }
  }
}
```

### Diff against the previous artifact

- `~ calibrator.by_lang.en.T: 1.525664 -> 1.666988`
- `~ calibrator.by_lang.es.T: 1.039443 -> 0.91377`
- `~ calibrator.by_lang.es-AR.T: 1.075648 -> 0.88783`
- `+ calibrator.by_lang.es-CO.T = 0.950337`
- `~ calibrator.by_lang.es-MX.T: 0.994325 -> 0.894171`
- `~ calibrator.by_lang.pt.T: 1.03712 -> 1.010123`
- `~ calibrator.by_lang.pt-BR.T: 1.03712 -> 1.010123`
- `~ evidence.config.sha256: 'd7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046' -> 'a7bf673fc652a3c0aac494d083a9f7d56a08242ae46d407fd3c82a9f67f58901'`
- `~ evidence.data.test.sha256: 'e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6' -> 'ede4a2ea431afdd95b28a94c4fddf0d670c7b3258f63c523cc9ed7015ca80c3c'`
- `~ evidence.data.train.sha256: '7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49' -> '7bf0412b479c0c2b83ff306daeb078a72a74c769a7c56d5388ec4d71ef63567f'`
- `~ evidence.data.validation.sha256: '28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e' -> 'c08804e29dee46fc052c64baf031a759961c9abb7342d2088f6cf35200eb28a7'`
- `~ evidence.per_lang.en.acted_coverage_test: 0.16 -> 0.0533`
- `~ evidence.per_lang.en.coverage_test: 0.4533 -> 0.2733`
- `~ evidence.per_lang.en.coverage_val: 0.5133 -> 0.34`
- `~ evidence.per_lang.en.ece_post: 0.112 -> 0.1055`
- `~ evidence.per_lang.en.ece_pre: 0.2056 -> 0.219`
- `~ evidence.per_lang.en.precision_test.report_lost_card: [0, 0, None] -> [1, 1, 0.2065]`
- `~ evidence.per_lang.en.precision_test.report_stolen_card: [3, 3, 0.4385] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.report_suspicious_activity: [6, 7, 0.4869] -> [4, 4, 0.5101]`
- `~ evidence.per_lang.en.precision_test.report_unrecognized_charge: [5, 5, 0.5655] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.request_dispute: [1, 1, 0.2065] -> [0, 0, None]`
- `~ evidence.per_lang.en.precision_test.request_human_agent: [8, 8, 0.6756] -> [3, 3, 0.4385]`
- `~ evidence.per_lang.en.recall_test.report_lost_card: 0.0 -> 0.1`
- `~ evidence.per_lang.en.recall_test.report_stolen_card: 0.3 -> 0.0`
- `~ evidence.per_lang.en.recall_test.report_suspicious_activity: 0.6 -> 0.4`
- `~ evidence.per_lang.en.recall_test.report_unrecognized_charge: 0.5 -> 0.0`
- `~ evidence.per_lang.en.recall_test.request_dispute: 0.1 -> 0.0`
- `~ evidence.per_lang.en.recall_test.request_human_agent: 0.8 -> 0.3`
- `~ evidence.per_lang.es.acted_coverage_test: 0.462 -> 0.4693`
- `~ evidence.per_lang.es.coverage_test: 0.9887 -> 1.0`
- `~ evidence.per_lang.es.ece_post: 0.0313 -> 0.0522`
- `~ evidence.per_lang.es.ece_pre: 0.0343 -> 0.0473`
- `~ evidence.per_lang.es.n_test: 1500 -> 2250`
- `~ evidence.per_lang.es.n_val: 1500 -> 2250`
- `~ evidence.per_lang.es.precision_test.report_lost_card: [96, 100, 0.9016] -> [132, 138, 0.9084]`
- `~ evidence.per_lang.es.precision_test.report_stolen_card: [100, 108, 0.8606] -> [149, 163, 0.861]`
- `~ evidence.per_lang.es.precision_test.report_suspicious_activity: [90, 99, 0.8362] -> [146, 183, 0.7338]`
- `~ evidence.per_lang.es.precision_test.report_unrecognized_charge: [96, 109, 0.8066] -> [138, 147, 0.8877]`
- `~ evidence.per_lang.es.precision_test.request_card_block: [91, 91, 0.9595] -> [139, 141, 0.9498]`
- `~ evidence.per_lang.es.precision_test.request_dispute: [84, 85, 0.9363] -> [134, 140, 0.9097]`
- `~ evidence.per_lang.es.precision_test.request_human_agent: [95, 101, 0.8764] -> [141, 144, 0.9405]`
- `~ evidence.per_lang.es.recall_test.report_lost_card: 0.96 -> 0.88`
- `~ evidence.per_lang.es.recall_test.report_stolen_card: 1.0 -> 0.9933`
- `~ evidence.per_lang.es.recall_test.report_suspicious_activity: 0.9 -> 0.9733`
- `~ evidence.per_lang.es.recall_test.report_unrecognized_charge: 0.96 -> 0.92`
- `~ evidence.per_lang.es.recall_test.request_card_block: 0.91 -> 0.9267`
- `~ evidence.per_lang.es.recall_test.request_dispute: 0.84 -> 0.8933`
- `~ evidence.per_lang.es.recall_test.request_human_agent: 0.95 -> 0.94`
- `~ evidence.per_lang.es-AR.acted_coverage_test: 0.4587 -> 0.4613`
- `~ evidence.per_lang.es-AR.coverage_test: 0.9867 -> 0.9947`
- `~ evidence.per_lang.es-AR.ece_post: 0.0298 -> 0.0604`
- `~ evidence.per_lang.es-AR.ece_pre: 0.0365 -> 0.0515`
- `~ evidence.per_lang.es-AR.precision_test.report_lost_card: [48, 50, 0.8654] -> [45, 46, 0.8866]`
- `~ evidence.per_lang.es-AR.precision_test.report_stolen_card: [50, 55, 0.8042] -> [50, 54, 0.8245]`
- `~ evidence.per_lang.es-AR.precision_test.report_suspicious_activity: [45, 51, 0.7662] -> [50, 64, 0.6657]`
- `~ evidence.per_lang.es-AR.precision_test.report_unrecognized_charge: [48, 54, 0.7781] -> [44, 46, 0.8547]`
- `~ evidence.per_lang.es-AR.precision_test.request_card_block: [44, 44, 0.9197] -> [46, 46, 0.9229]`
- `~ evidence.per_lang.es-AR.precision_test.request_dispute: [41, 42, 0.8768] -> [44, 45, 0.8843]`
- `~ evidence.per_lang.es-AR.precision_test.request_human_agent: [45, 48, 0.8316] -> [44, 45, 0.8843]`
- `~ evidence.per_lang.es-AR.recall_test.report_lost_card: 0.96 -> 0.9`
- `~ evidence.per_lang.es-AR.recall_test.report_suspicious_activity: 0.9 -> 1.0`
- `~ evidence.per_lang.es-AR.recall_test.report_unrecognized_charge: 0.96 -> 0.88`
- `~ evidence.per_lang.es-AR.recall_test.request_card_block: 0.88 -> 0.92`
- `~ evidence.per_lang.es-AR.recall_test.request_dispute: 0.82 -> 0.88`
- `~ evidence.per_lang.es-AR.recall_test.request_human_agent: 0.9 -> 0.88`
- `+ evidence.per_lang.es-CO.acted_coverage_test = 0.4747`
- `+ evidence.per_lang.es-CO.certified = False`
- `+ evidence.per_lang.es-CO.coverage_test = 1.0`
- `+ evidence.per_lang.es-CO.coverage_val = 1.0`
- `+ evidence.per_lang.es-CO.ece_post = 0.0444`
- `+ evidence.per_lang.es-CO.ece_pre = 0.0416`
- `+ evidence.per_lang.es-CO.n_test = 750`
- `+ evidence.per_lang.es-CO.n_val = 750`
- `+ evidence.per_lang.es-CO.precision_test.report_lost_card = [42, 46, 0.7968]`
- `+ evidence.per_lang.es-CO.precision_test.report_stolen_card = [49, 55, 0.7817]`
- `+ evidence.per_lang.es-CO.precision_test.report_suspicious_activity = [46, 58, 0.6723]`
- `+ evidence.per_lang.es-CO.precision_test.report_unrecognized_charge = [47, 51, 0.815]`
- `+ evidence.per_lang.es-CO.precision_test.request_card_block = [47, 49, 0.8629]`
- `+ evidence.per_lang.es-CO.precision_test.request_dispute = [44, 46, 0.8547]`
- `+ evidence.per_lang.es-CO.precision_test.request_human_agent = [50, 51, 0.897]`
- `... and 65 more changed fields`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (8 of 49 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 590.5 MB; the encoder's memory floor is checked by the service at startup).
- [ ] `make calibration-verify` and the encoder tests pass (run after committing the artifact).
- [ ] Shadow traffic or the eval run shows the DP against the LLM (`select_agreement`, `would_apply`): pending, needs WP4/WP6.
- [ ] Report and artifact committed; the `enforce` diff separate and reviewed.

**Sign-off: not ready for enforce.** A human signs off; this harness only computes the numbers.

## Residual risks

- The test split is AI-written and small; per-language precision has wide intervals (see the Wilson columns). No decision point is certified.
- tau was chosen with the point estimate on validation, which holds 10 rows per label and language: it is a starting point for shadow traffic, not a guarantee. Switch `constraint.ci` to `wilson95_lower` when validation is large enough to satisfy it.
- Labels outside a DP's constraint (for example `other`) are decided whenever they are on top; the engine does not act on them. `out_of_scope` is a sink (short replies, bare OTP digits): where it is constrained (`smalltalk_route`) read its precision above before trusting it (ADR-0012, context item 2).
- No hard-negative set exists; the gate's worst failure (a false `confirm`) is measured on ordinary utterances only.
- Latency and RAM are host measurements of one process, not the container limits; `make encoder-bench` for artifact backends is pending (WP7).
