# Deployment Architecture, Scalability & Configurability

This document details how Pattern Blue is deployed, how data isolation and credential boundaries are enforced, how the system is reconfigured across environments, and its current scaling limits.

All descriptions reflect **what exists on `main`**. Any planned capability or script is explicitly marked `⚠️ pending`.

---

## 1. Target Architecture & Trust Boundaries

The system separates conversational orchestration from banking operations across a strict trust boundary ([ADR-0004](adr/0004-trust-boundary.md)). The orchestrator runs in the untrusted zone and has no access to the database or core session state; `banking-core` runs in the trusted zone and dispatches all sensitive operations.

```mermaid
flowchart TD
    subgraph HostData ["Host Data Layer (Internal Network Only)"]
        PG[("PostgreSQL 17 + pgvector<br/>DB: bank · Role: app<br/>pg_hba: Docker subnet only")]
        subgraph RedisInstance ["Host Redis Instance (Redis 6+ ACL)"]
            RC["ACL: core-svc<br/>~session:* ~otp:*"]
            RE["ACL: edge-svc<br/>~orch:*"]
        end
    end

    subgraph AppStack ["Docker compose networks (core / edge)"]
        subgraph TrustedZone ["Trusted Zone"]
            CORE["banking-core<br/>(tools, FSM, policies, audit)"]
            MIG["migrate / seed<br/>(one-off tasks)"]
        end

        subgraph UntrustedZone ["Untrusted Zone"]
            ORC["orchestrator<br/>(chat API, turn engine, PII masking)"]
            ENC["encoder<br/>(local CPU inference)"]
        end
    end

    EXT[External Traffic] -->|HTTP :8080| ORC
    ORC -->|HTTP /v1/analyze| ENC
    ORC -->|HTTP /v1/tools/call| CORE
    CORE -->|DATABASE_URL| PG
    MIG -->|DATABASE_URL| PG
    CORE -->|REDIS_CORE_URL (core-svc)| RC
    ORC -->|REDIS_EDGE_URL (edge-svc)| RE

    classDef trusted fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef untrusted fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    classDef data fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;

    class CORE,MIG trusted;
    class ORC,ENC untrusted;
    class PG,RedisInstance,RC,RE data;
```

### Recommended Architecture (Production)

1. **PostgreSQL 17:**
   - Dedicated database (e.g. `bank`) and dedicated role (e.g. `app`) used exclusively by `banking-core` (and one-off `migrate`/`seed` tasks).
   - `pgvector` extension enabled inside that database ([ADR-0006](adr/0006-single-postgres-pgvector.md)).
   - Reachable **only internally** (no public/external port binding).
   - In `pg_hba.conf`, access is restricted to the Docker bridge network subnet (e.g. `172.17.0.0/16` or host Docker subnet) with scram-sha-256 password authentication.
   - The orchestrator never receives `DATABASE_URL` or PostgreSQL credentials.

2. **Redis 7 (ACL Segmentation):**
   - A single Redis instance partitioned using Redis 6+ Access Control Lists (ACLs).
   - Reachable **only internally** (no public/external port binding).
   - Two distinct ACL accounts with minimal command sets and strictly segmented key patterns:
     - **`core-svc`:** restricted to keys matching `~session:*` and `~otp:*`. Used only by `banking-core` for distributed session locking, FSM state, and OTP challenge verification.
     - **`edge-svc`:** restricted to keys matching `~orch:*`. Used only by `orchestrator` for encrypted conversation state caching and turn locks.
   - The orchestrator never receives `REDIS_CORE_URL` or credentials for the `core-svc` account.

3. **Application Stack:**
   - Containers run with dropped capabilities (`cap_drop: [ALL]`), `no-new-privileges:true`, and read-only root filesystems (`read_only: true` with temporary `/tmp` tmpfs mounts).
   - In production compose, `banking-core` and `encoder` expose no host ports. Only the `orchestrator` port (`8080`) is exposed (or placed behind an ingress reverse proxy).

### Internal Test Environment Deviation (The Project's VPS)

The internal test environment (the project's VPS) exposes the test Postgres/Redis for direct inspection; they hold no sensitive data:
- Both PostgreSQL and Redis are bound to external ports on the internal test environment host.
- **Rationale:** This deliberate exception allows the engineering team to directly inspect the test database tables, audit log chains, and Redis session keys during evaluation without jumping through container proxies.
- **Security posture:** The databases on the internal test environment hold synthetic test data only; no real customer PII or production secrets are stored.
- This deviation is recorded as a declared limitation in [docs/limitations.md](limitations.md).

---

## 2. Redis ACL Command Sets & Configuration

Both `banking-core` and `orchestrator` rely on Redis transactions and atomic operations. An ACL that omits transaction commands breaks distributed locks and causes turn saves to fail.

The required command sets derived from the codebase:

| Service | User | Key Patterns | Code References | Required Redis Commands |
|---|---|---|---|---|
| `banking-core` | `core-svc` | `~session:* ~otp:*` | `control/session.py`<br/>`identity/challenge_store.py` | `PING`, `GET`, `SET`, `DEL`, `INCR`, `EXPIRE`, `WATCH`, `MULTI`, `EXEC`, `UNWATCH` |
| `orchestrator` | `edge-svc` | `~orch:*` | `session/store.py` | `PING`, `GET`, `SET`, `DEL`, `WATCH`, `MULTI`, `EXEC`, `UNWATCH` |

### Why Transaction Commands Are Mandatory

1. **`banking-core` session store:** Uses `WATCH` / `MULTI` / `EXEC` for optimistic concurrency during state transitions (`atomic_update`), and `SET ... NX PX` plus a `WATCH`/`GET`/`DEL` pipeline to safely release per-session locks without clearing locks acquired by succeeding callers.
2. **`banking-core` challenge store:** Uses `INCR` and `EXPIRE` on `otp:challenge:<id>:evaluations` to atomically count attempts before verifying HMAC hashes, and `DEL` to invalidate challenges.
3. **`orchestrator` session store:** Uses `save_fenced` which wraps `WATCH` on the turn lock key, checks ownership, and writes state atomically with `MULTI` / `SET ... EX` / `EXEC`. Lock release similarly depends on `WATCH` / `MULTI` / `DEL` / `EXEC`.

If `WATCH`, `MULTI`, `EXEC`, or `UNWATCH` are omitted from the ACL, Redis returns `NOPERM` and operations fail.

### Exact Redis ACL Setup (`ACL SETUSER`)

Execute these commands in `redis-cli` on the host Redis instance:

```text
ACL SETUSER core-svc reset on >REPLACE_WITH_CORE_REDIS_PASSWORD ~session:* ~otp:* -@all +ping +get +set +del +incr +expire +watch +multi +exec +unwatch
ACL SETUSER edge-svc reset on >REPLACE_WITH_EDGE_REDIS_PASSWORD ~orch:* -@all +ping +get +set +del +watch +multi +exec +unwatch
```

Ensure the key prefix variables in `.env` match these patterns:
- `REDIS_SESSION_KEY_PREFIX=session:` (covered by `~session:*`)
- `REDIS_OTP_CHALLENGE_KEY_PREFIX=otp:challenge:` (covered by `~otp:*`)
- `REDIS_EDGE_KEY_PREFIX=orch:conv:` (covered by `~orch:*`)

---

## 3. Production Compose Configuration

Production deployment layers `infra/compose/docker-compose.prod.yml` over `infra/compose/docker-compose.yml`.

### Deployment Modes

#### 1. Host Data Mode (Default Production)
By default, `docker-compose.prod.yml` sets `profiles: ["bundled-data"]` on containerized `postgres`, `redis-core`, and `redis-edge`. They do not start unless the profile is activated.

The stack connects to PostgreSQL and Redis running on the host system via `host.docker.internal:host-gateway`.

```bash
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               up -d --wait
```

#### 2. Bundled Data Mode (Self-Contained Evaluation)
To run the full stack with containerized PostgreSQL and Redis under production security controls (read-only filesystems, prebuilt images, registry tags):

```bash
docker compose --profile bundled-data \
               -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               up -d --wait
```

### Environment Variables Matrix

The production compose override enforces explicit configuration without development defaults:

| Variable | Description | Services Consuming | Example Value |
|---|---|---|---|
| `REGISTRY` | Container registry prefix | `migrate`, `seed`, `banking-core`, `orchestrator`, `encoder` | `ghcr.io/org` |
| `IMAGE_TAG` | Image release version / commit SHA | `migrate`, `seed`, `banking-core`, `orchestrator`, `encoder` | `v1.0.0` or git SHA |
| `DATABASE_URL` | PostgreSQL connection URL (psycopg format) | `migrate`, `seed`, `banking-core` | `postgresql+psycopg://app:pass@host.docker.internal:5432/bank` |
| `REDIS_CORE_URL` | Redis URL for banking-core (`core-svc`) | `banking-core` | `redis://core-svc:pass@host.docker.internal:6379/0` |
| `REDIS_EDGE_URL` | Redis URL for orchestrator (`edge-svc`) | `orchestrator` | `redis://edge-svc:pass@host.docker.internal:6379/0` |
| `MASTER_KEY` | Master key for application-level encryption | `seed`, `banking-core` | 32-byte base64/hex secret |
| `BLIND_INDEX_SALT` | Salt for deterministic blind indexing | `seed`, `banking-core` | 32-byte secret |
| `SESSION_SECRET` | Secret key for conversation placeholder encryption | `orchestrator` | 32-byte secret |
| `BANKING_CORE_MEMORY_LIMIT` | Container memory limit for banking-core | `banking-core` | `2g` |
| `ENCODER_MEMORY_LIMIT` | Container memory limit for encoder | `encoder` | `3g` (default) or `4g` (`gliner`) |

### Trust Boundary Verification

Run this check against rendered Compose configuration to assert that the orchestrator receives neither PostgreSQL credentials nor core Redis URLs:

```bash
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               config --format json | python3 -c '
import json, sys
env = json.load(sys.stdin)["services"]["orchestrator"]["environment"]
assert not {"DATABASE_URL", "REDIS_CORE_URL", "POSTGRES_PASSWORD"} & env.keys(), "Trust boundary breached!"
print("Trust boundary verified: orchestrator has no core data credentials.")
'
```

---

## 4. Scalability & Configurability

### (a) Pure Environment Configuration vs. Runtime Database Configuration

The system enforces a clear separation between infrastructure plumbing and business behavior ([ADR-0002](adr/0002-config-code-boundary.md)):

```
Infrastructure Plumbing (.env / Container Environment)
  ├── DATABASE_URL, REDIS_CORE_URL, REDIS_EDGE_URL
  ├── MASTER_KEY, BLIND_INDEX_SALT, SESSION_SECRET
  ├── ENCODER_BACKEND, ENCODER_MODEL, ABSTENTION_THRESHOLD
  ├── EMBEDDING_MODEL, RETRIEVAL_MODE
  └── LLM_MODE, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY
        │
        ▼ (Seed only on initial boot)
Dynamic Business Rules (PostgreSQL `config` schema & Admin API)
  ├── Risk thresholds per currency (minor units)
  ├── Policy evaluation mode (flag vs block)
  └── Allowed tool dispatch matrices per FSM state
```

1. **Pure Environment (`.env`):**
   - **Data connectivity:** Plugging your own external PostgreSQL (`DATABASE_URL`, pgvector extension required) or Redis instances (`REDIS_CORE_URL`, `REDIS_EDGE_URL` supporting `redis://` or `rediss://` with username, password, port and TLS; use database 0, or add `+select` to both ACL users if you pick another DB number).
   - **Key prefixes:** Overriding `REDIS_SESSION_KEY_PREFIX`, `REDIS_OTP_CHALLENGE_KEY_PREFIX`, and `REDIS_EDGE_KEY_PREFIX`.
   - **Model selection:** Switching encoder backends (`ENCODER_BACKEND=tfidf_lr|gliner`), calibration abstention threshold (`ABSTENTION_THRESHOLD`), embedding models (`EMBEDDING_MODEL`), and retrieval modes (`RETRIEVAL_MODE=vector|bm25|hybrid`).
   - **LLM engine:** Switching between deterministic `replay` and live provider (`live`), model names (`LLM_MODEL`), base URLs, and timeouts.
   - **Resource caps:** Memory ceilings (`BANKING_CORE_MEMORY_LIMIT`, `ENCODER_MEMORY_LIMIT`).

2. **Database Runtime Configuration:**
   - Policy thresholds (`POLICY_SEED_THRESHOLDS_MINOR`), action modes (`POLICY_SEED_AMOUNT_MODE`), and verification policies are **not constants in code**.
   - The environment variables only seed initial values into PostgreSQL tables on first boot.
   - Active policies reside in the database and can be queried and modified at runtime via the banking-core Admin API (`GET` / `PUT /v1/admin/policy-config`, authenticated via bearer token when `ADMIN_API_ENABLED=true`), with zero service restart or redeployment.

3. **Managed Cloud Services Note (⚠️ Pending Validation):**
   - Any PostgreSQL instance with `pgvector` via `DATABASE_URL` and any Redis instance with ACL/TLS via `REDIS_CORE_URL` / `REDIS_EDGE_URL` (`rediss://`) are supported purely by configuration.
   - Marked **not yet exercised against a managed service**; public cloud deployment (e.g. AWS) remains pending (ADR rule 7: not described as existing).

### (b) Horizontal Scaling & Statelessness

The application services are architecturally stateless:
- **`orchestrator`:** Holds no local state. Conversation transcripts and masked placeholder maps are stored in Redis (`edge-svc`). Turn execution is serialized via Redis turn locks (`acquire_turn_lock`), and writes are fenced against token expiration (`save_fenced`).
- **`banking-core`:** Holds no local state. FSM verification states, attempt counters, and OTP challenge hashes reside in Redis (`core-svc`). Domain entities and append-only audit chains reside in PostgreSQL. Tool invocations acquire an exclusive per-session distributed lock (`lock` with `nx=True, px=...`).
- **Idempotency:** Tool invocations accept an `idempotency_key`, preventing duplicate card blocks or dispute actions across retries.

> [!WARNING]
> **Load Testing & Multi-Replica Status:** While the data structures, distributed locks, and idempotency guarantees are engineered for multiple replicas, the system **has not been load-tested or run with more than one replica**. Production operations currently run as single-instance deployments.

### (c) Resource Footprint & Operational Limits

| Component | Operational Ceiling / Limit | Notes |
|---|---|---|
| `banking-core` per-replica RAM | ~1.3 GB RSS added at startup (`BANKING_CORE_MEMORY_LIMIT=2g`) | Loads `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` and indexes the 120-snippet Knowledge Base in RAM on boot. Database `pgvector` table ingestion is pending. |
| `encoder` (`tfidf_lr`) | ~43 MB model footprint, < 500 MB total container RSS | Default fast lexical classifier on CPU. Runs easily within `ENCODER_MEMORY_LIMIT=3g`. |
| `encoder` (`gliner`) | ~3.45 GB peak RSS (`ENCODER_MEMORY_LIMIT=4g`) | Requires `ENCODER_GLINER_MIN_MEMORY_MB=4096`. **Not used on the VPS** due to resource constraints. |
| One-off tasks (`migrate`, `seed`) | Run once per deployment | Database migrations and initial seed run as separate execution tasks, never concurrently per replica. |
| Audit log verification | Linear verification over hash chain | Hash chain integrity is verified via `make verify-audit`. Tail truncation checkpointing to an external store remains pending. |

---

## 5. Deployment Commands & Verification

Commands available in the repository:

```bash
# Validate production compose syntax and environment interpolation
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               config

# Apply database migrations against target database
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               run --rm migrate

# Health check across running services
make smoke

# Verify audit log cryptographic integrity
make verify-audit
```

Automated production deployment automation via `make deploy` is currently `⚠️ pending`.
