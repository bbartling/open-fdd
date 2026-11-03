#!/usr/bin/env bash
# Boot csv-only recipe (central static UI at /app/), poll health, run minimal CSV upload smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PROJECT="openfdd-csv-smoke-$$"
COMPOSE=(docker compose -p "$PROJECT" -f docker/compose.csv.yml -f docker/compose.timescale.yml)
TIMEOUT_SECS="${OPENFDD_SMOKE_TIMEOUT_SECS:-300}"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-openfdd-central:ci}"
SKIP_BUILD="${OPENFDD_SMOKE_SKIP_BUILD:-0}"

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== CSV recipe boot smoke (central /app/) =="

export OPENFDD_CENTRAL_IMAGE="$CENTRAL_IMAGE"
export OPENFDD_MQTT_ENABLED=0
export OPENFDD_ALLOW_OPEN_BIND="${OPENFDD_ALLOW_OPEN_BIND:-1}"
export OPENFDD_STATIC_PRODUCT_UI=1

if [[ "$SKIP_BUILD" == "1" ]]; then
  echo "Using prebuilt image: central=$CENTRAL_IMAGE"
  docker image inspect "$CENTRAL_IMAGE" >/dev/null
else
  docker build -f services/central/Dockerfile -t "$CENTRAL_IMAGE" . >/dev/null
fi

"${COMPOSE[@]}" up -d --no-build central timescale

deadline=$((SECONDS + TIMEOUT_SECS))
until curl -fsS http://127.0.0.1:8080/api/health | jq -e '.service == "openfdd-central"' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: central /api/health timeout" >&2
    "${COMPOSE[@]}" logs central timescale >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK central /api/health"

until curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/app/ | grep -qE '200|302'; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: static UI /app/ timeout" >&2
    "${COMPOSE[@]}" logs central >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK static UI http://127.0.0.1:8080/app/"

FIXTURE="$ROOT/services/central/tests/fixtures/fc1_duct_static.csv"
test -f "$FIXTURE"

PREV="$(curl -fsS -X POST http://127.0.0.1:8080/api/csv/import/preview \
  -F "file=@${FIXTURE}")"
echo "$PREV" | jq -e '.ok == true and (.session_id | length > 0)' >/dev/null
SID="$(echo "$PREV" | jq -r '.session_id')"
echo "OK CSV preview session=$SID"

echo "PASS: csv recipe boot smoke"
