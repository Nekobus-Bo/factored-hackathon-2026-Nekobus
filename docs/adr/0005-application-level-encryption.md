# ADR-0005: Application-level encryption with a blind index

**Status:** Accepted · **Date:** 2026-09-26 · **Deciders:** TODO (team)

## Context

We store personal data (document number, phone, email, date of birth) and conversation transcripts containing sensitive information. We need encryption at rest without losing the ability to **search** by document or phone, which is exactly the first step of identity verification.

## Decision

- **Application-level encryption**, in `banking-core`, with per-field AES-GCM and envelope encryption (a data key per conversation or record, protected by a master key held outside the database).
- **Blind index** for searchable fields: HMAC-SHA256 with a per-field salt, stored in a separate indexed column. Enables exact-match lookup without decrypting.
- Transcripts are encrypted with a per-conversation data key.

## Options considered

### Option A: pgcrypto (encryption inside the database)

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Security | Medium-low |
| Performance | Medium |

**Pros:** little code; encryption and querying in the same place.
**Cons:** the key travels inside the SQL statement, which exposes it in logs and in query statistics; whoever compromises the database is usually also positioned to see statements. Key rotation means rewriting data from SQL.

### Option B (chosen): application-level encryption + blind index

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Security | High: the key never enters the database blast radius |
| Performance | Good; the blind index is an ordinary indexed lookup |

**Pros:** real separation of duties; rotation via envelope encryption; encryption sits on the side that already holds the authorization logic.
**Cons:** it has to be implemented and tested; the blind index only solves exact match, not partial search; a mishandled salt makes it vulnerable to dictionary attacks.

### Option C: disk encryption / TDE

**Pros:** transparent.
**Cons:** protects against volume theft, not against logical database access, which is the threat we care about. Not mutually exclusive: it complements.

### Option D: no encryption in a demo environment

Rejected. The data is synthetic, but the criterion being evaluated is whether the design would work in production.

## Trade-off analysis

Option A is three to five times cheaper in time. We still chose B because the difference is not marginal robustness but **threat model**: with pgcrypto, compromising the database tends to mean compromising the key. For a banking case, that distinction is exactly what a technical reviewer will look for.

We accept the blind index's exact-match limitation: our searchable fields are identifiers, not free text.

## Consequences

**Becomes easier:** rotating keys; sustaining the privacy argument; separating the database administrator role from access to personal data.

**Becomes harder:** analytics cannot read encrypted fields — they work on aggregated or pseudonymized views; debugging in the database requires going through the application.

**To revisit:** key management. In this submission the master key comes from the environment; in production it belongs in a KMS or HSM. Documented in `limitations.md`.

## Action items

1. [ ] Per-field encrypt/decrypt utilities with data keys
2. [ ] Blind index with per-field salt for document, phone and email
3. [ ] Analytics over pseudonymized views
4. [ ] Test: no personal data in cleartext in a database dump
