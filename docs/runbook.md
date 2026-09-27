# Runbook

How to download, run and test the system in your own environment.

**Goal: from `git clone` to a working conversation in under 10 minutes, without asking us for anything and without credentials of your own.**

> **Internal team note — delete before submitting.**
> Every command mentioned here must exist and must have been tested on a clean machine before submission. Cross-check checklist at the end of this document. If a command does not exist yet, mark it `⚠️ pending` on its line; never leave it silently promised.

---

## 1. Quick start

```bash
git clone <TODO-repo> && cd <TODO-repo>
make demo  # ⚠️ pending
```

`make demo` (⚠️ pending) brings everything up in **replay mode**: no API key, no external dataset, model responses prerecorded. Enough to see the full system working immediately. To try it live with your own messages, see section 4.

---

## 2. Requirements

| Requirement | Minimum | Notes |
|---|---|---|
| Docker + Docker Compose | v2 | The only mandatory dependency |
| Free RAM | 4 GB | Local models run on CPU, no GPU |
| Cores | 2 | |
| Disk | TODO GB | Includes local model weights |
| Architecture | x86_64 and arm64 | Tested on both, Apple Silicon included |
| Ports | 5173, 5174, 8080, 8081 | Configurable in `.env` if taken |

No Python, Node or Bun needed on the host: everything runs in containers.

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

In replay mode, a message with no recording returns an explicit "no recording for this input" notice. The system **does not improvise or simulate** a response: we would rather the limit be visible.

---

## 4. Live mode

```bash
cp .env.example .env
# edit .env and set:
#   LLM_MODE=live
#   LLM_API_KEY=<your key>
make up  # ⚠️ pending
```

The key we used is in the submission email, in case you prefer not to use your own. Provider and model are configurable in `.env`: the access layer is OpenAI-compatible, so any provider honoring that API works.

---

## 5. The dataset

**The dataset is not in the repository.** It is material provided by the organization and redistributing it is not ours to decide. The system ships with a small synthetic sample, enough for the demo and for replay mode.

To seed the database with the full dataset:

```bash
cp <path-to-dataset> data/raw/     # the same file delivered to teams
make seed  # ⚠️ pending
```

`make seed` (⚠️ pending) validates the data contract before loading and **fails with an explicit message** if the file is missing or does not match the expected schema. The field-by-field mapping against the data dictionary is in [data.md](data.md).

---

## 6. Step by step

```bash
git clone <TODO-repo>
cd <TODO-repo>
cp .env.example .env    # only if you are going to use live mode

make up                 # ⚠️ pending — services, migrations and model download
make seed               # ⚠️ pending — seed the database
make smoke              # ⚠️ pending — installation check
```

| Service | Local URL |
|---|---|
| Customer chat | http://localhost:5173 |
| Agent back office & metrics | http://localhost:5174 |
| Internal API (docs) | http://localhost:8081/docs |

**Demo credentials:** in `.env.example`. They belong to a test environment with non-production data.

> The first `make up` (⚠️ pending) downloads local model weights: **TODO minutes** depending on your connection, around TODO MB. Later runs come from cache. `make warmup` (⚠️ pending) preloads the models so the first turn does not pay the cold start.

### What `make smoke` (⚠️ pending) should print

```
✓ postgres        healthy
✓ redis           healthy
✓ banking-core    healthy   (migrations: TODO applied)
✓ orchestrator    healthy
✓ encoder         loaded    (TODO ms p95 over TODO test turns)
✓ knowledge base  TODO snippets indexed
✓ seeds           TODO customers, TODO cards, TODO transactions
✓ end-to-end conversation  OK
```

If anything comes up red, see section 10.

---

## 7. Demo walkthrough (5 minutes)

Works the same in replay and live mode.

1. **Happy path.** Open the chat and report a charge you do not recognize. Watch: intent classification with its score, ownership matching without disclosing data, the verification code, the card block, and the **verified receipt** re-read from the database.
2. **The system stops.** Ask to dispute the charge. The structured handoff appears and the case enters the back-office queue with verified facts, actions taken, verification method and open questions.
3. **Takeover.** From the back office, take the conversation and reply as a human agent.
4. **Guardrail, live.** Change the amount threshold in the back office and repeat the operation: the same action is now blocked. No deployment, no restart.
5. **Another workflow, no code.** Load the second workflow's configuration and use it right away. The diff is on screen: configuration only.
6. **Language.** Repeat step 1 in Portuguese.

Full scripts with exact messages: `demo/scripts/`.

---

## 8. Reproducing the reported metrics

```bash
make eval              # ⚠️ pending — baseline and proposed system on the scenario suite
make eval-adversarial  # ⚠️ pending — injection and abuse scenarios
make data-quality      # ⚠️ pending — data quality report
make verify-audit      # ⚠️ pending — verifies the audit log hash chain
```

Reports are written to `reports/` and versioned in the repository: you can compare your run against ours file by file. In replay mode the result must be **identical**; any difference is a finding and we want to hear about it.

`make eval` (⚠️ pending) takes around **TODO minutes**.

---

## 9. Deployed environment (⚠️ pending)

> ⚠️ **Pending:** Local-first development; the private VM environment is not yet provisioned. The deployment instructions and targets below are pending VM availability.

There is an instance running in a **private environment managed by the team**, available during the evaluation window, in case you prefer not to run anything locally. The link is in the submission email and in the repository README.

**Availability:** TODO (dates and hours). Outside that window it may be off; if you need it at another time, write to us and we will bring it up.

```bash
make deploy    # ⚠️ pending — requires target environment variables
```

Deployment uses the same images as the local environment: there is no special path that only works in production.

---

## 10. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| "no recording for this input" | You are in replay mode with a free-form message | Switch to live mode (section 4) or use the scripts in `demo/scripts/` |
| `make up` (⚠️ pending) fails downloading models | No network or corrupted cache | `make clean-models && make up` (⚠️ pending) |
| A `make` command does not exist | Not implemented yet | `make help` (⚠️ pending) lists the available ones |
| Chat replies but takes no actions | `make seed` (⚠️ pending) was not run | Seed and retry |
| `make seed` (⚠️ pending) fails with a contract error | Dataset missing or schema mismatch | See section 5; the message names the exact field |
| High latency on the first turn | Encoder cold start | Normal. `make warmup` (⚠️ pending) avoids it |
| Port already in use | Another local service on the same port | Change ports in `.env` |
| Encoder container keeps restarting | Less than 4 GB RAM available | Raise Docker's memory limit |
| `make smoke` (⚠️ pending) fails at the verification step | Outbound email not configured | Use the simulated mode in `.env.example` |
| Back office does not update live | WebSocket blocked by a proxy | Check the reverse proxy |
| No provider response in live mode | Invalid key or exhausted quota | Check `.env`. The system degrades to an unavailability message: **it does not invent responses** |
| Image will not start on Apple Silicon | Wrong architecture build | Report it: images are multi-arch and that would be our bug |

```bash
make logs                  # ⚠️ pending — logs from all services
make logs s=banking-core   # ⚠️ pending — from one
make down                  # ⚠️ pending — stop
make clean                 # ⚠️ pending — stop and drop volumes (destroys seeded data)
```

---

## 11. Contact

**TODO:** members, email and availability during the jury review window.

---

## Cross-check checklist (internal, delete before submitting)

Test on a clean machine, with no Docker cache, before submitting:

- [ ] `git clone` + `make demo` (⚠️ pending) works with no `.env` and no key
- [ ] Every command mentioned in this document exists in the `Makefile`
- [ ] Every URL in section 6 responds
- [ ] The real output of `make smoke` (⚠️ pending) matches section 6
- [ ] `make seed` (⚠️ pending) fails with a clear message when the dataset is missing
- [ ] `make eval` (⚠️ pending) in replay mode reproduces the numbers in `evaluation.md`
- [ ] Tested on x86_64 and on arm64
- [ ] Tested with no API key and with an invalid key
- [ ] Every TODO in this document replaced with a real value
- [ ] The private environment is up and the availability window is stated
