#!/usr/bin/env bash
# Check the Cloud Run environment from outside (ADR-0015): one line per check, non-zero exit
# if any fails, like infra/compose/smoke.sh. Needs gcloud (logged in), curl and python3.
#
# `make gcp-smoke` passes GCP_PROJECT, GCP_REGION and GCP_PREFIX; NETCHECK=1 also runs the
# netcheck job. deploy.yml runs it after every rollout.
#
#   positive  every service is ready and runs a real image, not the bootstrap one; the web
#             client answers /health and opens a conversation, which goes through the
#             orchestrator and banking-core without calling the LLM
#   negative  the orchestrator, banking-core and the model server do not answer from the
#             internet; the back office does not answer without passing IAP
set -u

: "${GCP_PROJECT:?set GCP_PROJECT}" "${GCP_REGION:?set GCP_REGION}" "${GCP_PREFIX:?set GCP_PREFIX}"
BOOTSTRAP_IMAGE=${BOOTSTRAP_IMAGE:-us-docker.pkg.dev/cloudrun/container/hello}

failed=0
pass() { printf '✓ %-32s %s\n' "$1" "$2"; }
fail() { printf '✗ %-32s %s\n' "$1" "$2"; failed=1; }

# "<Ready status> <url> <image>" of a service, or nothing if it does not exist.
describe() {
  local json
  json=$(gcloud run services describe "$GCP_PREFIX-$1" --region "$GCP_REGION" \
    --project "$GCP_PROJECT" --format json 2>/dev/null) || return 0
  printf '%s' "$json" | python3 -c '
import json, sys
service = json.load(sys.stdin)
conditions = {c["type"]: c["status"] for c in service["status"].get("conditions", [])}
image = service["spec"]["template"]["spec"]["containers"][0]["image"]
print(conditions.get("Ready", "Unknown"), service["status"].get("url", "-"), image)'
}

http_status() { curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }

# The URL of each service, without associative arrays (macOS ships bash 3.2).
set_url() { printf -v "url_${1//-/_}" '%s' "$2"; }
url() { local name="url_${1//-/_}"; printf '%s' "${!name:-}"; }

for svc in encoder banking-core orchestrator web-client web-backoffice; do
  read -r ready service_url image <<<"$(describe "$svc")"
  set_url "$svc" "${service_url:-}"
  if [ -z "${ready:-}" ]; then
    fail "$svc" "no such service"
  elif [ "$ready" != "True" ]; then
    fail "$svc" "latest revision not ready ($ready)"
  elif [ "${image%%@*}" = "$BOOTSTRAP_IMAGE" ] || [ "${image%%:*}" = "$BOOTSTRAP_IMAGE" ]; then
    fail "$svc" "still on the bootstrap image: run deploy.yml"
  else
    pass "$svc" "ready, ${image##*/}"
  fi
done

# Positive: the customer path.
web_client=$(url web-client)
if [ -n "$web_client" ]; then
  # /health, not /healthz: Cloud Run's front end answers some paths ending in "z" itself (404).
  code=$(http_status "$web_client/health")
  if [ "$code" = "200" ]; then
    pass "web-client /health" "200"
  else
    fail "web-client /health" "HTTP $code"
  fi

  body=$(curl -s --max-time 60 -X POST -H 'Content-Type: application/json' -d '{}' \
    -w '\n%{http_code}' "$web_client/api/conversations")
  code=${body##*$'\n'}
  if [ "$code" = "201" ] && printf '%s' "${body%$'\n'*}" | grep -q '"conversation_id"'; then
    pass "open a conversation" "201 (web-client → orchestrator → banking-core)"
  else
    fail "open a conversation" "HTTP $code: ${body%$'\n'*}"
  fi
fi

# Negative: the backends accept internal traffic only.
for svc in orchestrator banking-core encoder; do
  [ -n "$(url "$svc")" ] || continue
  code=$(http_status "$(url "$svc")/health")
  case "$code" in
    2??) fail "$svc from the internet" "HTTP $code: it must not answer" ;;
    *) pass "$svc from the internet" "refused (HTTP $code)" ;;
  esac
done

# Negative: the back office sends an anonymous visitor to Google's login, never the page.
if [ -n "$(url web-backoffice)" ]; then
  code=$(http_status "$(url web-backoffice)/")
  case "$code" in
    2??) fail "back office without IAP" "HTTP $code: it must not answer" ;;
    *) pass "back office without IAP" "refused (HTTP $code)" ;;
  esac
fi

if [ "${NETCHECK:-}" = "1" ]; then
  if gcloud run jobs execute "$GCP_PREFIX-netcheck" --region "$GCP_REGION" --project "$GCP_PROJECT" \
    --wait >/dev/null 2>&1; then
    pass "netcheck (edge → core data)" "blocked; redis-edge reachable"
  else
    fail "netcheck (edge → core data)" "failed: gcloud logging read 'resource.labels.job_name=\"$GCP_PREFIX-netcheck\"'"
  fi
fi

if [ "$failed" -ne 0 ]; then
  echo "smoke: FAILED" >&2
  exit 1
fi
echo "smoke: OK"
