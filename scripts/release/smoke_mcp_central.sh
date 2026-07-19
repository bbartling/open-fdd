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
  '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"openfdd_fdd_registry","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"openfdd_fdd_equipment","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"openfdd_fdd_results","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"openfdd_fdd_accuracy_snapshot","arguments":{}}}' \
  | docker run -i --rm --network "$NETWORK" \
      -e OPENFDD_API_BASE="http://${CENTRAL_NAME}:8080" \
      "$MCP_IMAGE")"

echo "$MCP_OUT" | jq -s '.[] | select(.id == 2) | .result.content[0].text | fromjson | .service == "openfdd-central"' | grep -q true
echo "OK MCP openfdd_health → central"
echo "$MCP_OUT" | jq -se '
  (map(select(.id == 3))[0].result.tools | map(.name)) as $tools
  | ["openfdd_fdd_registry","openfdd_fdd_equipment","openfdd_fdd_results",
     "openfdd_fdd_series","openfdd_fdd_accuracy_snapshot"]
  | all(. as $name | $tools | index($name) != null)
' | grep -q true
echo "OK MCP production FDD tools listed"

DIRECT_RULES="$(curl -fsS http://127.0.0.1:18080/api/fdd/rules | jq -c .)"
DIRECT_EQUIPMENT="$(curl -fsS http://127.0.0.1:18080/api/fdd/equipment | jq -c .)"
DIRECT_RESULTS="$(curl -fsS http://127.0.0.1:18080/api/fdd/results | jq -c .)"
MCP_RULES="$(echo "$MCP_OUT" | jq -rs '.[] | select(.id == 4) | .result.content[0].text | fromjson')"
MCP_EQUIPMENT="$(echo "$MCP_OUT" | jq -rs '.[] | select(.id == 5) | .result.content[0].text | fromjson')"
MCP_RESULTS="$(echo "$MCP_OUT" | jq -rs '.[] | select(.id == 6) | .result.content[0].text | fromjson')"
jq -ne --argjson direct "$DIRECT_RULES" --argjson mcp "$MCP_RULES" \
  '$direct.count == $mcp.count and ($direct.rules | map(.rule_id)) == ($mcp.rules | map(.rule_id))' | grep -q true
jq -ne --argjson direct "$DIRECT_EQUIPMENT" --argjson mcp "$MCP_EQUIPMENT" \
  '$direct.equipment == $mcp.equipment' | grep -q true
jq -ne --argjson direct "$DIRECT_RESULTS" --argjson mcp "$MCP_RESULTS" \
  '$direct.results == $mcp.results' | grep -q true
echo "OK MCP FDD answers exactly match direct central API"

echo "$MCP_OUT" | jq -rse \
  '.[] | select(.id == 7) | .result.content[0].text | fromjson | .ok' | grep -q true
echo "OK MCP accuracy snapshot"
echo "PASS: MCP central smoke"
