#!/usr/bin/env bash
# One-command demo (`make demo`): build and start the stack, preload the local
# models, seed the database, check it, and print what to open and who to use.
#
# Every step is a public make target (`make up`, `make seed`, `make smoke`, ...),
# so each can be run alone. Safe to run again: images and model caches are reused,
# `up` leaves a healthy stack alone, and the seed truncates and reloads the demo
# data, so a second run also resets the demo customers' cards and empties the
# handoff queue.
#
# Called by make, which passes COMPOSE (with --env-file .env when a .env exists)
# and MAKE. Configuration values that only decide what to print are read the way
# compose resolves them: shell environment, then .env, then the default.
set -Eeuo pipefail

COMPOSE=${COMPOSE:-docker compose -f infra/compose/docker-compose.yml}
MAKE=${MAKE:-make}
ENV_FILE=${ENV_FILE:-.env}
RECORDINGS_DIR=eval/replay # what the orchestrator container mounts as its REPLAY_DIR

STEP="starting"
WARNINGS=()
SERVICES=""

say() { printf '\n==> %s\n' "$*"; }
warn() { WARNINGS+=("$*"); printf 'warning: %s\n' "$*" >&2; }
die() { printf 'demo: %s\n' "$*" >&2; exit 1; }
on_error() { printf '\ndemo: failed during "%s". Inspect with: make logs\n' "$STEP" >&2; }
trap on_error ERR

# cfg NAME DEFAULT: the value compose would use for NAME. An empty value counts
# as unset, like ${NAME:-DEFAULT} in the compose file.
cfg() {
  local name=$1 default=${2-} value=${!1:-}
  if [ -z "$value" ] && [ -f "$ENV_FILE" ]; then
    value=$(sed -n "s/^${name}=//p" "$ENV_FILE" | tail -n 1 |
      sed -e 's/[[:space:]]\{1,\}#.*$//' -e 's/^["'\'']//' -e 's/["'\'']$//')
  fi
  printf '%s' "${value:-$default}"
}

# defined_service NAME: true when the compose file declares that service.
defined_service() {
  case $'\n'"$SERVICES"$'\n' in
    *$'\n'"$1"$'\n'*) return 0 ;;
  esac
  return 1
}

# Asks banking-core whether its policy config and kb.search are usable. /ready
# builds the kb.search index, which loads the embedding model: it also warms it,
# so the first chat turn does not pay for it. Prints "<status> <reason>".
readiness_probe() {
  $COMPOSE exec -T banking-core python - <<'PY'
import json
import urllib.error
import urllib.request

try:
    body = json.load(urllib.request.urlopen("http://127.0.0.1:8081/ready", timeout=180))
except urllib.error.HTTPError as error:
    body = json.load(error)
except Exception as error:
    body = {"status": "unreachable", "reason": type(error).__name__}
print(body.get("status", "unknown"), body.get("reason") or "")
PY
}

# The customers the demo signs in as, read from the seed fixtures so this script
# never holds a second copy. One "locale|name|type|document|birth date|last4" line
# each.
demo_customers() {
  $COMPOSE exec -T banking-core python - <<'PY'
from banking_core.seed.fixtures import create_scenario_fixtures, fixture_uuid

bundle = create_scenario_fixtures()
accounts = {a["customer_id"]: a for a in bundle.accounts}
cards = {c["account_id"]: c for c in bundle.cards}
for locale in ("es", "pt", "en"):
    customer_id = str(fixture_uuid(f"{locale}-demo-customer"))
    customer = next(c for c in bundle.customers if c["id"] == customer_id)
    card = cards[accounts[customer_id]["id"]]
    print(
        locale,
        customer["full_name"],
        customer["document_type"],
        customer["document_number"],
        customer["birth_date"],
        card["pan_last4"],
        sep="|",
    )
PY
}

STEP="checking Docker"
say "1/6 Checking Docker"
$COMPOSE config -q 2>/dev/null || die "docker compose (v2) is not available, or the compose file does not parse"
$COMPOSE ps -q >/dev/null 2>&1 || die "the Docker daemon is not reachable: start Docker and run 'make demo' again"
SERVICES=$($COMPOSE config --services 2>/dev/null || true)

STEP="building images"
say "2/6 Building images (the first build takes several minutes; later runs reuse the cache)"
$COMPOSE build

STEP="preloading local models"
say "3/6 Preloading local models"
# The encoder backend is built once so a bad backend fails here rather than at
# startup: tfidf_lr only checks its training data, gliner downloads its weights.
$MAKE --no-print-directory warmup-encoder
KB_OK=1
if [ "$(cfg RETRIEVAL_MODE vector)" = "bm25" ]; then
  echo "kb.search: RETRIEVAL_MODE=bm25, no embedding model to preload"
else
  echo "kb.search: embedding model (about 0.5 GB, downloaded once; the network is needed only if it is not cached)"
  if ! $MAKE --no-print-directory warmup-retrieval; then
    KB_OK=0
    warn "the embedding model could not be preloaded, so kb.search will not work. Connect to the network and run: make warmup-retrieval"
  fi
fi

STEP="starting the stack"
say "4/6 Starting the stack (migrations run first, as a dependency of banking-core)"
$MAKE --no-print-directory up

STEP="seeding the database"
say "5/6 Seeding the database (idempotent: it truncates and reloads the demo data)"
$MAKE --no-print-directory seed

STEP="checking the stack"
say "6/6 Checking the stack"
$MAKE --no-print-directory smoke
if [ "$KB_OK" = 1 ]; then
  readiness=$(readiness_probe || true)
  case "$readiness" in
    ready*) echo "banking-core /ready: ready (policy config and kb.search)" ;;
    *) warn "banking-core /ready: ${readiness:-no answer}. Check: make logs s=banking-core" ;;
  esac
fi

# --- Report -------------------------------------------------------------------
orchestrator_url="http://localhost:$(cfg PORT_ORCHESTRATOR 8080)"
core_url="http://localhost:$(cfg PORT_BANKING_CORE 8081)"

say "Pattern Blue is up"
echo
echo "Services"
printf '  %-15s %s\n' "orchestrator" "$orchestrator_url  (chat API: POST /v1/conversations; docs: $orchestrator_url/docs)"
printf '  %-15s %s\n' "banking-core" "$core_url/docs  (tool API and admin API)"
if defined_service web-client; then
  printf '  %-15s %s\n' "customer chat" "http://localhost:$(cfg PORT_CLIENT 5173)"
else
  printf '  %-15s %s\n' "customer chat" "pending (apps/web-client is not built yet)"
fi
if defined_service web-backoffice; then
  printf '  %-15s %s\n' "back office" "http://localhost:$(cfg PORT_BACKOFFICE 5174)"
else
  printf '  %-15s %s\n' "back office" "pending (apps/web-backoffice is not built yet)"
fi

echo
echo "Assistant"
llm_mode=$(cfg LLM_MODE replay)
llm_key=$(cfg LLM_API_KEY "")
recordings=$(find "$RECORDINGS_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
if [ "$llm_mode" = "replay" ]; then
  if [ "$recordings" = 0 ]; then
    echo "  NOTICE: no replay recordings yet — set LLM_API_KEY and LLM_MODE=live in .env to talk to the assistant"
    echo "  (until then a chat turn answers 503; the rest of the stack works)"
  else
    echo "  replay mode, recordings in $RECORDINGS_DIR: $recordings (a message with no recording answers 503)"
  fi
elif [ -z "$llm_key" ] || [ "$llm_key" = "TODO" ]; then
  echo "  NOTICE: LLM_MODE=$llm_mode but LLM_API_KEY is empty — a chat turn answers 503"
else
  echo "  live mode: turns call the configured provider (LLM_MODEL in .env)"
fi

echo
echo "Demo customers (synthetic data; identify with document and birth date)"
customers=$(demo_customers || true)
if [ -n "$customers" ]; then
  while IFS='|' read -r locale name doc_type doc_number born last4; do
    printf '  %-3s %-15s %-12s %-13s born %s   card ending %s\n' \
      "$locale" "$name" "$doc_type" "$doc_number" "$born" "$last4"
  done <<EOF
$customers
EOF
  echo "  Also seeded per language: a customer whose card is already blocked, and one with no OTP channel"
  echo "  (apps/banking-core/src/banking_core/seed/fixtures.py)"
else
  echo "  (could not read them from banking-core; see apps/banking-core/src/banking_core/seed/fixtures.py)"
fi
case "$(cfg ALLOW_DEV_OTP_HOOK false | tr '[:upper:]' '[:lower:]')" in
  true | 1 | yes | on)
    echo "  OTP codes: GET $core_url/v1/dev/otp/<challenge_id> (dev hook enabled)"
    ;;
  *)
    echo "  OTP codes go to a simulated channel that the customer web client will show (pending). Until then,"
    echo "  for local use only: set ALLOW_DEV_OTP_HOOK=true in .env, run 'make up', and read a code at"
    echo "  GET $core_url/v1/dev/otp/<challenge_id>"
    ;;
esac

admin_enabled=$(cfg ADMIN_API_ENABLED true | tr '[:upper:]' '[:lower:]')
case "$admin_enabled" in
  true | 1 | yes | on)
    admin_token=$(cfg ADMIN_API_TOKEN dev-only-admin-token)
    echo
    echo "Back office actions over HTTP, until the back office exists"
    if [ "$admin_token" = "dev-only-admin-token" ]; then
      echo "  $core_url/v1/admin/policy-config   Authorization: Bearer dev-only-admin-token (development token)"
    else
      echo "  $core_url/v1/admin/policy-config   Authorization: Bearer <your ADMIN_API_TOKEN>"
    fi
    ;;
esac

if [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo
  echo "Warnings"
  for message in "${WARNINGS[@]}"; do echo "  - $message"; done
fi

echo
echo "Stop with 'make down'; 'make clean' also deletes the data. 'make demo' can be run again at any time."
