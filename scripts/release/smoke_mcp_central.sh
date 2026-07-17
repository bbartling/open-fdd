#!/usr/bin/env bash
# Boot central in Docker and smoke MCP stdio against /api/health.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

NETWORK="openfdd-mcp-smoke-$$"
CENTRAL_NAME="openfdd-central-smoke-$$"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_SMOKE_IMAGE:-openfdd-central:ci}"
MCP_IMAGE="${OPENFDD_MCP_SMOKE_IMAGE:-openfdd-mcp:ci}"
TIMEOUT_SECS="${OPENFDD_SMOKE_TIMEOUT_SECS:-120}"

cleanup() {
  docker rm -f "$CENTRAL_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== MCP ↔ central smoke =="

docker network create "$NETWORK" >/dev/null

docker build -f services/central/Dockerfile -t "$CENTRAL_IMAGE" . >/dev/null
docker build -f Dockerfile.mcp -t "$MCP_IMAGE" . >/dev/null

docker run -d --name "$CENTRAL_NAME" --network "$NETWORK" \
  -p 127.0.0.1:18080:8080 \
  -e OPENFDD_MQTT_ENABLED=0 \
  -e OPENFDD_WORKSPACE=/workspace \
  -e OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet \
  "$CENTRAL_IMAGE" >/dev/null

deadline=$((SECONDS + TIMEOUT_SECS))
until curl -fsS "http://127.0.0.1:18080/api/health" \
  | jq -e '.service == "openfdd-central"' >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: central health timeout" >&2
    docker logs "$CENTRAL_NAME" >&2 || true
    exit 1
  fi
  sleep 2
done
echo "OK central health"

MCP_OUT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"openfdd_health","arguments":{}}}' \
  | docker run -i --rm --network "$NETWORK" \
      -e OPENFDD_API_BASE="http://${CENTRAL_NAME}:8080" \
      "$MCP_IMAGE")"

echo "$MCP_OUT" | jq -s '.[] | select(.id == 2) | .result.content[0].text | fromjson | .service == "openfdd-central"' | grep -q true
echo "OK MCP openfdd_health → central"
echo "PASS: MCP central smoke"
