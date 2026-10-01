# Decision Points Calibration Report

> [!WARNING]
> The test split is **provisional synthetic (not human)**: written by an AI agent, 10 rows per intent and language, never double-labeled. It cannot certify a precision of 0.95 (or 0.90): 22 correct of 22 accepted has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted with zero errors.
> Validation shares its generating process with train, so a calibrator fitted on it is over-confident on real traffic. Thresholds here are chosen on validation only; nothing in this report is a guarantee on real customers.
> Every decision point stays in `shadow` until a separate reviewed diff flips it to `enforce` after the sign-off of ADR-0012, Appendix F.5.

- **Run id:** `92e65dc2487d`
- **Date:** 2026-10-01
- **Task:** `decision-points` (ADR-0012, Appendix F)
- **Decision points in this run:** `intent_hint`, `clarify_route` (a partial run: the other decision points of the artifact are unchanged)
- **Artifact:** `packages/encoder/calibration/decision_points.json` -> `artifact_id` `09c0d617e904` (official run: merged into the committed artifact)
- **Environment:** Darwin 27.0.0 (arm64), Python 3.12.12, scikit-learn 1.9.1, 12 CPUs (host, single process; not measured under the container limits)

## Provenance and hashes

- **Configuration:** `tools/calibrate/configs/decision_points.yaml` (`edf6e6fc9df724d21057df5f1ce455cc9e77755b580e7e9931d642039020ee73`)
- **Data (per decision point):**
  - `data/eval/synthetic/decision.train.jsonl` (train): `a563c0c445d6450ed5a9800933508fa1931d5b616943a522852ef7409bfc3984`
  - `data/eval/synthetic/decision.validation.jsonl` (validation): `50c79fedeb123dd803cc7968147014b606227a6c68b30769fa0c2f6e2627e699`
  - `data/eval/synthetic/decision.test.provisional.jsonl` (test): `06c1226b79537b41945ef6fcec247942197d3d93259881fbe16f7a1de70c18f7`
- **Test provenance:** synthetic-provisional
- **Backends:**
  - `intent_tfidf`: `tfidf_lr@train-sha256:a563c0c445d6`

## Certification status

| Decision point | Status | Certified | Detail |
|---|---|:---:|---|
| `intent_hint` | calibrated | no | 0 of 45 scopes clear the Wilson bound |
| `clarify_route` | calibrated | no | 0 of 21 scopes clear the Wilson bound |

## Findings

The threshold chosen on validation did not hold on the held-out test split for these acted labels: their precision is below the floor even by the point estimate.

| Decision point | Scope | Label | Correct / decided | Precision | Floor |
|---|---|---|---:|---:|---:|
| `intent_hint` | es | `check_balance` | 7/8 | 0.88 | 0.90 |
| `intent_hint` | pt | `deny` | 8/9 | 0.89 | 0.90 |
| `intent_hint` | pt | `greeting` | 8/9 | 0.89 | 0.90 |
| `intent_hint` | es | `out_of_scope` | 5/9 | 0.56 | 0.90 |
| `intent_hint` | en | `out_of_scope` | 8/12 | 0.67 | 0.90 |
| `intent_hint` | es | `provide_otp_code` | 7/9 | 0.78 | 0.90 |
| `intent_hint` | pt | `provide_otp_code` | 5/6 | 0.83 | 0.90 |
| `intent_hint` | pt | `report_lost_card` | 5/6 | 0.83 | 0.90 |
| `intent_hint` | en | `report_lost_card` | 10/15 | 0.67 | 0.90 |
| `intent_hint` | es | `report_stolen_card` | 10/12 | 0.83 | 0.90 |
| `intent_hint` | en | `report_stolen_card` | 8/9 | 0.89 | 0.90 |
| `intent_hint` | en | `report_suspicious_activity` | 9/11 | 0.82 | 0.90 |
| `intent_hint` | es | `report_unrecognized_charge` | 7/8 | 0.88 | 0.90 |
| `intent_hint` | en | `report_unrecognized_charge` | 5/6 | 0.83 | 0.90 |
| `intent_hint` | en | `request_dispute` | 6/7 | 0.86 | 0.90 |
| `intent_hint` | en | `request_human_agent` | 10/12 | 0.83 | 0.90 |
| `clarify_route` | pt | `report_lost_card` | 5/6 | 0.83 | 0.90 |
| `clarify_route` | en | `report_lost_card` | 10/15 | 0.67 | 0.90 |
| `clarify_route` | es | `report_stolen_card` | 10/12 | 0.83 | 0.90 |
| `clarify_route` | en | `report_stolen_card` | 8/9 | 0.89 | 0.90 |
| `clarify_route` | en | `report_suspicious_activity` | 9/13 | 0.69 | 0.90 |
| `clarify_route` | es | `report_unrecognized_charge` | 7/8 | 0.88 | 0.90 |
| `clarify_route` | en | `report_unrecognized_charge` | 5/6 | 0.83 | 0.90 |
| `clarify_route` | en | `request_dispute` | 7/9 | 0.78 | 0.90 |
| `clarify_route` | en | `request_human_agent` | 10/14 | 0.71 | 0.90 |

- `clarify_route`: the constraint rejected nothing on validation in en, so those thresholds are only the lowest confidence seen (see each Thresholds table).

## Summary

| Decision point | Language | Status | tau | T | Coverage val | Coverage test | Acted coverage test | ECE pre -> post (test) | Certified |
|---|:---:|---|---|---:|---:|---:|---:|---|:---:|
| `intent_hint` | es | calibrated | 0.700545 | 0.191 | 96.7% | 77.3% | 77.3% | 0.491 -> 0.086 | no |
| `intent_hint` | pt | calibrated | 0.961811 | 0.183 | 74.0% | 58.0% | 58.0% | 0.519 -> 0.064 | no |
| `intent_hint` | en | calibrated | 0.531773 | 0.184 | 96.0% | 86.0% | 86.0% | 0.512 -> 0.085 | no |
| `clarify_route` | es | calibrated | 0.700545 | 0.191 | 96.7% | 77.3% | 36.7% | 0.491 -> 0.086 | no |
| `clarify_route` | pt | calibrated | 0.961811 | 0.183 | 74.0% | 58.0% | 28.0% | 0.519 -> 0.064 | no |
| `clarify_route` | en | calibrated | 0.274225 | 0.184 | 100.0% | 99.3% | 50.0% | 0.512 -> 0.085 | no |

## `intent_hint`

- **View:** 15 labels (labels)
- **Acted labels and precision floor:** `check_balance` >= 0.90, `check_recent_transactions` >= 0.90, `confirm` >= 0.90, `deny` >= 0.90, `greeting` >= 0.90, `out_of_scope` >= 0.90, `provide_identity_data` >= 0.90, `provide_otp_code` >= 0.90, `report_lost_card` >= 0.90, `report_stolen_card` >= 0.90, `report_suspicious_activity` >= 0.90, `report_unrecognized_charge` >= 0.90, `request_card_block` >= 0.90, `request_dispute` >= 0.90, `request_human_agent` >= 0.90
- **Selection rule on validation:** `point` precision, at least 10 validation rows of a label per fitting scope
- **Certification rule on test:** Wilson 95% lower bound >= floor (always, whatever the selection rule)
- **Threshold scope:** `per_language`; **calibrator:** `temperature`
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.16 ms, p95 0.22 ms (budget `timeout_ms` 200); RAM model+inference 49.3 MB
- **Status written:** `calibrated`; certified: **no** (0 of 45 scopes clear the Wilson bound)

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
| en | 0.531773 | language |  |

### Coverage and calibration on test

| Language | Validation rows | Test rows | Coverage val | Coverage test | Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post | ECE <= 0.10 |
|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| es | 150 | 150 | 96.7% | 77.3% | 77.3% | 0.793 | 0.491 | 0.086 | yes |
| pt | 150 | 150 | 74.0% | 58.0% | 58.0% | 0.844 | 0.519 | 0.064 | yes |
| en | 150 | 150 | 96.0% | 86.0% | 86.0% | 0.789 | 0.512 | 0.085 | yes |
| all | 450 | 450 | 88.9% | 73.8% | 73.8% | 0.809 | 0.506 | 0.065 | yes |

### Precision on test (acted labels)

| Scope | Label | Test rows | Decided | Correct | Precision | Wilson 95% lower | Recall | Floor |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| es | `check_balance` | 10 | 8 | 7 | 0.875 | 0.529 | 0.700 | 0.90 |
| es | `check_recent_transactions` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| es | `confirm` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| es | `deny` | 10 | 10 | 9 | 0.900 | 0.596 | 0.900 | 0.90 |
| es | `greeting` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| es | `out_of_scope` | 10 | 9 | 5 | 0.556 | 0.267 | 0.500 | 0.90 |
| es | `provide_identity_data` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| es | `provide_otp_code` | 10 | 9 | 7 | 0.778 | 0.453 | 0.700 | 0.90 |
| es | `report_lost_card` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| es | `report_stolen_card` | 10 | 12 | 10 | 0.833 | 0.552 | 1.000 | 0.90 |
| es | `report_suspicious_activity` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| es | `report_unrecognized_charge` | 10 | 8 | 7 | 0.875 | 0.529 | 0.700 | 0.90 |
| es | `request_card_block` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| es | `request_dispute` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| es | `request_human_agent` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| pt | `check_balance` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| pt | `check_recent_transactions` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `confirm` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| pt | `deny` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| pt | `greeting` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| pt | `out_of_scope` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `provide_identity_data` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `provide_otp_code` | 10 | 6 | 5 | 0.833 | 0.436 | 0.500 | 0.90 |
| pt | `report_lost_card` | 10 | 6 | 5 | 0.833 | 0.436 | 0.500 | 0.90 |
| pt | `report_stolen_card` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| pt | `report_suspicious_activity` | 10 | 6 | 6 | 1.000 | 0.610 | 0.600 | 0.90 |
| pt | `report_unrecognized_charge` | 10 | 3 | 3 | 1.000 | 0.439 | 0.300 | 0.90 |
| pt | `request_card_block` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| pt | `request_dispute` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| pt | `request_human_agent` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| en | `check_balance` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| en | `check_recent_transactions` | 10 | 4 | 4 | 1.000 | 0.510 | 0.400 | 0.90 |
| en | `confirm` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| en | `deny` | 10 | 7 | 7 | 1.000 | 0.646 | 0.700 | 0.90 |
| en | `greeting` | 10 | 9 | 9 | 1.000 | 0.701 | 0.900 | 0.90 |
| en | `out_of_scope` | 10 | 12 | 8 | 0.667 | 0.391 | 0.800 | 0.90 |
| en | `provide_identity_data` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| en | `provide_otp_code` | 10 | 5 | 5 | 1.000 | 0.566 | 0.500 | 0.90 |
| en | `report_lost_card` | 10 | 15 | 10 | 0.667 | 0.417 | 1.000 | 0.90 |
| en | `report_stolen_card` | 10 | 9 | 8 | 0.889 | 0.565 | 0.800 | 0.90 |
| en | `report_suspicious_activity` | 10 | 11 | 9 | 0.818 | 0.523 | 0.900 | 0.90 |
| en | `report_unrecognized_charge` | 10 | 6 | 5 | 0.833 | 0.436 | 0.500 | 0.90 |
| en | `request_card_block` | 10 | 8 | 8 | 1.000 | 0.676 | 0.800 | 0.90 |
| en | `request_dispute` | 10 | 7 | 6 | 0.857 | 0.487 | 0.600 | 0.90 |
| en | `request_human_agent` | 10 | 12 | 10 | 0.833 | 0.552 | 1.000 | 0.90 |
| all | `check_balance` | 30 | 21 | 20 | 0.952 | 0.773 | 0.667 | 0.90 |
| all | `check_recent_transactions` | 30 | 12 | 12 | 1.000 | 0.758 | 0.400 | 0.90 |
| all | `confirm` | 30 | 22 | 22 | 1.000 | 0.851 | 0.733 | 0.90 |
| all | `deny` | 30 | 26 | 24 | 0.923 | 0.759 | 0.800 | 0.90 |
| all | `greeting` | 30 | 25 | 24 | 0.960 | 0.805 | 0.800 | 0.90 |
| all | `out_of_scope` | 30 | 24 | 16 | 0.667 | 0.467 | 0.533 | 0.90 |
| all | `provide_identity_data` | 30 | 17 | 17 | 1.000 | 0.816 | 0.567 | 0.90 |
| all | `provide_otp_code` | 30 | 20 | 17 | 0.850 | 0.640 | 0.567 | 0.90 |
| all | `report_lost_card` | 30 | 27 | 21 | 0.778 | 0.592 | 0.700 | 0.90 |
| all | `report_stolen_card` | 30 | 27 | 24 | 0.889 | 0.719 | 0.800 | 0.90 |
| all | `report_suspicious_activity` | 30 | 25 | 23 | 0.920 | 0.750 | 0.767 | 0.90 |
| all | `report_unrecognized_charge` | 30 | 17 | 15 | 0.882 | 0.657 | 0.500 | 0.90 |
| all | `request_card_block` | 30 | 20 | 20 | 1.000 | 0.839 | 0.667 | 0.90 |
| all | `request_dispute` | 30 | 19 | 18 | 0.947 | 0.754 | 0.600 | 0.90 |
| all | `request_human_agent` | 30 | 30 | 28 | 0.933 | 0.787 | 0.933 | 0.90 |

### Certification

| Scope | Label | Correct / decided | Wilson 95% lower | Floor | Certified | Needs |
|---|---|---:|---:|---:|:---:|---|
| es | `check_balance` | 7/8 | 0.529 | 0.90 | no | 35 decided with zero errors (has 7/8) |
| pt | `check_balance` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| en | `check_balance` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| es | `check_recent_transactions` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt | `check_recent_transactions` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| en | `check_recent_transactions` | 4/4 | 0.510 | 0.90 | no | 35 decided with zero errors (has 4/4) |
| es | `confirm` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| pt | `confirm` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| en | `confirm` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| es | `deny` | 9/10 | 0.596 | 0.90 | no | 35 decided with zero errors (has 9/10) |
| pt | `deny` | 8/9 | 0.565 | 0.90 | no | 35 decided with zero errors (has 8/9) |
| en | `deny` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| es | `greeting` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| pt | `greeting` | 8/9 | 0.565 | 0.90 | no | 35 decided with zero errors (has 8/9) |
| en | `greeting` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| es | `out_of_scope` | 5/9 | 0.267 | 0.90 | no | 35 decided with zero errors (has 5/9) |
| pt | `out_of_scope` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| en | `out_of_scope` | 8/12 | 0.391 | 0.90 | no | 35 decided with zero errors (has 8/12) |
| es | `provide_identity_data` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| pt | `provide_identity_data` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| en | `provide_identity_data` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| es | `provide_otp_code` | 7/9 | 0.453 | 0.90 | no | 35 decided with zero errors (has 7/9) |
| pt | `provide_otp_code` | 5/6 | 0.436 | 0.90 | no | 35 decided with zero errors (has 5/6) |
| en | `provide_otp_code` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| es | `report_lost_card` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| pt | `report_lost_card` | 5/6 | 0.436 | 0.90 | no | 35 decided with zero errors (has 5/6) |
| en | `report_lost_card` | 10/15 | 0.417 | 0.90 | no | 35 decided with zero errors (has 10/15) |
| es | `report_stolen_card` | 10/12 | 0.552 | 0.90 | no | 35 decided with zero errors (has 10/12) |
| pt | `report_stolen_card` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| en | `report_stolen_card` | 8/9 | 0.565 | 0.90 | no | 35 decided with zero errors (has 8/9) |
| es | `report_suspicious_activity` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| pt | `report_suspicious_activity` | 6/6 | 0.610 | 0.90 | no | 35 decided with zero errors (has 6/6) |
| en | `report_suspicious_activity` | 9/11 | 0.523 | 0.90 | no | 35 decided with zero errors (has 9/11) |
| es | `report_unrecognized_charge` | 7/8 | 0.529 | 0.90 | no | 35 decided with zero errors (has 7/8) |
| pt | `report_unrecognized_charge` | 3/3 | 0.439 | 0.90 | no | 35 decided with zero errors (has 3/3) |
| en | `report_unrecognized_charge` | 5/6 | 0.436 | 0.90 | no | 35 decided with zero errors (has 5/6) |
| es | `request_card_block` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| pt | `request_card_block` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| en | `request_card_block` | 8/8 | 0.676 | 0.90 | no | 35 decided with zero errors (has 8/8) |
| es | `request_dispute` | 7/7 | 0.646 | 0.90 | no | 35 decided with zero errors (has 7/7) |
| pt | `request_dispute` | 5/5 | 0.566 | 0.90 | no | 35 decided with zero errors (has 5/5) |
| en | `request_dispute` | 6/7 | 0.487 | 0.90 | no | 35 decided with zero errors (has 6/7) |
| es | `request_human_agent` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| pt | `request_human_agent` | 9/9 | 0.701 | 0.90 | no | 35 decided with zero errors (has 9/9) |
| en | `request_human_agent` | 10/12 | 0.552 | 0.90 | no | 35 decided with zero errors (has 10/12) |

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
| `check_balance` | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 9 |
| `check_recent_transactions` | 1 | 12 | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 13 |
| `confirm` | 0 | 0 | 22 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 5 |
| `deny` | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| `greeting` | 0 | 0 | 0 | 0 | 24 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| `out_of_scope` | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 12 |
| `provide_identity_data` | 0 | 0 | 0 | 0 | 0 | 0 | 17 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| `provide_otp_code` | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 17 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| `report_lost_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 21 | 1 | 0 | 0 | 0 | 0 | 0 | 8 |
| `report_stolen_card` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 24 | 0 | 0 | 0 | 0 | 0 | 5 |
| `report_suspicious_activity` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 23 | 0 | 0 | 0 | 0 | 4 |
| `report_unrecognized_charge` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 15 | 0 | 0 | 0 | 13 |
| `request_card_block` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0 | 0 | 20 | 0 | 0 | 7 |
| `request_dispute` | 0 | 0 | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 18 | 0 | 7 |
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
    "intent_hint": {
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
        "candidate": "intent_tfidf",
        "certified": false,
        "config": {
          "path": "tools/calibrate/configs/decision_points.yaml",
          "sha256": "edf6e6fc9df724d21057df5f1ce455cc9e77755b580e7e9931d642039020ee73"
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
            "acted_coverage_test": 0.86,
            "certified": false,
            "coverage_test": 0.86,
            "coverage_val": 0.96,
            "ece_post": 0.0852,
            "ece_pre": 0.5117,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "check_balance": [
                8,
                8,
                0.6756
              ],
              "check_recent_transactions": [
                4,
                4,
                0.5101
              ],
              "confirm": [
                8,
                8,
                0.6756
              ],
              "deny": [
                7,
                7,
                0.6457
              ],
              "greeting": [
                9,
                9,
                0.7009
              ],
              "out_of_scope": [
                8,
                12,
                0.3906
              ],
              "provide_identity_data": [
                8,
                8,
                0.6756
              ],
              "provide_otp_code": [
                5,
                5,
                0.5655
              ],
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
                11,
                0.523
              ],
              "report_unrecognized_charge": [
                5,
                6,
                0.4365
              ],
              "request_card_block": [
                8,
                8,
                0.6756
              ],
              "request_dispute": [
                6,
                7,
                0.4869
              ],
              "request_human_agent": [
                10,
                12,
                0.552
              ]
            },
            "recall_test": {
              "check_balance": 0.8,
              "check_recent_transactions": 0.4,
              "confirm": 0.8,
              "deny": 0.7,
              "greeting": 0.9,
              "out_of_scope": 0.8,
              "provide_identity_data": 0.8,
              "provide_otp_code": 0.5,
              "report_lost_card": 1.0,
              "report_stolen_card": 0.8,
              "report_suspicious_activity": 0.9,
              "report_unrecognized_charge": 0.5,
              "request_card_block": 0.8,
              "request_dispute": 0.6,
              "request_human_agent": 1.0
            }
          },
          "es": {
            "acted_coverage_test": 0.7733,
            "certified": false,
            "coverage_test": 0.7733,
            "coverage_val": 0.9667,
            "ece_post": 0.0862,
            "ece_pre": 0.4909,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "check_balance": [
                7,
                8,
                0.5291
              ],
              "check_recent_transactions": [
                5,
                5,
                0.5655
              ],
              "confirm": [
                7,
                7,
                0.6457
              ],
              "deny": [
                9,
                10,
                0.5958
              ],
              "greeting": [
                7,
                7,
                0.6457
              ],
              "out_of_scope": [
                5,
                9,
                0.2667
              ],
              "provide_identity_data": [
                6,
                6,
                0.6097
              ],
              "provide_otp_code": [
                7,
                9,
                0.4526
              ],
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
              "check_balance": 0.7,
              "check_recent_transactions": 0.5,
              "confirm": 0.7,
              "deny": 0.9,
              "greeting": 0.7,
              "out_of_scope": 0.5,
              "provide_identity_data": 0.6,
              "provide_otp_code": 0.7,
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
            "acted_coverage_test": 0.58,
            "certified": false,
            "coverage_test": 0.58,
            "coverage_val": 0.74,
            "ece_post": 0.0642,
            "ece_pre": 0.5191,
            "n_test": 150,
            "n_val": 150,
            "precision_test": {
              "check_balance": [
                5,
                5,
                0.5655
              ],
              "check_recent_transactions": [
                3,
                3,
                0.4385
              ],
              "confirm": [
                7,
                7,
                0.6457
              ],
              "deny": [
                8,
                9,
                0.565
              ],
              "greeting": [
                8,
                9,
                0.565
              ],
              "out_of_scope": [
                3,
                3,
                0.4385
              ],
              "provide_identity_data": [
                3,
                3,
                0.4385
              ],
              "provide_otp_code": [
                5,
                6,
                0.4365
              ],
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
              "check_balance": 0.5,
              "check_recent_transactions": 0.3,
              "confirm": 0.7,
              "deny": 0.8,
              "greeting": 0.8,
              "out_of_scope": 0.3,
              "provide_identity_data": 0.3,
              "provide_otp_code": 0.5,
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
        "report": "reports/calibration-decision-points-2026-10-01-clarify_route+intent_hint.md",
        "run_id": "92e65dc2487d",
        "split": "test",
        "uncovered": []
      },
      "status": "calibrated",
      "thresholds": {
        "en": 0.531773,
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
- [ ] Constraint met on test with the Wilson bound (0 of 45 scopes clear the Wilson bound); otherwise the shortfall belongs in `docs/limitations.md`.
- [x] ECE after calibration <= 0.10 on test in every language.
- [x] p95 inside the DP's `timeout_ms` (RAM 49.3 MB; the encoder's memory floor is checked by the service at startup).
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
- **Backend:** `intent_tfidf` (`tfidf_lr@train-sha256:a563c0c445d6`), `tfidf_lr`, distribution
- **CPU latency (single text, host):** p50 0.16 ms, p95 0.22 ms (budget `timeout_ms` 200); RAM model+inference 49.3 MB
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
    "clarify_route": {
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
          "sha256": "edf6e6fc9df724d21057df5f1ce455cc9e77755b580e7e9931d642039020ee73"
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
        "report": "reports/calibration-decision-points-2026-10-01-clarify_route+intent_hint.md",
        "run_id": "92e65dc2487d",
        "split": "test",
        "uncovered": []
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
- [x] p95 inside the DP's `timeout_ms` (RAM 49.3 MB; the encoder's memory floor is checked by the service at startup).
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
