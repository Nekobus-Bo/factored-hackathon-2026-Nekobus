# Single entry point. `make help` lists every target.
# Targets marked "pending" exist so nothing is silently promised: they fail
# with an explicit message until implemented (AGENTS.md, rule 7).

COMPOSE_FILE ?= infra/compose/docker-compose.yml
WAIT_TIMEOUT ?= 240

# The compose file lives in infra/compose/, so compose would not find a root .env
# on its own. Pass it explicitly when it exists; with no .env every default applies.
COMPOSE = docker compose -f $(COMPOSE_FILE)$(if $(wildcard .env), --env-file .env)

.DEFAULT_GOAL := help
.PHONY: help up down logs clean smoke demo seed eval eval-baseline eval-adversarial \
	data-quality verify-audit warmup clean-models deploy calibrate

help: ## List available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "} {printf "  %-18s %s\n", $$1, $$2}'

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

demo: ## pending: full startup in replay mode
	@echo "pending: $@ is not implemented yet" >&2; exit 1

seed: ## pending: seed the database from data/raw
	@echo "pending: $@ is not implemented yet" >&2; exit 1

eval: ## pending: baseline vs proposed on the scenario suite
	@echo "pending: $@ is not implemented yet" >&2; exit 1

eval-baseline: ## pending: baseline system only
	@echo "pending: $@ is not implemented yet" >&2; exit 1

eval-adversarial: ## pending: injection and abuse scenarios
	@echo "pending: $@ is not implemented yet" >&2; exit 1

data-quality: ## pending: data quality report
	@echo "pending: $@ is not implemented yet" >&2; exit 1

verify-audit: ## pending: verify the audit log hash chain
	@echo "pending: $@ is not implemented yet" >&2; exit 1

warmup: ## pending: preload local models
	@echo "pending: $@ is not implemented yet" >&2; exit 1

clean-models: ## pending: drop cached model weights
	@echo "pending: $@ is not implemented yet" >&2; exit 1

deploy: ## pending: deploy to the target environment
	@echo "pending: $@ is not implemented yet" >&2; exit 1

calibrate: ## pending: calibrate the abstention threshold on validation (TASK=decision|embedding)
	@echo "pending: $@ is not implemented yet" >&2; exit 1
