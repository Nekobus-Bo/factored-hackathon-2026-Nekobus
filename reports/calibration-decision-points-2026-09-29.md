# Decision Points Calibration Report

> [!WARNING]
> The test split is **provisional synthetic (not human)**: written by an AI agent, 10 rows per intent and language, never double-labeled. It cannot certify a precision of 0.95 (or 0.90): 22 correct of 22 accepted has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted with zero errors.
> Validation shares its generating process with train, so a calibrator fitted on it is over-confident on real traffic. Thresholds here are chosen on validation only; nothing in this report is a guarantee on real customers.
> Every decision point stays in `shadow` until a separate reviewed diff flips it to `enforce` after the sign-off of ADR-0012, Appendix F.5.

- **Run id:** `602eaec9e0fe`
- **Date:** 2026-09-29
- **Task:** `decision-points` (ADR-0012, Appendix F)
- **Decision points in this run:** `turn_intent`, `confirm_gate`, `block_reason`, `handoff_route`, `smalltalk_route`
- **Artifact:** `packages/encoder/calibration/decision_points.json` -> `artifact_id` `c805801cea92` (official run: merged into the committed artifact)
- **Environment:** Linux 6.18.44-fc-v37 (x86_64), Python 3.12.3, scikit-learn 1.9.1, 4 CPUs (host, single process; not measured under the container limits)

## Provenance and hashes

- **Configuration:** `tools/calibrate/configs/decision_points.yaml` (`1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87`)
- **Data (per decision point):**
  - `data/eval/synthetic/decision.train.jsonl` (train): `a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984`
  - `data/eval/synthetic/decision.validation.jsonl` (validation): `50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699`
  - `data/eval/synthetic/decision.test.provisional.jsonl` (test): `06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7`
- **Test provenance:** synthetic-provisional
- **Backends:**
  - `gate_tfidf`: `tfidf_lr@map-38e4e1a6/train-sha256:a563c0c445d6`
  - `intent_tfidf`: `tfidf_lr@train-sha256:a563c0c445d6`

## Certification status

| Decision point | Status | Certified | Detail |
|---|---|:---:|---|
| `turn_intent` | calibrated | no | 0 of 21 scopes clear the Wilson bound |
| `confirm_gate` | calibrated | no | 0 of 6 scopes clear the Wilson bound |
| `block_reason` | calibrated | no | 0 of 5 scopes clear the Wilson bound |
| `handoff_route` | calibrated | no | 0 of 4 scopes clear the Wilson bound |
| `smalltalk_route` | calibrated | no | 0 of 6 scopes clear the Wilson bound |

## Findings

The threshold chosen on validation did not hold on the held-out test split for these acted labels: their precision is below the floor even by the point estimate.

| Decision point | Scope | Label | Correct / decided | Precision | Floor |
|---|---|---|---:|---:|---:|
| `turn_intent` | pt | `report_lost_card` | 5/6 | 0.83 | 0.90 |
| `turn_intent` | en | `report_lost_card` | 10/15 | 0.67 | 0.90 |
| `turn_intent` | es | `report_stolen_card` | 10/12 | 0.83 | 0.90 |
| `turn_intent` | en | `report_stolen_card` | 8/9 | 0.89 | 0.90 |
| `turn_intent` | en | `report_suspicious_activity` | 9/13 | 0.69 | 0.90 |
| `turn_intent` | es | `report_unrecognized_charge` | 7/8 | 0.88 | 0.90 |
| `turn_intent` | en | `report_unrecognized_charge` | 5/6 | 0.83 | 0.90 |
| `turn_intent` | en | `request_dispute` | 7/9 | 0.78 | 0.90 |
| `turn_intent` | en | `request_human_agent` | 10/14 | 0.71 | 0.90 |
| `confirm_gate` | es | `deny` | 9/11 | 0.82 | 0.90 |
| `confirm_gate` | pt | `deny` | 9/11 | 0.82 | 0.90 |
| `block_reason` | pooled (es, pt, en) | `LOST` | 24/29 | 0.83 | 0.90 |
| `block_reason` | pooled (es, pt, en) | `STOLEN` | 27/31 | 0.87 | 0.90 |
| `block_reason` | pooled (es, pt, en) | `SUSPICIOUS_ACTIVITY` | 26/31 | 0.84 | 0.90 |
| `block_reason` | pooled (es, pt, en) | `CUSTOMER_REQUEST` | 25/29 | 0.86 | 0.90 |
| `handoff_route` | pooled (es, pt, en) | `FRAUD` | 54/63 | 0.86 | 0.90 |
| `handoff_route` | pooled (es, pt, en) | `HUMAN_REQUEST` | 30/49 | 0.61 | 0.90 |
| `smalltalk_route` | pt | `greeting` | 9/10 | 0.90 | 0.95 |
| `smalltalk_route` | es | `out_of_scope` | 5/8 | 0.62 | 0.95 |
| `smalltalk_route` | pt | `out_of_scope` | 5/8 | 0.62 | 0.95 |
| `smalltalk_route` | en | `out_of_scope` | 7/11 | 0.64 | 0.95 |

- `turn_intent`: the constraint rejected nothing on validation in en, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `confirm_gate`: the constraint rejected nothing on validation in es/confirm, es/deny, pt/confirm, pt/deny, en/confirm, en/deny, so those thresholds are only the lowest confidence seen (see each Thresholds table).
- `smalltalk_route`: the constraint rejected nothing on validation in es, pt, en, so those thresholds are only the lowest confidence seen (see each Thresholds table).

## Summary

| Decision point | Language | Status | tau | T | Coverage val | Coverage test | Acted coverage test | ECE pre -> post (test) | Certified |
|---|:---:|---|---|---:|---:|---:|---:|---|:---:|
| `turn_intent` | es | calibrated | 0.700545 | 0.191 | 96.7% | 77.3% | 36.7% | 0.491 -> 0.086 | no |
| `turn_intent` | pt | calibrated | 0.961811 | 0.183 | 74.0% | 58.0% | 28.0% | 0.519 -> 0.064 | no |
| `turn_intent` | en | calibrated | 0.274225 | 0.184 | 100.0% | 99.3% | 50.0% | 0.512 -> 0.085 | no |
| `confirm_gate` | es | calibrated | confirm: 0.880956, deny: 0.742556, other: 0.000000 | 0.122 | 100.0% | 100.0% | 12.0% | 0.184 -> 0.041 | no |
| `confirm_gate` | pt | calibrated | confirm: 0.869226, deny: 0.805281, other: 0.000000 | 0.148 | 100.0% | 99.3% | 12.0% | 0.199 -> 0.039 | no |
| `confirm_gate` | en | calibrated | confirm: 0.987937, deny: 0.999998, other: 0.000000 | 0.116 | 100.0% | 97.3% | 7.3% | 0.210 -> 0.036 | no |
| `block_reason` | es | calibrated | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | 0.191 | 32.7% | 24.7% | 24.7% | 0.204 -> 0.050 | no |
| `block_reason` | pt | calibrated | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | 0.183 | 29.3% | 29.3% | 29.3% | 0.236 -> 0.056 | no |
| `block_reason` | en | calibrated | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | 0.184 | 30.7% | 32.7% | 32.7% | 0.214 -> 0.050 | no |
| `handoff_route` | es | calibrated | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | 0.191 | 32.7% | 34.7% | 34.7% | 0.217 -> 0.058 | no |
| `handoff_route` | pt | calibrated | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | 0.183 | 30.0% | 30.7% | 30.7% | 0.161 -> 0.045 | no |
| `handoff_route` | en | calibrated | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | 0.184 | 34.0% | 32.7% | 32.7% | 0.171 -> 0.035 | no |
| `smalltalk_route` | es | calibrated | 0.902537 | 0.191 | 100.0% | 83.3% | 9.3% | 0.119 -> 0.034 | no |
| `smalltalk_route` | pt | calibrated | 0.617591 | 0.183 | 100.0% | 95.3% | 12.0% | 0.107 -> 0.025 | no |
| `smalltalk_route` | en | calibrated | 0.575974 | 0.184 | 100.0% | 94.7% | 13.3% | 0.111 -> 0.057 | no |

## `turn_intent`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.53 ms, p95 0.93 ms (budget `timeout_ms` 200); RAM model+inference 17.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 21 scopes clear the Wilson bound)

### Candidate selection

'intent_tfidf' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 150 | 0.1910 | 1.034 -> 0.136 |  |
| pt | 150 | 0.1827 | 1.076 -> 0.170 |  |
| en | 150 | 0.1840 | 1.112 -> 0.181 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.700545 | language |  |
| pt | 0.961811 | language |  |
| en | 0.274225 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 96.7% | 77.3% | 36.7% | 0.793 | 0.491 | 0.086 | yes |
| pt | 150 | 150 | 74.0% | 58.0% | 28.0% | 0.844 | 0.519 | 0.064 | yes |
| en | 150 | 150 | 100.0% | 99.3% | 50.0% | 0.789 | 0.512 | 0.085 | yes |
| all | 450 | 450 | 90.2% | 78.2% | 38.2% | 0.809 | 0.506 | 0.065 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `report_lost_card` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| es | `report_stolen_card` | 10 | 12 | 10 | 0.833 | 0.552 | 1.000 | 0.90 |
| es | `report_suspicious_activity` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| es | `report_unrecognized_charge` | 10 | 8 | 7 | 0.875 | 0.529 | 0.700 | 0.90 |
| es | `request_card_block` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| es | `request_dispute` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| es | `request_human_agent` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| pt | `report_lost_card` | 10 | 6 | 5 | 0.833 | 0.436 | 0.500 | 0.90 |
| pt | `report_stolen_card` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| pt | `report_suspicious_activity` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| pt | `report_unrecognized_charge` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `request_card_block` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| pt | `request_dispute` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| pt | `request_human_agent` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| en | `report_lost_card` | 10 | 15 | 10 | 0.667 | 0.417 | 1.000 | 0.90 |
| en | `report_stolen_card` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| en | `report_suspicious_activity` | 10 | 13 | 9 | 0.692 | 0.424 | 0.900 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 6 | 5 | 0.833 | 0.436 | 0.500 | 0.90 |
| en | `request_card_block` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| en | `request_dispute` | 10 | 9 | 7 | 0.778 | 0.453 | 0.700 | 0.90 |
| en | `request_human_agent` | 10 | 14 | 10 | 0.714 | 0.454 | 1.000 | 0.90 |
| all | `report_lost_card` | 30 | 27 | 21 | 0.778 | 0.592 | 0.700 | 0.90 |
| all | `report_stolen_card` | 30 | 27 | 24 | 0.889 | 0.719 | 0.800 | 0.90 |
| all | `report_suspicious_activity` | 30 | 27 | 23 | 0.852 | 0.675 | 0.767 | 0.90 |
| all | `report_unrecognized_charge` | 30 | 17 | 15 | 0.882 | 0.657 | 0.500 | 0.90 |
| all | `request_card_block` | 30 | 21 | 21 | 1.000 | 0.845 | 0.700 | 0.90 |
| all | `request_dispute` | 30 | 21 | 19 | 0.905 | 0.711 | 0.633 | 0.90 |
| all | `request_human_agent` | 30 | 32 | 28 | 0.875 | 0.719 | 0.933 | 0.90 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `check_balance` | 30 | 23 | 21 | 0.913 | 0.732 | 0.700 | not acted on |
| all | `check_recent_transactions` | 30 | 12 | 12 | 1.000 | 0.758 | 0.400 | not acted on |
| all | `confirm` | 30 | 23 | 22 | 0.957 | 0.790 | 0.733 | not acted on |
| all | `deny` | 30 | 26 | 24 | 0.923 | 0.759 | 0.800 | not acted on |
| all | `greeting` | 30 | 25 | 24 | 0.960 | 0.805 | 0.800 | not acted on |
| all | `out_of_scope` | 30 | 32 | 16 | 0.500 | 0.336 | 0.533 | not acted on |
| all | `provide_identity_data` | 30 | 18 | 18 | 1.000 | 0.824 | 0.600 | not acted on |
| all | `provide_otp_code` | 30 | 21 | 17 | 0.810 | 0.600 | 0.567 | not acted on |
| all | `report_lost_card` | 30 | 27 | 21 | 0.778 | 0.592 | 0.700 | 0.90 |
| all | `report_stolen_card` | 30 | 27 | 24 | 0.889 | 0.719 | 0.800 | 0.90 |
| all | `report_suspicious_activity` | 30 | 27 | 23 | 0.852 | 0.675 | 0.767 | 0.90 |
| all | `report_unrecognized_charge` | 30 | 17 | 15 | 0.882 | 0.657 | 0.500 | 0.90 |
| all | `request_card_block` | 30 | 21 | 21 | 1.000 | 0.845 | 0.700 | 0.90 |
| all | `request_dispute` | 30 | 21 | 19 | 0.905 | 0.711 | 0.633 | 0.90 |
| all | `request_human_agent` | 30 | 32 | 28 | 0.875 | 0.719 | 0.933 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `report_lost_card` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| pt | `report_lost_card` | 5/6 | 0.436 | 0.90 | no | 35 decided with zero errors (has 5/6) |
| en | `report_lost_card` | 10/15 | 0.417 | 0.90 | no | 35 decided with zero errors (has 10/15) |
| es | `report_stolen_card` | 10/12 | 0.552 | 0.90 | no | 35 decided with zero errors (has 10/12) |
| pt | `report_stolen_card` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| en | `report_stolen_card` | 8/9 | 0.565 | 0.90 | no | 35 decided with zero errors (has 8/9) |
| es | `report_suspicious_activity` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| pt | `report_suspicious_activity` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| en | `report_suspicious_activity` | 9/13 | 0.424 | 0.90 | no | 35 decided with zero errors (has 9/13) |
| es | `report_unrecognized_charge` | 7/8 | 0.529 | 0.90 | no | 35 decided with zero errors (has 7/8) |
| pt | `report_unrecognized_charge` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| en | `report_unrecognized_charge` | 5/6 | 0.436 | 0.90 | no | 35 decided with zero errors (has 5/6) |
| es | `request_card_block` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt | `request_card_block` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| en | `request_card_block` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| es | `request_dispute` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| pt | `request_dispute` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| en | `request_dispute` | 7/9 | 0.453 | 0.90 | no | 35 decided with zero errors (has 7/9) |
| es | `request_human_agent` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| pt | `request_human_agent` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| en | `request_human_agent` | 10/14 | 0.454 | 0.90 | no | 35 decided with zero errors (has 10/14) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 |
| 0.2-0.3 | 3, 0.26, 0.00 | 0 | 1, 0.27, 1.00 |
| 0.3-0.4 | 8, 0.37, 0.12 | 4, 0.38, 0.00 | 11, 0.36, 0.09 |
| 0.4-0.5 | 2, 0.47, 0.00 | 6, 0.45, 0.33 | 6, 0.47, 0.33 |
| 0.5-0.6 | 13, 0.54, 0.46 | 7, 0.55, 0.71 | 9, 0.55, 0.67 |
| 0.6-0.7 | 8, 0.64, 0.62 | 6, 0.65, 0.50 | 9, 0.64, 0.56 |
| 0.7-0.8 | 4, 0.73, 1.00 | 11, 0.74, 0.64 | 9, 0.74, 0.56 |
| 0.8-0.9 | 15, 0.84, 0.67 | 8, 0.84, 0.88 | 8, 0.87, 0.75 |
| 0.9-1.0 | 97, 0.98, 0.94 | 108, 0.98, 0.94 | 97, 0.99, 0.95 |

### Confusion on test, languages pooled

| Truth \ decided | `check_balance` | `check_recent_transactions` | `confirm` | `deny` | `greeting` | `out_of_scope` | `provide_identity_data` | `provide_otp_code` | `report_lost_card` | `report_stolen_card` | `report_suspicious_activity` | `report_unrecognized_charge` | `request_card_block` | `request_dispute` | `request_human_agent` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `check_balance` | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | 7 |
| `check_recent_transactions` | 2 | 12 | 0 | 1 | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 10 |
| `confirm` | 0 | 0 | 22 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 4 |
| `deny` | 0 | 0 | 0 | 24 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `greeting` | 0 | 0 | 0 | 0 | 24 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |
| `out_of_scope` | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 12 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 18 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 10 |
| `provide_otp_code` | 0 | 0 | 1 | 0 | 0 | 3 | 0 | 17 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 8 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 21 | 1 | 0 | 0 | 0 | 0 | 0 | 8 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 24 | 0 | 0 | 0 | 0 | 0 | 4 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 23 | 0 | 0 | 0 | 0 | 4 |
| `report_unrecognized_charge` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 15 | 0 | 0 | 1 | 11 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | 0 | 21 | 0 | 0 | 6 |
| `request_dispute` | 0 | 0 | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 19 | 0 | 6 |
| `request_human_agent` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 28 | 2 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_tfidf": {
      "cost_class": "low",
      "kind": "tfidf_lr",
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
      "local_only": true,
      "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
      "params": {},
      "probability_kind": "distribution",
      "timeout_ms": 200,
      "train": {
        "path": "data/eval/synthetic/decision.train.jsonl",
        "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
      }
    }
  },
  "decision_points": {
    "turn_intent": {
      "always_on": true,
      "backend": "intent_tfidf",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 0.183985
          },
          "es": {
            "T": 0.191028
          },
          "pt": {
            "T": 0.182655
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
        "candidate": "intent_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87"
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
            "acted_coverage_test": 0.5,
            "certified": false,
            "coverage_test": 0.9933,
            "coverage_val": 1.0,
            "ece_post": 0.0852,
            "ece_pre": 0.5117,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                10,
                15,
                0.4171
              ],
              "report_stolen_card": [
                8,
                9,
                0.565
              ],
              "report_suspicious_activity": [
                9,
                13,
                0.4237
              ],
              "report_unrecognized_charge": [
                5,
                6,
                0.4365
              ],
              "request_card_block": [
                9,
                9,
                0.7009
              ],
              "request_dispute": [
                7,
                9,
                0.4526
              ],
              "request_human_agent": [
                10,
                14,
                0.4535
              ]
            },
            "recall_test": {
              "report_lost_card": 1.0,
              "report_stolen_card": 0.8,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.5,
              "request_card_block": 0.9,
              "request_dispute": 0.7,
              "request_human_agent": 1.0
            }
          },
          "es": {
            "acted_coverage_test": 0.3667,
            "certified": false,
            "coverage_test": 0.7733,
            "coverage_val": 0.9667,
            "ece_post": 0.0862,
            "ece_pre": 0.4909,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                6,
                6,
                0.6097
              ],
              "report_stolen_card": [
                10,
                12,
                0.552
              ],
              "report_suspicious_activity": [
                8,
                8,
                0.6756
              ],
              "report_unrecognized_charge": [
                7,
                8,
                0.5291
              ],
              "request_card_block": [
                5,
                5,
                0.5655
              ],
              "request_dispute": [
                7,
                7,
                0.6457
              ],
              "request_human_agent": [
                9,
                9,
                0.7009
              ]
            },
            "recall_test": {
              "report_lost_card": 0.6,
              "report_stolen_card": 1.0,
              "report_suspicious_activity": 0.8,
              "report_unrecognized_charge": 0.7,
              "request_card_block": 0.5,
              "request_dispute": 0.7,
              "request_human_agent": 0.9
            }
          },
          "pt": {
            "acted_coverage_test": 0.28,
            "certified": false,
            "coverage_test": 0.58,
            "coverage_val": 0.74,
            "ece_post": 0.0642,
            "ece_pre": 0.5191,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "report_lost_card": [
                5,
                6,
                0.4365
              ],
              "report_stolen_card": [
                6,
                6,
                0.6097
              ],
              "report_suspicious_activity": [
                6,
                6,
                0.6097
              ],
              "report_unrecognized_charge": [
                3,
                3,
                0.4385
              ],
              "request_card_block": [
                7,
                7,
                0.6457
              ],
              "request_dispute": [
                5,
                5,
                0.5655
              ],
              "request_human_agent": [
                9,
                9,
                0.7009
              ]
            },
            "recall_test": {
              "report_lost_card": 0.5,
              "report_stolen_card": 0.6,
              "report_suspicious_activity": 0.6,
              "report_unrecognized_charge": 0.3,
              "request_card_block": 0.7,
              "request_dispute": 0.5,
              "request_human_agent": 0.9
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-29.md",
        "run_id": "602eaec9e0fe",
        "split": "test"
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.274225,
        "es": 0.700545,
        "pt": 0.961811
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
- [ ] Constraint met on test with the Wilson bound (0 of 21 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 17.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **CPU latency (single text, host):** p50 0.66 ms, p95 1.01 ms (budget `timeout_ms` 200); RAM model+inference 2.9 MB
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
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87"
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
        "report": "reports/calibration-decision-points-2026-09-29.md",
        "run_id": "602eaec9e0fe",
        "split": "test"
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
- [x] p95 inside the DP's `timeout_ms` (RAM 2.9 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.53 ms, p95 0.93 ms (budget `timeout_ms` 200); RAM model+inference 17.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 5 scopes clear the Wilson bound)

### Candidate selection

'intent_tfidf' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 150 | 0.1910 | 1.034 -> 0.136 |  |
| pt | 150 | 0.1827 | 1.076 -> 0.170 |  |
| en | 150 | 0.1840 | 1.112 -> 0.181 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | pooled |  |
| pt | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | pooled |  |
| en | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | pooled |  |
| * | LOST: 0.601892, STOLEN: 0.520718, UNRECOGNIZED_CHARGE: 0.963534, SUSPICIOUS_ACTIVITY: 0.236208, CUSTOMER_REQUEST: 0.061919 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 32.7% | 24.7% | 24.7% | 0.507 | 0.204 | 0.050 | yes |
| pt | 150 | 150 | 29.3% | 29.3% | 29.3% | 0.610 | 0.236 | 0.056 | yes |
| en | 150 | 150 | 30.7% | 32.7% | 32.7% | 0.516 | 0.214 | 0.050 | yes |
| all | 450 | 450 | 30.9% | 28.9% | 28.9% | 0.533 | 0.218 | 0.026 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `LOST` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| es | `STOLEN` | 10 | 12 | 10 | 0.833 | 0.552 | 1.000 | 0.90 |
| es | `UNRECOGNIZED_CHARGE` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| es | `SUSPICIOUS_ACTIVITY` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| es | `CUSTOMER_REQUEST` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| pt | `LOST` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| pt | `STOLEN` | 10 | 10 | 9 | 0.900 | 0.596 | 0.900 | 0.90 |
| pt | `UNRECOGNIZED_CHARGE` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `SUSPICIOUS_ACTIVITY` | 10 | 10 | 9 | 0.900 | 0.596 | 0.900 | 0.90 |
| pt | `CUSTOMER_REQUEST` | 10 | 12 | 9 | 0.750 | 0.468 | 0.900 | 0.90 |
| en | `LOST` | 10 | 14 | 10 | 0.714 | 0.454 | 1.000 | 0.90 |
| en | `STOLEN` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| en | `UNRECOGNIZED_CHARGE` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| en | `SUSPICIOUS_ACTIVITY` | 10 | 13 | 9 | 0.692 | 0.424 | 0.900 | 0.90 |
| en | `CUSTOMER_REQUEST` | 10 | 10 | 9 | 0.900 | 0.596 | 0.900 | 0.90 |
| all | `LOST` | 30 | 29 | 24 | 0.828 | 0.655 | 0.800 | 0.90 |
| all | `STOLEN` | 30 | 31 | 27 | 0.871 | 0.711 | 0.900 | 0.90 |
| all | `UNRECOGNIZED_CHARGE` | 30 | 10 | 10 | 1.000 | 0.722 | 0.333 | 0.90 |
| all | `SUSPICIOUS_ACTIVITY` | 30 | 31 | 26 | 0.839 | 0.674 | 0.867 | 0.90 |
| all | `CUSTOMER_REQUEST` | 30 | 29 | 25 | 0.862 | 0.694 | 0.833 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| pooled (es, pt, en) | `LOST` | 24/29 | 0.655 | 0.90 | no | 35 decided with zero errors (has 24/29) |
| pooled (es, pt, en) | `STOLEN` | 27/31 | 0.711 | 0.90 | no | 35 decided with zero errors (has 27/31) |
| pooled (es, pt, en) | `UNRECOGNIZED_CHARGE` | 10/10 | 0.722 | 0.90 | no | 35 decided with zero errors (has 10/10) |
| pooled (es, pt, en) | `SUSPICIOUS_ACTIVITY` | 26/31 | 0.674 | 0.90 | no | 35 decided with zero errors (has 26/31) |
| pooled (es, pt, en) | `CUSTOMER_REQUEST` | 25/29 | 0.694 | 0.90 | no | 35 decided with zero errors (has 25/29) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 89, 0.01, 0.01 | 90, 0.01, 0.01 | 87, 0.01, 0.01 |
| 0.1-0.2 | 11, 0.13, 0.00 | 7, 0.13, 0.00 | 8, 0.13, 0.00 |
| 0.2-0.3 | 1, 0.22, 0.00 | 2, 0.25, 1.00 | 1, 0.27, 1.00 |
| 0.3-0.4 | 2, 0.37, 0.00 | 2, 0.31, 1.00 | 2, 0.32, 0.00 |
| 0.4-0.5 | 2, 0.47, 0.00 | 2, 0.45, 0.00 | 2, 0.44, 0.50 |
| 0.5-0.6 | 6, 0.52, 0.67 | 3, 0.54, 0.33 | 4, 0.55, 0.50 |
| 0.6-0.7 | 0 | 1, 0.66, 1.00 | 6, 0.65, 0.50 |
| 0.7-0.8 | 2, 0.75, 1.00 | 4, 0.72, 1.00 | 4, 0.74, 0.25 |
| 0.8-0.9 | 6, 0.84, 0.50 | 2, 0.85, 1.00 | 3, 0.88, 1.00 |
| 0.9-1.0 | 31, 0.98, 1.00 | 37, 0.98, 0.95 | 33, 0.98, 0.94 |

### Confusion on test, languages pooled

| Truth \ decided | `LOST` | `STOLEN` | `UNRECOGNIZED_CHARGE` | `SUSPICIOUS_ACTIVITY` | `CUSTOMER_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|---:|
| `LOST` | 24 | 1 | 0 | 0 | 0 | 5 |
| `STOLEN` | 1 | 27 | 0 | 0 | 0 | 2 |
| `UNRECOGNIZED_CHARGE` | 1 | 0 | 10 | 2 | 0 | 17 |
| `SUSPICIOUS_ACTIVITY` | 0 | 1 | 0 | 26 | 0 | 3 |
| `CUSTOMER_REQUEST` | 2 | 1 | 0 | 0 | 25 | 2 |
| `(outside the view)` | 1 | 1 | 0 | 3 | 4 | 291 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_tfidf": {
      "cost_class": "low",
      "kind": "tfidf_lr",
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
      "local_only": true,
      "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
      "params": {},
      "probability_kind": "distribution",
      "timeout_ms": 200,
      "train": {
        "path": "data/eval/synthetic/decision.train.jsonl",
        "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
      }
    }
  },
  "decision_points": {
    "block_reason": {
      "always_on": true,
      "backend": "intent_tfidf",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 0.183985
          },
          "es": {
            "T": 0.191028
          },
          "pt": {
            "T": 0.182655
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
        "candidate": "intent_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87"
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
            "acted_coverage_test": 0.3267,
            "certified": false,
            "coverage_test": 0.3267,
            "coverage_val": 0.3067,
            "ece_post": 0.0501,
            "ece_pre": 0.2141,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                9,
                10,
                0.5958
              ],
              "LOST": [
                10,
                14,
                0.4535
              ],
              "STOLEN": [
                8,
                9,
                0.565
              ],
              "SUSPICIOUS_ACTIVITY": [
                9,
                13,
                0.4237
              ],
              "UNRECOGNIZED_CHARGE": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.9,
              "LOST": 1.0,
              "STOLEN": 0.8,
              "SUSPICIOUS_ACTIVITY": 0.9,
              "UNRECOGNIZED_CHARGE": 0.3
            }
          },
          "es": {
            "acted_coverage_test": 0.2467,
            "certified": false,
            "coverage_test": 0.2467,
            "coverage_val": 0.3267,
            "ece_post": 0.0496,
            "ece_pre": 0.2041,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                7,
                7,
                0.6457
              ],
              "LOST": [
                6,
                6,
                0.6097
              ],
              "STOLEN": [
                10,
                12,
                0.552
              ],
              "SUSPICIOUS_ACTIVITY": [
                8,
                8,
                0.6756
              ],
              "UNRECOGNIZED_CHARGE": [
                4,
                4,
                0.5101
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.7,
              "LOST": 0.6,
              "STOLEN": 1.0,
              "SUSPICIOUS_ACTIVITY": 0.8,
              "UNRECOGNIZED_CHARGE": 0.4
            }
          },
          "pt": {
            "acted_coverage_test": 0.2933,
            "certified": false,
            "coverage_test": 0.2933,
            "coverage_val": 0.2933,
            "ece_post": 0.0559,
            "ece_pre": 0.236,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "CUSTOMER_REQUEST": [
                9,
                12,
                0.4677
              ],
              "LOST": [
                8,
                9,
                0.565
              ],
              "STOLEN": [
                9,
                10,
                0.5958
              ],
              "SUSPICIOUS_ACTIVITY": [
                9,
                10,
                0.5958
              ],
              "UNRECOGNIZED_CHARGE": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "CUSTOMER_REQUEST": 0.9,
              "LOST": 0.8,
              "STOLEN": 0.9,
              "SUSPICIOUS_ACTIVITY": 0.9,
              "UNRECOGNIZED_CHARGE": 0.3
            }
          }
        },
        "pooled_test": {
          "CUSTOMER_REQUEST": [
            25,
            29,
            0.6944,
            "pooled (es, pt, en)"
          ],
          "LOST": [
            24,
            29,
            0.6545,
            "pooled (es, pt, en)"
          ],
          "STOLEN": [
            27,
            31,
            0.7115,
            "pooled (es, pt, en)"
          ],
          "SUSPICIOUS_ACTIVITY": [
            26,
            31,
            0.6737,
            "pooled (es, pt, en)"
          ],
          "UNRECOGNIZED_CHARGE": [
            10,
            10,
            0.7225,
            "pooled (es, pt, en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-29.md",
        "run_id": "602eaec9e0fe",
        "split": "test"
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "CUSTOMER_REQUEST": 0.061919,
          "LOST": 0.601892,
          "STOLEN": 0.520718,
          "SUSPICIOUS_ACTIVITY": 0.236208,
          "UNRECOGNIZED_CHARGE": 0.963534
        },
        "en": {
          "CUSTOMER_REQUEST": 0.061919,
          "LOST": 0.601892,
          "STOLEN": 0.520718,
          "SUSPICIOUS_ACTIVITY": 0.236208,
          "UNRECOGNIZED_CHARGE": 0.963534
        },
        "es": {
          "CUSTOMER_REQUEST": 0.061919,
          "LOST": 0.601892,
          "STOLEN": 0.520718,
          "SUSPICIOUS_ACTIVITY": 0.236208,
          "UNRECOGNIZED_CHARGE": 0.963534
        },
        "pt": {
          "CUSTOMER_REQUEST": 0.061919,
          "LOST": 0.601892,
          "STOLEN": 0.520718,
          "SUSPICIOUS_ACTIVITY": 0.236208,
          "UNRECOGNIZED_CHARGE": 0.963534
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
- [ ] Constraint met on test with the Wilson bound (0 of 5 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 17.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.53 ms, p95 0.93 ms (budget `timeout_ms` 200); RAM model+inference 17.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 4 scopes clear the Wilson bound)

### Candidate selection

'intent_tfidf' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 150 | 0.1910 | 1.034 -> 0.136 |  |
| pt | 150 | 0.1827 | 1.076 -> 0.170 |  |
| en | 150 | 0.1840 | 1.112 -> 0.181 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | pooled |  |
| pt | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | pooled |  |
| en | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | pooled |  |
| * | DISPUTE: 0.247761, FRAUD: 0.466438, UNRECOGNIZED: 0.963534, HUMAN_REQUEST: 0.093443 | pooled languages |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 32.7% | 34.7% | 34.7% | 0.631 | 0.217 | 0.058 | yes |
| pt | 150 | 150 | 30.0% | 30.7% | 30.7% | 0.602 | 0.161 | 0.045 | yes |
| en | 150 | 150 | 34.0% | 32.7% | 32.7% | 0.568 | 0.171 | 0.035 | yes |
| all | 450 | 450 | 32.2% | 32.7% | 32.7% | 0.600 | 0.183 | 0.033 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `DISPUTE` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| es | `FRAUD` | 20 | 23 | 19 | 0.826 | 0.629 | 0.950 | 0.90 |
| es | `UNRECOGNIZED` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| es | `HUMAN_REQUEST` | 10 | 17 | 10 | 0.588 | 0.360 | 1.000 | 0.90 |
| pt | `DISPUTE` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| pt | `FRAUD` | 20 | 19 | 17 | 0.895 | 0.686 | 0.850 | 0.90 |
| pt | `UNRECOGNIZED` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `HUMAN_REQUEST` | 10 | 16 | 10 | 0.625 | 0.386 | 1.000 | 0.90 |
| en | `DISPUTE` | 10 | 9 | 7 | 0.778 | 0.453 | 0.700 | 0.90 |
| en | `FRAUD` | 20 | 21 | 18 | 0.857 | 0.654 | 0.900 | 0.90 |
| en | `UNRECOGNIZED` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| en | `HUMAN_REQUEST` | 10 | 16 | 10 | 0.625 | 0.386 | 1.000 | 0.90 |
| all | `DISPUTE` | 30 | 25 | 23 | 0.920 | 0.750 | 0.767 | 0.90 |
| all | `FRAUD` | 60 | 63 | 54 | 0.857 | 0.750 | 0.900 | 0.90 |
| all | `UNRECOGNIZED` | 30 | 10 | 10 | 1.000 | 0.722 | 0.333 | 0.90 |
| all | `HUMAN_REQUEST` | 30 | 49 | 30 | 0.612 | 0.472 | 1.000 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| pooled (es, pt, en) | `DISPUTE` | 23/25 | 0.750 | 0.90 | no | 35 decided with zero errors (has 23/25) |
| pooled (es, pt, en) | `FRAUD` | 54/63 | 0.750 | 0.90 | no | 35 decided with zero errors (has 54/63) |
| pooled (es, pt, en) | `UNRECOGNIZED` | 10/10 | 0.722 | 0.90 | no | 35 decided with zero errors (has 10/10) |
| pooled (es, pt, en) | `HUMAN_REQUEST` | 30/49 | 0.472 | 0.90 | no | 35 decided with zero errors (has 30/49) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 75, 0.01, 0.03 | 84, 0.01, 0.01 | 86, 0.01, 0.02 |
| 0.1-0.2 | 15, 0.13, 0.00 | 9, 0.14, 0.11 | 9, 0.13, 0.11 |
| 0.2-0.3 | 2, 0.24, 0.00 | 2, 0.27, 0.50 | 4, 0.26, 0.25 |
| 0.3-0.4 | 3, 0.37, 0.00 | 2, 0.32, 0.50 | 3, 0.37, 0.33 |
| 0.4-0.5 | 2, 0.47, 0.00 | 5, 0.47, 0.00 | 2, 0.44, 0.00 |
| 0.5-0.6 | 5, 0.53, 0.40 | 2, 0.54, 0.00 | 3, 0.55, 0.67 |
| 0.6-0.7 | 3, 0.65, 0.67 | 1, 0.62, 1.00 | 5, 0.65, 0.60 |
| 0.7-0.8 | 1, 0.77, 1.00 | 7, 0.75, 0.86 | 5, 0.73, 0.40 |
| 0.8-0.9 | 8, 0.83, 0.62 | 2, 0.85, 0.50 | 6, 0.89, 0.83 |
| 0.9-1.0 | 36, 0.99, 1.00 | 36, 0.98, 0.97 | 27, 0.99, 1.00 |

### Confusion on test, languages pooled

| Truth \ decided | `DISPUTE` | `FRAUD` | `UNRECOGNIZED` | `HUMAN_REQUEST` | `(abstained)` |
|---|---:|---:|---:|---:|---:|
| `DISPUTE` | 23 | 1 | 0 | 1 | 5 |
| `FRAUD` | 0 | 54 | 0 | 1 | 5 |
| `UNRECOGNIZED` | 0 | 1 | 10 | 1 | 18 |
| `HUMAN_REQUEST` | 0 | 0 | 0 | 30 | 0 |
| `(outside the view)` | 2 | 7 | 0 | 16 | 275 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_tfidf": {
      "cost_class": "low",
      "kind": "tfidf_lr",
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
      "local_only": true,
      "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
      "params": {},
      "probability_kind": "distribution",
      "timeout_ms": 200,
      "train": {
        "path": "data/eval/synthetic/decision.train.jsonl",
        "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
      }
    }
  },
  "decision_points": {
    "handoff_route": {
      "always_on": true,
      "backend": "intent_tfidf",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 0.183985
          },
          "es": {
            "T": 0.191028
          },
          "pt": {
            "T": 0.182655
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
        "candidate": "intent_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87"
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
            "acted_coverage_test": 0.3267,
            "certified": false,
            "coverage_test": 0.3267,
            "coverage_val": 0.34,
            "ece_post": 0.0347,
            "ece_pre": 0.1706,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "DISPUTE": [
                7,
                9,
                0.4526
              ],
              "FRAUD": [
                18,
                21,
                0.6536
              ],
              "HUMAN_REQUEST": [
                10,
                16,
                0.3864
              ],
              "UNRECOGNIZED": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "DISPUTE": 0.7,
              "FRAUD": 0.9,
              "HUMAN_REQUEST": 1.0,
              "UNRECOGNIZED": 0.3
            }
          },
          "es": {
            "acted_coverage_test": 0.3467,
            "certified": false,
            "coverage_test": 0.3467,
            "coverage_val": 0.3267,
            "ece_post": 0.0575,
            "ece_pre": 0.2168,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "DISPUTE": [
                8,
                8,
                0.6756
              ],
              "FRAUD": [
                19,
                23,
                0.6286
              ],
              "HUMAN_REQUEST": [
                10,
                17,
                0.3601
              ],
              "UNRECOGNIZED": [
                4,
                4,
                0.5101
              ]
            },
            "recall_test": {
              "DISPUTE": 0.8,
              "FRAUD": 0.95,
              "HUMAN_REQUEST": 1.0,
              "UNRECOGNIZED": 0.4
            }
          },
          "pt": {
            "acted_coverage_test": 0.3067,
            "certified": false,
            "coverage_test": 0.3067,
            "coverage_val": 0.3,
            "ece_post": 0.0451,
            "ece_pre": 0.1614,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "DISPUTE": [
                8,
                8,
                0.6756
              ],
              "FRAUD": [
                17,
                19,
                0.6861
              ],
              "HUMAN_REQUEST": [
                10,
                16,
                0.3864
              ],
              "UNRECOGNIZED": [
                3,
                3,
                0.4385
              ]
            },
            "recall_test": {
              "DISPUTE": 0.8,
              "FRAUD": 0.85,
              "HUMAN_REQUEST": 1.0,
              "UNRECOGNIZED": 0.3
            }
          }
        },
        "pooled_test": {
          "DISPUTE": [
            23,
            25,
            0.7503,
            "pooled (es, pt, en)"
          ],
          "FRAUD": [
            54,
            63,
            0.7503,
            "pooled (es, pt, en)"
          ],
          "HUMAN_REQUEST": [
            30,
            49,
            0.4725,
            "pooled (es, pt, en)"
          ],
          "UNRECOGNIZED": [
            10,
            10,
            0.7225,
            "pooled (es, pt, en)"
          ]
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-29.md",
        "run_id": "602eaec9e0fe",
        "split": "test"
      },
      "status": "calibrated",
      "thresholds": {
        "*": {
          "DISPUTE": 0.247761,
          "FRAUD": 0.466438,
          "HUMAN_REQUEST": 0.093443,
          "UNRECOGNIZED": 0.963534
        },
        "en": {
          "DISPUTE": 0.247761,
          "FRAUD": 0.466438,
          "HUMAN_REQUEST": 0.093443,
          "UNRECOGNIZED": 0.963534
        },
        "es": {
          "DISPUTE": 0.247761,
          "FRAUD": 0.466438,
          "HUMAN_REQUEST": 0.093443,
          "UNRECOGNIZED": 0.963534
        },
        "pt": {
          "DISPUTE": 0.247761,
          "FRAUD": 0.466438,
          "HUMAN_REQUEST": 0.093443,
          "UNRECOGNIZED": 0.963534
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
- [ ] Constraint met on test with the Wilson bound (0 of 4 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 17.8 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.53 ms, p95 0.93 ms (budget `timeout_ms` 200); RAM model+inference 17.8 MB
- **Status written:** `calibrated`; certified: **no** (0 of 6 scopes clear the Wilson bound)

### Candidate selection

'intent_tfidf' is the only candidate.

### Calibrator

| Language | Validation rows | T | Log loss before -> after | Note |
|:---:|---:|---:|---|---|
| es | 150 | 0.1910 | 1.034 -> 0.136 |  |
| pt | 150 | 0.1827 | 1.076 -> 0.170 |  |
| en | 150 | 0.1840 | 1.112 -> 0.181 |  |

### Thresholds

| Language | tau | Fitted on | Notes |
|:---:|---|---|---|
| es | 0.902537 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| pt | 0.617591 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |
| en | 0.575974 | language | not binding: every validation row is accepted, so tau is only the lowest confidence seen |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 100.0% | 83.3% | 9.3% | 0.778 | 0.119 | 0.034 | yes |
| pt | 150 | 150 | 100.0% | 95.3% | 12.0% | 0.832 | 0.107 | 0.025 | yes |
| en | 150 | 150 | 100.0% | 94.7% | 13.3% | 0.860 | 0.111 | 0.057 | yes |
| all | 450 | 450 | 100.0% | 91.1% | 11.6% | 0.825 | 0.112 | 0.028 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `greeting` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.95 |
| es | `out_of_scope` | 10 | 8 | 5 | 0.625 | 0.306 | 0.500 | 0.95 |
| pt | `greeting` | 10 | 10 | 9 | 0.900 | 0.596 | 0.900 | 0.95 |
| pt | `out_of_scope` | 10 | 8 | 5 | 0.625 | 0.306 | 0.500 | 0.95 |
| en | `greeting` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.95 |
| en | `out_of_scope` | 10 | 11 | 7 | 0.636 | 0.354 | 0.700 | 0.95 |
| all | `greeting` | 30 | 25 | 24 | 0.960 | 0.805 | 0.800 | 0.95 |
| all | `out_of_scope` | 30 | 27 | 17 | 0.630 | 0.442 | 0.567 | 0.95 |

All labels, languages pooled:

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | `greeting` | 30 | 25 | 24 | 0.960 | 0.805 | 0.800 | 0.95 |
| all | `out_of_scope` | 30 | 27 | 17 | 0.630 | 0.442 | 0.567 | 0.95 |
| all | `other` | 390 | 358 | 353 | 0.986 | 0.968 | 0.905 | not acted on |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `greeting` | 6/6 | 0.610 | 0.95 | no | 73 decided with zero errors (has 6/6) |
| pt | `greeting` | 9/10 | 0.596 | 0.95 | no | 73 decided with zero errors (has 9/10) |
| en | `greeting` | 9/9 | 0.701 | 0.95 | no | 73 decided with zero errors (has 9/9) |
| es | `out_of_scope` | 5/8 | 0.306 | 0.95 | no | 73 decided with zero errors (has 5/8) |
| pt | `out_of_scope` | 5/8 | 0.306 | 0.95 | no | 73 decided with zero errors (has 5/8) |
| en | `out_of_scope` | 7/11 | 0.354 | 0.95 | no | 73 decided with zero errors (has 7/11) |

### Reliability on test (after calibration; n, mean confidence, accuracy)

| Confidence bin | es: n, conf, acc | pt: n, conf, acc | en: n, conf, acc |
|---|---|---|---|
| 0.0-0.1 | 0 | 0 | 0 |
| 0.1-0.2 | 0 | 0 | 0 |
| 0.2-0.3 | 0 | 0 | 0 |
| 0.3-0.4 | 0 | 0 | 0 |
| 0.4-0.5 | 0 | 0 | 1, 0.49, 0.00 |
| 0.5-0.6 | 8, 0.53, 0.62 | 7, 0.53, 0.57 | 8, 0.52, 0.75 |
| 0.6-0.7 | 4, 0.66, 0.75 | 2, 0.69, 0.50 | 4, 0.64, 1.00 |
| 0.7-0.8 | 5, 0.74, 0.80 | 5, 0.75, 0.40 | 4, 0.74, 1.00 |
| 0.8-0.9 | 8, 0.84, 0.75 | 5, 0.86, 1.00 | 8, 0.84, 0.75 |
| 0.9-1.0 | 125, 0.99, 0.97 | 131, 0.99, 0.98 | 125, 0.99, 0.97 |

### Confusion on test, languages pooled

| Truth \ decided | `greeting` | `out_of_scope` | `other` | `(abstained)` |
|---|---:|---:|---:|---:|
| `greeting` | 24 | 2 | 0 | 4 |
| `out_of_scope` | 0 | 17 | 5 | 8 |
| `other` | 1 | 8 | 353 | 28 |

### Hard negatives

Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). Until there is, 'false accepts on hard negatives' is unknown, not zero.

### Artifact fragment (verbatim)

```json
{
  "backends": {
    "intent_tfidf": {
      "cost_class": "low",
      "kind": "tfidf_lr",
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
      "local_only": true,
      "model_id": "tfidf_lr@train-sha256:a563c0c445d6",
      "params": {},
      "probability_kind": "distribution",
      "timeout_ms": 200,
      "train": {
        "path": "data/eval/synthetic/decision.train.jsonl",
        "sha256": "a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984"
      }
    }
  },
  "decision_points": {
    "smalltalk_route": {
      "always_on": true,
      "backend": "intent_tfidf",
      "calibrator": {
        "by_lang": {
          "en": {
            "T": 0.183985
          },
          "es": {
            "T": 0.191028
          },
          "pt": {
            "T": 0.182655
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
        "candidate": "intent_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "1da459a46de4df0d5ce7c8c5cad360b2c713c6316deb2de75bda8d718f54db87"
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
            "acted_coverage_test": 0.1333,
            "certified": false,
            "coverage_test": 0.9467,
            "coverage_val": 1.0,
            "ece_post": 0.0566,
            "ece_pre": 0.1112,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "greeting": [
                9,
                9,
                0.7009
              ],
              "out_of_scope": [
                7,
                11,
                0.3538
              ]
            },
            "recall_test": {
              "greeting": 0.9,
              "out_of_scope": 0.7
            }
          },
          "es": {
            "acted_coverage_test": 0.0933,
            "certified": false,
            "coverage_test": 0.8333,
            "coverage_val": 1.0,
            "ece_post": 0.0338,
            "ece_pre": 0.1191,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "greeting": [
                6,
                6,
                0.6097
              ],
              "out_of_scope": [
                5,
                8,
                0.3057
              ]
            },
            "recall_test": {
              "greeting": 0.6,
              "out_of_scope": 0.5
            }
          },
          "pt": {
            "acted_coverage_test": 0.12,
            "certified": false,
            "coverage_test": 0.9533,
            "coverage_val": 1.0,
            "ece_post": 0.0254,
            "ece_pre": 0.1068,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "greeting": [
                9,
                10,
                0.5958
              ],
              "out_of_scope": [
                5,
                8,
                0.3057
              ]
            },
            "recall_test": {
              "greeting": 0.9,
              "out_of_scope": 0.5
            }
          }
        },
        "provenance": "synthetic-provisional",
        "report": "reports/calibration-decision-points-2026-09-29.md",
        "run_id": "602eaec9e0fe",
        "split": "test"
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.575974,
        "es": 0.902537,
        "pt": 0.617591
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
- [ ] Constraint met on test with the Wilson bound (0 of 6 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 17.8 MB; the encoder's memory floor is checked by the service at startup).
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
