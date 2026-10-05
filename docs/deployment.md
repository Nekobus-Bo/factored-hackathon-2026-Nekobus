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
            ENC["encoder = model server<br/>(decision model + embedding model, local CPU)"]
        end

        subgraph FrontEnds ["Front ends (edge network, same-origin BFFs)"]
            WC["web-client<br/>(customer chat, published on 127.0.0.1:5173)"]
            WB["web-backoffice<br/>(agent back office, not published in production)"]
        end
    end

    EXT[Customers] -->|HTTP :5173, through the platform ingress| WC
    OPS[Operator] -.->|its own login behind a proxy, or an SSH tunnel| WB
    WC -->|the five chat routes| ORC
    WB -->|/v1/agent, agent token| ORC
    WB -->|/v1/admin, admin token| CORE
    ORC -->|HTTP /v1/analyze| ENC
    CORE -->|HTTP /v1/embed (kb.search)| ENC
    ORC -->|HTTP /v1/tools/call| CORE
    CORE -->|DATABASE_URL| PG
    MIG -->|DATABASE_URL| PG
    CORE -->|REDIS_CORE_URL (core-svc)| RC
    ORC -->|REDIS_EDGE_URL (edge-svc)| RE

    classDef trusted fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef untrusted fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    classDef data fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px;

    class CORE,MIG trusted;
    class ORC,ENC,WC,WB untrusted;
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
   - In production compose, `banking-core`, `encoder` and `web-backoffice` expose no host ports. Two are published, both bound to `127.0.0.1` for an ingress reverse proxy on the same host: the `web-client` (`5173`, the customers' door) and the `orchestrator` (`8080`, which the web client calls and the deploy smoke checks). Nothing outside the compose networks reaches the back office (see "The front ends" in section 3).
   - **Model server (`encoder`):** it serves the decision model (`POST /v1/analyze`, `GET /v1/decision-points`) and the embedding model of `kb.search` (`POST /v1/embed`) ([ADR-0012](adr/0012-decision-points.md), Appendix J). It receives **raw customer text**, so it must run inside your private network and never be a third-party or public service. It can share the host with the rest of the stack or run on its own host: set `ENCODER_URL` (orchestrator) and `MODEL_SERVER_URL` (banking-core) to its address, publish its port only to those two services (firewall or security group), and fill its `hf-cache` volume there (`make warmup-retrieval`, with network once). **There is no authentication or TLS between the services and the model server yet**: the network is the control (declared in [limitations.md](limitations.md)). banking-core depends on it only for `kb.search`; if it is down or serves another model than `EMBEDDING_MODEL`/`EMBEDDING_REVISION`, `kb.search` is unavailable and every other tool is unaffected.
   - **Decision model weights ([ADR-0014](adr/0014-distilbert-intent-backend.md)):** the encoder image carries the pooled DistilBERT. `apps/encoder/Dockerfile` copies it from a public, multi-platform (amd64 and arm64) seed image on Docker Hub, pinned by digest, so building the image needs Docker Hub reachable once (about 0.55 GB) and the running container needs no network for it. The artifact pins the same weights by SHA-256 and the encoder refuses to start on a mismatch. An air-gapped build can pass `--build-context weights=<a local model directory>` instead.
   - **Client addresses behind a reverse proxy:** `POST /v1/conversations` is limited per client address (`RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR`; 30 per hour in production, 1000 in the development compose). The address is the connection peer unless `TRUSTED_PROXY_HOPS` says how many reverse proxies stand in front; the orchestrator's own default, `0`, ignores `X-Forwarded-For` so a client cannot pick its own bucket. **The compose files set `1`** (Cloud Run runs `0` as a stopgap, section 7), because the customer path is now the web-client BFF: it puts the address of its own connection in `X-Forwarded-For`, and with `0` every customer would share the BFF's address and budget, and once it is spent nobody can open a conversation until the hour ends. Set it higher than the real number and the extra entries are client-supplied, so the limit can be evaded. With `1` a request that reaches the orchestrator directly could carry a forged header and pick its own bucket, which is why the orchestrator's port is published on `127.0.0.1` only: that can happen only from the host itself, so an ingress must send customers to the web client (`5173`), never to the orchestrator. **Known limit:** the BFF sees only the address of the connection to it, so behind an ingress proxy in front of the web client every customer still shares that proxy's address and budget, until the BFF is taught to trust that proxy ([limitations.md](limitations.md), the customer app row). The orchestrator stores only a keyed hash of the address.
   - **Agent API (human takeover):** the orchestrator serves `/v1/agent` on its own port (`8080`), next to the customer chat, so a back-office server can read a conversation's transcript, take it over and write to the customer. It is **off unless `AGENT_API_ENABLED=true`** (the router is then not mounted: its paths answer 404) and every route needs `Authorization: Bearer <AGENT_API_TOKEN>`, compared in constant time. The development compose turns it on with the public token `dev-only-agent-token`; **the orchestrator refuses to start under `APP_ENV=production` with that token or an empty one**, and `docker-compose.prod.yml` pins the API back to off and the token to empty, so production enables it only with a secret of its own (`openssl rand -hex 32`). The token is its only protection: **no ingress should forward `/v1/agent`** (customers go to the web client, not to the orchestrator), and only the back-office server should hold the token. Design: [ADR-0013](adr/0013-front-ends-bff-takeover.md). `AGENT_LOCK_WAIT_SECONDS` (default `10`) is how long a takeover or an agent message waits for a customer turn in flight before answering `503 turn_in_progress`.

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
5. **`orchestrator` session store:** Uses `save_fenced` which wraps `WATCH` on the turn lock key, checks ownership, and writes state atomically with `MULTI` / `SET ... EX` / `EXEC`. Lock release similarly depends on `WATCH` / `MULTI` / `DEL` / `EXEC`. The same `MULTI` also sets the reverse index the agent API reads, `orch:session:<banking session id>` holding the conversation id (`SET ... EX`, the conversation's TTL, refreshed by every save); it needs no command beyond the set above and no `EXISTS`, `SCAN` or `KEYS`.
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
- `REDIS_EDGE_SESSION_INDEX_KEY_PREFIX=orch:session:` (covered by `~orch:*`)

---

## 3. Production Compose Configuration

Self-hosting on a Docker host layers `infra/compose/docker-compose.prod.yml` over `infra/compose/docker-compose.yml`, and — for bundled data only — `infra/compose/docker-compose.bundled.yml` on top of that. The team's presentation environment does not use these files: it runs on Cloud Run (section 6).

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

### The front ends (`web-client` and `web-backoffice`)

Two Bun servers, each serving its page and a same-origin BFF: the browser talks only to its own server, which forwards a closed list of routes to the orchestrator and, for the back office, to the `banking-core` admin API ([ADR-0013](adr/0013-front-ends-bff-takeover.md)). Neither has a database or Redis. Both are built from the repository root (`Dockerfile.dockerignore` next to each Dockerfile keeps the context to about 0.5 MB, against the whole repository), run as the non-root `bun` user, sit on the `edge` network only and answer `GET /healthz`, which is what their compose healthcheck calls.

| | `web-client` | `web-backoffice` |
|---|---|---|
| In-container port | `5173` | `5174` |
| Development compose | `127.0.0.1:${PORT_WEB_CLIENT:-5173}` | `127.0.0.1:${PORT_WEB_BACKOFFICE:-5174}` |
| Production overlay | Published the same way (`127.0.0.1`); `APP_ENV=production`, read-only root | **Not published** (`ports: !reset []`); `APP_ENV=production`, read-only root |
| Calls | The orchestrator, `ORCHESTRATOR_URL=http://orchestrator:8080` | The orchestrator (`/v1/agent`) and `banking-core` (`/v1/admin`), `http://orchestrator:8080` and `http://banking-core:8081` |
| Secrets | None | `ADMIN_API_TOKEN`, `AGENT_API_TOKEN`, `DEMO_AGENT_PASSWORD` and `BACKOFFICE_SESSION_SECRET`: `${VAR:?}` in the production overlay, so a deploy that lacks one fails at `compose config` naming it; the server also refuses the development values under `APP_ENV=production` |
| Also read | | `DEMO_AGENT_EMAIL` (the one login and the `agent_ref` of every claim; default `agent@demo.local`) |
| Memory | About 20 MiB at rest (limit `256m`) | About 20 MiB at rest (limit `256m`) |

In development the tokens have the same variables and public defaults as on `banking-core` and the orchestrator, so the three sides agree with no `.env`. In production the back office needs both APIs on: `ADMIN_API_ENABLED=true` and `AGENT_API_ENABLED=true`, both off in the production overlay by default. Without them it starts and logs in, but its screens fail: `404` when the API is off, `502 upstream_unauthorized` when the token is not the one the API expects.

**Reaching the back office in production.** There is no host port on purpose: the admin and agent tokens live in that server, and its one login is a demo credential. Two ways in, neither of which ships as a file:

- a reverse proxy on the same Docker network (`<project>_edge`) that adds its own authentication in front of `web-backoffice:5174`, or
- a loopback port that the operator publishes with an override file written on the server (not in the repository), and an SSH tunnel to it:

  ```yaml
  # /opt/pattern-blue/infra/compose/docker-compose.backoffice-tunnel.yml
  services:
    web-backoffice:
      ports:
        - "127.0.0.1:5174:5174"
  ```

  Add `-f` for it after the two files in the compose command, run `up -d web-backoffice`, and `ssh -L 5174:127.0.0.1:5174 <user>@<host>`; then open `http://localhost:5174`.

The check that the overlay publishes what it says (run it with the variables of section 3 set, as for the trust-boundary check below):

```bash
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
assert "ports" not in services["web-backoffice"], "the back office must not be published in production"
assert "ports" not in services["banking-core"] and "ports" not in services["encoder"]
print("Published in production:", sorted(n for n, s in services.items() if s.get("ports")))
'
```

It prints `Published in production: ['orchestrator', 'web-client']`.

### Environment Variables Matrix

The production compose override enforces explicit configuration without development defaults:

| Variable | Description | Services Consuming | Example Value |
|---|---|---|---|
| `REGISTRY` | Container registry prefix | `migrate`, `seed`, `banking-core`, `orchestrator`, `encoder`, `web-client`, `web-backoffice` | `ghcr.io/org` |
| `IMAGE_TAG` | Image release version / commit SHA | `migrate`, `seed`, `banking-core`, `orchestrator`, `encoder`, `web-client`, `web-backoffice` | `v1.0.0` or git SHA |
| `DATABASE_URL` | PostgreSQL connection URL (psycopg format) | `migrate`, `seed`, `banking-core` | `postgresql+psycopg://app:pass@host.docker.internal:5432/bank` |
| `REDIS_CORE_URL` | Redis URL for banking-core (`core-svc`) | `banking-core` | `redis://core-svc:pass@host.docker.internal:6379/0` |
| `REDIS_EDGE_URL` | Redis URL for orchestrator (`edge-svc`) | `orchestrator` | `redis://edge-svc:pass@host.docker.internal:6379/0` |
| `MASTER_KEY` | Master key for application-level encryption | `seed`, `banking-core` | 32-byte base64/hex secret |
| `BLIND_INDEX_SALT` | Salt for deterministic blind indexing | `seed`, `banking-core` | 32-byte secret |
| `SESSION_SECRET` | Secret key for conversation placeholder encryption | `orchestrator` | 32-byte secret |
| `ADMIN_API_ENABLED`, `ADMIN_API_TOKEN` | Switch on the admin API (`/v1/admin`) and its bearer token. The production override pins the switch to `false` and the token to empty for `banking-core`; the back office needs the switch on and the token **set** (`${ADMIN_API_TOKEN:?}` on `web-backoffice`). `banking-core` refuses an empty or the public development token under `APP_ENV=production` | `banking-core`, `web-backoffice` | `true` + `openssl rand -hex 32` |
| `AGENT_API_ENABLED`, `AGENT_API_TOKEN` | Switch on the agent API (`/v1/agent`, the human takeover) and its bearer token. The production override pins the switch to `false` and the token to empty for the orchestrator, which refuses to start under `APP_ENV=production` with an empty token or the public development token; the back office needs the switch on and the token **set** (`${AGENT_API_TOKEN:?}`) | `orchestrator`, `web-backoffice` | `true` + `openssl rand -hex 32` |
| `BACKOFFICE_SESSION_SECRET` | HMAC key of the back office's session cookie. Required in production; the server refuses the development default | `web-backoffice` | `openssl rand -hex 32` |
| `DEMO_AGENT_EMAIL`, `DEMO_AGENT_PASSWORD` | The back office's one demo login. The password is required in production and the server refuses the development one; the email defaults to `agent@demo.local` and is recorded as the agent on every claim | `web-backoffice` | an address, and a random password |
| `PORT_WEB_CLIENT`, `PORT_WEB_BACKOFFICE` | Host side of the front ends' loopback ports (development compose; the web client's also applies in production). Inside the containers the ports are fixed, `5173` and `5174` | `web-client`, `web-backoffice` | `5173`, `5174` |
| `BANKING_CORE_MEMORY_LIMIT` | Container memory limit for banking-core. The embedding model no longer loads there by default, so it can be lowered once measured on Linux | `banking-core` | `2g` |
| `ENCODER_MEMORY_LIMIT` | Container memory limit for the model server | `encoder` | `3g` (default; DistilBERT plus the fp32 Granite embedding model measured 2.08 GiB in the compose container, Linux arm64, 2026-10-02) or `5g` (`gliner` plus the embedding model, estimate) |
| `DECISION_POINTS_FILE` | Calibration artifact the encoder serves | `encoder` | `packages/encoder/calibration/decision_points.distilbert.json` (default, ADR-0014) or `packages/encoder/calibration/decision_points.json` (the `tfidf_lr` baseline, kill switch) |
| `ENCODER_EXTRAS` | Build argument: optional encoder dependencies | `encoder` (build) | `embed hf` (default: kb.search embeddings and the DistilBERT decision model) |
| `MODEL_SERVER_URL` | Base URL of the model server for `kb.search` | `banking-core` | `http://encoder:8090` (default) or `http://models.internal:8090` |
| `EMBEDDING_MODEL` | Embedding model the model server serves and banking-core expects | `encoder`, `banking-core` | `ibm-granite/granite-embedding-311m-multilingual-r2` |
| `EMBEDDING_REVISION` | Pin: a full 40-hex commit of that model. banking-core rejects any answer from another revision | `encoder`, `banking-core` | a 40-hex commit |
| `EMBEDDING_WEIGHTS_SHA256` | Optional pin: SHA-256 of the weights file, verified when the model server starts. `make warmup-retrieval` prints it | `encoder` | 64 hex characters |
| `EMBEDDING_DTYPE` | Precision the embedding weights load in. `float32` keeps CPU speed independent of bf16 support; Granite ships bf16 weights | `encoder` (and `banking-core` with `EMBEDDING_BACKEND=local`) | `float32` (default) or `bfloat16` |
| `EMBEDDING_BACKEND` | `remote` (the model server, default) or `local` (in process, tests and local development only; needs the `vector` extra in the image) | `banking-core` | `remote` |
| `DECISION_POINTS_FILE`, `DECISION_POINTS_ALLOW_STALE`, `DECISION_POINTS_TAU_RAISE` | Decision-point artifact path, downgrade of a pin mismatch (refused under `APP_ENV=production`), raise-only tau override. The committed seed artifact is used (provisional evidence, [ADR-0012](adr/0012-decision-points.md)); the model server runs in legacy seed mode only when no artifact file exists | `encoder` | empty, `false`, empty |

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
  ├── EMBEDDING_MODEL, EMBEDDING_REVISION, MODEL_SERVER_URL, RETRIEVAL_MODE
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
   - **Key prefixes:** Overriding `REDIS_SESSION_KEY_PREFIX`, `REDIS_OTP_CHALLENGE_KEY_PREFIX`, `REDIS_OTP_INBOX_KEY_PREFIX`, `REDIS_ATTEMPT_LIMIT_KEY_PREFIX`, `REDIS_EDGE_KEY_PREFIX`, `REDIS_EDGE_RATE_LIMIT_KEY_PREFIX`, and `REDIS_EDGE_SESSION_INDEX_KEY_PREFIX`. Keep the ACL key patterns aligned with them: a prefix outside `~session:*`, `~otp:*`, `~limit:*` (core) or `~orch:*` (edge) is refused with `NOPERM`.
   - **Model selection:** Switching encoder backends (`ENCODER_BACKEND=tfidf_lr|gliner`), calibration abstention threshold (`ABSTENTION_THRESHOLD`), the pinned embedding model (`EMBEDDING_MODEL`, `EMBEDDING_REVISION`) and where it runs (`MODEL_SERVER_URL`), and retrieval modes (`RETRIEVAL_MODE=vector|bm25|hybrid`).
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
| `banking-core` per-replica RAM | Small: the embedding model no longer loads here (it added ~1.3 GB RSS with the KB index, measured on macOS, when it did). The 120-snippet KB index is still built in RAM from vectors the model server returns. The Linux figure is pending; the `2g` limit is unchanged until it is measured | The image still installs the `vector` extra ([ADR-0012](adr/0012-decision-points.md), J.6). Database `pgvector` table ingestion is pending. |
| Model server (`encoder`) with `tfidf_lr` and the embedding model | ~43 MB for `tfidf_lr`, plus the embedding model (PyTorch and MiniLM; the Linux figure is pending) | Should fit `ENCODER_MEMORY_LIMIT=3g` (estimate). Loaded once, shared by every banking-core replica. Without `EMBEDDING_MODEL` it is < 500 MB. |
| Model server (`encoder`) with `gliner` | ~3.45 GB peak RSS alone (`ENCODER_MEMORY_LIMIT=5g` with the embedding model, estimate) | Requires `ENCODER_GLINER_MIN_MEMORY_MB=4096`. **Not the default**: `.env.example` seeds `ENCODER_BACKEND=tfidf_lr` because of this memory footprint. |
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

`make deploy` runs `.github/workflows/deploy.yml` on `main`, which deploys to Cloud Run (section 6). The commands above are for a self-hosted Docker host; the Cloud Run environment has its own under `make gcp-*`.

---

## 6. Continuous Deployment

The presentation environment runs on **Google Cloud Run** in `us-east1` ([ADR-0015](adr/0015-gcp-cloud-run-terraform.md)). Two pieces, with a strict split:

- **Terraform** in [`infra/deploy/gcp/`](../infra/deploy/gcp/) owns the infrastructure and the service configuration: the VPC and its three subnets, Cloud SQL, the two Memorystore instances, Secret Manager, one service account per service, the five services, the three jobs, Identity-Aware Proxy and the GitHub login. The runbook of a first deploy is in its [README](../infra/deploy/gcp/README.md).
- **`.github/workflows/deploy.yml`** owns the image: it builds the five images, pushes them to Artifact Registry and rolls every service and job out to them. Terraform ignores image changes after it creates a service.

How each compose guarantee of sections 1–3 is kept on Cloud Run (the `core` network, one Redis per zone, backends not published, the back office hidden, per-service secrets) is the table in ADR-0015. The compose production overlay of section 3 remains the way to self-host on a Docker host; nothing deploys it automatically.

**Triggers:** automatically after `ci` succeeds on `main` (`workflow_run`), or by hand with `make deploy` (`workflow_dispatch`, optionally with an existing `image_tag` for a rollback). It never runs for `pull_request` events.

**Fork PRs never reach `build` or `deploy`, by construction, not just by omitting `pull_request`.** `on.workflow_run.branches: [main]` matches on the *head branch name* of the completed run, regardless of which repository that branch lives in, so a fork PR opened from a branch literally named `main` would otherwise satisfy that filter. Both jobs additionally require, in their own `if:` (re-derived independently in `deploy`, not inherited from `build`'s result), that `github.event.workflow_run.event == 'push'`, `github.event.workflow_run.head_repository.full_name == github.repository` and `github.event.workflow_run.head_branch == 'main'`. `workflow_dispatch` is pinned to `github.ref == 'refs/heads/main'`. Both jobs also need the repository variable `DEPLOY_ENABLED=true`, so a fork or a copy without a GCP environment does nothing.

**GitHub holds no GCP secret.** The jobs log in with GitHub's OIDC token through Workload Identity Federation; the provider accepts a token only from one repository id, on `refs/heads/main`, from `deploy.yml` (`infra/deploy/gcp/ci.tf`). The deployer service account can push images, update and run the services and jobs, act as their runtime accounts and read logs; nothing else.

### Repository variables

All non-secret; `make gcp-gh-vars GH_REPO=owner/name` sets them from the Terraform outputs.

| Variable | Purpose |
|---|---|
| `DEPLOY_ENABLED` | `true` or both jobs are skipped |
| `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_NAME_PREFIX` | Where the environment is, and the prefix of its resource names |
| `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA` | The Workload Identity provider and the service account the jobs log in as |
| `GCP_REGISTRY` | Artifact Registry path the images are pushed to |
| `DEMO_SEED` | `true` runs the seed job on every deploy: it **truncates** the banking tables and reloads the synthetic demo customers (section 7) |
| `CI_IMAGE_PLATFORMS` | Platforms of the `ci` images job; `linux/amd64` in a copy whose Actions minutes are billed |

GitHub Environments are not used: nothing needs one, and a private repository on GitHub Free has none.

### What a deploy runs

1. **build** (matrix of five, `linux/amd64`, tagged `sha-<commit>`): `banking-core` without extras (its embeddings come from the model server, so PyTorch stays out of the trusted zone); the encoder with the `embed` and `hf` extras, the fine-tuned DistilBERT copied in by digest (ADR-0014) and the embedding model pinned in `.env.example` baked in, the build failing if the weights do not match the hash.
2. **deploy**, in dependency order: the model server; the `migrate` job, run and awaited; the `seed` job when `DEMO_SEED=true`; `banking-core`; the orchestrator; the two front ends. Each `gcloud run services update` waits for the new revision's startup probe; if it fails, the command fails and traffic stays on the previous revision.
3. **smoke**: [`infra/deploy/gcp/smoke.sh`](../infra/deploy/gcp/smoke.sh) with the network check. Positive: every service ready on a real image; the web client opens a conversation through the orchestrator and banking-core. Negative: the orchestrator, banking-core and the model server do not answer from the internet; the back office does not answer without IAP; from the edge zone, Cloud SQL and redis-core are unreachable while redis-edge is reachable. `make gcp-smoke NETCHECK=1` runs the same from a laptop.

### Rollback

`make deploy` runs the latest `main`. To go back, dispatch `deploy.yml` with the `image_tag` of a previous run (`sha-abc1234`, in the Actions log or in Artifact Registry): `build` is skipped and `deploy` rolls every service and job to that tag. Migrations only move forward; a rollback across a migration keeps the newer schema.

### Status: deployed

`deploy.yml` has rolled out to the presentation project, with its smoke test passing, since 2026-10-03 (first successful run on commit `3b0454e`; the Actions history of the `deploy` workflow lists every run). The same pieces are still checked offline on every change: `make gcp-check` (fmt, validate, tflint and `terraform test` against a mocked provider), actionlint, shellcheck, and the smoke script against a fake `gcloud` and the local stack. The rollback by `image_tag` has not been exercised.

---

## 7. Presentation environment

The team's own environment for presentations: the Cloud Run environment of section 6. There is **no separate environment for judges**: they clone the repository and run `make demo` on their machine ([runbook](runbook.md)), with at most an LLM API key in `.env`.

It stays `APP_ENV=production`, with **production-hardened defaults and each demo feature switched on explicitly** in `infra/deploy/gcp/services.tf`. The development defaults of `docker-compose.yml` (admin API and agent API on, each with a public token) never reach it: every token is generated by Terraform, and `banking-core`, the orchestrator and the back office refuse to start with a development value under `APP_ENV=production`.

### The switches

| Switch | Where | What it does |
|---|---|---|
| Admin API and agent API | On in `services.tf`; tokens generated by Terraform | What the back office calls: the queue, claims, guardrails, metrics, and the human takeover. Neither API is reachable from the internet: both services accept internal traffic only |
| Back office | IAP (`iap_members` in `local.tfvars`), then its own login | Only the listed accounts pass IAP; the demo login is `DEMO_AGENT_EMAIL` with the password Terraform generated (`gcloud secrets versions access latest --secret pb-demo-agent-password`). `backoffice_public` and `judge_accounts`, both off by default, open it for a judging window (below) |
| Detective mode | `detective_mode` in `variables.tf` (off), `true` in `presentation.tfvars` | Each chat turn returns its masked timeline and the chat offers a header button that shows it in a panel beside the chat (in place of the conversation on a narrow window); the back office's Guardrails screen turns it off and on for every conversation ([ADR-0019](adr/0019-detective-mode.md)). Anyone using the chat then sees the system prompt and the tool outcomes |
| `DEMO_RESET_ENABLED` | On in `services.tf` | `POST /v1/admin/demo/reset-fixtures` puts the fixture customers' cards back between runs |
| `OTP_CHANNEL_MODE` | `simulated` | The only delivery that exists: the customer web client shows the code in its inbox notice; the dev OTP endpoint stays off |
| `DEMO_SEED` | Repository variable | `true` reloads the demo customers on every deploy (it truncates the banking tables and empties the handoff queue); `make gcp-seed` does it once |
| LLM | `LLM_MODE=live`, `llm_model` and `llm_reasoning_effort` in `variables.tf`; key by `make gcp-llm-key` | The key is added by hand and never enters the Terraform state. Replay recordings are not shipped |
| Decision model | `decision_points_file` in `variables.tf`, the DistilBERT artifact by default | The encoder serves the pooled DistilBERT ([ADR-0014](adr/0014-distilbert-intent-backend.md)), the artifact `.env.example` names; a `terraform test` keeps them equal. `packages/encoder/calibration/decision_points.json` and `make gcp-apply` switch back to the `tfidf_lr` baseline, which is in the same image |
| Decision point modes | `decision_points_modes` in `local.tfvars`, empty by default | The orchestrator runs the modes of `decision_effects.yaml`: `intent_hint` and `clarify_route` in `enforce`, the rest in `shadow` ([ADR-0014](adr/0014-distilbert-intent-backend.md), amendment 2026-10-01). `intent_hint=shadow,clarify_route=shadow` and `make gcp-apply` is the kill switch, with no new image |
| Per-address conversation limit | `trusted_proxy_hops = 0`, `rate_limit_conversations_per_ip_hour = 1000` | **Stopgap** ([ADR-0015](adr/0015-gcp-cloud-run-terraform.md)): behind Google's front end the web-client BFF cannot see the customer's address, so every customer counts as one; the limit is high until the BFF forwards the address ([limitations](limitations.md)) |
| `warm` | `variables.tf`, `true` by default | One instance of the model server, `banking-core` and the orchestrator stays running; `false` scales everything to zero between presentations (about $3.5–4 a day instead of $8–11) |

### Opening the back office to judges

IAP lets in only the Google accounts in `iap_members`, and judges' accounts are not known in advance. For an evaluation window, an operator with access to the project can take IAP off the back office and give each judge a login of their own ([ADR-0015](adr/0015-gcp-cloud-run-terraform.md), amendment of 2026-10-03):

```bash
make gcp-backoffice-open JUDGES=5   # no IAP on the back office; judge1@ to judge5@ at the demo agent's domain
make gcp-judges                     # the back office URL and each judge's e-mail and password, to hand out
make gcp-smoke                      # open: the page answers, and its API refuses a request with no session
make gcp-backoffice-close           # IAP back on, the judge logins dropped
```

- **Both open and close are a full `terraform apply` that asks before it changes anything.** The plan should touch only the back office service (IAP, the invoker check, a new revision for the logins), its IAP bindings, and the judge passwords and their secret. Anything else in the plan is drift: stop and look.
- **While open, the back office's own login is its only lock**, the page faces the internet, there is no login rate limit, and every login can change the guardrails that apply to every live conversation ([limitations](limitations.md)). Keep the window short, hand each judge one login, and close it afterwards.
- **A plain `make gcp-apply` closes it too**: both variables default to off, so the next routine apply puts IAP back and drops the judge logins, unless `local.tfvars` sets them.
- **Each judge's actions are recorded under their own e-mail**, like the demo agent's. The passwords are 24 random letters and digits in the `pb-demo-judge-accounts` secret, which only the back office reads (`DEMO_EXTRA_AGENTS`).
- **Locally there is no IAP**: `DEMO_EXTRA_AGENTS` in `.env` adds the same kind of logins to `make demo`.

### Not yet exercised on this environment

The environment itself is deployed (section 6), but opening and closing the back office for judges has not been run on it yet. Opening and closing the back office is checked offline too (`tests/judging.tftest.hcl`). The IAP switch itself was tried on 2026-10-03 on a throwaway Cloud Run service (Google's hello image, the same `google_cloud_run_v2_service` settings, provider 8.5) in a separate project: closed, open and closed again were each an in-place update, with no replacement and no new revision. An anonymous visitor was refused while closed and got 200 within seconds of opening, and the Run v2 API reported `iapEnabled` the way the smoke test reads it. Not tried: the real back office in this environment, the judge logins' new revision, and IAP's Google login screen (that project has no OAuth client).
