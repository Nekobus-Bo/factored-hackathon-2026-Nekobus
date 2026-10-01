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

`make demo` builds and starts the whole stack (the two web front ends included), applies the migrations, seeds the synthetic demo data, preloads the local models, checks that everything is healthy, and prints the URLs, the back-office login and the demo customers to use. It needs no `.env`, no API key and no external dataset: every default is a development default that works as it is. Running it again is safe; it re-seeds, so the demo customers' cards go back to their seed state and the handoff queue is emptied.

One thing is still pending, and `make demo` says so in its summary instead of failing silently:

- ⚠️ **Replay recordings.** `eval/replay/` is empty, so replay mode has nothing to replay and a chat turn answers 503. Until the recordings exist, talk to the assistant in live mode (section 4): `LLM_MODE=live` and your `LLM_API_KEY` in `.env`. The rest of the stack works without either: both web front ends open, the back office shows its queue, guardrails and metrics, and the customer chat says plainly that a message could not be sent.

When it finishes, open the customer chat at http://localhost:5173 and the back office at http://localhost:5174 (login in section 6).

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
| Ports | 5173 (customer chat), 5174 (back office), 8080, 8081, 8090 | Bound to `127.0.0.1` only. Configurable in `.env` if taken |

No Python, Node or Bun needed on the host: everything, the two front ends included, is built and runs in containers. `make demo` needs only Docker Compose, `make` and `bash`. Bun 1.3 or later is needed only to work on a front end from the host (`make web-client`, `make web-backoffice`, `make web-check`).

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
3. Preloads the local models on the model server (the `encoder` service): `make warmup-encoder` (builds the configured decision backend once, so a bad backend fails here) and `make warmup-retrieval` (puts the pinned `kb.search` embedding model, `EMBEDDING_MODEL` at `EMBEDDING_REVISION`, in the `hf-cache` volume and prints the hash to pin; it uses the network only if the model is not cached). If the download fails, `make demo` continues and prints a warning: everything but `kb.search` works, and `make warmup-retrieval` fixes it once you are online.
4. `make up`: starts the services and waits until they are healthy. The migrations run first, as a dependency of `banking-core`.
5. `make seed`: loads the synthetic demo data. It truncates and reloads it, which is what makes running `make demo` twice safe.
6. `make smoke` and a `banking-core` readiness check, then the summary: the URLs of the customer chat and the back office, the back-office login, the assistant's mode (with the notice when there are no recordings), the demo customers and the admin API hint.

To go one step at a time instead: `make warmup`, `make up`, `make seed`, `make smoke`.

| Service | Local URL |
|---|---|
| Customer chat (`web-client`) | http://localhost:5173 |
| Agent back office & metrics (`web-backoffice`) | http://localhost:5174 |
| Orchestrator: chat API and its docs | http://localhost:8080/docs |
| Internal API (docs) | http://localhost:8081/docs |

**Back office login** (the one demo agent): `agent@demo.local` / `demo-only-change-me`. These are development-only credentials, public in this repository; they are `DEMO_AGENT_EMAIL` and `DEMO_AGENT_PASSWORD` in `.env.example`, and the back office refuses to start with them under `APP_ENV=production`. The email is recorded on every claim and takeover.

The containers are `postgres`, `banking-core`, `orchestrator`, `encoder`, one Redis per trust zone ([ADR-0006](adr/0006-single-postgres-pgvector.md)): `redis-core` (internal network, used only by `banking-core`) and `redis-edge` (perimeter network, used by `orchestrator`), and the two front ends, `web-client` and `web-backoffice`. Each front end is a Bun server that serves its page and a same-origin BFF: the browser never talks to the orchestrator or `banking-core` directly, and the tokens stay in the back-office server ([ADR-0013](adr/0013-front-ends-bff-takeover.md)). To work on one from the host, with hot reload, against the stack from `make up`:

```bash
docker compose -f infra/compose/docker-compose.yml stop web-client   # the container holds :5173
make web-client                                                      # or: make web-backoffice (stop web-backoffice first)
```

Both need Bun. They reach the stack on `PORT_ORCHESTRATOR` and `PORT_BANKING_CORE` (8080 and 8081; pass them on the command line if you changed them) and use the development tokens and login.

**Demo customers** (synthetic, identified by document and birth date, source of truth `apps/banking-core/src/banking_core/seed/fixtures.py`; `make demo` prints them too):

| Language | Name | Document | Born | Card |
|---|---|---|---|---|
| es | Carlos Gomez | NATIONAL_ID `1020304050` | 1988-05-20 | ending 1050 |
| pt | Mariana Silva | NATIONAL_ID `12345678900` | 1988-05-20 | ending 1060 |
| en | Alice Johnson | PASSPORT `P12345678` | 1988-05-20 | ending 1070 |

Each language also has a customer whose card is already blocked and one with no OTP channel (the latter must end in a human handoff).

**Back-office actions over HTTP** (the alternative to the back office: it makes these same calls from its screens): in development the admin API is on with the public, development-only token `dev-only-admin-token`, so `GET`/`PUT http://localhost:8081/v1/admin/policy-config` work with `Authorization: Bearer dev-only-admin-token`. `banking-core` refuses to start with that token under `APP_ENV=production`. The same token lists the handoff queue (`GET /v1/admin/handoffs`), shows a case (`GET /v1/admin/handoffs/<handoff_ref>`), takes it (`POST /v1/admin/handoffs/<handoff_ref>/claim` with `{"agent_ref": "<email>"}`) and returns counts (`GET /v1/admin/metrics?hours=24`). Taking a case from the API only claims it in `banking-core`; the back office also takes the conversation over in the orchestrator (the agent API, `AGENT_API_TOKEN`), which is what lets the agent write to the customer.

**OTP codes** go to a simulated channel and the customer web client shows them: when the assistant sends a code, the chat says "you got an email with the code" (with the masked destination and a countdown), and "Open inbox" then "Show code" reveal it. Nothing is sent anywhere, and the code disappears at expiry (`OTP_TTL_SECONDS`). Only for scripts, and for local use only, set `ALLOW_DEV_OTP_HOOK=true` in `.env`, run `make up`, and read a code at `GET http://localhost:8081/v1/dev/otp/<challenge_id>`.

> The first `make demo` builds the images and downloads the embedding model: **TODO minutes** depending on your connection, around **TODO MB** (not measured yet). Later runs come from cache.

### What `make smoke` should print

```
✓ postgres       healthy
✓ redis-core     healthy
✓ redis-edge     healthy
✓ banking-core   healthy
✓ orchestrator   healthy
✓ encoder        healthy
✓ web-client     healthy
✓ web-backoffice healthy
✓ migration      applied head (<revision>)
smoke: OK
```

The two front ends' check is `GET /healthz` inside the container: liveness only, it does not call the orchestrator or `banking-core`.

If anything comes up red, see section 10.

---

### Running several copies

Two clones (or git worktrees) can run at the same time if each has its own compose project name and its own host ports. Otherwise the second `make demo` or `make up` reuses the first one's project and ports, and a `make down` in one tears down the other.

```bash
COMPOSE_PROJECT_NAME=pb-b PORT_ORCHESTRATOR=58180 PORT_BANKING_CORE=58181 PORT_ENCODER=58190 PORT_WEB_CLIENT=58173 PORT_WEB_BACKOFFICE=58174 make demo
COMPOSE_PROJECT_NAME=pb-b PORT_ORCHESTRATOR=58180 PORT_BANKING_CORE=58181 PORT_ENCODER=58190 PORT_WEB_CLIENT=58173 PORT_WEB_BACKOFFICE=58174 make smoke
```

Use the same variables for `make down` and `make logs` (or put them in that copy's `.env`). Containers, networks, volumes and image tags are all prefixed by the project name. The default is `pattern-blue`.

---

## 7. Demo walkthrough (5 minutes)

Works the same in replay and live mode.

1. **Happy path.** Open the customer chat (http://localhost:5173) and report a charge you do not recognize. Watch: intent classification with its score, ownership matching without disclosing data, the verification code, the card block, and the **verified receipt** re-read from the database. Talking to the assistant needs an LLM key in `.env` (section 4) until the replay recordings exist (section 3). Nothing is sent: the code arrives as a simulated "you got an email with the code" notice in the chat (a demo customer's registered channel is email), read from an in-app inbox that expires with the code (`OTP_TTL_SECONDS`, 5 minutes by default): "Open inbox", then "Show code". Whoever sees the browser sees the code: in the demo the OTP does not prove possession of the channel ([limitations.md](limitations.md)).
2. **The system stops.** Ask to dispute the charge. The structured handoff appears in the chat (the customer sees the state, never the summary) and the case enters the back-office queue (http://localhost:5174, login in section 6; the queue refreshes every 3 seconds) with verified facts, actions taken, verification method and open questions.
3. **Takeover.** In the back office, open the case and press "Tomar caso" ("Take case" in English; the language switch is in the header). The claim is audited with the agent's email (`admin.handoff.claimed`), the conversation switches to the agent and the reply box opens. Reply as a human agent: the customer's chat shows "Un agente está atendiendo tu caso" (in the customer's language) and the message within 2 seconds. From then on the assistant never sees that conversation, and there is no hand-back ([limitations.md](limitations.md)).
4. **Guardrail, live.** The threshold is compared against the amount of the disputed charge **as stored in the database**, never against what the customer types. The demo customer holds an unrecognized charge (Global Electronics Megastore, USD 139.99 for the English customer), and the default USD threshold is USD 500, so step 1 ends with the card blocked and no handoff. In the back office, open **Guardrails**, lower the USD threshold to 100, set the mode to "handoff required" (`block`), press "Save changes" and confirm. Then repeat the same conversation: the card is still blocked, but the conversation now ends in a **priority handoff** to a human agent, created by the system itself and not by the model, instead of automated resolution. No deployment, no restart. In `flag` mode (handoff recommended) the same change only suggests the handoff. The same change over the API, as the alternative (the request replaces the whole set of thresholds; the development token is `dev-only-admin-token`):

   ```bash
   curl -sS -X PUT http://localhost:8081/v1/admin/policy-config \
     -H "Authorization: Bearer dev-only-admin-token" -H "Content-Type: application/json" \
     -d '{"amount_mode": "block", "thresholds_minor": {"USD": 10000, "EUR": 50000, "BRL": 250000, "COP": 200000000, "ARS": 17795642}}'
   ```

   Put it back the same way, with `"amount_mode": "flag"` and `"USD": 50000`. "Reset demo" in Guardrails restores the demo cards and the tools, not the thresholds or the mode.
5. **Another workflow, no code.** The second workflow, account inquiries, uses `account.get_summary`, which starts disabled. As a verified customer, ask for your balance: the assistant says it cannot help with that here, because banking-core refuses the tool (audited as `TOOL_DISABLED`). Then, in the back office, open **Guardrails**, find `account.get_summary` in "Tools by state", switch it on and save. Or enable it, live, with the admin API (in development it is already on; use your own `ADMIN_API_TOKEN` if `.env` sets one; banking-core listens on `PORT_BANKING_CORE`, 8081 by default):

   ```bash
   curl -sS -X PUT http://localhost:8081/v1/admin/tool-policy \
     -H "Authorization: Bearer $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"tools": {"account.get_summary": ["VERIFIED"]}}'
   ```

   Ask again: the balance comes back. No deployment, no restart, no code: the response is the new policy version, and the audit row `admin.tool_policy.updated` keeps the before and after. `GET /v1/admin/tool-policy` shows the policy in force and the code floor; asking for a state beyond it (for example `card.block` for `ANONYMOUS`) is refused with a 422, and the Guardrails screen shows that refusal when you click a cell beyond the floor. To run the demo again, "Reset demo" in Guardrails, or `POST /v1/admin/demo/reset-fixtures` with the same header (and `DEMO_RESET_ENABLED=true` under `APP_ENV=production`), puts the tool back to disabled, along with the demo cards.
6. **Language.** Repeat step 1 in Portuguese. The customer page follows the browser's language (Spanish, Portuguese or English; Spanish when it is none of them) and has a language switch in its header.

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
| A chat turn answers 503 (`replay_miss`, or no provider key); in the chat the message stays marked "Not sent" with a "Try again" button | Replay mode with no recording for that message (no recordings exist yet, ⚠️ pending), or live mode without a valid `LLM_API_KEY` | Switch to live mode (section 4). `make demo` prints this as a notice when it finishes |
| `make demo` stops at "the Docker daemon is not reachable" | Docker is not running | Start Docker and run `make demo` again |
| `make demo` warns that the embedding model could not be preloaded | No network on the first run, so `kb.search` is unavailable | Get online and run `make warmup-retrieval`; the rest of the stack is unaffected |
| `banking-core` `/ready` answers 503 `knowledge search unavailable` | The model server is not up yet or unreachable at `MODEL_SERVER_URL`; or the embedding model is not in its `hf-cache` volume (`GET http://localhost:8090/ready` shows `embedding.state`); or `EMBEDDING_MODEL`/`EMBEDDING_REVISION` differ between banking-core and the model server | `make warmup-retrieval`, check both services use the same two variables, then `make logs s=banking-core` and `make logs s=encoder` if it persists |
| `encoder` exits at startup with a message that starts `embedding:` | `EMBEDDING_MODEL` is set but the pin is invalid (`EMBEDDING_REVISION` must be a full 40-hex commit), the cached weights do not match `EMBEDDING_WEIGHTS_SHA256`, or the image was built without `ENCODER_EXTRAS=embed` | Fix the variable the message names, or rebuild with `ENCODER_EXTRAS=embed` (`make up` does), or unset `EMBEDDING_MODEL` to run without `kb.search` |
| Cannot download models even with a network | Corrupted cache | `make clean-models` (⚠️ pending), or `make clean` (also deletes the data) and `make demo` |
| A `make` command does not exist | Not implemented yet | `make help` lists the available ones |
| `orchestrator` exits at startup with a message that starts `effects file` or `DECISION_POINTS_MODES` | The decision-effects file is invalid, or the override in `.env` is malformed or names a decision point that is not in the file. It fails loud on purpose: a gate that cannot be read must not be guessed | Fix what the message names (`apps/orchestrator/config/decision_effects.yaml`, `DECISION_EFFECTS_FILE`, `DECISION_POINTS_MODES`) |
| Chat replies but takes no actions | `make seed` was not run (`make demo` runs it) | `make seed` and retry |
| I ran `make demo` again and my cards and handoffs are gone | It re-seeds by design | Expected: the demo data is reset to its seed state |
| `make seed` fails with a contract error | Dataset missing or schema mismatch | See section 5; the message names the exact field |
| High latency on the first turn | Encoder or embedding model cold start | Normal on a stack that was not started with `make demo`, which warms both; `make warmup` preloads them |
| `banking-core` exits at startup with "no real OTP delivery provider is implemented; set OTP_CHANNEL_MODE=simulated" | `OTP_CHANNEL_MODE` in `.env` is not `simulated`; it is the only delivery mode implemented | Set `OTP_CHANNEL_MODE=simulated` (or remove it: unset means `simulated`) |
| The "you got an email with the code" notice is gone or empty | The code expired (`OTP_TTL_SECONDS`), or the conversation or its banking session expired | Ask for a new code; the inbox only holds unexpired ones |
| Port already in use | Another local service on the same port | Change ports in `.env` |
| Encoder container keeps restarting | Less than 4 GB RAM available | Raise Docker's memory limit |
| `make smoke` fails | A service is unhealthy or not running | Run `make logs s=<service>` to inspect |
| Back office (or the chat, during a takeover) does not update on its own | Nothing is pushed: both poll (the queue every 3 s, an open case and a taken-over chat every 2 s), and only while the tab is visible, so a background tab catches up when you come back to it | Bring the tab forward. There is no WebSocket, so a proxy is not the cause; if requests fail, `make logs s=web-backoffice` and `make logs s=web-client` |
| The back office logs in but its screens show an error instead of data (`/api/handoffs` answers 404, or 502 `upstream_unauthorized`) | The admin API or the agent API is off (404), or its token differs from the one the back office holds (502) | Check `ADMIN_API_ENABLED`, `AGENT_API_ENABLED`, `ADMIN_API_TOKEN` and `AGENT_API_TOKEN` in `.env`; in development the defaults already match. Then `make up` |
| The back office rejects `agent@demo.local` | `DEMO_AGENT_EMAIL` or `DEMO_AGENT_PASSWORD` was changed in `.env` | Use the values in `.env`, then `make up` if you just changed them |
| No provider response in live mode | Invalid key or exhausted quota | Check `.env`. The system degrades to an unavailability message: **it does not invent responses** |
| Image will not start on Apple Silicon | Wrong architecture build | Report it: images are multi-arch and that would be our bug |
| `make data-quality` cannot write to `reports/` | On Linux, `reports/` is owned by a different uid | The container writes as uid 1000: `sudo chown -R 1000:1000 reports/`, or run the service with `--user $(id -u):$(id -g)` |

```bash
make logs                  # logs from all services
make logs s=banking-core   # from one
make down                  # stop
make clean                 # stop and drop volumes (destroys seeded data)
```

### Turning a decision point down (the mode kill switch)

Each decision point of [ADR-0012](adr/0012-decision-points.md) has a mode in `apps/orchestrator/config/decision_effects.yaml`: `off` (ignored), `shadow` (computed and recorded, nothing changes) or `enforce` (applied). Every one ships in `shadow`. If one that was flipped to `enforce` misbehaves in a demo or on the presentation environment (a gate asking for a confirmation it should not, a block reason that looks wrong), turn it down with an environment change and no code:

```bash
# .env
DECISION_POINTS_MODES=confirm_gate=shadow,block_reason=off

make up          # recreates the orchestrator with the new value
```

`id=mode` pairs, separated by commas; the override wins over the file. An entry that cannot be read, or that names a decision point the file does not have, stops the orchestrator at startup instead of being skipped, so a typo cannot leave the decision point enforcing. Check it took effect in the turn metadata (`mode` of each decision record) or in the orchestrator log at startup (`Decision points from ...: confirm_gate=shadow, ...`). Emptying the variable restores the modes of the file. Turning `confirm_gate` down to `shadow` removes the confirmation question: `card.block` is again the LLM's proposal, authorized by banking-core as before.

### Switching the decision model back to the baseline

The encoder serves the pooled DistilBERT by default ([ADR-0014](adr/0014-distilbert-intent-backend.md)). If it misbehaves, go back to the `tfidf_lr` artifact with an environment change; the weights stay in the image, unused:

```bash
# .env
DECISION_POINTS_FILE=packages/encoder/calibration/decision_points.json

make up          # recreates the encoder; /v1/decision-points shows the other config_version
```

To make one market stricter without recalibrating, raise its threshold (raise-only; a value at or below the calibrated one stops the encoder at startup):

```bash
DECISION_POINTS_TAU_RAISE=turn_intent.es-MX=0.9,intent_hint.pt-BR=0.95
```

### Retraining and publishing the decision model

Needs the local regional datasets (`data/staging/`, not versioned), Apple Silicon or CPU, Docker with buildx, and a Docker Hub login with write access to the seed repository.

```bash
make pool-data-regional                       # pt-BR + es-MX + es-AR (+ English validation/test)
make train-encoder                            # ~3 min on MPS; gates per locale, writes a pinned dir
make encoder-weights-image DOCKERHUB_NAMESPACE=<namespace> PUSH=1
#   prints: pin in apps/encoder/Dockerfile: docker.io/<namespace>/pattern_blue-encoder-weights@sha256:<digest>
```

Then, in one pull request:

1. Put the printed digest in the `ENCODER_WEIGHTS_IMAGE` default of `apps/encoder/Dockerfile`.
2. Put the pins `make train-encoder` printed (`model_id`, `revision`, `weights_sha256`) in `tools/calibrate/configs/decision_points_distilbert.yaml`.
3. Recalibrate and verify: `make calibrate TASK=decision-points CONFIG=tools/calibrate/configs/decision_points_distilbert.yaml OUT=reports`, then `make calibration-verify ARTIFACT=packages/encoder/calibration/decision_points.distilbert.json`.
4. Rebuild and check: `make up && make warmup-encoder` (fails loud if the image's weights and the artifact's pins disagree).

A new digest invalidates nothing that is enforced today; once `intent_hint` is in `enforce`, it also means re-recording the replays.

---

## 11. Contact

**TODO:** members, email and availability during the jury review window.

---

## Cross-check checklist (internal, delete before submitting)

Test on a clean machine, with no Docker cache, before submitting:

- [ ] `git clone` + `make demo` works with no `.env` and no key (the chat answers 503 until recordings exist or a key is set, and `make demo` says so)
- [x] Every command mentioned in this document exists in the `Makefile` (a static check: every `make <target>` in this file and in the README is a target)
- [ ] Every URL in section 6 responds, and the back-office login in section 6 signs in
- [ ] The walkthrough in section 7 runs in a browser, steps 1 to 6 (steps 1 to 3 need an LLM key until the replay recordings exist)
- [ ] The real output of `make smoke` matches section 6
- [ ] Running `make demo` twice in a row succeeds, on a clean machine and on one with the caches warm
- [ ] `make seed` fails with a clear message when `data/raw/` holds a dataset with no ingest mapping
- [ ] `make eval` (⚠️ pending) in replay mode reproduces the numbers in `evaluation.md`
- [ ] Tested on x86_64 and on arm64 (`make build-multiarch` builds both; CI does it too. On Linux, install QEMU emulators first: `docker run --privileged --rm tonistiigi/binfmt --install all`)
- [ ] Tested with no API key and with an invalid key
- [ ] Every TODO in this document replaced with a real value
- [ ] Nothing in this document, the README or `00-problem.md` promises judges a hosted instance or an availability window
