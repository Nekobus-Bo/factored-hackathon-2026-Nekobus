#!/usr/bin/env bash
# Live end-to-end evaluation (`make eval-live`): the proposed system, with the
# orchestrator calling its model live, scored by evalrunner on banking-core's
# own evidence. Not replayable: the report says so and names the model.
#
#   make eval-live                                 # the model in .env (gpt-6-luna)
#   make eval-live LOCAL_MODEL=qwen3.6-35b-a3b     # a model served on 127.0.0.1:8099
#   make eval-live LOCAL_MODEL=qwen3.6-35b-a3b-think LOCAL_TEMPERATURE=0.6
#   make eval-live ARGS="--group happy_path"       # any evalrunner filter
#
# Steps: start the stack with docker-compose.eval.yml on top (rebuilding from the
# working tree), create the read-only role eval_reader with a fresh password, run
# evalrunner, then put the stack back on the plain compose file and disable the
# role, whatever the outcome. Run nothing else against the stack meanwhile: the
# runner matches each scenario to its banking session by an audit watermark.
#
# Called by make, which passes COMPOSE (with --env-file .env when a .env exists).
set -Eeuo pipefail
COMPOSE=${COMPOSE:-docker compose -f infra/compose/docker-compose.yml}
EVAL_COMPOSE="$COMPOSE -f infra/compose/docker-compose.eval.yml"
ENV_FILE=${ENV_FILE:-.env}
LOCAL_MODEL=${LOCAL_MODEL:-}
LOCAL_PORT=${LOCAL_PORT:-8099}
ARGS=${ARGS:-}
die() { printf 'eval-live: %s\n' "$*" >&2; exit 1; }
say() { printf '\n==> %s\n' "$*"; }

# cfg NAME DEFAULT: the value compose would use (shell, then .env, then default).
cfg() {
  local name=$1 default=${2-} value=${!1:-}
  if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then
    value=$(sed -n "s/^${name}=//p" "$ENV_FILE" | tail -n 1 |
      sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/^["'\'']//' -e 's/["'\'']$//')
  fi
  printf '%s' "${value:-$default}"
}

if [ -n "$LOCAL_MODEL" ]; then
  served=$(curl -s -m 5 "http://127.0.0.1:${LOCAL_PORT}/v1/models" || true)
  case "$served" in
    *"\"$LOCAL_MODEL\""*) ;;
    *) die "no server on 127.0.0.1:${LOCAL_PORT} serves '$LOCAL_MODEL' (make llm-bench-serve, or the tunnel to the GPU box)" ;;
  esac
  # Compose takes the shell's value over .env's.
  export LLM_MODEL="openai/${LOCAL_MODEL}"
  export LLM_BASE_URL="http://host.docker.internal:${LOCAL_PORT}/v1"
  export LLM_API_KEY="sk-local"
  export LLM_REASONING_EFFORT=""
  export LLM_TIMEOUT_SECONDS="${LLM_TIMEOUT_SECONDS:-120}"
  export LLM_TEMPERATURE="${LOCAL_TEMPERATURE:-0}"
  LABEL="$LOCAL_MODEL"
else
  model=$(cfg LLM_MODEL)
  [ -n "$model" ] && [ "$model" != "TODO" ] || die "LLM_MODEL is not set in $ENV_FILE"
  [ -n "$(cfg LLM_API_KEY)" ] || die "LLM_API_KEY is not set in $ENV_FILE"
  LABEL="${model#openai/}"
fi
OUT=${OUT:-reports/eval-live-$(date -u +%Y-%m-%d)-${LABEL}.md}
PG_USER=$(cfg POSTGRES_USER app)
PG_DB=$(cfg POSTGRES_DB bank)

restore() {
  say "Returning the stack to the plain compose file"
  $EVAL_COMPOSE exec -T postgres psql -q -U "$PG_USER" -d "$PG_DB" \
    -c "ALTER ROLE eval_reader NOLOGIN" >/dev/null 2>&1 || true
  # Drop the local model's settings exported above, so the stack goes back to .env's.
  unset LLM_MODEL LLM_BASE_URL LLM_API_KEY LLM_REASONING_EFFORT LLM_TIMEOUT_SECONDS LLM_TEMPERATURE
  $COMPOSE up -d --wait --remove-orphans >/dev/null || printf 'eval-live: restore failed; run make up\n' >&2
}
trap restore EXIT

say "Starting the stack for a live run with $LABEL"
$EVAL_COMPOSE up -d --build --wait --wait-timeout "${WAIT_TIMEOUT:-240}"

if [ -n "$LOCAL_MODEL" ]; then
  $EVAL_COMPOSE exec -T orchestrator python -c \
    "import urllib.request; urllib.request.urlopen('${LLM_BASE_URL}/models', timeout=10)" ||
    die "the orchestrator container cannot reach ${LLM_BASE_URL}"
fi

customers=$($EVAL_COMPOSE exec -T postgres psql -tA -U "$PG_USER" -d "$PG_DB" \
  -c "SELECT count(*) FROM core_bank.customer" 2>/dev/null || echo 0)
if [ "${customers//[[:space:]]/}" = "0" ]; then
  say "Seeding the demo data"
  $COMPOSE run --rm seed python -m banking_core.seed.cli seed
fi

say "Creating the read-only role eval_reader"
password=$(openssl rand -hex 16)
$EVAL_COMPOSE exec -T postgres psql -q -v ON_ERROR_STOP=1 -v pw="$password" \
  -U "$PG_USER" -d "$PG_DB" >/dev/null <<'SQL'
SELECT 'CREATE ROLE eval_reader' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'eval_reader') \gexec
ALTER ROLE eval_reader LOGIN PASSWORD :'pw';
ALTER ROLE eval_reader SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA ops, core_bank, config TO eval_reader;
GRANT SELECT ON ops.audit_log, core_bank.card, core_bank.account, core_bank.customer, config.policy_config TO eval_reader;
SELECT 'GRANT SELECT ON ops.handoff TO eval_reader' WHERE to_regclass('ops.handoff') IS NOT NULL \gexec
SQL

say "Running the scenario suite (report: $OUT)"
set +e
EVAL_READONLY_DSN="postgresql://eval_reader:${password}@127.0.0.1:$(cfg PORT_EVAL_DB 5433)/${PG_DB}" \
EVAL_ADMIN_TOKEN="$(cfg ADMIN_API_TOKEN dev-only-admin-token)" \
EVAL_ORCHESTRATOR_URL="http://127.0.0.1:$(cfg PORT_ORCHESTRATOR 8080)" \
EVAL_BANKING_CORE_URL="http://127.0.0.1:$(cfg PORT_BANKING_CORE 8081)" \
  uv run --package evalrunner python -m evalrunner --system proposed \
  --live-llm "$LABEL" --out "$OUT" $ARGS
rc=$?
set -e
# evalrunner exits 1 when any scenario fails: that is a result, not an error.
[ "$rc" -le 1 ] || die "evalrunner failed (exit $rc)"
