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
# the front ends are built in containers. Bun is needed to regenerate or check packages/design-tokens.
BUN ?= bun
NO_BUN = { echo "bun is not installed (BUN=$(BUN)). Install it from https://bun.sh, 1.3 or later, or pass BUN=/path/to/bun." >&2; exit 1; }

# How infra/compose/demo.sh calls back into make. Not spelled $(MAKE) in the
# recipe on purpose: make runs any recipe line containing that string even under
# `make -n`, and a dry run of `make demo` must not start a stack.
SUBMAKE := $(MAKE) --no-print-directory

.DEFAULT_GOAL := help
.PHONY: help up down logs clean smoke build-multiarch demo seed eval eval-baseline eval-adversarial \
	data-quality verify-audit warmup warmup-encoder warmup-retrieval encoder-bench clean-models deploy calibrate calibration-verify synth-data generate-labels migrate \
	profile-factored ingest design-tokens design-tokens-check

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

smoke: ## Check all six components are healthy
	@COMPOSE="$(COMPOSE)" bash infra/compose/smoke.sh

build-multiarch: ## Build app images for linux/amd64 and linux/arm64, no push (uses a pb-multiarch buildx builder if the default cannot; slow under emulation)
	@if docker info 2>/dev/null | grep -q 'io.containerd.snapshotter'; then B=""; else \
		echo "note: default docker driver cannot build multi-platform; using buildx builder pb-multiarch"; \
		docker buildx inspect pb-multiarch >/dev/null 2>&1 || docker buildx create --name pb-multiarch --driver docker-container >/dev/null || exit 1; \
		B="--builder pb-multiarch"; \
	fi; \
	for s in banking-core orchestrator encoder; do \
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

clean-models: ## pending: drop cached model weights
	@echo "pending: $@ is not implemented yet" >&2; exit 1

deploy: ## pending: deploy to the target environment
	@echo "pending: $@ is not implemented yet" >&2; exit 1

calibrate: ## Compare and calibrate models (TASK=decision|embedding|decision-points, DP=, CONFIG=, OUT=reports)
	@test -n "$(TASK)" || { echo "calibrate: set TASK=decision, embedding or decision-points" >&2; exit 1; }
	uv run $(UV_RUN_FLAGS) --package calibrate python -m calibrate.cli --task $(TASK) $(if $(CONFIG),--config $(CONFIG)) $(if $(DP),--dp $(DP)) $(if $(ARTIFACT),--artifact $(ARTIFACT)) --out $(or $(OUT),reports)

calibration-verify: ## Static check of the calibration artifact: schema, pins, data hashes, reports (ARTIFACT=, EFFECTS=)
	uv run $(UV_RUN_FLAGS) --package calibrate python -m calibrate.verify $(if $(ARTIFACT),--artifact $(ARTIFACT)) $(if $(EFFECTS),--effects $(EFFECTS))

synth-data: ## Generate reproducible synthetic train and validation datasets
	uv run --with pyyaml python -m tools.synthdata.generate

profile-factored: ## Profile the Factored dataset and print aggregate statistics
	uv run --package profile-factored python -m profile_factored.cli $(if $(DATA_DIR),--data-dir $(DATA_DIR)) $(if $(OUT),--markdown-out $(OUT))

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
