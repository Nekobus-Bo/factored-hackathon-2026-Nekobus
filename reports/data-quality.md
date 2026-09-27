# Data Quality Report

**Generated:** 2026-09-27 12:33:06 UTC  
**Pipeline Version:** `v0.1.0`  
**Environment:** Seed Pipeline (`banking_core.seed`)  
**Dataset Origin:** Deterministic synthetic sample (`seed=42`)  

## 1. Summary Volumes

| Entity | Total Records | Data Origin | Source Format |
|---|---|---|---|
| `core_bank.customer` | 300 | synthetic | JSONL (`data/raw/synthetic/customers.jsonl`) |
| `core_bank.account` | 399 | synthetic | JSONL (`data/raw/synthetic/accounts.jsonl`) |
| `core_bank.card` | 690 | synthetic | JSONL (`data/raw/synthetic/cards.jsonl`) |
| `core_bank.transaction` | 14,719 | synthetic | JSONL (`data/raw/synthetic/transactions.jsonl`) |

## 2. Distribution by Locale

| Locale | Language | Currency | Customers | Accounts | Cards | Transactions |
|---|---|---|---|---|---|---|
| `es` | Spanish (Colombia) | COP | 100 | 129 | 218 | 4,891 |
| `pt` | Portuguese (Brazil) | BRL | 100 | 137 | 250 | 4,905 |
| `en` | English (United States) | USD | 100 | 133 | 222 | 4,923 |
| **Total** | - | - | **300** | **399** | **690** | **14,719** |

## 3. Staging Validation Checklist (docs/data.md §3)

| Check Category | Description | Status | Fail-Loud Policy |
|---|---|---|---|
| **Schema and Types** | Pydantic strict typing, non-empty fields, valid enum instances | ✅ PASS | `StagingValidationError` naming table and field |
| **Keys and Uniqueness** | Unique primary keys, unique card references, unique `(document_type, document_number)` | ✅ PASS | `StagingValidationError` on duplicate key detection |
| **Referential Integrity** | Accounts link to Customers, Cards to Accounts, Transactions to Accounts & Cards | ✅ PASS | `StagingValidationError` on orphan foreign keys |
| **Ranges and Domains** | Locales in `es|pt|en`, ISO 4217 match, E.164 phones, tx in last 120 days | ✅ PASS | `StagingValidationError` on out-of-bounds values |
| **Completeness** | Zero nulls on required columns; controlled nulls only on optional attributes | ✅ PASS | `StagingValidationError` on unexpected null counts |

## 4. Completeness and Null Analysis

### Customers (`core_bank.customer`)

| Field | Non-Null Count | Null Count | Null % | Expected Null Policy |
|---|---|---|---|---|
| `id` | 300 | 0 | 0.0% | Mandatory (0%) |
| `document_type` | 300 | 0 | 0.0% | Mandatory (0%) |
| `document_number` | 300 | 0 | 0.0% | Mandatory (0%) |
| `full_name` | 300 | 0 | 0.0% | Mandatory (0%) |
| `email` | 300 | 0 | 0.0% | Mandatory (0%) |
| `phone` | 300 | 0 | 0.0% | Mandatory (0%) |
| `birth_date` | 300 | 0 | 0.0% | Mandatory (0%) |
| `preferred_locale` | 300 | 0 | 0.0% | Mandatory (0%) |
| `registered_otp_channel` | 300 | 0 | 0.0% | Mandatory (0%) |

### Accounts (`core_bank.account`)

| Field | Non-Null Count | Null Count | Null % | Expected Null Policy |
|---|---|---|---|---|
| `id` | 399 | 0 | 0.0% | Mandatory (0%) |
| `customer_id` | 399 | 0 | 0.0% | Mandatory (0%) |
| `type` | 399 | 0 | 0.0% | Mandatory (0%) |
| `currency` | 399 | 0 | 0.0% | Mandatory (0%) |
| `available_balance_minor` | 399 | 0 | 0.0% | Mandatory (0%) |
| `ledger_balance_minor` | 399 | 0 | 0.0% | Mandatory (0%) |
| `status` | 399 | 0 | 0.0% | Mandatory (0%) |

### Cards (`core_bank.card`)

| Field | Non-Null Count | Null Count | Null % | Expected Null Policy |
|---|---|---|---|---|
| `id` | 690 | 0 | 0.0% | Mandatory (0%) |
| `account_id` | 690 | 0 | 0.0% | Mandatory (0%) |
| `card_ref` | 690 | 0 | 0.0% | Mandatory (0%) |
| `pan` | 690 | 0 | 0.0% | Mandatory (0%) |
| `pan_last4` | 690 | 0 | 0.0% | Mandatory (0%) |
| `brand` | 690 | 0 | 0.0% | Mandatory (0%) |
| `status` | 690 | 0 | 0.0% | Mandatory (0%) |
| `blocked_at` | 20 | 670 | 97.1% | Nullable when status=ACTIVE |
| `blocked_reason` | 20 | 670 | 97.1% | Nullable when status=ACTIVE |

### Transactions (`core_bank.transaction`)

| Field | Non-Null Count | Null Count | Null % | Expected Null Policy |
|---|---|---|---|---|
| `id` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `account_id` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `card_id` | 13,331 | 1,388 | 9.4% | Nullable for non-card wire/account transfers (~10%) |
| `amount_minor` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `currency` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `merchant` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `mcc` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `occurred_at` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `status` | 14,719 | 0 | 0.0% | Mandatory (0%) |
| `dispute_eligible` | 14,719 | 0 | 0.0% | Mandatory (0%) |

## 5. Intentionally Not Cleaned (docs/data.md §3)

In accordance with repository guidelines, the following attributes contain non-standard or partial values intentionally, with reasoned justification:

1. **Transactions with Null `card_id` (~10% of total volume)**:
   - **Reasoning**: In retail banking, non-card transactions (e.g. direct ACH debits, bill payments, account-to-account transfers) belong to an account but have no associated physical/virtual card.
   - **Handling**: Validated by referential integrity that `account_id` is present and valid; `card_id` is legitimately `NULL`.

2. **Cards in `BLOCKED` Status with Populated `blocked_reason`**:
   - **Reasoning**: Compromised or customer-reported blocked cards must retain their historical blockage timestamp and reason (`LOST`, `STOLEN`, `SUSPICIOUS_ACTIVITY`) to test guardrail behavior and FSM transitions.
   - **Handling**: Staging validation strictly enforces that `blocked_at` and `blocked_reason` are present if and only if `status == 'BLOCKED'`.

3. **Customers with `registered_otp_channel = 'NONE'` (Escalation Fixtures)**:
   - **Reasoning**: To verify that the orchestrator and banking-core FSM correctly escalate to a human backoffice ticket when a customer cannot complete automated out-of-band authentication.
   - **Handling**: Explicitly included in the deterministic scenario fixtures.

4. **Lineage and Origin Tracking**:
   - **Reasoning**: All generated records carry `data_origin = 'synthetic'`, `source_ref = 'synthetic/*.jsonl'`, `loaded_at`, and `code_version = 'v0.1.0'` to provide auditability and clear separation from any future organization dataset.
