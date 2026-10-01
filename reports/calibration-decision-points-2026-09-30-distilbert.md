# Decision Points Calibration Report

> [!WARNING]
> The test split is **provisional synthetic (not human)**: written by an AI agent, 10 rows per intent and language, never double-labeled. It cannot certify a precision of 0.95 (or 0.90): 22 correct of 22 accepted has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted with zero errors.
> Validation shares its generating process with train, so a calibrator fitted on it is over-confident on real traffic. Thresholds here are chosen on validation only; nothing in this report is a guarantee on real customers.
> Every decision point stays in `shadow` until a separate reviewed diff flips it to `enforce` after the sign-off of ADR-0012, Appendix F.5.

- **Run id:** `aa9fde2d56f3`
- **Date:** 2026-09-30
- **Task:** `decision-points` (ADR-0012, Appendix F)
- **Decision points in this run:** `turn_intent`, `confirm_gate`, `block_reason`, `handoff_route`, `smalltalk_route`, `intent_hint`, `clarify_route`
- **Artifact:** `packages/encoder/calibration/decision_points.distilbert.json` -> `artifact_id` `1697e0f1c15e` (official run: merged into the committed artifact)
- **Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, scikit-learn 1.9.1, 12 CPUs (host, single process; not measured under the container limits)

## Provenance and hashes

- **Configuration:** `tools/calibrate/configs/decision_points_distilbert.yaml` (`d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046`)
- **Data (per decision point):**
  - `data/staging/decision_pooled/decision.pooled.train.jsonl` (train): `7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49`
  - `data/staging/decision_pooled/decision.pooled.validation.jsonl` (validation): `28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e`
  - `data/staging/decision_pooled/decision.pooled.test.jsonl` (test): `e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6`
  - `data/eval/synthetic/decision.train.jsonl` (train): `a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984`
  - `data/eval/synthetic/decision.validation.jsonl` (validation): `50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699`
  - `data/eval/synthetic/decision.test.provisional.jsonl` (test): `06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7`
- **Test provenance:** synthetic-provisional
- **Backends:**
  - `gate_tfidf`: `tfidf_lr@map-38e4e1a6/train-sha256:a563c0c445d6`
  - `intent_distilbert`: `hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`

## Certification status

| Decision point | Status | Certified | Detail |
|---|---|:---:|---|
| `turn_intent` | calibrated | no | 6 of 42 scopes clear the Wilson bound |
| `confirm_gate` | calibrated | no | 0 of 6 scopes clear the Wilson bound |
| `block_reason` | calibrated | no | 0 of 15 scopes clear the Wilson bound |
| `handoff_route` | calibrated | no | 0 of 12 scopes clear the Wilson bound |
| `smalltalk_route` | calibrated | no | 0 of 12 scopes clear the Wilson bound |
| `intent_hint` | calibrated | no | 14 of 90 scopes clear the Wilson bound |
| `clarify_route` | calibrated | no | 6 of 42 scopes clear the Wilson bound |

## Findings

The threshold chosen on validation did not hold on the held-out test split for these acted labels: their precision is below the floor even by the point estimate.

| Decision point | Scope | Label | Correct / decided | Precision | Floor |
|---|---|---|---:|---:|---:|
| `turn_intent` | pt | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `turn_intent` | pt-BR | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `turn_intent` | pt | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `turn_intent` | pt-BR | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `turn_intent` | en | `report_suspicious_activity` | 6/7 | 0.86 | 0.90 |
| `turn_intent` | es-AR | `report_suspicious_activity` | 45/51 | 0.88 | 0.90 |
| `turn_intent` | es | `report_unrecognized_charge` | 96/109 | 0.88 | 0.90 |
| `turn_intent` | pt | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `turn_intent` | pt-BR | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `turn_intent` | es-MX | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |
| `turn_intent` | es-AR | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |
| `confirm_gate` | es | `deny` | 9/11 | 0.82 | 0.90 |
| `confirm_gate` | pt | `deny` | 9/11 | 0.82 | 0.90 |
| `block_reason` | es | `LOST` | 96/122 | 0.79 | 0.90 |
| `block_reason` | pt | `LOST` | 46/61 | 0.75 | 0.90 |
| `block_reason` | pooled (en) | `LOST` | 4/10 | 0.40 | 0.90 |
| `block_reason` | es | `STOLEN` | 100/115 | 0.87 | 0.90 |
| `block_reason` | pt | `STOLEN` | 47/56 | 0.84 | 0.90 |
| `block_reason` | pooled (en) | `STOLEN` | 5/12 | 0.42 | 0.90 |
| `block_reason` | es | `UNRECOGNIZED_CHARGE` | 96/111 | 0.86 | 0.90 |
| `block_reason` | pt | `UNRECOGNIZED_CHARGE` | 45/62 | 0.73 | 0.90 |
| `block_reason` | pooled (en) | `UNRECOGNIZED_CHARGE` | 6/9 | 0.67 | 0.90 |
| `block_reason` | es | `SUSPICIOUS_ACTIVITY` | 95/153 | 0.62 | 0.90 |
| `block_reason` | pooled (en) | `SUSPICIOUS_ACTIVITY` | 9/30 | 0.30 | 0.90 |
| `block_reason` | es | `CUSTOMER_REQUEST` | 92/114 | 0.81 | 0.90 |
| `block_reason` | pt | `CUSTOMER_REQUEST` | 48/67 | 0.72 | 0.90 |
| `block_reason` | pooled (en) | `CUSTOMER_REQUEST` | 5/9 | 0.56 | 0.90 |
| `handoff_route` | es | `DISPUTE` | 87/115 | 0.76 | 0.90 |
| `handoff_route` | pt | `DISPUTE` | 45/52 | 0.87 | 0.90 |
| `handoff_route` | pooled (en) | `DISPUTE` | 7/12 | 0.58 | 0.90 |
| `handoff_route` | es | `FRAUD` | 199/264 | 0.75 | 0.90 |
| `handoff_route` | pt | `FRAUD` | 95/122 | 0.78 | 0.90 |
| `handoff_route` | pooled (en) | `FRAUD` | 19/46 | 0.41 | 0.90 |
| `handoff_route` | es | `UNRECOGNIZED` | 96/111 | 0.86 | 0.90 |
| `handoff_route` | pt | `UNRECOGNIZED` | 46/62 | 0.74 | 0.90 |
| `handoff_route` | pooled (en) | `UNRECOGNIZED` | 6/9 | 0.67 | 0.90 |
| `handoff_route` | es | `HUMAN_REQUEST` | 98/169 | 0.58 | 0.90 |
| `handoff_route` | pooled (en) | `HUMAN_REQUEST` | 10/16 | 0.62 | 0.90 |
| `smalltalk_route` | pt | `greeting` | 35/37 | 0.95 | 0.95 |
| `smalltalk_route` | pt-BR | `greeting` | 35/37 | 0.95 | 0.95 |
| `smalltalk_route` | es | `out_of_scope` | 88/119 | 0.74 | 0.95 |
| `smalltalk_route` | pt | `out_of_scope` | 38/49 | 0.78 | 0.95 |
| `smalltalk_route` | en | `out_of_scope` | 4/9 | 0.44 | 0.95 |
| `smalltalk_route` | pt-BR | `out_of_scope` | 38/49 | 0.78 | 0.95 |
| `smalltalk_route` | es-MX | `out_of_scope` | 44/59 | 0.75 | 0.95 |
| `smalltalk_route` | es-AR | `out_of_scope` | 44/60 | 0.73 | 0.95 |
| `intent_hint` | pt | `confirm` | 44/54 | 0.81 | 0.90 |
| `intent_hint` | pt-BR | `confirm` | 44/54 | 0.81 | 0.90 |
| `intent_hint` | pt | `deny` | 44/49 | 0.90 | 0.90 |
| `intent_hint` | pt-BR | `deny` | 44/49 | 0.90 | 0.90 |
| `intent_hint` | es | `out_of_scope` | 88/119 | 0.74 | 0.90 |
| `intent_hint` | pt | `out_of_scope` | 41/57 | 0.72 | 0.90 |
| `intent_hint` | pt-BR | `out_of_scope` | 41/57 | 0.72 | 0.90 |
| `intent_hint` | es-MX | `out_of_scope` | 44/59 | 0.75 | 0.90 |
| `intent_hint` | es-AR | `out_of_scope` | 44/60 | 0.73 | 0.90 |
| `intent_hint` | pt | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `intent_hint` | pt-BR | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `intent_hint` | pt | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `intent_hint` | pt-BR | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `intent_hint` | es-AR | `report_suspicious_activity` | 45/51 | 0.88 | 0.90 |
| `intent_hint` | es | `report_unrecognized_charge` | 96/109 | 0.88 | 0.90 |
| `intent_hint` | pt | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `intent_hint` | pt-BR | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `intent_hint` | es-MX | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |
| `intent_hint` | es-AR | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |
| `clarify_route` | pt | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `clarify_route` | pt-BR | `report_lost_card` | 46/54 | 0.85 | 0.90 |
| `clarify_route` | pt | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `clarify_route` | pt-BR | `report_stolen_card` | 47/53 | 0.89 | 0.90 |
| `clarify_route` | en | `report_suspicious_activity` | 6/7 | 0.86 | 0.90 |
| `clarify_route` | es-AR | `report_suspicious_activity` | 45/51 | 0.88 | 0.90 |
| `clarify_route` | es | `report_unrecognized_charge` | 96/109 | 0.88 | 0.90 |
| `clarify_route` | pt | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `clarify_route` | pt-BR | `report_unrecognized_charge` | 44/52 | 0.85 | 0.90 |
| `clarify_route` | es-MX | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |
| `clarify_route` | es-AR | `report_unrecognized_charge` | 48/54 | 0.89 | 0.90 |

- `turn_intent`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `confirm_gate`: the constraint rejected nothing on validation in es/confirm, es/deny, pt/confirm, pt/deny, en/confirm, en/deny, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `smalltalk_route`: the constraint rejected nothing on validation in es, es-MX, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `intent_hint`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `clarify_route`: the constraint rejected nothing on validation in es, pt, pt-BR, es-MX, es-AR, so those thresholds are only the lowest confidence seen (see each Thresholds table).

## Summary

| Decision point | Language | Status | tau | T | Coverage val | Coverage test | Acted coverage test | ECE pre -> post (test) | Certified |
|---|:---:|---|---|---:|---:|---:|---:|---|:---:|
| `turn_intent` | es | calibrated | 0.496802 | 1.039 | 100.0% | 98.9% | 46.2% | 0.034 -> 0.031 | no |
| `turn_intent` | pt | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 45.7% | 0.056 -> 0.053 | no |
| `turn_intent` | en | calibrated | 0.841088 | 1.526 | 51.3% | 45.3% | 16.0% | 0.206 -> 0.112 | no |
| `turn_intent` | pt-BR | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 45.7% | 0.056 -> 0.053 | no |
| `turn_intent` | es-MX | calibrated | 0.498938 | 0.994 | 100.0% | 98.8% | 46.4% | 0.033 -> 0.033 | no |
| `turn_intent` | es-AR | calibrated | 0.502128 | 1.076 | 100.0% | 98.7% | 45.9% | 0.037 -> 0.030 | no |
| `confirm_gate` | es | calibrated | confirm: 0.880956, deny: 0.742556, other: 0.000000 | 0.122 | 100.0% | 100.0% | 12.0% | 0.184 -> 0.041 | no |
| `confirm_gate` | pt | calibrated | confirm: 0.869226, deny: 0.805281, other: 0.000000 | 0.148 | 100.0% | 99.3% | 12.0% | 0.199 -> 0.039 | no |
| `confirm_gate` | en | calibrated | confirm: 0.987937, deny: 0.999998, other: 0.000000 | 0.116 | 100.0% | 97.3% | 7.3% | 0.210 -> 0.036 | no |
| `block_reason` | es | calibrated | LOST: 0.004574, STOLEN: 0.000661, UNRECOGNIZED_CHARGE: 0.331689, SUSPICIOUS_ACTIVITY: 0.001761, CUSTOMER_REQUEST: 0.005726 | 1.039 | 36.6% | 41.0% | 41.0% | 0.017 -> 0.017 | no |
| `block_reason` | pt | calibrated | LOST: 0.015591, STOLEN: 0.000796, UNRECOGNIZED_CHARGE: 0.028379, SUSPICIOUS_ACTIVITY: 0.002756, CUSTOMER_REQUEST: 0.008131 | 1.037 | 36.3% | 38.7% | 38.7% | 0.029 -> 0.028 | no |
| `block_reason` | en | calibrated | LOST: 0.013180, STOLEN: 0.000910, UNRECOGNIZED_CHARGE: 0.289093, SUSPICIOUS_ACTIVITY: 0.020100, CUSTOMER_REQUEST: 0.029937 | 1.526 | 48.0% | 46.7% | 46.7% | 0.087 -> 0.049 | no |
| `handoff_route` | es | calibrated | DISPUTE: 0.001697, FRAUD: 0.004285, UNRECOGNIZED: 0.289093, HUMAN_REQUEST: 0.002508 | 1.039 | 36.4% | 43.9% | 43.9% | 0.016 -> 0.017 | no |
| `handoff_route` | pt | calibrated | DISPUTE: 0.051414, FRAUD: 0.003069, UNRECOGNIZED: 0.028379, HUMAN_REQUEST: 0.154970 | 1.037 | 36.3% | 38.0% | 38.0% | 0.025 -> 0.024 | no |
| `handoff_route` | en | calibrated | DISPUTE: 0.023572, FRAUD: 0.015406, UNRECOGNIZED: 0.246887, HUMAN_REQUEST: 0.058411 | 1.526 | 58.0% | 55.3% | 55.3% | 0.058 -> 0.040 | no |
| `smalltalk_route` | es | calibrated | 0.502214 | 1.039 | 100.0% | 99.8% | 14.1% | 0.022 -> 0.022 | no |
| `smalltalk_route` | pt | calibrated | 0.721955 | 1.037 | 99.5% | 96.4% | 11.5% | 0.028 -> 0.027 | no |
| `smalltalk_route` | en | calibrated | 0.783180 | 1.526 | 84.0% | 78.7% | 8.7% | 0.121 -> 0.064 | no |
| `smalltalk_route` | pt-BR | calibrated | 0.721955 | 1.037 | 99.5% | 96.4% | 11.5% | 0.028 -> 0.027 | no |
| `smalltalk_route` | es-MX | calibrated | 0.509892 | 0.994 | 100.0% | 99.7% | 13.9% | 0.022 -> 0.022 | no |
| `smalltalk_route` | es-AR | calibrated | 0.531993 | 1.076 | 99.9% | 99.9% | 14.3% | 0.022 -> 0.020 | no |
| `intent_hint` | es | calibrated | 0.496802 | 1.039 | 100.0% | 98.9% | 98.9% | 0.034 -> 0.031 | no |
| `intent_hint` | pt | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 99.2% | 0.056 -> 0.053 | no |
| `intent_hint` | en | calibrated | 0.930547 | 1.526 | 22.7% | 24.0% | 24.0% | 0.206 -> 0.112 | no |
| `intent_hint` | pt-BR | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 99.2% | 0.056 -> 0.053 | no |
| `intent_hint` | es-MX | calibrated | 0.498938 | 0.994 | 100.0% | 98.8% | 98.8% | 0.033 -> 0.033 | no |
| `intent_hint` | es-AR | calibrated | 0.502128 | 1.076 | 100.0% | 98.7% | 98.7% | 0.037 -> 0.030 | no |
| `clarify_route` | es | calibrated | 0.496802 | 1.039 | 100.0% | 98.9% | 46.2% | 0.034 -> 0.031 | no |
| `clarify_route` | pt | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 45.7% | 0.056 -> 0.053 | no |
| `clarify_route` | en | calibrated | 0.841088 | 1.526 | 51.3% | 45.3% | 16.0% | 0.206 -> 0.112 | no |
| `clarify_route` | pt-BR | calibrated | 0.449888 | 1.037 | 100.0% | 99.2% | 45.7% | 0.056 -> 0.053 | no |
| `clarify_route` | es-MX | calibrated | 0.498938 | 0.994 | 100.0% | 98.8% | 46.4% | 0.033 -> 0.033 | no |
| `clarify_route` | es-AR | calibrated | 0.502128 | 1.076 | 100.0% | 98.7% | 45.9% | 0.037 -> 0.030 | no |

## `turn_intent`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (6 of 42 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |
| pt-BR | 750 | 1.0371 | 0.085 -> 0.085 |  |
| es-MX | 750 | 0.9943 | 0.053 -> 0.053 |  |
| es-AR | 750 | 1.0756 | 0.085 -> 0.084 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.496802 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.841088 | language |  |
| pt-BR | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.498938 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.502128 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 100.0% | 98.9% | 46.2% | 0.930 | 0.034 | 0.031 | yes |
| pt | 750 | 750 | 100.0% | 99.2% | 45.7% | 0.903 | 0.056 | 0.053 | yes |
| en | 150 | 150 | 51.3% | 45.3% | 16.0% | 0.647 | 0.206 | 0.112 | no |
| pt-BR | 750 | 750 | 100.0% | 99.2% | 45.7% | 0.903 | 0.056 | 0.053 | yes |
| es-MX | 750 | 750 | 100.0% | 98.8% | 46.4% | 0.932 | 0.033 | 0.033 | yes |
| es-AR | 750 | 750 | 100.0% | 98.7% | 45.9% | 0.929 | 0.037 | 0.030 | yes |
| all | 4650 | 4650 | 98.4% | 97.2% | 45.1% | 0.913 | 0.046 | 0.039 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `report_lost_card` | 100 | 100 | 96 | 0.960 | 0.902 | 0.960 | 0.90 |
| es | `report_stolen_card` | 100 | 108 | 100 | 0.926 | 0.861 | 1.000 | 0.90 |
| es | `report_suspicious_activity` | 100 | 99 | 90 | 0.909 | 0.836 | 0.900 | 0.90 |
| es | `report_unrecognized_charge` | 100 | 109 | 96 | 0.881 | 0.807 | 0.960 | 0.90 |
| es | `request_card_block` | 100 | 91 | 91 | 1.000 | 0.959 | 0.910 | 0.90 |
| es | `request_dispute` | 100 | 85 | 84 | 0.988 | 0.936 | 0.840 | 0.90 |
| es | `request_human_agent` | 100 | 101 | 95 | 0.941 | 0.876 | 0.950 | 0.90 |
| pt | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| en | `report_lost_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_stolen_card` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| en | `report_suspicious_activity` | 10 | 7 | 6 | 0.857 | 0.487 | 0.600 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 1 | 1 | 1.000 | 0.207 | 0.100 | 0.90 |
| en | `request_human_agent` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt-BR | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt-BR | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-MX | `request_card_block` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `request_dispute` | 50 | 43 | 43 | 1.000 | 0.918 | 0.860 | 0.90 |
| es-MX | `request_human_agent` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-AR | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 55 | 50 | 0.909 | 0.804 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-AR | `request_card_block` | 50 | 44 | 44 | 1.000 | 0.920 | 0.880 | 0.90 |
| es-AR | `request_dispute` | 50 | 42 | 41 | 0.976 | 0.877 | 0.820 | 0.90 |
| es-AR | `request_human_agent` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| all | `report_lost_card` | 310 | 308 | 284 | 0.922 | 0.887 | 0.916 | 0.90 |
| all | `report_stolen_card` | 310 | 325 | 297 | 0.914 | 0.878 | 0.958 | 0.90 |
| all | `report_suspicious_activity` | 310 | 279 | 258 | 0.925 | 0.888 | 0.832 | 0.90 |
| all | `report_unrecognized_charge` | 310 | 326 | 285 | 0.874 | 0.834 | 0.919 | 0.90 |
| all | `request_card_block` | 310 | 286 | 278 | 0.972 | 0.946 | 0.897 | 0.90 |
| all | `request_dispute` | 310 | 267 | 259 | 0.970 | 0.942 | 0.835 | 0.90 |
| all | `request_human_agent` | 310 | 304 | 290 | 0.954 | 0.924 | 0.935 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `check_balance` | 310 | 300 | 284 | 0.947 | 0.915 | 0.916 | not acted on |
| all | `check_recent_transactions` | 310 | 273 | 263 | 0.963 | 0.934 | 0.848 | not acted on |
| all | `confirm` | 310 | 306 | 278 | 0.908 | 0.871 | 0.897 | not acted on |
| all | `deny` | 310 | 297 | 279 | 0.939 | 0.906 | 0.900 | not acted on |
| all | `greeting` | 310 | 274 | 260 | 0.949 | 0.916 | 0.839 | not acted on |
| all | `out_of_scope` | 310 | 356 | 260 | 0.730 | 0.682 | 0.839 | not acted on |
| all | `provide_identity_data` | 310 | 309 | 307 | 0.994 | 0.977 | 0.990 | not acted on |
| all | `provide_otp_code` | 310 | 310 | 310 | 1.000 | 0.988 | 1.000 | not acted on |
| all | `report_lost_card` | 310 | 308 | 284 | 0.922 | 0.887 | 0.916 | 0.90 |
| all | `report_stolen_card` | 310 | 325 | 297 | 0.914 | 0.878 | 0.958 | 0.90 |
| all | `report_suspicious_activity` | 310 | 279 | 258 | 0.925 | 0.888 | 0.832 | 0.90 |
| all | `report_unrecognized_charge` | 310 | 326 | 285 | 0.874 | 0.834 | 0.919 | 0.90 |
| all | `request_card_block` | 310 | 286 | 278 | 0.972 | 0.946 | 0.897 | 0.90 |
| all | `request_dispute` | 310 | 267 | 259 | 0.970 | 0.942 | 0.835 | 0.90 |
| all | `request_human_agent` | 310 | 304 | 290 | 0.954 | 0.924 | 0.935 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `report_lost_card` | 96/100 | 0.902 | 0.90 | yes |  |
| pt | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| en | `report_lost_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| es-MX | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es-AR | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es | `report_stolen_card` | 100/108 | 0.861 | 0.90 | no | 35 decided with zero errors (has 100/108) |
| pt | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| en | `report_stolen_card` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| pt-BR | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| es-MX | `report_stolen_card` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `report_stolen_card` | 50/55 | 0.804 | 0.90 | no | 35 decided with zero errors (has 50/55) |
| es | `report_suspicious_activity` | 90/99 | 0.836 | 0.90 | no | 35 decided with zero errors (has 90/99) |
| pt | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| en | `report_suspicious_activity` | 6/7 | 0.487 | 0.90 | no | 35 decided with zero errors (has 6/7) |
| pt-BR | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| es-MX | `report_suspicious_activity` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-AR | `report_suspicious_activity` | 45/51 | 0.766 | 0.90 | no | 35 decided with zero errors (has 45/51) |
| es | `report_unrecognized_charge` | 96/109 | 0.807 | 0.90 | no | 35 decided with zero errors (has 96/109) |
| pt | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| en | `report_unrecognized_charge` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt-BR | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| es-MX | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es-AR | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es | `request_card_block` | 91/91 | 0.959 | 0.90 | yes |  |
| pt | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| es-MX | `request_card_block` | 47/47 | 0.924 | 0.90 | yes |  |
| es-AR | `request_card_block` | 44/44 | 0.920 | 0.90 | yes |  |
| es | `request_dispute` | 84/85 | 0.936 | 0.90 | yes |  |
| pt | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| en | `request_dispute` | 1/1 | 0.207 | 0.90 | no | 35 decided with zero errors (has 1/1) |
| pt-BR | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-MX | `request_dispute` | 43/43 | 0.918 | 0.90 | yes |  |
| es-AR | `request_dispute` | 41/42 | 0.877 | 0.90 | no | 35 decided with zero errors (has 41/42) |
| es | `request_human_agent` | 95/101 | 0.876 | 0.90 | no | 35 decided with zero errors (has 95/101) |
| pt | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| en | `request_human_agent` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| pt-BR | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-MX | `request_human_agent` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `request_human_agent` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 5, 0.26, 0.20 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.35, 0.00 | 4, 0.37, 0.50 | 12, 0.35, 0.42 | 4, 0.37, 0.50 | 2, 0.36, 0.00 | 2, 0.34, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.31 | 8, 0.47, 0.38 | 15, 0.46, 0.27 | 8, 0.47, 0.38 | 7, 0.45, 0.14 | 7, 0.46, 0.43 |
| 0.5-0.6 | 25, 0.56, 0.44 | 18, 0.55, 0.50 | 13, 0.54, 0.31 | 18, 0.55, 0.50 | 10, 0.56, 0.50 | 12, 0.55, 0.42 |
| 0.6-0.7 | 30, 0.65, 0.53 | 15, 0.65, 0.53 | 10, 0.66, 0.30 | 15, 0.65, 0.53 | 15, 0.65, 0.40 | 15, 0.65, 0.53 |
| 0.7-0.8 | 33, 0.76, 0.48 | 15, 0.75, 0.40 | 19, 0.75, 0.58 | 15, 0.75, 0.40 | 15, 0.74, 0.73 | 16, 0.75, 0.56 |
| 0.8-0.9 | 45, 0.85, 0.82 | 24, 0.86, 0.67 | 24, 0.86, 0.79 | 24, 0.86, 0.67 | 22, 0.85, 0.68 | 23, 0.85, 0.78 |
| 0.9-1.0 | 1350, 0.99, 0.97 | 666, 0.99, 0.95 | 52, 0.94, 0.96 | 666, 0.99, 0.95 | 679, 0.99, 0.97 | 675, 0.99, 0.97 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 284 | 0 | 2 | 0 | 0 | 12 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `check_recent_transactions` | 0 | 263 | 0 | 0 | 0 | 31 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| `confirm` | 4 | 2 | 278 | 2 | 6 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 10 |
| `deny` | 0 | 0 | 10 | 279 | 6 | 6 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 7 |
| `greeting` | 4 | 0 | 13 | 4 | 260 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 6 | 17 |
| `out_of_scope` | 8 | 4 | 3 | 6 | 0 | 260 | 0 | 0 | 0 | 0 | 2 | 8 | 2 | 2 | 6 | 9 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 307 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 310 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 284 | 10 | 0 | 0 | 6 | 0 | 0 | 10 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 297 | 1 | 0 | 0 | 0 | 0 | 6 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 2 | 12 | 258 | 6 | 0 | 2 | 0 | 6 |
| `report_unrecognized_charge` | 0 | 4 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 2 | 4 | 285 | 0 | 2 | 0 | 7 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 4 | 12 | 0 | 278 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 2 | 27 | 0 | 259 | 0 | 19 |
| `request_human_agent` | 0 | 0 | 0 | 6 | 2 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 290 | 4 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "turn_intent": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "es-AR": {
            "T": 1.075648
          },
          "es-MX": {
            "T": 0.994325
          },
          "pt": {
            "T": 1.03712
          },
          "pt-BR": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.16,
            "certified": false,
            "coverage_test": 0.4533,
            "coverage_val": 0.5133,
            "ece_post": 0.112,
            "ece_pre": 0.2056,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                0,
                0,
                null
              ],
              "report_stolen_card": [
                3,
                3,
                0.4385
              ],
              "report_suspicious_activity": [
                6,
                7,
                0.4869
              ],
              "report_unrecognized_charge": [
                5,
                5,
                0.5655
              ],
              "request_card_block": [
                0,
                0,
                null
              ],
              "request_dispute": [
                1,
                1,
                0.2065
              ],
              "request_human_agent": [
                8,
                8,
                0.6756
              ]
            },
            "recall_test": {
              "report_lost_card": 0.0,
              "report_stolen_card": 0.3,
              "report_suspicious_activity": 0.6,
              "report_unrecognized_charge": 0.5,
              "request_card_block": 0.0,
              "request_dispute": 0.1,
              "request_human_agent": 0.8
            }
          },
          "es": {
            "acted_coverage_test": 0.462,
            "certified": false,
            "coverage_test": 0.9887,
            "coverage_val": 1.0,
            "ece_post": 0.0313,
            "ece_pre": 0.0343,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "report_lost_card": [
                96,
                100,
                0.9016
              ],
              "report_stolen_card": [
                100,
                108,
                0.8606
              ],
              "report_suspicious_activity": [
                90,
                99,
                0.8362
              ],
              "report_unrecognized_charge": [
                96,
                109,
                0.8066
              ],
              "request_card_block": [
                91,
                91,
                0.9595
              ],
              "request_dispute": [
                84,
                85,
                0.9363
              ],
              "request_human_agent": [
                95,
                101,
                0.8764
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.91,
              "request_dispute": 0.84,
              "request_human_agent": 0.95
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.4587,
            "certified": false,
            "coverage_test": 0.9867,
            "coverage_val": 1.0,
            "ece_post": 0.0298,
            "ece_pre": 0.0365,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                55,
                0.8042
              ],
              "report_suspicious_activity": [
                45,
                51,
                0.7662
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                44,
                44,
                0.9197
              ],
              "request_dispute": [
                41,
                42,
                0.8768
              ],
              "request_human_agent": [
                45,
                48,
                0.8316
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.88,
              "request_dispute": 0.82,
              "request_human_agent": 0.9
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.988,
            "coverage_val": 1.0,
            "ece_post": 0.033,
            "ece_pre": 0.0326,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                53,
                0.8463
              ],
              "report_suspicious_activity": [
                45,
                48,
                0.8316
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                47,
                47,
                0.9244
              ],
              "request_dispute": [
                43,
                43,
                0.918
              ],
              "request_human_agent": [
                50,
                53,
                0.8463
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.94,
              "request_dispute": 0.86,
              "request_human_agent": 1.0
            }
          },
          "pt": {
            "acted_coverage_test": 0.4573,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.4573,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.841088,
        "es": 0.496802,
        "es-AR": 0.502128,
        "es-MX": 0.498938,
        "pt": 0.449888,
        "pt-BR": 0.449888
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (6 of 42 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **CPU latency (single text, host):** p50 0.17 ms, p95 0.23 ms (budget `timeout_ms` 200); RAM model+inference 5.4 MB
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
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
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 6 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 5.4 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 15 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | LOST: 0.004574, STOLEN: 0.000661, UNRECOGNIZED_CHARGE: 0.331689, SUSPICIOUS_ACTIVITY: 0.001761, CUSTOMER_REQUEST: 0.005726 | language |  |
| pt | LOST: 0.015591, STOLEN: 0.000796, UNRECOGNIZED_CHARGE: 0.028379, SUSPICIOUS_ACTIVITY: 0.002756, CUSTOMER_REQUEST: 0.008131 | language |  |
| en | LOST: 0.013180, STOLEN: 0.000910, UNRECOGNIZED_CHARGE: 0.289093, SUSPICIOUS_ACTIVITY: 0.020100, CUSTOMER_REQUEST: 0.029937 | pooled |  |
| * | LOST: 0.013180, STOLEN: 0.000910, UNRECOGNIZED_CHARGE: 0.289093, SUSPICIOUS_ACTIVITY: 0.020100, CUSTOMER_REQUEST: 0.029937 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 36.6% | 41.0% | 41.0% | 0.505 | 0.017 | 0.017 | yes |
| pt | 750 | 750 | 36.3% | 38.7% | 38.7% | 0.472 | 0.029 | 0.028 | yes |
| en | 150 | 150 | 48.0% | 46.7% | 46.7% | 0.325 | 0.087 | 0.049 | yes |
| all | 2400 | 2400 | 37.2% | 40.6% | 40.6% | 0.483 | 0.022 | 0.018 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `LOST` | 100 | 122 | 96 | 0.787 | 0.706 | 0.960 | 0.90 |
| es | `STOLEN` | 100 | 115 | 100 | 0.870 | 0.796 | 1.000 | 0.90 |
| es | `UNRECOGNIZED_CHARGE` | 100 | 111 | 96 | 0.865 | 0.789 | 0.960 | 0.90 |
| es | `SUSPICIOUS_ACTIVITY` | 100 | 153 | 95 | 0.621 | 0.542 | 0.950 | 0.90 |
| es | `CUSTOMER_REQUEST` | 100 | 114 | 92 | 0.807 | 0.725 | 0.920 | 0.90 |
| pt | `LOST` | 50 | 61 | 46 | 0.754 | 0.633 | 0.920 | 0.90 |
| pt | `STOLEN` | 50 | 56 | 47 | 0.839 | 0.722 | 0.940 | 0.90 |
| pt | `UNRECOGNIZED_CHARGE` | 50 | 62 | 45 | 0.726 | 0.604 | 0.900 | 0.90 |
| pt | `SUSPICIOUS_ACTIVITY` | 50 | 44 | 41 | 0.932 | 0.818 | 0.820 | 0.90 |
| pt | `CUSTOMER_REQUEST` | 50 | 67 | 48 | 0.716 | 0.599 | 0.960 | 0.90 |
| en | `LOST` | 10 | 10 | 4 | 0.400 | 0.168 | 0.400 | 0.90 |
| en | `STOLEN` | 10 | 12 | 5 | 0.417 | 0.193 | 0.500 | 0.90 |
| en | `UNRECOGNIZED_CHARGE` | 10 | 9 | 6 | 0.667 | 0.354 | 0.600 | 0.90 |
| en | `SUSPICIOUS_ACTIVITY` | 10 | 30 | 9 | 0.300 | 0.167 | 0.900 | 0.90 |
| en | `CUSTOMER_REQUEST` | 10 | 9 | 5 | 0.556 | 0.267 | 0.500 | 0.90 |
| all | `LOST` | 160 | 193 | 146 | 0.756 | 0.691 | 0.912 | 0.90 |
| all | `STOLEN` | 160 | 183 | 152 | 0.831 | 0.770 | 0.950 | 0.90 |
| all | `UNRECOGNIZED_CHARGE` | 160 | 182 | 147 | 0.808 | 0.744 | 0.919 | 0.90 |
| all | `SUSPICIOUS_ACTIVITY` | 160 | 227 | 145 | 0.639 | 0.574 | 0.906 | 0.90 |
| all | `CUSTOMER_REQUEST` | 160 | 190 | 145 | 0.763 | 0.698 | 0.906 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `LOST` | 96/122 | 0.706 | 0.90 | no | 35 decided with zero errors (has 96/122) |
| pt | `LOST` | 46/61 | 0.633 | 0.90 | no | 35 decided with zero errors (has 46/61) |
| pooled (en) | `LOST` | 4/10 | 0.168 | 0.90 | no | 35 decided with zero errors (has 4/10) |
| es | `STOLEN` | 100/115 | 0.796 | 0.90 | no | 35 decided with zero errors (has 100/115) |
| pt | `STOLEN` | 47/56 | 0.722 | 0.90 | no | 35 decided with zero errors (has 47/56) |
| pooled (en) | `STOLEN` | 5/12 | 0.193 | 0.90 | no | 35 decided with zero errors (has 5/12) |
| es | `UNRECOGNIZED_CHARGE` | 96/111 | 0.789 | 0.90 | no | 35 decided with zero errors (has 96/111) |
| pt | `UNRECOGNIZED_CHARGE` | 45/62 | 0.604 | 0.90 | no | 35 decided with zero errors (has 45/62) |
| pooled (en) | `UNRECOGNIZED_CHARGE` | 6/9 | 0.354 | 0.90 | no | 35 decided with zero errors (has 6/9) |
| es | `SUSPICIOUS_ACTIVITY` | 95/153 | 0.542 | 0.90 | no | 35 decided with zero errors (has 95/153) |
| pt | `SUSPICIOUS_ACTIVITY` | 41/44 | 0.818 | 0.90 | no | 35 decided with zero errors (has 41/44) |
| pooled (en) | `SUSPICIOUS_ACTIVITY` | 9/30 | 0.167 | 0.90 | no | 35 decided with zero errors (has 9/30) |
| es | `CUSTOMER_REQUEST` | 92/114 | 0.725 | 0.90 | no | 35 decided with zero errors (has 92/114) |
| pt | `CUSTOMER_REQUEST` | 48/67 | 0.599 | 0.90 | no | 35 decided with zero errors (has 48/67) |
| pooled (en) | `CUSTOMER_REQUEST` | 5/9 | 0.267 | 0.90 | no | 35 decided with zero errors (has 5/9) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 976, 0.00, 0.00 | 489, 0.00, 0.00 | 100, 0.02, 0.03 |
| 0.1-0.2 | 5, 0.15, 0.40 | 6, 0.15, 0.00 | 6, 0.15, 0.17 |
| 0.2-0.3 | 4, 0.27, 0.25 | 4, 0.24, 0.50 | 5, 0.24, 0.40 |
| 0.3-0.4 | 6, 0.35, 0.50 | 1, 0.34, 1.00 | 7, 0.34, 0.43 |
| 0.4-0.5 | 2, 0.43, 0.00 | 3, 0.44, 0.33 | 4, 0.46, 0.75 |
| 0.5-0.6 | 8, 0.56, 0.12 | 6, 0.57, 0.33 | 4, 0.53, 0.25 |
| 0.6-0.7 | 10, 0.66, 0.50 | 3, 0.64, 0.67 | 2, 0.67, 0.50 |
| 0.7-0.8 | 10, 0.74, 0.70 | 4, 0.73, 0.25 | 5, 0.75, 0.60 |
| 0.8-0.9 | 11, 0.86, 1.00 | 11, 0.86, 0.45 | 6, 0.85, 0.67 |
| 0.9-1.0 | 468, 0.99, 0.96 | 223, 0.99, 0.95 | 11, 0.92, 0.91 |

### Confusion on test, languages pooled

| Truth \ decided | `LOST` | `STOLEN` | `UNRECOGNIZED_CHARGE` | `SUSPICIOUS_ACTIVITY` | `CUSTOMER_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|
| `LOST` | 146 | 5 | 1 | 3 | 4 | 1 |
| `STOLEN` | 2 | 152 | 0 | 5 | 1 | 0 |
| `UNRECOGNIZED_CHARGE` | 4 | 1 | 147 | 3 | 0 | 5 |
| `SUSPICIOUS_ACTIVITY` | 1 | 6 | 6 | 145 | 1 | 1 |
| `CUSTOMER_REQUEST` | 3 | 3 | 0 | 9 | 145 | 0 |
| `(outside the view)` | 37 | 16 | 28 | 62 | 39 | 1418 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "block_reason": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "pt": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.4667,
            "certified": false,
            "coverage_test": 0.4667,
            "coverage_val": 0.48,
            "ece_post": 0.049,
            "ece_pre": 0.0872,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                5,
                9,
                0.2667
              ],
              "LOST": [
                4,
                10,
                0.1682
              ],
              "STOLEN": [
                5,
                12,
                0.1933
              ],
              "SUSPICIOUS_ACTIVITY": [
                9,
                30,
                0.1666
              ],
              "UNRECOGNIZED_CHARGE": [
                6,
                9,
                0.3542
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.5,
              "LOST": 0.4,
              "STOLEN": 0.5,
              "SUSPICIOUS_ACTIVITY": 0.9,
              "UNRECOGNIZED_CHARGE": 0.6
            }
          },
          "es": {
            "acted_coverage_test": 0.41,
            "certified": false,
            "coverage_test": 0.41,
            "coverage_val": 0.366,
            "ece_post": 0.0171,
            "ece_pre": 0.0174,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                92,
                114,
                0.7251
              ],
              "LOST": [
                96,
                122,
                0.706
              ],
              "STOLEN": [
                100,
                115,
                0.7959
              ],
              "SUSPICIOUS_ACTIVITY": [
                95,
                153,
                0.542
              ],
              "UNRECOGNIZED_CHARGE": [
                96,
                111,
                0.789
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.92,
              "LOST": 0.96,
              "STOLEN": 1.0,
              "SUSPICIOUS_ACTIVITY": 0.95,
              "UNRECOGNIZED_CHARGE": 0.96
            }
          },
          "pt": {
            "acted_coverage_test": 0.3867,
            "certified": false,
            "coverage_test": 0.3867,
            "coverage_val": 0.3627,
            "ece_post": 0.0278,
            "ece_pre": 0.0293,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                48,
                67,
                0.5991
              ],
              "LOST": [
                46,
                61,
                0.6332
              ],
              "STOLEN": [
                47,
                56,
                0.7219
              ],
              "SUSPICIOUS_ACTIVITY": [
                41,
                44,
                0.8177
              ],
              "UNRECOGNIZED_CHARGE": [
                45,
                62,
                0.6041
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.96,
              "LOST": 0.92,
              "STOLEN": 0.94,
              "SUSPICIOUS_ACTIVITY": 0.82,
              "UNRECOGNIZED_CHARGE": 0.9
            }
          }
        },
        "pooled_test": {
          "CUSTOMER_REQUEST": [
            5,
            9,
            0.2667,
            "pooled (en)"
          ],
          "LOST": [
            4,
            10,
            0.1682,
            "pooled (en)"
          ],
          "STOLEN": [
            5,
            12,
            0.1933,
            "pooled (en)"
          ],
          "SUSPICIOUS_ACTIVITY": [
            9,
            30,
            0.1666,
            "pooled (en)"
          ],
          "UNRECOGNIZED_CHARGE": [
            6,
            9,
            0.3542,
            "pooled (en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "CUSTOMER_REQUEST": 0.029937,
          "LOST": 0.01318,
          "STOLEN": 0.00091,
          "SUSPICIOUS_ACTIVITY": 0.0201,
          "UNRECOGNIZED_CHARGE": 0.289093
        },
        "en": {
          "CUSTOMER_REQUEST": 0.029937,
          "LOST": 0.01318,
          "STOLEN": 0.00091,
          "SUSPICIOUS_ACTIVITY": 0.0201,
          "UNRECOGNIZED_CHARGE": 0.289093
        },
        "es": {
          "CUSTOMER_REQUEST": 0.005726,
          "LOST": 0.004574,
          "STOLEN": 0.000661,
          "SUSPICIOUS_ACTIVITY": 0.001761,
          "UNRECOGNIZED_CHARGE": 0.331689
        },
        "pt": {
          "CUSTOMER_REQUEST": 0.008131,
          "LOST": 0.015591,
          "STOLEN": 0.000796,
          "SUSPICIOUS_ACTIVITY": 0.002756,
          "UNRECOGNIZED_CHARGE": 0.028379
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 15 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 12 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | DISPUTE: 0.001697, FRAUD: 0.004285, UNRECOGNIZED: 0.289093, HUMAN_REQUEST: 0.002508 | language |  |
| pt | DISPUTE: 0.051414, FRAUD: 0.003069, UNRECOGNIZED: 0.028379, HUMAN_REQUEST: 0.154970 | language |  |
| en | DISPUTE: 0.023572, FRAUD: 0.015406, UNRECOGNIZED: 0.246887, HUMAN_REQUEST: 0.058411 | pooled |  |
| * | DISPUTE: 0.023572, FRAUD: 0.015406, UNRECOGNIZED: 0.246887, HUMAN_REQUEST: 0.058411 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 36.4% | 43.9% | 43.9% | 0.499 | 0.016 | 0.017 | yes |
| pt | 750 | 750 | 36.3% | 38.0% | 38.0% | 0.485 | 0.025 | 0.024 | yes |
| en | 150 | 150 | 58.0% | 55.3% | 55.3% | 0.455 | 0.058 | 0.040 | yes |
| all | 2400 | 2400 | 37.7% | 42.8% | 42.8% | 0.491 | 0.020 | 0.017 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `DISPUTE` | 100 | 115 | 87 | 0.757 | 0.671 | 0.870 | 0.90 |
| es | `FRAUD` | 200 | 264 | 199 | 0.754 | 0.698 | 0.995 | 0.90 |
| es | `UNRECOGNIZED` | 100 | 111 | 96 | 0.865 | 0.789 | 0.960 | 0.90 |
| es | `HUMAN_REQUEST` | 100 | 169 | 98 | 0.580 | 0.505 | 0.980 | 0.90 |
| pt | `DISPUTE` | 50 | 52 | 45 | 0.865 | 0.747 | 0.900 | 0.90 |
| pt | `FRAUD` | 100 | 122 | 95 | 0.779 | 0.697 | 0.950 | 0.90 |
| pt | `UNRECOGNIZED` | 50 | 62 | 46 | 0.742 | 0.621 | 0.920 | 0.90 |
| pt | `HUMAN_REQUEST` | 50 | 49 | 47 | 0.959 | 0.863 | 0.940 | 0.90 |
| en | `DISPUTE` | 10 | 12 | 7 | 0.583 | 0.320 | 0.700 | 0.90 |
| en | `FRAUD` | 20 | 46 | 19 | 0.413 | 0.283 | 0.950 | 0.90 |
| en | `UNRECOGNIZED` | 10 | 9 | 6 | 0.667 | 0.354 | 0.600 | 0.90 |
| en | `HUMAN_REQUEST` | 10 | 16 | 10 | 0.625 | 0.386 | 1.000 | 0.90 |
| all | `DISPUTE` | 160 | 179 | 139 | 0.777 | 0.710 | 0.869 | 0.90 |
| all | `FRAUD` | 320 | 432 | 313 | 0.725 | 0.681 | 0.978 | 0.90 |
| all | `UNRECOGNIZED` | 160 | 182 | 148 | 0.813 | 0.750 | 0.925 | 0.90 |
| all | `HUMAN_REQUEST` | 160 | 234 | 155 | 0.662 | 0.600 | 0.969 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `DISPUTE` | 87/115 | 0.671 | 0.90 | no | 35 decided with zero errors (has 87/115) |
| pt | `DISPUTE` | 45/52 | 0.747 | 0.90 | no | 35 decided with zero errors (has 45/52) |
| pooled (en) | `DISPUTE` | 7/12 | 0.320 | 0.90 | no | 35 decided with zero errors (has 7/12) |
| es | `FRAUD` | 199/264 | 0.698 | 0.90 | no | 35 decided with zero errors (has 199/264) |
| pt | `FRAUD` | 95/122 | 0.697 | 0.90 | no | 35 decided with zero errors (has 95/122) |
| pooled (en) | `FRAUD` | 19/46 | 0.283 | 0.90 | no | 35 decided with zero errors (has 19/46) |
| es | `UNRECOGNIZED` | 96/111 | 0.789 | 0.90 | no | 35 decided with zero errors (has 96/111) |
| pt | `UNRECOGNIZED` | 46/62 | 0.621 | 0.90 | no | 35 decided with zero errors (has 46/62) |
| pooled (en) | `UNRECOGNIZED` | 6/9 | 0.354 | 0.90 | no | 35 decided with zero errors (has 6/9) |
| es | `HUMAN_REQUEST` | 98/169 | 0.505 | 0.90 | no | 35 decided with zero errors (has 98/169) |
| pt | `HUMAN_REQUEST` | 47/49 | 0.863 | 0.90 | no | 35 decided with zero errors (has 47/49) |
| pooled (en) | `HUMAN_REQUEST` | 10/16 | 0.386 | 0.90 | no | 35 decided with zero errors (has 10/16) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 972, 0.00, 0.00 | 499, 0.00, 0.02 | 84, 0.02, 0.01 |
| 0.1-0.2 | 7, 0.13, 0.14 | 6, 0.13, 0.17 | 7, 0.14, 0.14 |
| 0.2-0.3 | 7, 0.24, 0.29 | 3, 0.24, 0.33 | 9, 0.25, 0.33 |
| 0.3-0.4 | 5, 0.36, 0.80 | 2, 0.35, 1.00 | 7, 0.35, 0.57 |
| 0.4-0.5 | 7, 0.44, 0.57 | 5, 0.47, 0.60 | 2, 0.45, 0.50 |
| 0.5-0.6 | 8, 0.57, 0.25 | 2, 0.59, 0.50 | 4, 0.55, 0.50 |
| 0.6-0.7 | 11, 0.65, 0.55 | 5, 0.62, 0.60 | 4, 0.66, 0.50 |
| 0.7-0.8 | 9, 0.74, 0.56 | 4, 0.74, 0.25 | 3, 0.75, 0.67 |
| 0.8-0.9 | 9, 0.86, 1.00 | 7, 0.86, 0.57 | 11, 0.86, 0.82 |
| 0.9-1.0 | 465, 0.99, 0.96 | 217, 0.99, 0.97 | 19, 0.93, 1.00 |

### Confusion on test, languages pooled

| Truth \ decided | `DISPUTE` | `FRAUD` | `UNRECOGNIZED` | `HUMAN_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|
| `DISPUTE` | 139 | 4 | 16 | 0 | 1 |
| `FRAUD` | 1 | 313 | 5 | 0 | 1 |
| `UNRECOGNIZED` | 3 | 4 | 148 | 0 | 5 |
| `HUMAN_REQUEST` | 1 | 1 | 0 | 155 | 3 |
| `(outside the view)` | 35 | 110 | 13 | 79 | 1363 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "handoff_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "pt": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.5533,
            "certified": false,
            "coverage_test": 0.5533,
            "coverage_val": 0.58,
            "ece_post": 0.0401,
            "ece_pre": 0.0577,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "DISPUTE": [
                7,
                12,
                0.3195
              ],
              "FRAUD": [
                19,
                46,
                0.2829
              ],
              "HUMAN_REQUEST": [
                10,
                16,
                0.3864
              ],
              "UNRECOGNIZED": [
                6,
                9,
                0.3542
              ]
            },
            "recall_test": {
              "DISPUTE": 0.7,
              "FRAUD": 0.95,
              "HUMAN_REQUEST": 1.0,
              "UNRECOGNIZED": 0.6
            }
          },
          "es": {
            "acted_coverage_test": 0.4393,
            "certified": false,
            "coverage_test": 0.4393,
            "coverage_val": 0.364,
            "ece_post": 0.0167,
            "ece_pre": 0.0164,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "DISPUTE": [
                87,
                115,
                0.6706
              ],
              "FRAUD": [
                199,
                264,
                0.6984
              ],
              "HUMAN_REQUEST": [
                98,
                169,
                0.5045
              ],
              "UNRECOGNIZED": [
                96,
                111,
                0.789
              ]
            },
            "recall_test": {
              "DISPUTE": 0.87,
              "FRAUD": 0.995,
              "HUMAN_REQUEST": 0.98,
              "UNRECOGNIZED": 0.96
            }
          },
          "pt": {
            "acted_coverage_test": 0.38,
            "certified": false,
            "coverage_test": 0.38,
            "coverage_val": 0.3627,
            "ece_post": 0.0237,
            "ece_pre": 0.0255,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "DISPUTE": [
                45,
                52,
                0.7473
              ],
              "FRAUD": [
                95,
                122,
                0.6972
              ],
              "HUMAN_REQUEST": [
                47,
                49,
                0.8629
              ],
              "UNRECOGNIZED": [
                46,
                62,
                0.6212
              ]
            },
            "recall_test": {
              "DISPUTE": 0.9,
              "FRAUD": 0.95,
              "HUMAN_REQUEST": 0.94,
              "UNRECOGNIZED": 0.92
            }
          }
        },
        "pooled_test": {
          "DISPUTE": [
            7,
            12,
            0.3195,
            "pooled (en)"
          ],
          "FRAUD": [
            19,
            46,
            0.2829,
            "pooled (en)"
          ],
          "HUMAN_REQUEST": [
            10,
            16,
            0.3864,
            "pooled (en)"
          ],
          "UNRECOGNIZED": [
            6,
            9,
            0.3542,
            "pooled (en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "DISPUTE": 0.023572,
          "FRAUD": 0.015406,
          "HUMAN_REQUEST": 0.058411,
          "UNRECOGNIZED": 0.246887
        },
        "en": {
          "DISPUTE": 0.023572,
          "FRAUD": 0.015406,
          "HUMAN_REQUEST": 0.058411,
          "UNRECOGNIZED": 0.246887
        },
        "es": {
          "DISPUTE": 0.001697,
          "FRAUD": 0.004285,
          "HUMAN_REQUEST": 0.002508,
          "UNRECOGNIZED": 0.289093
        },
        "pt": {
          "DISPUTE": 0.051414,
          "FRAUD": 0.003069,
          "HUMAN_REQUEST": 0.15497,
          "UNRECOGNIZED": 0.028379
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 12 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 12 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |
| pt-BR | 750 | 1.0371 | 0.085 -> 0.085 |  |
| es-MX | 750 | 0.9943 | 0.053 -> 0.053 |  |
| es-AR | 750 | 1.0756 | 0.085 -> 0.084 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.502214 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.721955 | language |  |
| en | 0.783180 | language |  |
| pt-BR | 0.721955 | language |  |
| es-MX | 0.509892 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.531993 | language |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 100.0% | 99.8% | 14.1% | 0.896 | 0.022 | 0.022 | yes |
| pt | 750 | 750 | 99.5% | 96.4% | 11.5% | 0.873 | 0.028 | 0.027 | yes |
| en | 150 | 150 | 84.0% | 78.7% | 8.7% | 0.665 | 0.121 | 0.064 | yes |
| pt-BR | 750 | 750 | 99.5% | 96.4% | 11.5% | 0.873 | 0.028 | 0.027 | yes |
| es-MX | 750 | 750 | 100.0% | 99.7% | 13.9% | 0.893 | 0.022 | 0.022 | yes |
| es-AR | 750 | 750 | 99.9% | 99.9% | 14.3% | 0.900 | 0.022 | 0.020 | yes |
| all | 4650 | 4650 | 99.3% | 98.0% | 13.1% | 0.880 | 0.025 | 0.023 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `greeting` | 100 | 92 | 88 | 0.957 | 0.893 | 0.880 | 0.95 |
| es | `out_of_scope` | 100 | 119 | 88 | 0.739 | 0.654 | 0.880 | 0.95 |
| pt | `greeting` | 50 | 37 | 35 | 0.946 | 0.823 | 0.700 | 0.95 |
| pt | `out_of_scope` | 50 | 49 | 38 | 0.776 | 0.641 | 0.760 | 0.95 |
| en | `greeting` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.95 |
| en | `out_of_scope` | 10 | 9 | 4 | 0.444 | 0.189 | 0.400 | 0.95 |
| pt-BR | `greeting` | 50 | 37 | 35 | 0.946 | 0.823 | 0.700 | 0.95 |
| pt-BR | `out_of_scope` | 50 | 49 | 38 | 0.776 | 0.641 | 0.760 | 0.95 |
| es-MX | `greeting` | 50 | 45 | 43 | 0.956 | 0.852 | 0.860 | 0.95 |
| es-MX | `out_of_scope` | 50 | 59 | 44 | 0.746 | 0.622 | 0.880 | 0.95 |
| es-AR | `greeting` | 50 | 47 | 45 | 0.957 | 0.858 | 0.900 | 0.95 |
| es-AR | `out_of_scope` | 50 | 60 | 44 | 0.733 | 0.610 | 0.880 | 0.95 |
| all | `greeting` | 310 | 262 | 250 | 0.954 | 0.922 | 0.806 | 0.95 |
| all | `out_of_scope` | 310 | 345 | 256 | 0.742 | 0.693 | 0.826 | 0.95 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `greeting` | 310 | 262 | 250 | 0.954 | 0.922 | 0.806 | 0.95 |
| all | `out_of_scope` | 310 | 345 | 256 | 0.742 | 0.693 | 0.826 | 0.95 |
| all | `other` | 4030 | 3951 | 3882 | 0.983 | 0.978 | 0.963 | not acted on |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `greeting` | 88/92 | 0.893 | 0.95 | no | 73 decided with zero errors (has 88/92) |
| pt | `greeting` | 35/37 | 0.823 | 0.95 | no | 73 decided with zero errors (has 35/37) |
| en | `greeting` | 4/4 | 0.510 | 0.95 | no | 73 decided with zero errors (has 4/4) |
| pt-BR | `greeting` | 35/37 | 0.823 | 0.95 | no | 73 decided with zero errors (has 35/37) |
| es-MX | `greeting` | 43/45 | 0.852 | 0.95 | no | 73 decided with zero errors (has 43/45) |
| es-AR | `greeting` | 45/47 | 0.858 | 0.95 | no | 73 decided with zero errors (has 45/47) |
| es | `out_of_scope` | 88/119 | 0.654 | 0.95 | no | 73 decided with zero errors (has 88/119) |
| pt | `out_of_scope` | 38/49 | 0.641 | 0.95 | no | 73 decided with zero errors (has 38/49) |
| en | `out_of_scope` | 4/9 | 0.189 | 0.95 | no | 73 decided with zero errors (has 4/9) |
| pt-BR | `out_of_scope` | 38/49 | 0.641 | 0.95 | no | 73 decided with zero errors (has 38/49) |
| es-MX | `out_of_scope` | 44/59 | 0.622 | 0.95 | no | 73 decided with zero errors (has 44/59) |
| es-AR | `out_of_scope` | 44/60 | 0.610 | 0.95 | no | 73 decided with zero errors (has 44/60) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.3-0.4 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.4-0.5 | 3, 0.48, 0.00 | 2, 0.47, 1.00 | 2, 0.46, 0.00 | 2, 0.47, 1.00 | 2, 0.48, 0.00 | 1, 0.48, 0.00 |
| 0.5-0.6 | 11, 0.56, 0.73 | 10, 0.54, 0.50 | 12, 0.55, 0.67 | 10, 0.54, 0.50 | 6, 0.55, 0.67 | 5, 0.57, 0.60 |
| 0.6-0.7 | 16, 0.64, 0.62 | 13, 0.65, 0.69 | 8, 0.66, 0.75 | 13, 0.65, 0.69 | 9, 0.64, 0.67 | 6, 0.64, 0.67 |
| 0.7-0.8 | 19, 0.77, 0.32 | 10, 0.76, 0.60 | 12, 0.75, 0.50 | 10, 0.76, 0.60 | 7, 0.75, 0.71 | 13, 0.77, 0.31 |
| 0.8-0.9 | 41, 0.85, 0.73 | 10, 0.85, 0.80 | 19, 0.86, 0.68 | 10, 0.85, 0.80 | 20, 0.85, 0.65 | 19, 0.85, 0.74 |
| 0.9-1.0 | 1410, 1.00, 0.98 | 705, 0.99, 0.97 | 97, 0.98, 0.98 | 705, 0.99, 0.97 | 706, 1.00, 0.98 | 706, 0.99, 0.99 |

### Confusion on test, languages pooled

| Truth \ decided | `greeting` | `out_of_scope` | `other` | `(abstained)` |
|---|---:|---:|---:|---:|
| `greeting` | 250 | 2 | 30 | 28 |
| `out_of_scope` | 0 | 256 | 39 | 15 |
| `other` | 12 | 87 | 3882 | 49 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "smalltalk_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "es-AR": {
            "T": 1.075648
          },
          "es-MX": {
            "T": 0.994325
          },
          "pt": {
            "T": 1.03712
          },
          "pt-BR": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.0867,
            "certified": false,
            "coverage_test": 0.7867,
            "coverage_val": 0.84,
            "ece_post": 0.0645,
            "ece_pre": 0.1209,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "greeting": [
                4,
                4,
                0.5101
              ],
              "out_of_scope": [
                4,
                9,
                0.1888
              ]
            },
            "recall_test": {
              "greeting": 0.4,
              "out_of_scope": 0.4
            }
          },
          "es": {
            "acted_coverage_test": 0.1407,
            "certified": false,
            "coverage_test": 0.998,
            "coverage_val": 1.0,
            "ece_post": 0.0216,
            "ece_pre": 0.0218,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "greeting": [
                88,
                92,
                0.8935
              ],
              "out_of_scope": [
                88,
                119,
                0.654
              ]
            },
            "recall_test": {
              "greeting": 0.88,
              "out_of_scope": 0.88
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.1427,
            "certified": false,
            "coverage_test": 0.9987,
            "coverage_val": 0.9987,
            "ece_post": 0.0199,
            "ece_pre": 0.0225,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                45,
                47,
                0.8575
              ],
              "out_of_scope": [
                44,
                60,
                0.6099
              ]
            },
            "recall_test": {
              "greeting": 0.9,
              "out_of_scope": 0.88
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.1387,
            "certified": false,
            "coverage_test": 0.9973,
            "coverage_val": 1.0,
            "ece_post": 0.0219,
            "ece_pre": 0.0218,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                43,
                45,
                0.8517
              ],
              "out_of_scope": [
                44,
                59,
                0.622
              ]
            },
            "recall_test": {
              "greeting": 0.86,
              "out_of_scope": 0.88
            }
          },
          "pt": {
            "acted_coverage_test": 0.1147,
            "certified": false,
            "coverage_test": 0.964,
            "coverage_val": 0.9947,
            "ece_post": 0.0274,
            "ece_pre": 0.0282,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                35,
                37,
                0.823
              ],
              "out_of_scope": [
                38,
                49,
                0.6412
              ]
            },
            "recall_test": {
              "greeting": 0.7,
              "out_of_scope": 0.76
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.1147,
            "certified": false,
            "coverage_test": 0.964,
            "coverage_val": 0.9947,
            "ece_post": 0.0274,
            "ece_pre": 0.0282,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "greeting": [
                35,
                37,
                0.823
              ],
              "out_of_scope": [
                38,
                49,
                0.6412
              ]
            },
            "recall_test": {
              "greeting": 0.7,
              "out_of_scope": 0.76
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.78318,
        "es": 0.502214,
        "es-AR": 0.531993,
        "es-MX": 0.509892,
        "pt": 0.721955,
        "pt-BR": 0.721955
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (0 of 12 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (14 of 90 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |
| pt-BR | 750 | 1.0371 | 0.085 -> 0.085 |  |
| es-MX | 750 | 0.9943 | 0.053 -> 0.053 |  |
| es-AR | 750 | 1.0756 | 0.085 -> 0.084 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.496802 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.930547 | language |  |
| pt-BR | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.498938 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.502128 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 100.0% | 98.9% | 98.9% | 0.930 | 0.034 | 0.031 | yes |
| pt | 750 | 750 | 100.0% | 99.2% | 99.2% | 0.903 | 0.056 | 0.053 | yes |
| en | 150 | 150 | 22.7% | 24.0% | 24.0% | 0.647 | 0.206 | 0.112 | no |
| pt-BR | 750 | 750 | 100.0% | 99.2% | 99.2% | 0.903 | 0.056 | 0.053 | yes |
| es-MX | 750 | 750 | 100.0% | 98.8% | 98.8% | 0.932 | 0.033 | 0.033 | yes |
| es-AR | 750 | 750 | 100.0% | 98.7% | 98.7% | 0.929 | 0.037 | 0.030 | yes |
| all | 4650 | 4650 | 97.5% | 96.5% | 96.5% | 0.913 | 0.046 | 0.039 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `check_balance` | 100 | 101 | 96 | 0.950 | 0.889 | 0.960 | 0.90 |
| es | `check_recent_transactions` | 100 | 88 | 84 | 0.955 | 0.889 | 0.840 | 0.90 |
| es | `confirm` | 100 | 95 | 91 | 0.958 | 0.897 | 0.910 | 0.90 |
| es | `deny` | 100 | 95 | 91 | 0.958 | 0.897 | 0.910 | 0.90 |
| es | `greeting` | 100 | 92 | 88 | 0.957 | 0.893 | 0.880 | 0.90 |
| es | `out_of_scope` | 100 | 119 | 88 | 0.739 | 0.654 | 0.880 | 0.90 |
| es | `provide_identity_data` | 100 | 100 | 100 | 1.000 | 0.963 | 1.000 | 0.90 |
| es | `provide_otp_code` | 100 | 100 | 100 | 1.000 | 0.963 | 1.000 | 0.90 |
| es | `report_lost_card` | 100 | 100 | 96 | 0.960 | 0.902 | 0.960 | 0.90 |
| es | `report_stolen_card` | 100 | 108 | 100 | 0.926 | 0.861 | 1.000 | 0.90 |
| es | `report_suspicious_activity` | 100 | 99 | 90 | 0.909 | 0.836 | 0.900 | 0.90 |
| es | `report_unrecognized_charge` | 100 | 109 | 96 | 0.881 | 0.807 | 0.960 | 0.90 |
| es | `request_card_block` | 100 | 91 | 91 | 1.000 | 0.959 | 0.910 | 0.90 |
| es | `request_dispute` | 100 | 85 | 84 | 0.988 | 0.936 | 0.840 | 0.90 |
| es | `request_human_agent` | 100 | 101 | 95 | 0.941 | 0.876 | 0.950 | 0.90 |
| pt | `check_balance` | 50 | 49 | 46 | 0.939 | 0.835 | 0.920 | 0.90 |
| pt | `check_recent_transactions` | 50 | 48 | 47 | 0.979 | 0.891 | 0.940 | 0.90 |
| pt | `confirm` | 50 | 54 | 44 | 0.815 | 0.692 | 0.880 | 0.90 |
| pt | `deny` | 50 | 49 | 44 | 0.898 | 0.782 | 0.880 | 0.90 |
| pt | `greeting` | 50 | 43 | 40 | 0.930 | 0.814 | 0.800 | 0.90 |
| pt | `out_of_scope` | 50 | 57 | 41 | 0.719 | 0.592 | 0.820 | 0.90 |
| pt | `provide_identity_data` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| pt | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| en | `check_balance` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `check_recent_transactions` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `confirm` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| en | `deny` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| en | `greeting` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| en | `out_of_scope` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `provide_identity_data` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| en | `provide_otp_code` | 10 | 10 | 10 | 1.000 | 0.722 | 1.000 | 0.90 |
| en | `report_lost_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_stolen_card` | 10 | 1 | 1 | 1.000 | 0.207 | 0.100 | 0.90 |
| en | `report_suspicious_activity` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_human_agent` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| pt-BR | `check_balance` | 50 | 49 | 46 | 0.939 | 0.835 | 0.920 | 0.90 |
| pt-BR | `check_recent_transactions` | 50 | 48 | 47 | 0.979 | 0.891 | 0.940 | 0.90 |
| pt-BR | `confirm` | 50 | 54 | 44 | 0.815 | 0.692 | 0.880 | 0.90 |
| pt-BR | `deny` | 50 | 49 | 44 | 0.898 | 0.782 | 0.880 | 0.90 |
| pt-BR | `greeting` | 50 | 43 | 40 | 0.930 | 0.814 | 0.800 | 0.90 |
| pt-BR | `out_of_scope` | 50 | 57 | 41 | 0.719 | 0.592 | 0.820 | 0.90 |
| pt-BR | `provide_identity_data` | 50 | 51 | 50 | 0.980 | 0.897 | 1.000 | 0.90 |
| pt-BR | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt-BR | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt-BR | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `check_balance` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| es-MX | `check_recent_transactions` | 50 | 42 | 40 | 0.952 | 0.842 | 0.800 | 0.90 |
| es-MX | `confirm` | 50 | 48 | 46 | 0.958 | 0.860 | 0.920 | 0.90 |
| es-MX | `deny` | 50 | 47 | 45 | 0.957 | 0.858 | 0.900 | 0.90 |
| es-MX | `greeting` | 50 | 45 | 43 | 0.956 | 0.852 | 0.860 | 0.90 |
| es-MX | `out_of_scope` | 50 | 59 | 44 | 0.746 | 0.622 | 0.880 | 0.90 |
| es-MX | `provide_identity_data` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-MX | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-MX | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-MX | `request_card_block` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `request_dispute` | 50 | 43 | 43 | 1.000 | 0.918 | 0.860 | 0.90 |
| es-MX | `request_human_agent` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-AR | `check_balance` | 50 | 49 | 48 | 0.980 | 0.893 | 0.960 | 0.90 |
| es-AR | `check_recent_transactions` | 50 | 46 | 44 | 0.957 | 0.855 | 0.880 | 0.90 |
| es-AR | `confirm` | 50 | 46 | 45 | 0.978 | 0.887 | 0.900 | 0.90 |
| es-AR | `deny` | 50 | 48 | 46 | 0.958 | 0.860 | 0.920 | 0.90 |
| es-AR | `greeting` | 50 | 47 | 45 | 0.957 | 0.858 | 0.900 | 0.90 |
| es-AR | `out_of_scope` | 50 | 60 | 44 | 0.733 | 0.610 | 0.880 | 0.90 |
| es-AR | `provide_identity_data` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-AR | `provide_otp_code` | 50 | 50 | 50 | 1.000 | 0.929 | 1.000 | 0.90 |
| es-AR | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 55 | 50 | 0.909 | 0.804 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-AR | `request_card_block` | 50 | 44 | 44 | 1.000 | 0.920 | 0.880 | 0.90 |
| es-AR | `request_dispute` | 50 | 42 | 41 | 0.976 | 0.877 | 0.820 | 0.90 |
| es-AR | `request_human_agent` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| all | `check_balance` | 310 | 300 | 284 | 0.947 | 0.915 | 0.916 | 0.90 |
| all | `check_recent_transactions` | 310 | 272 | 262 | 0.963 | 0.934 | 0.845 | 0.90 |
| all | `confirm` | 310 | 301 | 274 | 0.910 | 0.873 | 0.884 | 0.90 |
| all | `deny` | 310 | 293 | 275 | 0.939 | 0.905 | 0.887 | 0.90 |
| all | `greeting` | 310 | 273 | 259 | 0.949 | 0.916 | 0.835 | 0.90 |
| all | `out_of_scope` | 310 | 352 | 258 | 0.733 | 0.684 | 0.832 | 0.90 |
| all | `provide_identity_data` | 310 | 309 | 307 | 0.994 | 0.977 | 0.990 | 0.90 |
| all | `provide_otp_code` | 310 | 310 | 310 | 1.000 | 0.988 | 1.000 | 0.90 |
| all | `report_lost_card` | 310 | 308 | 284 | 0.922 | 0.887 | 0.916 | 0.90 |
| all | `report_stolen_card` | 310 | 323 | 295 | 0.913 | 0.878 | 0.952 | 0.90 |
| all | `report_suspicious_activity` | 310 | 272 | 252 | 0.926 | 0.889 | 0.813 | 0.90 |
| all | `report_unrecognized_charge` | 310 | 321 | 280 | 0.872 | 0.831 | 0.903 | 0.90 |
| all | `request_card_block` | 310 | 286 | 278 | 0.972 | 0.946 | 0.897 | 0.90 |
| all | `request_dispute` | 310 | 266 | 258 | 0.970 | 0.942 | 0.832 | 0.90 |
| all | `request_human_agent` | 310 | 302 | 288 | 0.954 | 0.924 | 0.929 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `check_balance` | 96/101 | 0.889 | 0.90 | no | 35 decided with zero errors (has 96/101) |
| pt | `check_balance` | 46/49 | 0.835 | 0.90 | no | 35 decided with zero errors (has 46/49) |
| en | `check_balance` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `check_balance` | 46/49 | 0.835 | 0.90 | no | 35 decided with zero errors (has 46/49) |
| es-MX | `check_balance` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| es-AR | `check_balance` | 48/49 | 0.893 | 0.90 | no | 35 decided with zero errors (has 48/49) |
| es | `check_recent_transactions` | 84/88 | 0.889 | 0.90 | no | 35 decided with zero errors (has 84/88) |
| pt | `check_recent_transactions` | 47/48 | 0.891 | 0.90 | no | 35 decided with zero errors (has 47/48) |
| en | `check_recent_transactions` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `check_recent_transactions` | 47/48 | 0.891 | 0.90 | no | 35 decided with zero errors (has 47/48) |
| es-MX | `check_recent_transactions` | 40/42 | 0.842 | 0.90 | no | 35 decided with zero errors (has 40/42) |
| es-AR | `check_recent_transactions` | 44/46 | 0.855 | 0.90 | no | 35 decided with zero errors (has 44/46) |
| es | `confirm` | 91/95 | 0.897 | 0.90 | no | 35 decided with zero errors (has 91/95) |
| pt | `confirm` | 44/54 | 0.692 | 0.90 | no | 35 decided with zero errors (has 44/54) |
| en | `confirm` | 4/4 | 0.510 | 0.90 | no | 35 decided with zero errors (has 4/4) |
| pt-BR | `confirm` | 44/54 | 0.692 | 0.90 | no | 35 decided with zero errors (has 44/54) |
| es-MX | `confirm` | 46/48 | 0.860 | 0.90 | no | 35 decided with zero errors (has 46/48) |
| es-AR | `confirm` | 45/46 | 0.887 | 0.90 | no | 35 decided with zero errors (has 45/46) |
| es | `deny` | 91/95 | 0.897 | 0.90 | no | 35 decided with zero errors (has 91/95) |
| pt | `deny` | 44/49 | 0.782 | 0.90 | no | 35 decided with zero errors (has 44/49) |
| en | `deny` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt-BR | `deny` | 44/49 | 0.782 | 0.90 | no | 35 decided with zero errors (has 44/49) |
| es-MX | `deny` | 45/47 | 0.858 | 0.90 | no | 35 decided with zero errors (has 45/47) |
| es-AR | `deny` | 46/48 | 0.860 | 0.90 | no | 35 decided with zero errors (has 46/48) |
| es | `greeting` | 88/92 | 0.893 | 0.90 | no | 35 decided with zero errors (has 88/92) |
| pt | `greeting` | 40/43 | 0.814 | 0.90 | no | 35 decided with zero errors (has 40/43) |
| en | `greeting` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| pt-BR | `greeting` | 40/43 | 0.814 | 0.90 | no | 35 decided with zero errors (has 40/43) |
| es-MX | `greeting` | 43/45 | 0.852 | 0.90 | no | 35 decided with zero errors (has 43/45) |
| es-AR | `greeting` | 45/47 | 0.858 | 0.90 | no | 35 decided with zero errors (has 45/47) |
| es | `out_of_scope` | 88/119 | 0.654 | 0.90 | no | 35 decided with zero errors (has 88/119) |
| pt | `out_of_scope` | 41/57 | 0.592 | 0.90 | no | 35 decided with zero errors (has 41/57) |
| en | `out_of_scope` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `out_of_scope` | 41/57 | 0.592 | 0.90 | no | 35 decided with zero errors (has 41/57) |
| es-MX | `out_of_scope` | 44/59 | 0.622 | 0.90 | no | 35 decided with zero errors (has 44/59) |
| es-AR | `out_of_scope` | 44/60 | 0.610 | 0.90 | no | 35 decided with zero errors (has 44/60) |
| es | `provide_identity_data` | 100/100 | 0.963 | 0.90 | yes |  |
| pt | `provide_identity_data` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |
| en | `provide_identity_data` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| pt-BR | `provide_identity_data` | 50/51 | 0.897 | 0.90 | no | 35 decided with zero errors (has 50/51) |
| es-MX | `provide_identity_data` | 50/50 | 0.929 | 0.90 | yes |  |
| es-AR | `provide_identity_data` | 50/50 | 0.929 | 0.90 | yes |  |
| es | `provide_otp_code` | 100/100 | 0.963 | 0.90 | yes |  |
| pt | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| en | `provide_otp_code` | 10/10 | 0.722 | 0.90 | no | 35 decided with zero errors (has 10/10) |
| pt-BR | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es-MX | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es-AR | `provide_otp_code` | 50/50 | 0.929 | 0.90 | yes |  |
| es | `report_lost_card` | 96/100 | 0.902 | 0.90 | yes |  |
| pt | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| en | `report_lost_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| es-MX | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es-AR | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es | `report_stolen_card` | 100/108 | 0.861 | 0.90 | no | 35 decided with zero errors (has 100/108) |
| pt | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| en | `report_stolen_card` | 1/1 | 0.207 | 0.90 | no | 35 decided with zero errors (has 1/1) |
| pt-BR | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| es-MX | `report_stolen_card` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `report_stolen_card` | 50/55 | 0.804 | 0.90 | no | 35 decided with zero errors (has 50/55) |
| es | `report_suspicious_activity` | 90/99 | 0.836 | 0.90 | no | 35 decided with zero errors (has 90/99) |
| pt | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| en | `report_suspicious_activity` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| es-MX | `report_suspicious_activity` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-AR | `report_suspicious_activity` | 45/51 | 0.766 | 0.90 | no | 35 decided with zero errors (has 45/51) |
| es | `report_unrecognized_charge` | 96/109 | 0.807 | 0.90 | no | 35 decided with zero errors (has 96/109) |
| pt | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| en | `report_unrecognized_charge` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| es-MX | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es-AR | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es | `request_card_block` | 91/91 | 0.959 | 0.90 | yes |  |
| pt | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| es-MX | `request_card_block` | 47/47 | 0.924 | 0.90 | yes |  |
| es-AR | `request_card_block` | 44/44 | 0.920 | 0.90 | yes |  |
| es | `request_dispute` | 84/85 | 0.936 | 0.90 | yes |  |
| pt | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| en | `request_dispute` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-MX | `request_dispute` | 43/43 | 0.918 | 0.90 | yes |  |
| es-AR | `request_dispute` | 41/42 | 0.877 | 0.90 | no | 35 decided with zero errors (has 41/42) |
| es | `request_human_agent` | 95/101 | 0.876 | 0.90 | no | 35 decided with zero errors (has 95/101) |
| pt | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| en | `request_human_agent` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| pt-BR | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-MX | `request_human_agent` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `request_human_agent` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 5, 0.26, 0.20 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.35, 0.00 | 4, 0.37, 0.50 | 12, 0.35, 0.42 | 4, 0.37, 0.50 | 2, 0.36, 0.00 | 2, 0.34, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.31 | 8, 0.47, 0.38 | 15, 0.46, 0.27 | 8, 0.47, 0.38 | 7, 0.45, 0.14 | 7, 0.46, 0.43 |
| 0.5-0.6 | 25, 0.56, 0.44 | 18, 0.55, 0.50 | 13, 0.54, 0.31 | 18, 0.55, 0.50 | 10, 0.56, 0.50 | 12, 0.55, 0.42 |
| 0.6-0.7 | 30, 0.65, 0.53 | 15, 0.65, 0.53 | 10, 0.66, 0.30 | 15, 0.65, 0.53 | 15, 0.65, 0.40 | 15, 0.65, 0.53 |
| 0.7-0.8 | 33, 0.76, 0.48 | 15, 0.75, 0.40 | 19, 0.75, 0.58 | 15, 0.75, 0.40 | 15, 0.74, 0.73 | 16, 0.75, 0.56 |
| 0.8-0.9 | 45, 0.85, 0.82 | 24, 0.86, 0.67 | 24, 0.86, 0.79 | 24, 0.86, 0.67 | 22, 0.85, 0.68 | 23, 0.85, 0.78 |
| 0.9-1.0 | 1350, 0.99, 0.97 | 666, 0.99, 0.95 | 52, 0.94, 0.96 | 666, 0.99, 0.95 | 679, 0.99, 0.97 | 675, 0.99, 0.97 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 284 | 0 | 2 | 0 | 0 | 12 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `check_recent_transactions` | 0 | 262 | 0 | 0 | 0 | 30 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 14 |
| `confirm` | 4 | 2 | 274 | 2 | 6 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 14 |
| `deny` | 0 | 0 | 10 | 275 | 6 | 6 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| `greeting` | 4 | 0 | 12 | 4 | 259 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 6 | 19 |
| `out_of_scope` | 8 | 4 | 3 | 6 | 0 | 258 | 0 | 0 | 0 | 0 | 2 | 8 | 2 | 2 | 6 | 11 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 307 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 310 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 284 | 10 | 0 | 0 | 6 | 0 | 0 | 10 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 295 | 0 | 0 | 0 | 0 | 0 | 9 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 2 | 12 | 252 | 6 | 0 | 2 | 0 | 12 |
| `report_unrecognized_charge` | 0 | 4 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 2 | 4 | 280 | 0 | 2 | 0 | 12 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 4 | 12 | 0 | 278 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 27 | 0 | 258 | 0 | 21 |
| `request_human_agent` | 0 | 0 | 0 | 6 | 2 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 288 | 6 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "intent_hint": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "es-AR": {
            "T": 1.075648
          },
          "es-MX": {
            "T": 0.994325
          },
          "pt": {
            "T": 1.03712
          },
          "pt-BR": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.24,
            "certified": false,
            "coverage_test": 0.24,
            "coverage_val": 0.2267,
            "ece_post": 0.112,
            "ece_pre": 0.2056,
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
                4,
                4,
                0.5101
              ],
              "deny": [
                5,
                5,
                0.5655
              ],
              "greeting": [
                3,
                3,
                0.4385
              ],
              "out_of_scope": [
                0,
                0,
                null
              ],
              "provide_identity_data": [
                7,
                7,
                0.6457
              ],
              "provide_otp_code": [
                10,
                10,
                0.7225
              ],
              "report_lost_card": [
                0,
                0,
                null
              ],
              "report_stolen_card": [
                1,
                1,
                0.2065
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
                6,
                6,
                0.6097
              ]
            },
            "recall_test": {
              "check_balance": 0.0,
              "check_recent_transactions": 0.0,
              "confirm": 0.4,
              "deny": 0.5,
              "greeting": 0.3,
              "out_of_scope": 0.0,
              "provide_identity_data": 0.7,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.0,
              "report_stolen_card": 0.1,
              "report_suspicious_activity": 0.0,
              "report_unrecognized_charge": 0.0,
              "request_card_block": 0.0,
              "request_dispute": 0.0,
              "request_human_agent": 0.6
            }
          },
          "es": {
            "acted_coverage_test": 0.9887,
            "certified": false,
            "coverage_test": 0.9887,
            "coverage_val": 1.0,
            "ece_post": 0.0313,
            "ece_pre": 0.0343,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "check_balance": [
                96,
                101,
                0.8893
              ],
              "check_recent_transactions": [
                84,
                88,
                0.8889
              ],
              "confirm": [
                91,
                95,
                0.8967
              ],
              "deny": [
                91,
                95,
                0.8967
              ],
              "greeting": [
                88,
                92,
                0.8935
              ],
              "out_of_scope": [
                88,
                119,
                0.654
              ],
              "provide_identity_data": [
                100,
                100,
                0.963
              ],
              "provide_otp_code": [
                100,
                100,
                0.963
              ],
              "report_lost_card": [
                96,
                100,
                0.9016
              ],
              "report_stolen_card": [
                100,
                108,
                0.8606
              ],
              "report_suspicious_activity": [
                90,
                99,
                0.8362
              ],
              "report_unrecognized_charge": [
                96,
                109,
                0.8066
              ],
              "request_card_block": [
                91,
                91,
                0.9595
              ],
              "request_dispute": [
                84,
                85,
                0.9363
              ],
              "request_human_agent": [
                95,
                101,
                0.8764
              ]
            },
            "recall_test": {
              "check_balance": 0.96,
              "check_recent_transactions": 0.84,
              "confirm": 0.91,
              "deny": 0.91,
              "greeting": 0.88,
              "out_of_scope": 0.88,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.91,
              "request_dispute": 0.84,
              "request_human_agent": 0.95
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.9867,
            "certified": false,
            "coverage_test": 0.9867,
            "coverage_val": 1.0,
            "ece_post": 0.0298,
            "ece_pre": 0.0365,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                48,
                49,
                0.8931
              ],
              "check_recent_transactions": [
                44,
                46,
                0.8547
              ],
              "confirm": [
                45,
                46,
                0.8866
              ],
              "deny": [
                46,
                48,
                0.8602
              ],
              "greeting": [
                45,
                47,
                0.8575
              ],
              "out_of_scope": [
                44,
                60,
                0.6099
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
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                55,
                0.8042
              ],
              "report_suspicious_activity": [
                45,
                51,
                0.7662
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                44,
                44,
                0.9197
              ],
              "request_dispute": [
                41,
                42,
                0.8768
              ],
              "request_human_agent": [
                45,
                48,
                0.8316
              ]
            },
            "recall_test": {
              "check_balance": 0.96,
              "check_recent_transactions": 0.88,
              "confirm": 0.9,
              "deny": 0.92,
              "greeting": 0.9,
              "out_of_scope": 0.88,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.88,
              "request_dispute": 0.82,
              "request_human_agent": 0.9
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.988,
            "certified": false,
            "coverage_test": 0.988,
            "coverage_val": 1.0,
            "ece_post": 0.033,
            "ece_pre": 0.0326,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                48,
                52,
                0.8183
              ],
              "check_recent_transactions": [
                40,
                42,
                0.8421
              ],
              "confirm": [
                46,
                48,
                0.8602
              ],
              "deny": [
                45,
                47,
                0.8575
              ],
              "greeting": [
                43,
                45,
                0.8517
              ],
              "out_of_scope": [
                44,
                59,
                0.622
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
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                53,
                0.8463
              ],
              "report_suspicious_activity": [
                45,
                48,
                0.8316
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                47,
                47,
                0.9244
              ],
              "request_dispute": [
                43,
                43,
                0.918
              ],
              "request_human_agent": [
                50,
                53,
                0.8463
              ]
            },
            "recall_test": {
              "check_balance": 0.96,
              "check_recent_transactions": 0.8,
              "confirm": 0.92,
              "deny": 0.9,
              "greeting": 0.86,
              "out_of_scope": 0.88,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.94,
              "request_dispute": 0.86,
              "request_human_agent": 1.0
            }
          },
          "pt": {
            "acted_coverage_test": 0.992,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                46,
                49,
                0.8348
              ],
              "check_recent_transactions": [
                47,
                48,
                0.891
              ],
              "confirm": [
                44,
                54,
                0.6916
              ],
              "deny": [
                44,
                49,
                0.7824
              ],
              "greeting": [
                40,
                43,
                0.8139
              ],
              "out_of_scope": [
                41,
                57,
                0.5917
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
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "check_balance": 0.92,
              "check_recent_transactions": 0.94,
              "confirm": 0.88,
              "deny": 0.88,
              "greeting": 0.8,
              "out_of_scope": 0.82,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.992,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "check_balance": [
                46,
                49,
                0.8348
              ],
              "check_recent_transactions": [
                47,
                48,
                0.891
              ],
              "confirm": [
                44,
                54,
                0.6916
              ],
              "deny": [
                44,
                49,
                0.7824
              ],
              "greeting": [
                40,
                43,
                0.8139
              ],
              "out_of_scope": [
                41,
                57,
                0.5917
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
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "check_balance": 0.92,
              "check_recent_transactions": 0.94,
              "confirm": 0.88,
              "deny": 0.88,
              "greeting": 0.8,
              "out_of_scope": 0.82,
              "provide_identity_data": 1.0,
              "provide_otp_code": 1.0,
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.930547,
        "es": 0.496802,
        "es-AR": 0.502128,
        "es-MX": 0.498938,
        "pt": 0.449888,
        "pt-BR": 0.449888
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (14 of 90 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_distilbert` (`hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e`), `hf_seqcls`, distribution
- **CPU latency (single text, host):** p50 6.96 ms, p95 9.53 ms (budget `timeout_ms` 1000); RAM model+inference 588.8 MB
- **Status written:** `calibrated`; certified: **no** (6 of 42 scopes clear the Wilson bound)

### Candidate selection

'intent_distilbert' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 1500 | 1.0394 | 0.069 -> 0.069 |  |
| pt | 750 | 1.0371 | 0.085 -> 0.085 |  |
| en | 150 | 1.5257 | 1.135 -> 0.990 |  |
| pt-BR | 750 | 1.0371 | 0.085 -> 0.085 |  |
| es-MX | 750 | 0.9943 | 0.053 -> 0.053 |  |
| es-AR | 750 | 1.0756 | 0.085 -> 0.084 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.496802 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.841088 | language |  |
| pt-BR | 0.449888 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-MX | 0.498938 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| es-AR | 0.502128 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 1500 | 1500 | 100.0% | 98.9% | 46.2% | 0.930 | 0.034 | 0.031 | yes |
| pt | 750 | 750 | 100.0% | 99.2% | 45.7% | 0.903 | 0.056 | 0.053 | yes |
| en | 150 | 150 | 51.3% | 45.3% | 16.0% | 0.647 | 0.206 | 0.112 | no |
| pt-BR | 750 | 750 | 100.0% | 99.2% | 45.7% | 0.903 | 0.056 | 0.053 | yes |
| es-MX | 750 | 750 | 100.0% | 98.8% | 46.4% | 0.932 | 0.033 | 0.033 | yes |
| es-AR | 750 | 750 | 100.0% | 98.7% | 45.9% | 0.929 | 0.037 | 0.030 | yes |
| all | 4650 | 4650 | 98.4% | 97.2% | 45.1% | 0.913 | 0.046 | 0.039 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `report_lost_card` | 100 | 100 | 96 | 0.960 | 0.902 | 0.960 | 0.90 |
| es | `report_stolen_card` | 100 | 108 | 100 | 0.926 | 0.861 | 1.000 | 0.90 |
| es | `report_suspicious_activity` | 100 | 99 | 90 | 0.909 | 0.836 | 0.900 | 0.90 |
| es | `report_unrecognized_charge` | 100 | 109 | 96 | 0.881 | 0.807 | 0.960 | 0.90 |
| es | `request_card_block` | 100 | 91 | 91 | 1.000 | 0.959 | 0.910 | 0.90 |
| es | `request_dispute` | 100 | 85 | 84 | 0.988 | 0.936 | 0.840 | 0.90 |
| es | `request_human_agent` | 100 | 101 | 95 | 0.941 | 0.876 | 0.950 | 0.90 |
| pt | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| en | `report_lost_card` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `report_stolen_card` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| en | `report_suspicious_activity` | 10 | 7 | 6 | 0.857 | 0.487 | 0.600 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| en | `request_card_block` | 10 | 0 | 0 | - | - | 0.000 | 0.90 |
| en | `request_dispute` | 10 | 1 | 1 | 1.000 | 0.207 | 0.100 | 0.90 |
| en | `request_human_agent` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| pt-BR | `report_lost_card` | 50 | 54 | 46 | 0.852 | 0.734 | 0.920 | 0.90 |
| pt-BR | `report_stolen_card` | 50 | 53 | 47 | 0.887 | 0.774 | 0.940 | 0.90 |
| pt-BR | `report_suspicious_activity` | 50 | 37 | 36 | 0.973 | 0.862 | 0.720 | 0.90 |
| pt-BR | `report_unrecognized_charge` | 50 | 52 | 44 | 0.846 | 0.725 | 0.880 | 0.90 |
| pt-BR | `request_card_block` | 50 | 52 | 48 | 0.923 | 0.818 | 0.960 | 0.90 |
| pt-BR | `request_dispute` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| pt-BR | `request_human_agent` | 50 | 47 | 46 | 0.979 | 0.889 | 0.920 | 0.90 |
| es-MX | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-MX | `report_stolen_card` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-MX | `report_suspicious_activity` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| es-MX | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-MX | `request_card_block` | 50 | 47 | 47 | 1.000 | 0.924 | 0.940 | 0.90 |
| es-MX | `request_dispute` | 50 | 43 | 43 | 1.000 | 0.918 | 0.860 | 0.90 |
| es-MX | `request_human_agent` | 50 | 53 | 50 | 0.943 | 0.846 | 1.000 | 0.90 |
| es-AR | `report_lost_card` | 50 | 50 | 48 | 0.960 | 0.865 | 0.960 | 0.90 |
| es-AR | `report_stolen_card` | 50 | 55 | 50 | 0.909 | 0.804 | 1.000 | 0.90 |
| es-AR | `report_suspicious_activity` | 50 | 51 | 45 | 0.882 | 0.766 | 0.900 | 0.90 |
| es-AR | `report_unrecognized_charge` | 50 | 54 | 48 | 0.889 | 0.778 | 0.960 | 0.90 |
| es-AR | `request_card_block` | 50 | 44 | 44 | 1.000 | 0.920 | 0.880 | 0.90 |
| es-AR | `request_dispute` | 50 | 42 | 41 | 0.976 | 0.877 | 0.820 | 0.90 |
| es-AR | `request_human_agent` | 50 | 48 | 45 | 0.938 | 0.832 | 0.900 | 0.90 |
| all | `report_lost_card` | 310 | 308 | 284 | 0.922 | 0.887 | 0.916 | 0.90 |
| all | `report_stolen_card` | 310 | 325 | 297 | 0.914 | 0.878 | 0.958 | 0.90 |
| all | `report_suspicious_activity` | 310 | 279 | 258 | 0.925 | 0.888 | 0.832 | 0.90 |
| all | `report_unrecognized_charge` | 310 | 326 | 285 | 0.874 | 0.834 | 0.919 | 0.90 |
| all | `request_card_block` | 310 | 286 | 278 | 0.972 | 0.946 | 0.897 | 0.90 |
| all | `request_dispute` | 310 | 267 | 259 | 0.970 | 0.942 | 0.835 | 0.90 |
| all | `request_human_agent` | 310 | 304 | 290 | 0.954 | 0.924 | 0.935 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `check_balance` | 310 | 300 | 284 | 0.947 | 0.915 | 0.916 | not acted on |
| all | `check_recent_transactions` | 310 | 273 | 263 | 0.963 | 0.934 | 0.848 | not acted on |
| all | `confirm` | 310 | 306 | 278 | 0.908 | 0.871 | 0.897 | not acted on |
| all | `deny` | 310 | 297 | 279 | 0.939 | 0.906 | 0.900 | not acted on |
| all | `greeting` | 310 | 274 | 260 | 0.949 | 0.916 | 0.839 | not acted on |
| all | `out_of_scope` | 310 | 356 | 260 | 0.730 | 0.682 | 0.839 | not acted on |
| all | `provide_identity_data` | 310 | 309 | 307 | 0.994 | 0.977 | 0.990 | not acted on |
| all | `provide_otp_code` | 310 | 310 | 310 | 1.000 | 0.988 | 1.000 | not acted on |
| all | `report_lost_card` | 310 | 308 | 284 | 0.922 | 0.887 | 0.916 | 0.90 |
| all | `report_stolen_card` | 310 | 325 | 297 | 0.914 | 0.878 | 0.958 | 0.90 |
| all | `report_suspicious_activity` | 310 | 279 | 258 | 0.925 | 0.888 | 0.832 | 0.90 |
| all | `report_unrecognized_charge` | 310 | 326 | 285 | 0.874 | 0.834 | 0.919 | 0.90 |
| all | `request_card_block` | 310 | 286 | 278 | 0.972 | 0.946 | 0.897 | 0.90 |
| all | `request_dispute` | 310 | 267 | 259 | 0.970 | 0.942 | 0.835 | 0.90 |
| all | `request_human_agent` | 310 | 304 | 290 | 0.954 | 0.924 | 0.935 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `report_lost_card` | 96/100 | 0.902 | 0.90 | yes |  |
| pt | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| en | `report_lost_card` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `report_lost_card` | 46/54 | 0.734 | 0.90 | no | 35 decided with zero errors (has 46/54) |
| es-MX | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es-AR | `report_lost_card` | 48/50 | 0.865 | 0.90 | no | 35 decided with zero errors (has 48/50) |
| es | `report_stolen_card` | 100/108 | 0.861 | 0.90 | no | 35 decided with zero errors (has 100/108) |
| pt | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| en | `report_stolen_card` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| pt-BR | `report_stolen_card` | 47/53 | 0.774 | 0.90 | no | 35 decided with zero errors (has 47/53) |
| es-MX | `report_stolen_card` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `report_stolen_card` | 50/55 | 0.804 | 0.90 | no | 35 decided with zero errors (has 50/55) |
| es | `report_suspicious_activity` | 90/99 | 0.836 | 0.90 | no | 35 decided with zero errors (has 90/99) |
| pt | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| en | `report_suspicious_activity` | 6/7 | 0.487 | 0.90 | no | 35 decided with zero errors (has 6/7) |
| pt-BR | `report_suspicious_activity` | 36/37 | 0.862 | 0.90 | no | 35 decided with zero errors (has 36/37) |
| es-MX | `report_suspicious_activity` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-AR | `report_suspicious_activity` | 45/51 | 0.766 | 0.90 | no | 35 decided with zero errors (has 45/51) |
| es | `report_unrecognized_charge` | 96/109 | 0.807 | 0.90 | no | 35 decided with zero errors (has 96/109) |
| pt | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| en | `report_unrecognized_charge` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt-BR | `report_unrecognized_charge` | 44/52 | 0.725 | 0.90 | no | 35 decided with zero errors (has 44/52) |
| es-MX | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es-AR | `report_unrecognized_charge` | 48/54 | 0.778 | 0.90 | no | 35 decided with zero errors (has 48/54) |
| es | `request_card_block` | 91/91 | 0.959 | 0.90 | yes |  |
| pt | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| en | `request_card_block` | 0/0 | - | 0.90 | no | 35 decided with zero errors (has 0/0) |
| pt-BR | `request_card_block` | 48/52 | 0.818 | 0.90 | no | 35 decided with zero errors (has 48/52) |
| es-MX | `request_card_block` | 47/47 | 0.924 | 0.90 | yes |  |
| es-AR | `request_card_block` | 44/44 | 0.920 | 0.90 | yes |  |
| es | `request_dispute` | 84/85 | 0.936 | 0.90 | yes |  |
| pt | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| en | `request_dispute` | 1/1 | 0.207 | 0.90 | no | 35 decided with zero errors (has 1/1) |
| pt-BR | `request_dispute` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |
| es-MX | `request_dispute` | 43/43 | 0.918 | 0.90 | yes |  |
| es-AR | `request_dispute` | 41/42 | 0.877 | 0.90 | no | 35 decided with zero errors (has 41/42) |
| es | `request_human_agent` | 95/101 | 0.876 | 0.90 | no | 35 decided with zero errors (has 95/101) |
| pt | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| en | `request_human_agent` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| pt-BR | `request_human_agent` | 46/47 | 0.889 | 0.90 | no | 35 decided with zero errors (has 46/47) |
| es-MX | `request_human_agent` | 50/53 | 0.846 | 0.90 | no | 35 decided with zero errors (has 50/53) |
| es-AR | `request_human_agent` | 45/48 | 0.832 | 0.90 | no | 35 decided with zero errors (has 45/48) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc | pt-BR: n, conf, acc | es-MX: n, conf, acc | es-AR: n, conf, acc |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 5, 0.26, 0.20 | 0 | 0 | 0 |
| 0.3-0.4 | 4, 0.35, 0.00 | 4, 0.37, 0.50 | 12, 0.35, 0.42 | 4, 0.37, 0.50 | 2, 0.36, 0.00 | 2, 0.34, 0.00 |
| 0.4-0.5 | 13, 0.45, 0.31 | 8, 0.47, 0.38 | 15, 0.46, 0.27 | 8, 0.47, 0.38 | 7, 0.45, 0.14 | 7, 0.46, 0.43 |
| 0.5-0.6 | 25, 0.56, 0.44 | 18, 0.55, 0.50 | 13, 0.54, 0.31 | 18, 0.55, 0.50 | 10, 0.56, 0.50 | 12, 0.55, 0.42 |
| 0.6-0.7 | 30, 0.65, 0.53 | 15, 0.65, 0.53 | 10, 0.66, 0.30 | 15, 0.65, 0.53 | 15, 0.65, 0.40 | 15, 0.65, 0.53 |
| 0.7-0.8 | 33, 0.76, 0.48 | 15, 0.75, 0.40 | 19, 0.75, 0.58 | 15, 0.75, 0.40 | 15, 0.74, 0.73 | 16, 0.75, 0.56 |
| 0.8-0.9 | 45, 0.85, 0.82 | 24, 0.86, 0.67 | 24, 0.86, 0.79 | 24, 0.86, 0.67 | 22, 0.85, 0.68 | 23, 0.85, 0.78 |
| 0.9-1.0 | 1350, 0.99, 0.97 | 666, 0.99, 0.95 | 52, 0.94, 0.96 | 666, 0.99, 0.95 | 679, 0.99, 0.97 | 675, 0.99, 0.97 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 284 | 0 | 2 | 0 | 0 | 12 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| `check_recent_transactions` | 0 | 263 | 0 | 0 | 0 | 31 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| `confirm` | 4 | 2 | 278 | 2 | 6 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 10 |
| `deny` | 0 | 0 | 10 | 279 | 6 | 6 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 7 |
| `greeting` | 4 | 0 | 13 | 4 | 260 | 4 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 6 | 17 |
| `out_of_scope` | 8 | 4 | 3 | 6 | 0 | 260 | 0 | 0 | 0 | 0 | 2 | 8 | 2 | 2 | 6 | 9 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 307 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 310 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 284 | 10 | 0 | 0 | 6 | 0 | 0 | 10 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 297 | 1 | 0 | 0 | 0 | 0 | 6 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 2 | 12 | 258 | 6 | 0 | 2 | 0 | 6 |
| `report_unrecognized_charge` | 0 | 4 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 2 | 4 | 285 | 0 | 2 | 0 | 7 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 4 | 4 | 12 | 0 | 278 | 0 | 0 | 10 |
| `request_dispute` | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 2 | 27 | 0 | 259 | 0 | 19 |
| `request_human_agent` | 0 | 0 | 0 | 6 | 2 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 290 | 4 |

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
      "model_id": "hf_seqcls:distilbert-intent-pooled@sha256:f43063c6d82e",
      "params": {
        "batch_size": 64,
        "max_length": 256,
        "model": "packages/encoder/weights/distilbert-intent-pooled"
      },
      "probability_kind": "distribution",
      "revision": "distilbert-intent-pooled:59bdfe5dc8c1",
      "timeout_ms": 1000,
      "weights_sha256": "f43063c6d82e28180adf288a39ebe2f7131c245e48d40469908c7755fbcd62ce"
    }
  },
  "decision_points": {
    "clarify_route": {
      "always_on": true,
      "backend": "intent_distilbert",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 1.525664
          },
          "es": {
            "T": 1.039443
          },
          "es-AR": {
            "T": 1.075648
          },
          "es-MX": {
            "T": 0.994325
          },
          "pt": {
            "T": 1.03712
          },
          "pt-BR": {
            "T": 1.03712
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
          "sha256": "d7c56048a3342a73e9c0547aa1a5b5f6950c161b76aa31e5429ae5cbb696d046"
        },
        "data": {
          "test": {
            "path": "data/staging/decision_pooled/decision.pooled.test.jsonl",
            "sha256": "e955802c1bd39bdbe7f6cd4e0b2fd7591f1c1079589595b637c885be3b8e32b6"
          },
          "train": {
            "path": "data/staging/decision_pooled/decision.pooled.train.jsonl",
            "sha256": "7d137d689ea40f5001a6892cf7b0ca6a1e3a367cccabd785620b49294244da49"
          },
          "validation": {
            "path": "data/staging/decision_pooled/decision.pooled.validation.jsonl",
            "sha256": "28fb448a4a54643cc65f323d267d090191ebd3f016750f94840664e26132a07e"
          }
        },
        "per_lang": {
          "en": {
            "acted_coverage_test": 0.16,
            "certified": false,
            "coverage_test": 0.4533,
            "coverage_val": 0.5133,
            "ece_post": 0.112,
            "ece_pre": 0.2056,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                0,
                0,
                null
              ],
              "report_stolen_card": [
                3,
                3,
                0.4385
              ],
              "report_suspicious_activity": [
                6,
                7,
                0.4869
              ],
              "report_unrecognized_charge": [
                5,
                5,
                0.5655
              ],
              "request_card_block": [
                0,
                0,
                null
              ],
              "request_dispute": [
                1,
                1,
                0.2065
              ],
              "request_human_agent": [
                8,
                8,
                0.6756
              ]
            },
            "recall_test": {
              "report_lost_card": 0.0,
              "report_stolen_card": 0.3,
              "report_suspicious_activity": 0.6,
              "report_unrecognized_charge": 0.5,
              "request_card_block": 0.0,
              "request_dispute": 0.1,
              "request_human_agent": 0.8
            }
          },
          "es": {
            "acted_coverage_test": 0.462,
            "certified": false,
            "coverage_test": 0.9887,
            "coverage_val": 1.0,
            "ece_post": 0.0313,
            "ece_pre": 0.0343,
            "n_test": 1500,
            "n_val": 1500,
            "precision_test": {
              "report_lost_card": [
                96,
                100,
                0.9016
              ],
              "report_stolen_card": [
                100,
                108,
                0.8606
              ],
              "report_suspicious_activity": [
                90,
                99,
                0.8362
              ],
              "report_unrecognized_charge": [
                96,
                109,
                0.8066
              ],
              "request_card_block": [
                91,
                91,
                0.9595
              ],
              "request_dispute": [
                84,
                85,
                0.9363
              ],
              "request_human_agent": [
                95,
                101,
                0.8764
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.91,
              "request_dispute": 0.84,
              "request_human_agent": 0.95
            }
          },
          "es-AR": {
            "acted_coverage_test": 0.4587,
            "certified": false,
            "coverage_test": 0.9867,
            "coverage_val": 1.0,
            "ece_post": 0.0298,
            "ece_pre": 0.0365,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                55,
                0.8042
              ],
              "report_suspicious_activity": [
                45,
                51,
                0.7662
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                44,
                44,
                0.9197
              ],
              "request_dispute": [
                41,
                42,
                0.8768
              ],
              "request_human_agent": [
                45,
                48,
                0.8316
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.88,
              "request_dispute": 0.82,
              "request_human_agent": 0.9
            }
          },
          "es-MX": {
            "acted_coverage_test": 0.464,
            "certified": false,
            "coverage_test": 0.988,
            "coverage_val": 1.0,
            "ece_post": 0.033,
            "ece_pre": 0.0326,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                48,
                50,
                0.8654
              ],
              "report_stolen_card": [
                50,
                53,
                0.8463
              ],
              "report_suspicious_activity": [
                45,
                48,
                0.8316
              ],
              "report_unrecognized_charge": [
                48,
                54,
                0.7781
              ],
              "request_card_block": [
                47,
                47,
                0.9244
              ],
              "request_dispute": [
                43,
                43,
                0.918
              ],
              "request_human_agent": [
                50,
                53,
                0.8463
              ]
            },
            "recall_test": {
              "report_lost_card": 0.96,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.96,
              "request_card_block": 0.94,
              "request_dispute": 0.86,
              "request_human_agent": 1.0
            }
          },
          "pt": {
            "acted_coverage_test": 0.4573,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          },
          "pt-BR": {
            "acted_coverage_test": 0.4573,
            "certified": false,
            "coverage_test": 0.992,
            "coverage_val": 1.0,
            "ece_post": 0.0526,
            "ece_pre": 0.0558,
            "n_test": 750,
            "n_val": 750,
            "precision_test": {
              "report_lost_card": [
                46,
                54,
                0.734
              ],
              "report_stolen_card": [
                47,
                53,
                0.7742
              ],
              "report_suspicious_activity": [
                36,
                37,
                0.8618
              ],
              "report_unrecognized_charge": [
                44,
                52,
                0.7248
              ],
              "request_card_block": [
                48,
                52,
                0.8183
              ],
              "request_dispute": [
                45,
                48,
                0.8316
              ],
              "request_human_agent": [
                46,
                47,
                0.8889
              ]
            },
            "recall_test": {
              "report_lost_card": 0.92,
              "report_stolen_card": 0.94,
              "report_suspicious_activity": 0.72,
              "report_unrecognized_charge": 0.88,
              "request_card_block": 0.96,
              "request_dispute": 0.9,
              "request_human_agent": 0.92
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-30-distilbert.md",
        "run_id": "aa9fde2d56f3",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.841088,
        "es": 0.496802,
        "es-AR": 0.502128,
        "es-MX": 0.498938,
        "pt": 0.449888,
        "pt-BR": 0.449888
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

- `new decision point (no previous entry)`

### Definition of done (Appendix F.5)

- [x] Artifact entry `status: calibrated` (this run: `calibrated`).
- [ ] Constraint met on test with the Wilson bound (6 of 42 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [ ] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 588.8 MB; the encoder's memory floor is checked by the service at startup).
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
