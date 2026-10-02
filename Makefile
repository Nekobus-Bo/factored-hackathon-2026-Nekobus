# Single entry point. `make help` lists every target.
# Targets marked "pending" exist so nothing is silently promised: they fail
# with an explicit message until implemented (AGENTS.md, rule 7).

COMPOSE_FILE ?= infra/compose/docker-compose.yml
WAIT_TIMEOUT ?= 240

# The compose file lives in infra/compose/, so compose would not find a root .env
# on its own. Pass it explicitly when it exists; with no .env every default applies.
COMPOSE = docker compose -f $(COMPOSE_FILE)$(if $(wildcard .env), --env-file .env)

# `uv run --package calibrate` installs PyTorch, which the decision and embedding tasks
# need. TASK=decision-points and calibration-verify do not; where the PyTorch wheels
# cannot be downloaded, prepare an environment without them and pass
# UV_RUN_FLAGS=--no-sync (tools/calibrate/README.md, "Without PyTorch").
UV_RUN_FLAGS ?=

# The TypeScript side is a Bun workspace at the root (ADR-0009). The stack and `make demo` do not need it:
# the front ends are built in containers. Bun is needed to regenerate or check packages/design-tokens, and to
# run a front end's dev server on the host (`make web-client`, `make web-backoffice`).
BUN ?= bun
NO_BUN = { echo "bun is not installed (BUN=$(BUN)). Install it from https://bun.sh, 1.3 or later, or pass BUN=/path/to/bun." >&2; exit 1; }

# llmbench (tools/llmbench): local LLMs served by llama.cpp, benchmarked against the real turn engine
# on a sandbox bank. `brew install llama.cpp` provides llama-server. The language filter is BENCH_LANG,
# not LANG, which the shell already sets to the locale.
LLAMA_SERVER ?= llama-server
NO_LLAMA = { echo "llama-server is not installed (LLAMA_SERVER=$(LLAMA_SERVER)): brew install llama.cpp, or https://github.com/ggml-org/llama.cpp" >&2; exit 1; }
NO_MODEL = { echo "$@: set MODEL=<alias from tools/llmbench/models.yaml>: qwen3.5-4b, granite-4.2-3b, granite-4.0-1b or qwen3-1.7b" >&2; exit 1; }
LLMBENCH = uv run --package llmbench python -m llmbench.cli

# What `make web-check` covers: the shared contracts, then every web app (apps/web-client,
# apps/web-backoffice) as soon as it has a package.json. Each needs `typecheck` and `test` scripts;
# one without them fails the gate instead of being skipped. packages/design-tokens keeps its own gate
# (design-tokens-check), which also checks that dist/ matches src/.
WEB_PACKAGES = packages/contracts $(sort $(patsubst %/package.json,%,$(wildcard apps/web-*/package.json)))

# Where the host dev servers (`make web-client`, `make web-backoffice`) find the stack that `make up` started:
# the ports compose publishes on 127.0.0.1. The Makefile does not read .env, so a PORT_* changed there is
# repeated here: `make web-client PORT_ORCHESTRATOR=58180`.
PORT_ORCHESTRATOR ?= 8080
PORT_BANKING_CORE ?= 8081
PORT_WEB_CLIENT ?= 5173
PORT_WEB_BACKOFFICE ?= 5174

# How infra/compose/demo.sh calls back into make. Not spelled $(MAKE) in the
# recipe on purpose: make runs any recipe line containing that string even under
# `make -n`, and a dry run of `make demo` must not start a stack.
SUBMAKE := $(MAKE) --no-print-directory

# The presentation environment on Cloud Run (ADR-0015), Terraform in infra/deploy/gcp. The project
# and the name prefix are read from the tfvars files, so nothing here repeats them; GCP_PROJECT=
# overrides. The state bucket is created once by `make gcp-state`.
TF ?= terraform
GCLOUD ?= gcloud
GH ?= gh
TF_DIR := infra/deploy/gcp
GCP_PROJECT ?= $(shell sed -n 's/^project_id *= *"\(.*\)"/\1/p' $(TF_DIR)/local.tfvars 2>/dev/null)
GCP_PREFIX := $(shell sed -n 's/^name_prefix *= *"\(.*\)"/\1/p' $(TF_DIR)/presentation.tfvars)
GCP_REGION := $(shell sed -n 's/^region *= *"\(.*\)"/\1/p' $(TF_DIR)/presentation.tfvars)
GCP_STATE_BUCKET ?= $(GCP_PROJECT)-$(GCP_PREFIX)-tfstate
GCP_STATE_PREFIX ?= pattern-blue/presentation
# `make gcp-apply SERVICES=false` is the first apply: everything but the Cloud Run services and jobs.
SERVICES ?= true
TF_VARS = -var-file=presentation.tfvars $(if $(wildcard $(TF_DIR)/local.tfvars),-var-file=local.tfvars) -var services_enabled=$(SERVICES)
NO_GCLOUD = { echo "gcloud is not installed (GCLOUD=$(GCLOUD)): brew install --cask google-cloud-sdk, or https://cloud.google.com/sdk/docs/install" >&2; exit 1; }
NO_TF = { echo "terraform is not installed (TF=$(TF)): https://developer.hashicorp.com/terraform/install, 1.11 or later" >&2; exit 1; }
NO_PROJECT = { echo "no GCP project: copy $(TF_DIR)/local.tfvars.example to $(TF_DIR)/local.tfvars and set project_id, or pass GCP_PROJECT=" >&2; exit 1; }
# Runs a Cloud Run job of the environment and waits for it: $(call gcp_job,migrate).
gcp_job = $(GCLOUD) run jobs execute $(GCP_PREFIX)-$(1) --region $(GCP_REGION) --project $(GCP_PROJECT) --wait

.DEFAULT_GOAL := help
.PHONY: help up down logs clean smoke build-multiarch demo seed eval eval-live eval-baseline eval-adversarial \
	data-quality verify-audit warmup warmup-encoder warmup-retrieval encoder-bench llm-bench-serve llm-bench llm-bench-compare llm-bench-check clean-models deploy calibrate calibration-verify synth-data stage-data-co synth-data-regional synth-retrieval-regional build-test-regional check-data-regional pool-data-regional train-encoder encoder-weights-image generate-labels migrate \
	profile-factored lab ingest design-tokens design-tokens-check web-check web-client web-backoffice \
	gcp-state gcp-init gcp-check gcp-plan gcp-apply gcp-destroy gcp-llm-key gcp-iap-oauth gcp-gh-vars gcp-migrate gcp-seed \
	gcp-netcheck gcp-smoke

generate-labels: ## Generate packages/contracts/src/contracts/labels.py from schema.yaml
	uv run generate-contracts-labels

help: ## List available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "} {printf "  %-20s %s\n", $$1, $$2}'

migrate: ## apply database migrations (alembic upgrade head)
	$(COMPOSE) run --rm migrate

up: ## Build and start all services, wait until healthy
	$(COMPOSE) up -d --build --wait --wait-timeout $(WAIT_TIMEOUT)

down: ## Stop all services (keeps volumes)
	$(COMPOSE) down

logs: ## Follow logs; one service with s=<service>
	$(COMPOSE) logs -f --tail=100 $(s)

clean: ## Stop and delete volumes (DESTROYS seeded data)
	@echo "WARNING: deleting volumes. Seeded data will be lost." >&2
	$(COMPOSE) down -v

smoke: ## Check every service is healthy: databases, backends and both front ends
	@COMPOSE="$(COMPOSE)" bash infra/compose/smoke.sh

build-multiarch: ## Build app images for linux/amd64 and linux/arm64, no push (uses a pb-multiarch buildx builder if the default cannot; slow under emulation)
	@if docker info 2>/dev/null | grep -q 'io.containerd.snapshotter'; then B=""; else \
		echo "note: default docker driver cannot build multi-platform; using buildx builder pb-multiarch"; \
		docker buildx inspect pb-multiarch >/dev/null 2>&1 || docker buildx create --name pb-multiarch --driver docker-container >/dev/null || exit 1; \
		B="--builder pb-multiarch"; \
	fi; \
	for s in banking-core orchestrator encoder web-client web-backoffice; do \
		docker buildx build $$B --platform linux/amd64,linux/arm64 -f apps/$$s/Dockerfile . || exit 1; \
	done

demo: ## One command: build, start, seed, preload models, print URLs and demo customers
	@COMPOSE="$(COMPOSE)" MAKE="$(SUBMAKE)" bash infra/compose/demo.sh

seed: ## Seed the database: synthetic demo data + every ingested dataset in data/staging
	$(COMPOSE) run --rm seed python -m banking_core.seed.cli seed

ingest: ## Map a delivered dataset data/raw/SOURCE -> data/staging/SOURCE (SOURCE=factored)
	@test -n "$(SOURCE)" || { echo "ingest: set SOURCE, e.g. make ingest SOURCE=factored" >&2; exit 1; }
	$(COMPOSE) run --rm seed python -m banking_core.seed.cli ingest --source $(SOURCE)

eval: ## pending: baseline vs proposed on the scenario suite
	@echo "pending: $@ is not implemented yet" >&2; exit 1

eval-live: ## Proposed system end to end with the LLM called live, not replayable: reports/eval-live-<date>-<model>.md (LOCAL_MODEL=<llmbench alias> served on :8099; ARGS="--group happy_path")
	@COMPOSE="$(COMPOSE)" LOCAL_MODEL="$(LOCAL_MODEL)" ARGS="$(ARGS)" OUT="$(OUT)" bash infra/compose/eval-live.sh

eval-baseline: ## pending: baseline system only
	@echo "pending: $@ is not implemented yet" >&2; exit 1

eval-adversarial: ## pending: injection and abuse scenarios
	@echo "pending: $@ is not implemented yet" >&2; exit 1

data-quality: ## Generate data quality report in reports/data-quality.md
	$(COMPOSE) run --rm seed python -m banking_core.seed.cli data-quality

verify-audit: ## verify the audit log hash chain
	$(COMPOSE) run --rm banking-core python -m banking_core.audit.verify

warmup: warmup-encoder warmup-retrieval ## Preload every local model on the model server (decision backend + kb.search embeddings)

warmup-encoder: ## Preload the configured decision backend (GLiNER weights into the hf-cache volume; tfidf_lr only checks its data)
	$(COMPOSE) run --rm --no-deps encoder python -m encoder_service.warmup --only decision

warmup-retrieval: ## Download the pinned kb.search embedding model onto the model server (needs network once) and print its hash pin
	$(COMPOSE) run --rm --no-deps encoder python -m encoder_service.warmup --only embedding

encoder-bench: ## Encoder p95 latency and peak RAM on CPU (ENCODER_BACKEND=tfidf_lr|gliner, ENCODER_MODEL=, DATA=)
	ENCODER_BACKEND=$(or $(ENCODER_BACKEND),tfidf_lr) uv run --package encoder-service $(if $(filter gliner,$(ENCODER_BACKEND)),--extra gliner) python -m encoder_service.bench --data $(or $(DATA),data/eval/synthetic/decision.validation.jsonl)

llm-bench-serve: ## Serve a local model for llmbench with llama.cpp, in the foreground (MODEL=qwen3.5-4b|granite-4.2-3b|granite-4.0-1b|qwen3-1.7b; downloads the GGUF once)
	@test -n "$(MODEL)" || $(NO_MODEL)
	@command -v $(LLAMA_SERVER) >/dev/null 2>&1 || $(NO_LLAMA)
	@cmd="$$($(LLMBENCH) serve-cmd --model $(MODEL) --binary $(LLAMA_SERVER))" && echo "$$cmd" && eval "$$cmd"

llm-bench: ## Benchmark the served model: 42 probes + 21 episodes (MODEL=; ROUTE=1 offers only state-allowed tools; BENCH_LANG=es|pt|en; ONLY=probes|episodes; REPEAT=; TAG=)
	@test -n "$(MODEL)" || $(NO_MODEL)
	$(LLMBENCH) run --model $(MODEL) $(if $(ROUTE),--route-tools) $(if $(BENCH_LANG),--lang $(BENCH_LANG)) $(if $(ONLY),--only $(ONLY)) $(if $(REPEAT),--repeat $(REPEAT)) $(if $(TAG),--tag $(TAG))

llm-bench-compare: ## Compare the llmbench runs in tools/llmbench/results (PUBLISH=1 also writes reports/llm-bench-<date>.md)
	$(LLMBENCH) compare $(if $(PUBLISH),--publish)

llm-bench-check: ## llmbench tests: sandbox bank, probes, episodes and CLI with stand-in models; no model server needed
	uv run --package llmbench pytest -q tools/llmbench

clean-models: ## pending: drop cached model weights
	@echo "pending: $@ is not implemented yet" >&2; exit 1

deploy: ## Run deploy.yml on main: build, migrate and roll out to Cloud Run (GH_REPO=owner/name if not this checkout's repository; needs gh)
	@command -v $(GH) >/dev/null 2>&1 || { echo "deploy: gh is not installed (GH=$(GH)): https://cli.github.com" >&2; exit 1; }
	$(GH) workflow run deploy.yml --ref main $(if $(GH_REPO),--repo $(GH_REPO))

calibrate: ## Compare and calibrate models (TASK=decision|embedding|decision-points, DP=, CONFIG=, OUT=reports)
	@test -n "$(TASK)" || { echo "calibrate: set TASK=decision, embedding or decision-points" >&2; exit 1; }
	uv run $(UV_RUN_FLAGS) --package calibrate python -m calibrate.cli --task $(TASK) $(if $(CONFIG),--config $(CONFIG)) $(if $(DP),--dp $(DP)) $(if $(ARTIFACT),--artifact $(ARTIFACT)) --out $(or $(OUT),reports)

calibration-verify: ## Static check of the calibration artifact: schema, pins, data hashes, reports (ARTIFACT=, EFFECTS=)
	uv run $(UV_RUN_FLAGS) --package calibrate python -m calibrate.verify $(if $(ARTIFACT),--artifact $(ARTIFACT)) $(if $(EFFECTS),--effects $(EFFECTS))

synth-data: ## Generate reproducible synthetic train and validation datasets
	uv run --with pyyaml python -m tools.synthdata.generate

SYNTH_REGIONAL = uv run --with polars --with pyyaml --with scikit-learn --with litellm python -m tools.synthdata_regional

stage-data-co: ## Stage the Colombian and Mexican bank threads from data/raw/apple_store_reviews (tuquejasuma.com) for es-CO
	$(SYNTH_REGIONAL).stage_tqs

synth-data-regional: ## Mine real text, generate train/validation with an LLM, then check (LOCALE=pt-BR|es-MX|es-AR|es-CO; LLM_API_KEY unless cached)
	@test -n "$(LOCALE)" || { echo "synth-data-regional: set LOCALE=pt-BR, es-MX, es-AR or es-CO" >&2; exit 1; }
	$(SYNTH_REGIONAL).mine --locale $(LOCALE) --if-missing
	$(SYNTH_REGIONAL).generate --locale $(LOCALE) --mode full
	$(MAKE) check-data-regional LOCALE=$(LOCALE)

build-test-regional: ## Fill the hand-written test templates into the provisional test split (LOCALE=pt-BR|es-MX|es-AR|es-CO)
	@test -n "$(LOCALE)" || { echo "build-test-regional: set LOCALE=pt-BR, es-MX, es-AR or es-CO" >&2; exit 1; }
	$(SYNTH_REGIONAL).build_test --locale $(LOCALE)

synth-retrieval-regional: ## Generate kb.search test questions from real regional text with an LLM, plus the kb_search query the orchestrator's LLM would send (LOCALE=pt-BR|es-MX|es-AR|es-CO; POOL=1 pools the locales and writes checks.md; GENERATOR=claude reads the hand-written set)
	@test -n "$(LOCALE)$(POOL)" || { echo "synth-retrieval-regional: set LOCALE=pt-BR, es-MX, es-AR or es-CO, and/or POOL=1" >&2; exit 1; }
	$(SYNTH_REGIONAL).retrieval $(if $(LOCALE),--locale $(LOCALE)) $(if $(POOL),--pool) $(if $(GENERATOR),--generator $(GENERATOR))

check-data-regional: ## Quality gate for a regional dataset; writes checks.md next to it (LOCALE=pt-BR|es-MX|es-AR|es-CO)
	@test -n "$(LOCALE)" || { echo "check-data-regional: set LOCALE=pt-BR, es-MX, es-AR or es-CO" >&2; exit 1; }
	$(SYNTH_REGIONAL).checks --locale $(LOCALE)

pool-data-regional: ## Pool the pt-BR, es-MX, es-AR and es-CO splits (+ English template validation/test) into data/staging/decision_pooled
	uv run python -m tools.synthdata_regional.pool

train-encoder: ## Fine-tune and pin a decision model (CONFIG=tools/calibrate/configs/train_intent_distilbert.yaml); MPS when available
	uv run $(UV_RUN_FLAGS) --package calibrate python -m calibrate.train --config $(or $(CONFIG),tools/calibrate/configs/train_intent_distilbert.yaml)

WEIGHTS_DIR ?= packages/encoder/weights/distilbert-intent-pooled
# Docker Hub repository of the seed image (public; ADR-0015). Set DOCKERHUB_NAMESPACE.
DOCKERHUB_NAMESPACE ?=
WEIGHTS_IMAGE ?= docker.io/$(DOCKERHUB_NAMESPACE)/pattern_blue-encoder-weights

encoder-weights-image: ## Pack a trained model dir into the weights-only seed image (WEIGHTS=, IMAGE=); PUSH=1 pushes amd64+arm64 and prints the digest to pin
	@set -e; dir="$(or $(WEIGHTS),$(WEIGHTS_DIR))"; repo="$(or $(IMAGE),$(WEIGHTS_IMAGE))"; \
	case "$$repo" in docker.io//*) echo "encoder-weights-image: set DOCKERHUB_NAMESPACE=<your Docker Hub user or org> (or IMAGE=)" >&2; exit 1;; esac; \
	uv run python -m encoder.weights verify "$$dir"; \
	pins="$$(uv run python -m encoder.weights show "$$dir")"; \
	rev="$$(printf '%s' "$$pins" | python3 -c 'import json,sys; print(json.load(sys.stdin)["revision"])')"; \
	sha="$$(printf '%s' "$$pins" | python3 -c 'import json,sys; print(json.load(sys.stdin)["weights_sha256"])')"; \
	image="$$repo:$$(printf '%s' "$$rev" | tr ':' '-')"; \
	args="-f apps/encoder/weights.Dockerfile --build-arg MODEL_NAME=$${rev%%:*} --build-arg REVISION_LABEL=$$rev --build-arg WEIGHTS_SHA256=$$sha"; \
	if [ -n "$(PUSH)" ]; then \
		docker buildx build --platform linux/amd64,linux/arm64 $$args -t "$$image" --push "$$dir"; \
		digest="$$(docker buildx imagetools inspect "$$image" --format '{{json .Manifest.Digest}}' | tr -d '"')"; \
		echo "pushed $$image"; echo "pin in apps/encoder/Dockerfile: $$repo@$$digest"; \
	else \
		docker buildx build $$args -t "$$image" --load "$$dir"; \
		echo "built $$image (local, single platform); PUSH=1 publishes amd64+arm64 to $$repo"; \
	fi

profile-factored: ## Profile the Factored dataset and print aggregate statistics
	uv run --package profile-factored python -m profile_factored.cli $(if $(DATA_DIR),--data-dir $(DATA_DIR)) $(if $(OUT),--markdown-out $(OUT))

lab: ## Open the exploratory marimo notebooks in lab/ (NB=<file> opens one; DATA_DIR overrides data/raw/factored)
	uv run --project lab marimo edit lab/notebooks$(if $(NB),/$(NB))

design-tokens: ## Generate packages/design-tokens/dist (tokens.css, tokens.ts, fonts.html) from src/tokens.json; needs Bun
	@command -v $(BUN) >/dev/null 2>&1 || { printf 'design-tokens: ' >&2; $(NO_BUN); }
	$(BUN) install --frozen-lockfile
	$(BUN) run --cwd packages/design-tokens build

design-tokens-check: ## Design tokens gate, as CI runs it: dist/ matches src/, typecheck, bun test; needs Bun
	@command -v $(BUN) >/dev/null 2>&1 || { printf 'design-tokens-check: ' >&2; $(NO_BUN); }
	$(BUN) install --frozen-lockfile
	$(BUN) run --cwd packages/design-tokens check
	$(BUN) run --cwd packages/design-tokens typecheck
	$(BUN) run --cwd packages/design-tokens test

web-check: ## Front-end gate, as CI runs it: typecheck and bun test for @pattern-blue/contracts and each web app; needs Bun
	@command -v $(BUN) >/dev/null 2>&1 || { printf 'web-check: ' >&2; $(NO_BUN); }
	$(BUN) install --frozen-lockfile
	@for pkg in $(WEB_PACKAGES); do \
		for script in typecheck test; do \
			echo "==> $$pkg: $$script"; \
			$(BUN) run --cwd $$pkg $$script || exit 1; \
		done; \
	done

web-client: ## Dev server of the customer app on the host (hot reload; needs Bun), against the stack from `make up`
	@command -v $(BUN) >/dev/null 2>&1 || { printf 'web-client: ' >&2; $(NO_BUN); }
	@echo "web-client on http://localhost:$(PORT_WEB_CLIENT), orchestrator at http://localhost:$(PORT_ORCHESTRATOR) (if the compose container holds that port: docker compose stop web-client)"
	$(BUN) install --frozen-lockfile
	PORT=$(PORT_WEB_CLIENT) ORCHESTRATOR_URL=http://localhost:$(PORT_ORCHESTRATOR) $(BUN) run --cwd apps/web-client dev

web-backoffice: ## Dev server of the back office on the host (hot reload; needs Bun), against the stack from `make up`
	@command -v $(BUN) >/dev/null 2>&1 || { printf 'web-backoffice: ' >&2; $(NO_BUN); }
	@echo "web-backoffice on http://localhost:$(PORT_WEB_BACKOFFICE), orchestrator at :$(PORT_ORCHESTRATOR), banking-core at :$(PORT_BANKING_CORE); tokens and login are the development defaults (if the compose container holds the port: docker compose stop web-backoffice)"
	$(BUN) install --frozen-lockfile
	PORT=$(PORT_WEB_BACKOFFICE) ORCHESTRATOR_URL=http://localhost:$(PORT_ORCHESTRATOR) BANKING_CORE_URL=http://localhost:$(PORT_BANKING_CORE) $(BUN) run --cwd apps/web-backoffice dev

gcp-state: ## GCP: create the Terraform state bucket, once per project (private, versioned); needs gcloud
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-state: ' >&2; $(NO_GCLOUD); }
	@test -n "$(GCP_PROJECT)" || { printf 'gcp-state: ' >&2; $(NO_PROJECT); }
	$(GCLOUD) services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com storage.googleapis.com --project $(GCP_PROJECT)
	@$(GCLOUD) storage buckets describe gs://$(GCP_STATE_BUCKET) --project $(GCP_PROJECT) >/dev/null 2>&1 || \
		$(GCLOUD) storage buckets create gs://$(GCP_STATE_BUCKET) --project $(GCP_PROJECT) --location $(GCP_REGION) \
			--uniform-bucket-level-access --public-access-prevention
	$(GCLOUD) storage buckets update gs://$(GCP_STATE_BUCKET) --versioning

gcp-init: ## GCP: terraform init against the state bucket
	@command -v $(TF) >/dev/null 2>&1 || { printf 'gcp-init: ' >&2; $(NO_TF); }
	@test -n "$(GCP_PROJECT)" || { printf 'gcp-init: ' >&2; $(NO_PROJECT); }
	$(TF) -chdir=$(TF_DIR) init -backend-config=bucket=$(GCP_STATE_BUCKET) -backend-config=prefix=$(GCP_STATE_PREFIX)

gcp-check: ## GCP: offline gate, as CI runs it: fmt, validate, tflint and terraform test (mocked provider, no credentials)
	@command -v $(TF) >/dev/null 2>&1 || { printf 'gcp-check: ' >&2; $(NO_TF); }
	$(TF) -chdir=$(TF_DIR) fmt -check -recursive
	$(TF) -chdir=$(TF_DIR) init -backend=false -input=false >/dev/null
	$(TF) -chdir=$(TF_DIR) validate
	@if command -v tflint >/dev/null 2>&1; then \
		(cd $(TF_DIR) && tflint --init >/dev/null && tflint); \
	else echo "gcp-check: tflint is not installed, skipped (CI runs it)" >&2; fi
	$(TF) -chdir=$(TF_DIR) test

gcp-plan: ## GCP: terraform plan (SERVICES=false for the first apply)
	@command -v $(TF) >/dev/null 2>&1 || { printf 'gcp-plan: ' >&2; $(NO_TF); }
	$(TF) -chdir=$(TF_DIR) plan $(TF_VARS)

gcp-apply: ## GCP: terraform apply (SERVICES=false for the first apply, before the LLM key exists)
	@command -v $(TF) >/dev/null 2>&1 || { printf 'gcp-apply: ' >&2; $(NO_TF); }
	$(TF) -chdir=$(TF_DIR) apply $(TF_VARS)

gcp-destroy: ## GCP: terraform destroy (set data_deletion_protection = false first; deleting the project is cleaner)
	@command -v $(TF) >/dev/null 2>&1 || { printf 'gcp-destroy: ' >&2; $(NO_TF); }
	@echo "WARNING: destroys the environment and its database. Cloud SQL keeps the network peering busy for days: 'gcloud projects delete' is the reliable teardown." >&2
	$(TF) -chdir=$(TF_DIR) destroy $(TF_VARS)

gcp-llm-key: ## GCP: add the LLM API key to Secret Manager (asks for it, input hidden; never enters the Terraform state)
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-llm-key: ' >&2; $(NO_GCLOUD); }
	@test -n "$(GCP_PROJECT)" || { printf 'gcp-llm-key: ' >&2; $(NO_PROJECT); }
	@printf 'LLM API key for %s (input hidden): ' "$(GCP_PREFIX)-llm-api-key" >&2; \
		stty -echo 2>/dev/null; read -r key; stty echo 2>/dev/null; printf '\n' >&2; \
		test -n "$$key" || { echo "gcp-llm-key: empty key, nothing stored" >&2; exit 1; }; \
		printf '%s' "$$key" | $(GCLOUD) secrets versions add $(GCP_PREFIX)-llm-api-key --data-file=- --project $(GCP_PROJECT)

gcp-iap-oauth: ## GCP, project with no organization only: give IAP the OAuth client created by hand (asks for its ID and secret, secret hidden); needs gcloud
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-iap-oauth: ' >&2; $(NO_GCLOUD); }
	@test -n "$(GCP_PROJECT)" || { printf 'gcp-iap-oauth: ' >&2; $(NO_PROJECT); }
	@printf 'OAuth client ID: ' >&2; read -r id; \
		printf 'OAuth client secret (input hidden): ' >&2; \
		stty -echo 2>/dev/null; read -r secret; stty echo 2>/dev/null; printf '\n' >&2; \
		test -n "$$id" && test -n "$$secret" || { echo "gcp-iap-oauth: the client ID and secret are both required, nothing set" >&2; exit 1; }; \
		f="$$(mktemp)"; trap 'rm -f "$$f"' EXIT; chmod 600 "$$f"; \
		printf 'access_settings:\n  oauth_settings:\n    client_id: %s\n    client_secret: %s\n' "$$id" "$$secret" > "$$f"; \
		$(GCLOUD) iap settings set "$$f" --project=$(GCP_PROJECT) | grep -v -i secret

gcp-gh-vars: ## GCP: set deploy.yml's repository variables from the Terraform outputs (GH_REPO=owner/name, DEMO_SEED=true|false); needs gh
	@command -v $(GH) >/dev/null 2>&1 || { echo "gcp-gh-vars: gh is not installed (GH=$(GH)): https://cli.github.com" >&2; exit 1; }
	@test -n "$(GH_REPO)" || { echo "gcp-gh-vars: set GH_REPO=owner/name" >&2; exit 1; }
	@$(TF) -chdir=$(TF_DIR) output -json github_variables | python3 -c 'import json, sys; [print(k, v) for k, v in json.load(sys.stdin).items()]' | \
		while read -r name value; do $(GH) variable set "$$name" --repo $(GH_REPO) --body "$$value" || exit 1; done
	$(GH) variable set DEPLOY_ENABLED --repo $(GH_REPO) --body true
	$(GH) variable set DEMO_SEED --repo $(GH_REPO) --body $(or $(DEMO_SEED),false)
	$(GH) variable set CI_IMAGE_PLATFORMS --repo $(GH_REPO) --body $(or $(CI_IMAGE_PLATFORMS),linux/amd64)

gcp-migrate: ## GCP: run the migrate job (alembic upgrade head) and wait; needs gcloud
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-migrate: ' >&2; $(NO_GCLOUD); }
	$(call gcp_job,migrate)

gcp-seed: ## GCP: run the seed job: TRUNCATES and reloads the banking tables with the synthetic demo customers; needs gcloud
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-seed: ' >&2; $(NO_GCLOUD); }
	$(call gcp_job,seed)

gcp-netcheck: ## GCP: run the netcheck job: from the edge zone, core data must be unreachable and redis-edge reachable; needs gcloud
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-netcheck: ' >&2; $(NO_GCLOUD); }
	$(call gcp_job,netcheck)

gcp-smoke: ## GCP: check the deployed environment from outside (NETCHECK=1 also runs the netcheck job); needs gcloud and curl
	@command -v $(GCLOUD) >/dev/null 2>&1 || { printf 'gcp-smoke: ' >&2; $(NO_GCLOUD); }
	@GCP_PROJECT=$(GCP_PROJECT) GCP_REGION=$(GCP_REGION) GCP_PREFIX=$(GCP_PREFIX) NETCHECK=$(NETCHECK) bash $(TF_DIR)/smoke.sh
