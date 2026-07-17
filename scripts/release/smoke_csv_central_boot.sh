#!/usr/bin/env bash
# Boot csv-only recipe (central + ui), poll health, run minimal CSV upload smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="openfdd-csv-smoke-$$"
COMPOSE=(docker compose -p "$PROJECT" -f docker/compose.csv.yml)
TIMEOUT_SECS="${OPENFDD_SMOKE_TIMEOUT_SECS:-180}"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-openfdd-central:ci}"
UI_IMAGE="${OPENFDD_UI_IMAGE:-openfdd-ui:ci}"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== CSV recipe boot smoke =="

export OPENFDD_CENTRAL_IMAGE="$CENTRAL_IMAGE"
export OPENFDD_UI_IMAGE="$UI_IMAGE"
export OPENFDD_MQTT_ENABLED=0

docker build -f services/central/Dockerfile -t "$CENTRAL_IMAGE" . >/dev/null
docker build -f workspace/dashboard/Dockerfile \
  --build-arg VITE_OUT_DIR=dist \
  --build-arg VITE_API_BASE= \
  -t "$UI_IMAGE" . >/dev/null

"${COMPOSE[@]}" up -d --no-build central ui

deadline=$((SECONDS + TIMEOUT_SECS))
until curl -fsS http://127.0.0.1:8080/api/health | jq -e '.service == "openfdd-central"' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: central /api/health timeout" >&2
    "${COMPOSE[@]}" logs central >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK central /api/health"

until curl -fsS http://127.0.0.1:3000/api/health | jq -e '.service == "openfdd-central"' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: UI proxy /api/health timeout" >&2
    "${COMPOSE[@]}" logs ui central >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK UI proxy /api/health"

FIXTURE="$ROOT/services/central/tests/fixtures/fc1_duct_static.csv"
test -f "$FIXTURE"

PREV="$(curl -fsS -X POST http://127.0.0.1:8080/api/csv/import/preview \
  -F "file=@${FIXTURE}")"
echo "$PREV" | jq -e '.ok == true and (.session_id | length > 0)' >/dev/null
SID="$(echo "$PREV" | jq -r '.session_id')"
echo "OK CSV preview session=$SID"

echo "PASS: csv recipe boot smoke"
