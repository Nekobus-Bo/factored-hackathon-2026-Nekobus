# Knowledge Base (KB) Content

Curated, multi-lingual knowledge base for the simulated bank. This directory contains the authoritative policy snippets queried by the retrieval service (hybrid BM25 + `pgvector` dense search, conditional on beating the BM25 baseline) and evaluated by the embedding calibration harness ([ADR-0006](../../../docs/adr/0006-single-postgres-pgvector.md), [ADR-0010](../../../docs/adr/0010-model-selection-calibration-harness.md)).

## 1. What This Is

The knowledge base provides factual customer service guidance for the core banking workflows, including:
- Card security, emergency precautionary blocking, and verified receipts
- Reporting lost vs. stolen cards
- Unrecognized transactions, fraud reporting, and billing descriptors
- Dispute, claim, and chargeback procedures (managed exclusively by human analysts)
- Identity verification and OTP authentication rules
- Session lockouts and structured human agent handoff
- Secondary read-only inquiries (balance and recent transactions)
- Phishing, security hygiene, and privacy/PII masking policies

All snippets represent the simulated bank's actual operating policies, reflecting deterministic system invariants: precautionary blocks are reversible and return verified receipts, disputes are never decided autonomously by AI, unblocking requires human verification, and the assistant never picks the OTP delivery channel.

Adoption of dense vector retrieval alongside sparse search (hybrid retrieval) is strictly conditional on dense embeddings outperforming the BM25 keyword baseline in benchmark evaluation ([ADR-0006](../../../docs/adr/0006-single-postgres-pgvector.md)).

## 2. Structure & ID Convention

Snippets are stored in `packages/retrieval/kb/snippets.jsonl`. Each line is an independent JSON object with the following schema:

```json
{
  "id": "card_security.01.es",
  "topic_id": "card_security.01",
  "lang": "es",
  "title": "Bloqueo preventivo de tarjeta",
  "text": "Si sospecha que su tarjeta ha sido comprometida..."
}
```

### Identifier Breakdown

- `topic_id` (`<category>.<nn>`): The semantic policy topic (e.g. `card_security.01`, `disputes.02`, `auth_identity.03`).
- `id` (`<topic_id>.<lang>`): Unique snippet identifier composed of the topic ID and language code (e.g. `card_security.01.es`, `card_security.01.pt`, `card_security.01.en`).
- `lang`: Customer language code (`es`, `pt`, or `en`).

### Cross-Language Alignment

Every `topic_id` exists in all three supported languages (`es`, `pt`, and `en`). The snippets across languages for a given `topic_id` represent direct semantic counterparts of the same policy. This enables rigorous benchmarking of multilingual retrieval, specifically:
- Monolingual query matching (e.g., Spanish query $\to$ Spanish policy snippet).
- Cross-language retrieval performance (e.g., evaluating whether a Portuguese or Spanish customer query successfully retrieves the relevant English policy snippet, and vice-versa).

## 3. Seeded as Configuration (ADR-0002)

In accordance with [ADR-0002 (Boundary between configuration and code)](../../../docs/adr/0002-config-code-boundary.md), knowledge base content is **configuration, not code**:
- Policies do not live inside model system prompts.
- `snippets.jsonl` is the source of truth for all bank policy knowledge.
- In the current evaluation harness, retrieval evaluates snippets indexed directly in memory.
- ⚠️ **Pending:** Seeding `snippets.jsonl` into a PostgreSQL `knowledge_snippets` table via `make seed` and an ingestion step that persists dense embeddings in `pgvector` are pending implementation for full database deployment.
- As noted in [ADR-0006](../../../docs/adr/0006-single-postgres-pgvector.md), dense embedding storage in PostgreSQL/`pgvector` and hybrid retrieval will only be enabled if calibration confirms that dense vectors outperform the BM25 baseline.
- Changes to bank policies, contact details, or thresholds require updating this configuration file and re-seeding, without requiring application code changes or model prompt alterations.

## 4. How to Add a Snippet

When adding a new policy or updating an existing topic:

1. **Identify or create the topic:**
   - If extending an existing topic, maintain its `topic_id`.
   - If adding a new policy, choose the appropriate category (`card_security`, `fraud_reporting`, `disputes`, `auth_identity`, `support_handoff`, `account_inquiry`, `security_privacy`) and allocate the next sequential number (e.g., `card_security.09`).
2. **Author in all three languages:**
   - Write parallel entries for Spanish (`es`), Portuguese (`pt`), and English (`en`).
   - Maintain length between **40 and 120 words** per snippet for optimal vector chunking and BM25 token distribution.
3. **Enforce factual system constraints:**
   - **Bank name:** Use generic placeholders ("the bank" / "el banco" / "o banco") as the fintech trade name is configurable.
   - **No real third-party entities:** Do not use real bank names, real customer phone numbers, or external URLs. Use `example.com` for links.
   - **No empty promises (AGENTS rule 7):** Do not promise capabilities not supported by the system (e.g. automated chargeback grants or self-service biometric unblocking).
4. **Append to `snippets.jsonl`:**
   - Ensure the file remains valid JSON Lines format.
   - Verify that all `id` attributes are strictly unique.
