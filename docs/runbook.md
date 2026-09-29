# Runbook

How to download, run and test the system in your own environment.

**Goal: from `git clone` to a working conversation in under 10 minutes, without asking us for anything and without credentials of your own.**

> **Internal team note — delete before submitting.**
> Every command mentioned here must exist and must have been tested on a clean machine before submission. Cross-check checklist at the end of this document. If a command does not exist yet, mark it `⚠️ pending` on its line; never leave it silently promised.

---

## 1. Quick start

```bash
git clone https://github.com/Nekobus-Bo/pattern_blue.git && cd pattern_blue
make demo
```

`make demo` builds and starts the whole stack, applies the migrations, seeds the synthetic demo data, preloads the local models, checks that everything is healthy, and prints the URLs and the demo customers to use. It needs no `.env`, no API key and no external dataset: every default is a development default that works as it is. Running it again is safe; it re-seeds, so the demo customers' cards go back to their seed state and the handoff queue is emptied.

Two things are still pending, and `make demo` says so in its summary instead of failing silently:

- ⚠️ **Replay recordings.** `eval/replay/` is empty, so replay mode has nothing to replay and a chat turn answers 503. Until the recordings exist, talk to the assistant in live mode (section 4): `LLM_MODE=live` and your `LLM_API_KEY` in `.env`. The rest of the stack works without either.
- ⚠️ **The two web frontends** (customer chat and back office). Until they exist the system is driven over HTTP, see the URLs in section 6.

---

## 2. Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Docker + Docker Compose | v2 | The only mandatory container dependency |
| `make` and `bash` | any | `make` is the single entry point (`make help` lists the targets) |
| Network | first run only | Base images, Python packages and the `kb.search` embedding model are downloaded once; later runs reuse the caches |
| Free RAM | 4 GB | Local models run on CPU, no GPU |
| Cores | 2 | |
| Disk | TODO GB | Includes local model weights |
| Architecture | x86_64 and arm64 | Tested on both, Apple Silicon included |
| Ports | 8080, 8081, 8090 (and 5173, 5174 once the frontends exist) | Bound to `127.0.0.1` only. Configurable in `.env` if taken |

No Python, Node or Bun needed on the host: everything runs in containers. `make demo` needs only Docker Compose, `make` and `bash`.

---

## 3. Run modes

The system starts in one of two modes. The difference is where the language model's responses come from.

| | **Replay mode** (default) | **Live mode** |
|---|---|---|
| API key | Not required | Required |
| LLM responses | Prerecorded from our runs | Generated in real time |
| Conversations | Those in the demo and evaluation scripts | Anything |
| Determinism | Total: reproduces the reported metrics exactly | Variable |
| Use it for | Verifying the system and reproducing results without credentials | Testing with your own messages |

**Why replay mode exists.** We cannot publish an API key in a repository, and we do not want testing the system to depend on you having a provider account. Also, by fixing the model's responses, the metrics in [evaluation.md](evaluation.md) reproduce exactly, which is what a reproducible result is supposed to mean.

In replay mode, a message with no recording is answered with an explicit error (HTTP 503, `replay_miss`). The system **does not improvise or simulate** a response: we would rather the limit be visible.

> ⚠️ **Pending:** the recordings themselves. `eval/replay/` is empty, so today replay mode replays nothing; the orchestrator container already mounts that folder read-only, so recordings work as soon as they are committed. Until then use live mode.

---

## 4. Live mode

```bash
cp .env.example .env
# edit .env and set:
#   LLM_MODE=live
#   LLM_API_KEY=<your key>
#   (LLM_BASE_URL and LLM_MODEL: see the comments in .env.example)
make demo      # or just `make up`: it recreates the orchestrator with the new environment
```

`.env.example` carries the same development values as the built-in defaults, so copying it changes nothing except what you edit.

The key we used is in the submission email, in case you prefer not to use your own. Provider and model are configurable in `.env`: the access layer is OpenAI-compatible, so any provider honoring that API works.

---

## 5. The dataset

**The dataset is not in the repository.** It is material provided by the organization and redistributing it is not ours to decide. The system ships with a small synthetic sample, enough for the demo and for replay mode.

To seed the database with the full dataset:

```bash
cp -r <path-to-dataset> data/raw/factored     # the dataset delivered to teams
make ingest SOURCE=factored                   # maps it into data/staging/factored
make seed
```

`make seed` validates the data contract before loading and **fails with an explicit message** if `data/raw/` holds a dataset it has no ingest mapping for, or if the staged data does not match the expected schema. The demo customers are always loaded, first; the delivered dataset is added after them ([ADR-0011](adr/0011-hybrid-seed-dataset-ingest.md)). The field-by-field mapping against the data dictionary is in [data.md](data.md).

---

## 6. Step by step

```bash
git clone https://github.com/Nekobus-Bo/pattern_blue.git
cd pattern_blue
cp .env.example .env    # only to use live mode (section 4); not needed otherwise

make demo               # everything below, in one command
```

`make demo` runs these steps in order; each one is also a target you can run alone:

1. Checks that Docker Compose and the Docker daemon are available.
2. Builds the images (the first build takes several minutes; later runs reuse the cache).
3. Preloads the local models: `make warmup-encoder` (builds the configured encoder backend once, so a bad backend fails here) and `make warmup-retrieval` (puts the `kb.search` embedding model in the `hf-cache` volume; it uses the network only if the model is not cached). If the download fails, `make demo` continues and prints a warning: everything but `kb.search` works, and `make warmup-retrieval` fixes it once you are online.
4. `make up`: starts the services and waits until they are healthy. The migrations run first, as a dependency of `banking-core`.
5. `make seed`: loads the synthetic demo data. It truncates and reloads it, which is what makes running `make demo` twice safe.
6. `make smoke` and a `banking-core` readiness check, then the summary: URLs, the assistant's mode (with the notice when there are no recordings), the demo customers and the admin API hint.

To go one step at a time instead: `make warmup`, `make up`, `make seed`, `make smoke`.

| Service | Local URL |
|---|---|
| Customer chat (⚠️ pending) | http://localhost:5173 |
| Agent back office & metrics (⚠️ pending) | http://localhost:5174 |
| Orchestrator: chat API and its docs | http://localhost:8080/docs |
| Internal API (docs) | http://localhost:8081/docs |

Backend containers include `postgres`, `banking-core`, `orchestrator`, `encoder`, and one Redis per trust zone ([ADR-0006](adr/0006-single-postgres-pgvector.md)): `redis-core` (internal network, used only by `banking-core`) and `redis-edge` (perimeter network, used by `orchestrator`).

**Demo customers** (synthetic, identified by document and birth date, source of truth `apps/banking-core/src/banking_core/seed/fixtures.py`; `make demo` prints them too):

| Language | Name | Document | Born | Card |
|---|---|---|---|---|
| es | Carlos Gomez | NATIONAL_ID `1020304050` | 1988-05-20 | ending 1050 |
| pt | Mariana Silva | NATIONAL_ID `12345678900` | 1988-05-20 | ending 1060 |
| en | Alice Johnson | PASSPORT `P12345678` | 1988-05-20 | ending 1070 |

Each language also has a customer whose card is already blocked and one with no OTP channel (the latter must end in a human handoff).

**Back-office actions over HTTP** (until the back office exists): in development the admin API is on with the public, development-only token `dev-only-admin-token`, so `GET`/`PUT http://localhost:8081/v1/admin/policy-config` work with `Authorization: Bearer dev-only-admin-token`. `banking-core` refuses to start with that token under `APP_ENV=production`. Agent login for the back office (⚠️ pending) is `DEMO_AGENT_*` in `.env.example`.

**OTP codes** go to a simulated channel that the customer web client will show (⚠️ pending). Until then, for local use only, set `ALLOW_DEV_OTP_HOOK=true` in `.env`, run `make up`, and read a code at `GET http://localhost:8081/v1/dev/otp/<challenge_id>`.

> The first `make demo` builds the images and downloads the embedding model: **TODO minutes** depending on your connection, around **TODO MB** (not measured yet). Later runs come from cache.

### What `make smoke` should print

```
✓ postgres       healthy
✓ redis-core     healthy
✓ redis-edge     healthy
✓ banking-core   healthy
✓ orchestrator   healthy
✓ encoder        healthy
✓ migration      applied head (<revision>)
smoke: OK
```

If anything comes up red, see section 10.

---

### Running several copies

Two clones (or git worktrees) can run at the same time if each has its own compose project name and its own host ports. Otherwise the second `make demo` or `make up` reuses the first one's project and ports, and a `make down` in one tears down the other.

```bash
COMPOSE_PROJECT_NAME=pb-b PORT_ORCHESTRATOR=58180 PORT_BANKING_CORE=58181 PORT_ENCODER=58190 make demo
COMPOSE_PROJECT_NAME=pb-b PORT_ORCHESTRATOR=58180 PORT_BANKING_CORE=58181 PORT_ENCODER=58190 make smoke
```

Use the same variables for `make down` and `make logs` (or put them in that copy's `.env`). Containers, networks, volumes and image tags are all prefixed by the project name. The default is `pattern-blue`.

---

## 7. Demo walkthrough (5 minutes)

Works the same in replay and live mode.

1. **Happy path (⚠️ pending UI).** Open the chat and report a charge you do not recognize. Watch: intent classification with its score, ownership matching without disclosing data, the verification code, the card block, and the **verified receipt** re-read from the database.
2. **The system stops (⚠️ pending UI).** Ask to dispute the charge. The structured handoff appears and the case enters the back-office queue with verified facts, actions taken, verification method and open questions.
3. **Takeover (⚠️ pending UI).** From the back office, take the conversation and reply as a human agent.
4. **Guardrail, live (⚠️ pending UI).** The threshold is compared against the amount of the disputed charge **as stored in the database**, never against what the customer types. The demo customer holds an unrecognized charge (Global Electronics Megastore, USD 139.99 for the English customer), and the default USD threshold is USD 500, so step 1 ends with the card blocked and no handoff. Lower the USD threshold to, say, USD 100 and set the mode to `block` (handoff required), then repeat the same conversation: the card is still blocked, but the conversation now ends in a **priority handoff** to a human agent, created by the system itself and not by the model, instead of automated resolution. No deployment, no restart. Until the back-office UI exists, change the policy with the banking-core admin API (`PUT /v1/admin/policy-config`, see [deployment.md](deployment.md)); in `flag` mode (handoff recommended) the same change only suggests the handoff.
5. **Another workflow, no code (⚠️ pending UI).** Load the second workflow's configuration and use it right away. The diff is on screen: configuration only.
6. **Language (⚠️ pending UI).** Repeat step 1 in Portuguese.

Full scripts with exact messages: `demo/scripts/`.

---

## 8. Reproducing the reported metrics

```bash
make eval              # ⚠️ pending — baseline and proposed system on the scenario suite
make eval-adversarial  # ⚠️ pending — injection and abuse scenarios
make data-quality      # data quality report, written to reports/data-quality.md
make verify-audit      # verifies the audit log hash chain
```

Reports are written to `reports/` and versioned in the repository: you can compare your run against ours file by file. In replay mode the result must be **identical**; any difference is a finding and we want to hear about it.

`make eval` (⚠️ pending) takes around **TODO minutes**.

---

## 9. Deployment and the presentation environment

**There is no hosted instance for judges.** You run the system on your own machine with `make demo` (section 1); that is the supported way to evaluate it, and nothing here depends on a server of ours being up.

The team keeps its own environment for its live presentation. It is not part of the evaluation, no link is published, and no availability is promised. What it is, how it is deployed and which demo features it switches on are described in **[deployment.md](deployment.md)**, section 7 (the platform is still to be decided, `⚠️ pending`). Production architecture, host Redis ACL configuration and scalability limits are in the same document.

```bash
make deploy    # ⚠️ pending — the CD workflow deploys over SSH without calling it, see deployment.md
```

That environment runs the same images as `make demo`: there is no special path that only works in production.

---

## 10. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| A chat turn answers 503 (`replay_miss`, or no provider key) | Replay mode with no recording for that message (no recordings exist yet, ⚠️ pending), or live mode without a valid `LLM_API_KEY` | Switch to live mode (section 4). `make demo` prints this as a notice when it finishes |
| `make demo` stops at "the Docker daemon is not reachable" | Docker is not running | Start Docker and run `make demo` again |
| `make demo` warns that the embedding model could not be preloaded | No network on the first run, so `kb.search` is unavailable | Get online and run `make warmup-retrieval`; the rest of the stack is unaffected |
| `banking-core` `/ready` answers 503 `knowledge search unavailable` | The embedding model is not in the `hf-cache` volume | `make warmup-retrieval`, then `make logs s=banking-core` if it persists |
| Cannot download models even with a network | Corrupted cache | `make clean-models` (⚠️ pending), or `make clean` (also deletes the data) and `make demo` |
| A `make` command does not exist | Not implemented yet | `make help` lists the available ones |
| Chat replies but takes no actions | `make seed` was not run (`make demo` runs it) | `make seed` and retry |
| I ran `make demo` again and my cards and handoffs are gone | It re-seeds by design | Expected: the demo data is reset to its seed state |
| `make seed` fails with a contract error | Dataset missing or schema mismatch | See section 5; the message names the exact field |
| High latency on the first turn | Encoder or embedding model cold start | Normal on a stack that was not started with `make demo`, which warms both; `make warmup` preloads them |
| Port already in use | Another local service on the same port | Change ports in `.env` |
| Encoder container keeps restarting | Less than 4 GB RAM available | Raise Docker's memory limit |
| `make smoke` fails | A service is unhealthy or not running | Run `make logs s=<service>` to inspect |
| Back office does not update live | WebSocket blocked by a proxy | Check the reverse proxy |
| No provider response in live mode | Invalid key or exhausted quota | Check `.env`. The system degrades to an unavailability message: **it does not invent responses** |
| Image will not start on Apple Silicon | Wrong architecture build | Report it: images are multi-arch and that would be our bug |
| `make data-quality` cannot write to `reports/` | On Linux, `reports/` is owned by a different uid | The container writes as uid 1000: `sudo chown -R 1000:1000 reports/`, or run the service with `--user $(id -u):$(id -g)` |

```bash
make logs                  # logs from all services
make logs s=banking-core   # from one
make down                  # stop
make clean                 # stop and drop volumes (destroys seeded data)
```

---

## 11. Contact

**TODO:** members, email and availability during the jury review window.

---

## Cross-check checklist (internal, delete before submitting)

Test on a clean machine, with no Docker cache, before submitting:

- [ ] `git clone` + `make demo` works with no `.env` and no key (the chat answers 503 until recordings exist or a key is set, and `make demo` says so)
- [ ] Every command mentioned in this document exists in the `Makefile`
- [ ] Every URL in section 6 responds
- [ ] The real output of `make smoke` matches section 6
- [ ] Running `make demo` twice in a row succeeds, on a clean machine and on one with the caches warm
- [ ] `make seed` fails with a clear message when `data/raw/` holds a dataset with no ingest mapping
- [ ] `make eval` (⚠️ pending) in replay mode reproduces the numbers in `evaluation.md`
- [ ] Tested on x86_64 and on arm64 (`make build-multiarch` builds both; CI does it too. On Linux, install QEMU emulators first: `docker run --privileged --rm tonistiigi/binfmt --install all`)
- [ ] Tested with no API key and with an invalid key
- [ ] Every TODO in this document replaced with a real value
- [ ] Nothing in this document, the README or `00-problem.md` promises judges a hosted instance or an availability window
