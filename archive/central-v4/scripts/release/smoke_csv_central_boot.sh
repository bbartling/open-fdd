#!/usr/bin/env bash
# Boot csv-only recipe (central static UI at /app/), poll health, run minimal CSV upload smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="openfdd-csv-smoke-$$"
COMPOSE=(docker compose -p "$PROJECT" -f docker/compose.csv.yml)
TIMEOUT_SECS="${OPENFDD_SMOKE_TIMEOUT_SECS:-300}"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-openfdd-central:ci}"
SKIP_BUILD="${OPENFDD_SMOKE_SKIP_BUILD:-0}"
CENTRAL_BASE="${OPENFDD_SMOKE_CENTRAL_BASE:-http://127.0.0.1:8080}"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== CSV recipe boot smoke (central static /app/) =="

export OPENFDD_CENTRAL_IMAGE="$CENTRAL_IMAGE"
export OPENFDD_MQTT_ENABLED=0
export OPENFDD_ALLOW_OPEN_BIND="${OPENFDD_ALLOW_OPEN_BIND:-1}"
export OPENFDD_STATIC_PRODUCT_UI="${OPENFDD_STATIC_PRODUCT_UI:-1}"

if [[ "$SKIP_BUILD" == "1" ]]; then
  echo "Using prebuilt image: central=$CENTRAL_IMAGE"
  docker image inspect "$CENTRAL_IMAGE" >/dev/null
else
  docker build -f services/central/Dockerfile -t "$CENTRAL_IMAGE" . >/dev/null
fi

"${COMPOSE[@]}" up -d --no-build central

deadline=$((SECONDS + TIMEOUT_SECS))
until curl -fsS "${CENTRAL_BASE}/api/health" | jq -e '.service == "openfdd-central"' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: central /api/health timeout" >&2
    "${COMPOSE[@]}" logs central >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK central /api/health"

for path in /app/ /app/assets/js/app.js; do
  until curl -fsS -o /dev/null -w '%{http_code}' "${CENTRAL_BASE}${path}" | grep -q '^200$'; do
    if (( SECONDS >= deadline )); then
      echo "FAIL: static UI GET ${path} timeout" >&2
      "${COMPOSE[@]}" logs central >&2 || true
      exit 1
    fi
    sleep 2
  done
  echo "OK static UI GET ${path}"
done

FIXTURE="$ROOT/services/central/tests/fixtures/fc1_duct_static.csv"
test -f "$FIXTURE"

PREV="$(curl -fsS -X POST "${CENTRAL_BASE}/api/csv/import/preview" \
  -F "file=@${FIXTURE}")"
echo "$PREV" | jq -e '.ok == true and (.session_id | length > 0)' >/dev/null
SID="$(echo "$PREV" | jq -r '.session_id')"
echo "OK CSV preview session=$SID"

echo "PASS: csv recipe boot smoke"
