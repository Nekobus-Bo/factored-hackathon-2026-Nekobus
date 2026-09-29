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
            RC["ACL: core-svc<br/>~session:* ~otp:* ~limit:*"]
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
     - **`core-svc`:** restricted to keys matching `~session:*`, `~otp:*` and `~limit:*`. Used only by `banking-core` for distributed session locking, FSM state, OTP challenge verification, the simulated OTP inbox (`otp:inbox:*`, [ADR-0007](adr/0007-no-llm-biometrics.md)), and the cross-session attempt limits (per-customer OTP lock, per-document match counters).
     - **`edge-svc`:** restricted to keys matching `~orch:*`. Used only by `orchestrator` for encrypted conversation state caching and turn locks.
   - The orchestrator never receives `REDIS_CORE_URL` or credentials for the `core-svc` account.

3. **Application Stack:**
   - Containers run with dropped capabilities (`cap_drop: [ALL]`), `no-new-privileges:true`, and read-only root filesystems (`read_only: true` with temporary `/tmp` tmpfs mounts).
   - In production compose, `banking-core` and `encoder` expose no host ports. Only the `orchestrator` port (`8080`) is exposed (or placed behind an ingress reverse proxy).
   - **Client addresses behind a reverse proxy:** `POST /v1/conversations` is limited per client address (`RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR`; 30 per hour in production, 1000 in the development compose). The address is the connection peer unless `TRUSTED_PROXY_HOPS` says how many reverse proxies stand in front; the default, `0`, ignores `X-Forwarded-For` so a client cannot pick its own bucket. Behind an ingress proxy that appends the address it saw (nginx `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`), set `TRUSTED_PROXY_HOPS=1` (one more per extra proxy). **Left at `0` behind a proxy, every customer shares the proxy's address and its budget, and once it is spent nobody can open a conversation until the hour ends.** Set it higher than the real number and the extra entries are client-supplied, so the limit can be evaded. The orchestrator stores only a keyed hash of the address.

---

## 2. Redis ACL Command Sets & Configuration

Both `banking-core` and `orchestrator` rely on Redis transactions and atomic operations. An ACL that omits transaction commands breaks distributed locks and causes turn saves to fail.

The required command sets derived from the codebase:

| Service | User | Key Patterns | Code References | Required Redis Commands |
|---|---|---|---|---|
| `banking-core` | `core-svc` | `~session:* ~otp:* ~limit:*` | `control/session.py`<br/>`identity/challenge_store.py`<br/>`identity/simulated_inbox.py`<br/>`control/attempt_limits.py` | `PING`, `GET`, `SET`, `DEL`, `INCR`, `INCRBY`, `EXPIRE`, `WATCH`, `MULTI`, `EXEC`, `UNWATCH` |
| `orchestrator` | `edge-svc` | `~orch:*` | `session/store.py`<br/>`session/rate_limit.py` | `PING`, `GET`, `SET`, `DEL`, `INCR`, `INCRBY`, `EXPIRE`, `WATCH`, `MULTI`, `EXEC`, `UNWATCH` |

### Why Transaction Commands Are Mandatory

1. **`banking-core` session store:** Uses `WATCH` / `MULTI` / `EXEC` for optimistic concurrency during state transitions (`atomic_update`), and `SET ... NX PX` plus a `WATCH`/`GET`/`DEL` pipeline to safely release per-session locks without clearing locks acquired by succeeding callers.
2. **`banking-core` challenge store:** Uses `INCR` and `EXPIRE` on `otp:challenge:<id>:evaluations` to atomically count attempts before verifying HMAC hashes, and `DEL` to invalidate challenges. redis-py sends `INCR` as `INCRBY key 1`, so `+incrby` is required: an ACL with `+incr` alone fails every `otp.verify` with `NOPERM`.
3. **`banking-core` attempt limits:** `control/attempt_limits.py` creates a fixed-window counter with `SET key 0 NX EX <window>` and `INCR` in one `MULTI`, reads locks with `GET`, sets them with `SET NX EX`, and gives a successful match's count back with `WATCH` / `GET` / `MULTI` / `SET XX KEEPTTL` / `EXEC`. It needs no command beyond the set above; only the key pattern `~limit:*` is new.
4. **`banking-core` simulated OTP inbox:** `identity/simulated_inbox.py` keeps one entry per challenge (`otp:inbox:challenge:<challenge_id>`, `SET ... EX <challenge TTL>`) and a small index of a session's challenge ids (`otp:inbox:session:<session_id>`, at most 10) so an inbox can be listed. The index is rewritten with `WATCH` / `GET` / `MULTI` / `SET EX` / `DEL` / `EXEC`. It never uses `SCAN`, `KEYS`, `MGET` or sorted sets, which the `core-svc` ACL does not grant. **The entry holds the clear OTP code** (the challenge store keeps only an HMAC): that is the simulated delivery, and it lives for the challenge TTL (`OTP_TTL_SECONDS`) and nowhere else. Keep `redis-core` internal, and keep the inbox prefix under `~otp:*`.
5. **`orchestrator` session store:** Uses `save_fenced` which wraps `WATCH` on the turn lock key, checks ownership, and writes state atomically with `MULTI` / `SET ... EX` / `EXEC`. Lock release similarly depends on `WATCH` / `MULTI` / `DEL` / `EXEC`.
6. **`orchestrator` conversation rate limit:** `session/rate_limit.py` counts `POST /v1/conversations` per client address with `INCR` (sent as `INCRBY`) and `EXPIRE` in one `MULTI`, under `orch:ratelimit:conversations:<keyed hash>:<window>`. An `edge-svc` ACL written before this limit lacks `+incrby +expire`: the limiter then fails closed and every `POST /v1/conversations` answers 503.

If `WATCH`, `MULTI`, `EXEC`, or `UNWATCH` are omitted from the ACL, Redis returns `NOPERM` and operations fail.

### Exact Redis ACL Setup (`ACL SETUSER`)

Execute these commands in `redis-cli` on the host Redis instance:

```text
ACL SETUSER core-svc reset on >REPLACE_WITH_CORE_REDIS_PASSWORD ~session:* ~otp:* ~limit:* -@all +ping +get +set +del +incr +incrby +expire +watch +multi +exec +unwatch
ACL SETUSER edge-svc reset on >REPLACE_WITH_EDGE_REDIS_PASSWORD ~orch:* -@all +ping +get +set +del +incr +incrby +expire +watch +multi +exec +unwatch
```

Ensure the key prefix variables in `.env` match these patterns:
- `REDIS_SESSION_KEY_PREFIX=session:` (covered by `~session:*`)
- `REDIS_OTP_CHALLENGE_KEY_PREFIX=otp:challenge:` (covered by `~otp:*`)
- `REDIS_OTP_INBOX_KEY_PREFIX=otp:inbox:` (covered by `~otp:*`; the simulated OTP inbox)
- `REDIS_ATTEMPT_LIMIT_KEY_PREFIX=limit:` (covered by `~limit:*`)
- `REDIS_EDGE_KEY_PREFIX=orch:conv:` (covered by `~orch:*`)
- `REDIS_EDGE_RATE_LIMIT_KEY_PREFIX=orch:ratelimit:` (covered by `~orch:*`)

---

## 3. Production Compose Configuration

Production deployment layers `infra/compose/docker-compose.prod.yml` over `infra/compose/docker-compose.yml`, and — for bundled data only — `infra/compose/docker-compose.bundled.yml` on top of that.

### Deployment Modes

#### 1. Host Data Mode (Default Production)
By default, `docker-compose.prod.yml` sets `profiles: ["bundled-data"]` on `postgres`, `redis-core`, and `redis-edge`, with no other configuration on them. They do not start unless the profile is activated, and — because they carry no required (`:?`) variables in this file — `docker compose` does not ask for their passwords in this mode either: Compose validates a service's required variables during `config`/`up` even when a profile keeps it from starting, so those passwords could not live directly in `docker-compose.prod.yml` without breaking host mode (see `docker-compose.bundled.yml`'s header comment).

The stack connects to PostgreSQL and Redis running on the host system via `host.docker.internal:host-gateway`.

```bash
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               up -d --wait
```

#### 2. Bundled Data Mode (Self-Contained Evaluation)
To run the full stack with containerized PostgreSQL and Redis under production security controls (read-only filesystems, prebuilt images, registry tags), also layer `docker-compose.bundled.yml`, which is where `POSTGRES_PASSWORD`, `REDIS_CORE_PASSWORD`, and `REDIS_EDGE_PASSWORD` are required:

```bash
docker compose --profile bundled-data \
               -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               -f infra/compose/docker-compose.bundled.yml \
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
  ├── Policy amount mode (`flag` = handoff recommended, `block` = handoff required)
  └── Allowed tool dispatch matrices per FSM state
```

1. **Pure Environment (`.env`):**
   - **Data connectivity:** Plugging your own external PostgreSQL (`DATABASE_URL`, pgvector extension required) or Redis instances (`REDIS_CORE_URL`, `REDIS_EDGE_URL` supporting `redis://` or `rediss://` with username, password, port and TLS; use database 0, or add `+select` to both ACL users if you pick another DB number).
   - **Key prefixes:** Overriding `REDIS_SESSION_KEY_PREFIX`, `REDIS_OTP_CHALLENGE_KEY_PREFIX`, `REDIS_OTP_INBOX_KEY_PREFIX`, `REDIS_ATTEMPT_LIMIT_KEY_PREFIX`, `REDIS_EDGE_KEY_PREFIX`, and `REDIS_EDGE_RATE_LIMIT_KEY_PREFIX`. Keep the ACL key patterns aligned with them: a prefix outside `~session:*`, `~otp:*`, `~limit:*` (core) or `~orch:*` (edge) is refused with `NOPERM`.
   - **Model selection:** Switching encoder backends (`ENCODER_BACKEND=tfidf_lr|gliner`), calibration abstention threshold (`ABSTENTION_THRESHOLD`), embedding models (`EMBEDDING_MODEL`), and retrieval modes (`RETRIEVAL_MODE=vector|bm25|hybrid`).
   - **LLM engine:** Switching between deterministic `replay` and live provider (`live`), model names (`LLM_MODEL`), base URLs, and timeouts.
   - **Resource caps:** Memory ceilings (`BANKING_CORE_MEMORY_LIMIT`, `ENCODER_MEMORY_LIMIT`).

2. **Database Runtime Configuration:**
   - Policy thresholds (`POLICY_SEED_THRESHOLDS_MINOR`), the amount mode (`POLICY_SEED_AMOUNT_MODE`: `flag` recommends a handoff above the threshold, `block` requires one), and verification policies are **not constants in code**.
   - The environment variables only seed initial values into PostgreSQL tables on first boot.
   - Active policies reside in the database and can be queried and modified at runtime via the banking-core Admin API (`GET` / `PUT /v1/admin/policy-config`, authenticated via bearer token when `ADMIN_API_ENABLED=true`), with zero service restart or redeployment.
   - The same goes for which tools are enabled (the state × tool matrix, only ever narrower than the code floor): `POLICY_SEED_DISABLED_TOOLS` (default `account.get_summary`) seeds the first version, and `GET` / `PUT /v1/admin/tool-policy` read and change it. Each change is a new audited version that applies to the next tool call. Migration `0007` makes `config.tool_policy` versioned.

3. **Managed Cloud Services Note (⚠️ Pending Validation):**
   - Any PostgreSQL instance with `pgvector` via `DATABASE_URL` and any Redis instance with ACL/TLS via `REDIS_CORE_URL` / `REDIS_EDGE_URL` (`rediss://`) are supported purely by configuration.
   - Marked **not yet exercised against a managed service**; public cloud deployment (e.g. AWS) remains pending (ADR rule 7: not described as existing).

### (b) Horizontal Scaling & Statelessness

The application services are architecturally stateless:
- **`orchestrator`:** Holds no local state. Conversation transcripts and masked placeholder maps are stored in Redis (`edge-svc`). Turn execution is serialized via Redis turn locks (`acquire_turn_lock`), and writes are fenced against token expiration (`save_fenced`).
- **`banking-core`:** Holds no local state. FSM verification states, attempt counters, cross-session attempt limits (per-customer OTP failures and lock, per-document match failures), OTP challenge hashes and the simulated OTP inbox entries (with the clear code, for the challenge TTL) reside in Redis (`core-svc`). Domain entities and append-only audit chains reside in PostgreSQL. Tool invocations acquire an exclusive per-session distributed lock (`lock` with `nx=True, px=...`).
- **Idempotency:** Tool invocations accept an `idempotency_key`, preventing duplicate card blocks or dispute actions across retries.

> [!WARNING]
> **Load Testing & Multi-Replica Status:** While the data structures, distributed locks, and idempotency guarantees are engineered for multiple replicas, the system **has not been load-tested or run with more than one replica**. Production operations currently run as single-instance deployments.

### (c) Resource Footprint & Operational Limits

| Component | Operational Ceiling / Limit | Notes |
|---|---|---|
| `banking-core` per-replica RAM | ~1.3 GB RSS added at startup (`BANKING_CORE_MEMORY_LIMIT=2g`) | Loads `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` and indexes the 120-snippet Knowledge Base in RAM on boot. Database `pgvector` table ingestion is pending. |
| `encoder` (`tfidf_lr`) | ~43 MB model footprint, < 500 MB total container RSS | Default fast lexical classifier on CPU. Runs easily within `ENCODER_MEMORY_LIMIT=3g`. |
| `encoder` (`gliner`) | ~3.45 GB peak RSS (`ENCODER_MEMORY_LIMIT=4g`) | Requires `ENCODER_GLINER_MIN_MEMORY_MB=4096`. **Not the default**: `.env.example` seeds `ENCODER_BACKEND=tfidf_lr` because of this memory footprint. |
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

Automated production deployment automation via `make deploy` is currently `⚠️ pending`
(the CD workflow below deploys over SSH directly; it does not call `make deploy`).

---

## 6. Continuous Deployment

`.github/workflows/deploy.yml` builds the three application images, pushes them to
GHCR, and deploys to a target host over SSH. The target is a Docker host (VM) on the
chosen cloud platform (AWS, Google Cloud Platform or Microsoft Azure; decision pending),
reached over SSH. It runs on GitHub-hosted `ubuntu-latest` runners only — no
self-hosted runner, because this repository is public.

Deploying to a managed container service (e.g. ECS, Cloud Run, Azure Container Apps)
instead of a VM would need a different deploy job; this remains pending the platform
decision and is not implemented.

**Triggers:** automatically after `ci` succeeds on `main` (`workflow_run`), or manually
via `workflow_dispatch` (pick an environment, optionally an existing image tag for a
rollback). It never runs for `pull_request` events. The default GitHub Environment is
`production`.

**Fork PRs never reach `build` or `deploy`, by construction, not just by omitting
`pull_request`.** `on.workflow_run.branches: [main]` matches on the *head branch name*
of the completed run, regardless of which repository that branch lives in — so a fork
PR opened from a branch literally named `main` would otherwise satisfy that filter and
fire `workflow_run` in *this* repository, with this repository's secrets and
`packages: write`. Both the `build` and `deploy` jobs additionally require, in their own
`if:` (re-derived independently in `deploy`, not inherited from `build`'s result), that
`github.event.workflow_run.event == 'push'` and
`github.event.workflow_run.head_repository.full_name == github.repository` and
`github.event.workflow_run.head_branch == 'main'` — none of which a fork's pull_request
can satisfy, since its head repository is the fork, not this repository, no matter what
it names its branch. `workflow_dispatch` is additionally pinned to
`github.ref == 'refs/heads/main'`.

### Creating a GitHub Environment

`Settings → Environments → New environment`, named to match what
`vars.DEPLOY_ENVIRONMENT` (repository variable) or the `workflow_dispatch` input
resolves to — `production` if neither is set. Add the secrets and variables from the
table below to that environment. Optionally add required reviewers or a wait timer;
the workflow's `concurrency: deploy-<environment>` group already prevents two deploys
to the same environment from overlapping.

### Repository-level configuration (not environment-scoped)

| Name | Kind | Purpose | Default |
|---|---|---|---|
| `DEPLOY_PLATFORMS` | variable | Build target(s): `linux/amd64`, `linux/arm64`, or both comma-separated | `linux/amd64` |
| `BANKING_CORE_SYNC_ARGS` | variable | Build arg forwarded to `apps/banking-core/Dockerfile` | `--extra vector` |
| `ENCODER_EXTRAS` | variable | Build arg forwarded to `apps/encoder/Dockerfile` (`gliner` to include it; empty for `tfidf_lr` only) | empty |
| `DEPLOY_ENABLED` | variable | Must be `"true"` or the `deploy` job no-ops cleanly (this is what lets a fork exist without a working deploy). **Must be set at the repository level, not inside a GitHub Environment**: the `deploy` job's `if:` is evaluated before the job's `environment:` binds, so an environment-scoped variable of the same name would never be visible there and the job would silently skip forever | unset |

### Per-environment configuration

| Name | Kind | Required when | Purpose |
|---|---|---|---|
| `DEPLOY_SSH_KEY` | secret | always | Private key for `DEPLOY_USER@DEPLOY_HOST`; the matching public key must be authorized on the target host |
| `DEPLOY_KNOWN_HOSTS` | secret | always | Output of `ssh-keyscan <host>`, captured and pinned once by hand. Never `StrictHostKeyChecking=no` |
| `DEPLOY_HOST` | secret | always | Target host (hostname or IP) |
| `DEPLOY_USER` | secret | always | SSH user on the target host |
| `DEPLOY_PATH` | variable | always | Absolute path on the target host for the compose files and `.env` (e.g. `/opt/pattern-blue`) |
| `DATA_MODE` | variable | always | `host` (default: use the target's own Postgres/Redis, see §1–§3 above) or `bundled` (adds `--profile bundled-data` and `-f docker-compose.bundled.yml`: a dedicated server gets Postgres/Redis containers from zero, no host prep) |
| `DATABASE_URL` | secret | always | See §3 table above |
| `REDIS_CORE_URL` | secret | always | See §3 table above |
| `REDIS_EDGE_URL` | secret | always | See §3 table above |
| `SESSION_SECRET` | secret | always | See §3 table above |
| `MASTER_KEY` | secret | always | See §3 table above |
| `BLIND_INDEX_SALT` | secret | always | See §3 table above |
| `ADMIN_API_ENABLED` | variable | optional | `true` to enable the admin API on `banking-core` |
| `ADMIN_API_TOKEN` | secret | when `ADMIN_API_ENABLED=true` | Bearer token for the admin API. A real random secret: `banking-core` refuses to start under `APP_ENV=production` with an empty token or the public development token |
| `DEMO_RESET_ENABLED` | variable | optional | `true` to allow `POST /v1/admin/demo/reset-fixtures` under `APP_ENV=production` (it also needs the admin API). See §7 |
| `OTP_CHANNEL_MODE` | variable | optional | `simulated`, the default and the only delivery that exists. See §7 |
| `DEMO_SEED` | variable | optional | `true` to load the synthetic demo customers after `up`, with the seed's `--force`. It **deletes the banking tables' contents**: set it on the presentation Environment only. See §7 |
| `LLM_MODE`, `LLM_BASE_URL`, `LLM_MODEL` | variable | optional | Defaults to `replay` (no external calls, no key needed) |
| `LLM_API_KEY` | secret | when `LLM_MODE=live` | Provider API key |
| `RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR`, `TRUSTED_PROXY_HOPS` | variable | optional | Conversations one client address may open per hour (`30` unless set; the development compose defaults to `1000`), and how many reverse proxies stand in front of the orchestrator (default `0`: `X-Forwarded-For` is ignored). Set `TRUSTED_PROXY_HOPS` to the real number when an ingress proxy fronts the stack, see §1 |
| `ENCODER_BACKEND`, `ABSTENTION_THRESHOLD` | variable | optional | Default to the calibrated seed in `.env.example` (`tfidf_lr`, `0.37`). `ENCODER_BACKEND=gliner` also needs the `ENCODER_EXTRAS` build variable and about 4 GB of memory |
| `POSTGRES_PASSWORD` | secret | when `DATA_MODE=bundled` | Password for the bundled `postgres` container |
| `REDIS_CORE_PASSWORD` | secret | when `DATA_MODE=bundled` | Password for the bundled `redis-core` container |
| `REDIS_EDGE_PASSWORD` | secret | when `DATA_MODE=bundled` | Password for the bundled `redis-edge` container |

`DATA_MODE=host` needs the one-time host preparation described in §1 (PostgreSQL role,
database, `pgvector`, `pg_hba.conf`) and §2 (Redis ACL users) above, done once by
whoever administers that host. `DATA_MODE=bundled` needs none of that: the compose
`bundled-data` profile starts `postgres`, `redis-core`, and `redis-edge` as containers
on the target itself.

### What a deploy runs

In order, over SSH on the target: create `$DEPLOY_PATH/infra/compose` and `$DEPLOY_PATH/eval/replay`
(the orchestrator's read-only recordings mount) and copy the compose files; write
`$DEPLOY_PATH/.env` (mode 600); `pull`; `run --rm migrate`; `up -d --wait`; when
`DEMO_SEED=true`, `run --rm seed ... seed --force`; then a `/health` smoke check on the
orchestrator. The images already contain the code; nothing is built on the server.

### Forking this repository

A fork gets the workflow file as-is and does nothing on its own: `vars.DEPLOY_ENABLED`
is unset on a fresh fork, so the `deploy` job's `if:` condition is false and it is
skipped, not failed. The `build` job still runs and pushes to the fork owner's own
`ghcr.io/<fork-owner>/pattern_blue-*` packages (`github.repository_owner` is always
resolved from the repository the workflow runs in). To deploy from a fork, its owner
creates their own GitHub Environment and secrets exactly as described above — nothing
in the workflow needs editing.

### GitHub secret limits

Each secret is capped at 48 KB, and a job's combined secrets must stay under 64 KB.
None of the values above approach that. If a future need requires a large blob (a TLS
certificate bundle, for instance — not needed today, since Redis/Postgres access from
the app containers is not encrypted at the ADR-0004 trust-boundary hop), base64-encode
it into a secret and `base64 -d` it back into a file inside the job. GitHub Actions has
no "secure files" feature comparable to Azure DevOps; a base64 secret decoded at
deploy time is the equivalent.

### Where images live

The three images (`ghcr.io/<owner>/pattern_blue-banking-core`,
`pattern_blue-orchestrator`, `pattern_blue-encoder`) are **GHCR public packages** by
intent. GHCR packages are **private by default on first push** regardless of the
repository's own visibility, so after the first successful `build` job, go to
`https://github.com/users/<owner>/packages/container/<package>/settings` (or the org
equivalent) for each of the three and set visibility to Public once. Public packages
need no authentication to `docker pull`, which is why the `deploy` job does not log in
to GHCR before pulling — if a package is kept private instead, add a `docker login`
step there with a token that has at least `read:packages`.

### Rollback

Re-run the workflow via `workflow_dispatch` with the same `environment` and an
`image_tag` from a previous successful run (visible in the Actions run log, or as a
GHCR package version, e.g. `sha-abc1234`). The `build` job is skipped in that case —
nothing is rebuilt — and `deploy` runs the SSH steps against the given tag.

### Status: not yet exercised

`deploy.yml` has been designed and syntax/render-validated locally (`config` against
both `DATA_MODE` values, the trust-boundary check, YAML parsing) but **no deploy has
actually run** against any target — no Environment has been created yet, and no
`DEPLOY_*` secret exists anywhere. Treat this section as a design, not a proven
procedure, until a first real run against the platform is logged here.

---

## 7. Presentation environment

The team's own environment for presentations. There is **no separate environment for
judges**: they clone the repository and run `make demo` on their machine
([runbook](runbook.md)), with at most an LLM API key in `.env`.

The presentation environment is an ordinary deployment (§6, same images, same
`deploy.yml`) that stays `APP_ENV=production`, with **production-hardened defaults and
each demo feature switched on explicitly**. The development defaults of
`docker-compose.yml` (admin API on with a public token) never reach it:
`docker-compose.prod.yml` pins them back to off, and `banking-core` refuses to start
with the development token when `APP_ENV=production`.

**The hosting platform is still to be decided** (AWS, Google Cloud Platform or Microsoft
Azure, §6). Nothing below depends on which one it is.

### The switches

| Switch | Set it to | What it turns on | Notes |
|---|---|---|---|
| `ADMIN_API_ENABLED` + `ADMIN_API_TOKEN` | `true` + a random secret (`openssl rand -hex 32`) | Back-office actions over HTTP: `GET`/`PUT /v1/admin/policy-config` | Startup fails on an empty token or the development token. Keep the token out of the repository: it is a GitHub secret |
| `DEMO_RESET_ENABLED` | `true` | `POST /v1/admin/demo/reset-fixtures`: puts the fixture customers' cards back to their seed state between demo runs | Without it the endpoint answers 403 in production. It also needs the admin API |
| `OTP_CHANNEL_MODE` | `simulated` (the default) | The simulated OTP delivery: no code leaves the system | Today this is the only delivery that exists; `banking-core` does not read the variable yet, and the real channel is an open decision ([limitations](limitations.md)). The panel that shows simulated codes belongs to the customer web client, which is pending, and the dev OTP endpoint stays off (`deploy.yml` never sets `ALLOW_DEV_OTP_HOOK`) |
| `DEMO_SEED` | `true` | After `up`, `deploy.yml` runs `python -m banking_core.seed.cli seed --force` in the `seed` service | The seed refuses to run under `APP_ENV=production` without `--force`. It **truncates and reloads** the banking tables with the synthetic demo customers (es/pt/en), so every deploy with the variable set resets the demo data and empties the handoff queue: leave it on only for a deploy that should do that. Set it on the presentation GitHub Environment, never at repository level and never on an environment that holds real customer data: it would wipe it |
| `TRUSTED_PROXY_HOPS` | the number of reverse proxies the platform puts in front of the orchestrator | Which client address the per-address limit counts | `0` (default) ignores `X-Forwarded-For` and counts the connection peer, so behind a proxy every customer shares the proxy's address and budget. Never set more than the real number: the extra entries come from the client |
| `RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR` | leave at `30` | Conversations one client address may open per hour | `deploy.yml` writes `30` unless the variable is set, and `docker-compose.prod.yml` pins the same default; the development compose defaults to `1000` so local runs and evaluation runs from one address are not limited. It must be at least `1`: `0` is not "unlimited", the orchestrator refuses to start |
| `LLM_MODE` + `LLM_API_KEY` | `live` + the key (secret) | Real model calls | With `replay` the orchestrator answers 503 on a message that has no recording, and `deploy.yml` does not ship `eval/replay` yet |

Everything else keeps its production default: `APP_ENV=production`, only the orchestrator
publishes a port, the dev OTP endpoint is off, `EVAL_EXPOSE_TURN` is refused, and the
secrets (`MASTER_KEY`, `BLIND_INDEX_SALT`, `SESSION_SECRET`, database and Redis URLs) come
from the GitHub Environment.

### Not yet exercised

The seed service runs from the registry image with `/app/data` as scratch space (the base
file's bind mounts of `data/` and `reports/` would be root-owned empty directories on a
server). Like the rest of §6, this has been render-validated but never run against a real
target.
