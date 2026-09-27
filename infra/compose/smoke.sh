#!/usr/bin/env bash
# Installation check: one line per component, non-zero exit if any is not healthy.
# Health comes from the compose healthchecks. Each app's healthcheck validates
# the GET /health contract in-container: {"status":"ok","service":"<name>"}.
set -u

COMPOSE=${COMPOSE:-docker compose -f infra/compose/docker-compose.yml}
SERVICES="postgres redis-core redis-edge banking-core orchestrator encoder"

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

if [ "$failed" -ne 0 ]; then
  echo "smoke: FAILED (see 'make logs s=<service>')" >&2
  exit 1
fi
echo "smoke: OK"
