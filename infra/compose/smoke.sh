#!/usr/bin/env bash
# Installation check: one line per component, non-zero exit if any is not healthy.
# Health comes from the compose healthchecks. Each Python app's healthcheck validates
# the GET /health contract in-container: {"status":"ok","service":"<name>"}. The two
# front ends' check is GET /healthz (liveness only: it does not call their upstreams).
set -u
# Honors COMPOSE_PROJECT_NAME: it queries through `docker compose` of the same project
# (make passes its own COMPOSE), so it never assumes the default project or ports.

COMPOSE=${COMPOSE:-docker compose -f infra/compose/docker-compose.yml}
SERVICES="postgres redis-core redis-edge banking-core orchestrator encoder web-client web-backoffice"

failed=0
for svc in $SERVICES; do
  state=$($COMPOSE ps --format '{{.State}}/{{.Health}}' "$svc" 2>/dev/null | head -n 1)
  if [ "$state" = "running/healthy" ]; then
    printf '✓ %-14s healthy\n' "$svc"
  else
    printf '✗ %-14s %s\n' "$svc" "${state:-not running}"
    failed=1
  fi
done

# Migration status check: report the applied Alembic migration head using container env credentials
migration_head=$($COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "SELECT version_num FROM alembic_version LIMIT 1;"' 2>/dev/null || true)
if [ -n "$migration_head" ]; then
  printf '✓ %-14s applied head (%s)\n' "migration" "$migration_head"
else
  printf '✗ %-14s %s\n' "migration" "no migration head applied"
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  echo "smoke: FAILED (see 'make logs s=<service>')" >&2
  exit 1
fi
echo "smoke: OK"
