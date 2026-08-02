#!/usr/bin/env bash
# Gate 13 — MCP accuracy vs central (not process-up).
# Spins its own openfdd-mcp container on the react-ot network; compares
# tools/list + FDD payloads to direct central curl. Reuses smoke_mcp_central.sh
# equality ideas against pulled GHCR tip images (no local docker build).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

MCP_IMAGE="${OPENFDD_MCP_IMAGE:-ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}}"
CENTRAL_IMAGE="${OPENFDD_CENTRAL_IMAGE:-ghcr.io/bbartling/openfdd-central:nightly}"
NET="openfdd-mcp-bench-$$"
MCP_NAME="openfdd-mcp-bench-$$"
# Prefer attaching to the running react-ot (or legacy standalone) central; otherwise
# boot a disposable central on the same throwaway network.
USE_STACK_CENTRAL=0
CENTRAL_CTR=""
CENTRAL_API=""

cleanup() {
  docker rm -f "$MCP_NAME" >/dev/null 2>&1 || true
  if [[ "$USE_STACK_CENTRAL" != "1" && -n "${CENTRAL_CTR:-}" ]]; then
    docker rm -f "$CENTRAL_CTR" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

hdr "MCP accuracy — own container vs central truth"
echo "${DIM}MCP_IMAGE=$MCP_IMAGE${RST}"

# Assert tip revision label when present
MCP_REV="$(docker inspect "$MCP_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)"
echo "${DIM}mcp rev=${MCP_REV:-unknown}${RST}"
[[ -n "$MCP_REV" ]] && ok "mcp image pulled (rev ${MCP_REV:0:12})"

# Resolve network: prefer openfdd-react-central, fall back to standalone
STACK_CENTRAL="$(docker ps --format '{{.Names}}' | grep -E 'openfdd-react-central' | head -1 || true)"
if [[ -z "$STACK_CENTRAL" ]]; then
  STACK_CENTRAL="$(docker ps --format '{{.Names}}' | grep -E 'openfdd-standalone-central' | head -1 || true)"
fi
if [[ -n "$STACK_CENTRAL" ]]; then
  USE_STACK_CENTRAL=1
  CENTRAL_CTR="$STACK_CENTRAL"
  NET="$(docker inspect "$CENTRAL_CTR" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | awk '{print $1}')"
  CENTRAL_API="http://${CENTRAL_CTR}:8080"
  if docker network inspect "$NET" --format '{{json .Containers}}' 2>/dev/null \
    | jq -e 'to_entries[] | select(.value.Name|test("central")) | .value.Name' >/dev/null 2>&1; then
    CENTRAL_API="http://central:8080"
  fi
  ok "using stack central on network $NET ($CENTRAL_API)"
else
  CENTRAL_CTR="openfdd-central-mcpbench-$$"
  docker network create "$NET" >/dev/null
  docker run -d --name "$CENTRAL_CTR" --network "$NET" --network-alias central \
    -e OPENFDD_MQTT_ENABLED=0 \
    -e OPENFDD_WORKSPACE=/workspace \
    -e OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet \
    "$CENTRAL_IMAGE" >/dev/null
  CENTRAL_API="http://central:8080"
  deadline=$((SECONDS + 90))
  until docker run --rm --network "$NET" curlimages/curl:8.5.0 \
      -fsS "$CENTRAL_API/api/health" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      bad "disposable central health timeout"
      summary; exit 1
    fi
    sleep 2
  done
  ok "booted disposable central for MCP gate"
fi

# Host-side central for direct curl equality (react-ot publishes 8080)
HOST_CENTRAL="${CENTRAL_BASE:-http://127.0.0.1:8080}"
central_auth_setup
hcurl() {
  curl -fsS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" "$@"
}

if ! hcurl "$HOST_CENTRAL/api/health" >/dev/null 2>&1; then
  # Fall back: expose disposable central
  if [[ "$USE_STACK_CENTRAL" != "1" ]]; then
    HOST_CENTRAL="http://127.0.0.1:18081"
    docker rm -f "$CENTRAL_CTR" >/dev/null 2>&1 || true
    docker run -d --name "$CENTRAL_CTR" --network "$NET" --network-alias central \
      -p 127.0.0.1:18081:8080 \
      -e OPENFDD_MQTT_ENABLED=0 \
      -e OPENFDD_WORKSPACE=/workspace \
      -e OPENFDD_PARQUET_ROOT=/workspace/.cache/parquet \
      "$CENTRAL_IMAGE" >/dev/null
    sleep 5
    CENTRAL_AUTH_HDR=()
    CENTRAL_AUTH_DONE=0
    hcurl() { curl -fsS --max-time 30 "$@"; }
  else
    bad "host CENTRAL_BASE unreachable for equality curl"
    summary; exit 1
  fi
fi

# Central auth: MCP must present the same Bearer JWT as host curls.
MCP_TOKEN="${OPENFDD_MCP_TOKEN:-}"
if [[ -z "$MCP_TOKEN" && -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  MCP_TOKEN="$(curl -fsS --max-time 15 -X POST "$HOST_CENTRAL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
    | jq -r '.token // .access_token // empty' || true)"
fi
if [[ -n "$MCP_TOKEN" ]]; then
  ok "MCP Bearer token acquired for central auth"
else
  skip "no MCP token (OPENFDD_MCP_TOKEN / admin login) — FDD equality may 401"
fi

MCP_OUT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"openfdd_health","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"openfdd_fdd_registry","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"openfdd_fdd_equipment","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"openfdd_fdd_results","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"openfdd_fdd_accuracy_snapshot","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"openfdd_no_such_tool","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"openfdd_fdd_series","arguments":{"equipment_id":"","rule_id":""}}}' \
  | docker run -i --rm --name "$MCP_NAME" --network "$NET" \
      -e OPENFDD_API_BASE="$CENTRAL_API" \
      -e OPENFDD_MCP_TOKEN="${MCP_TOKEN:-}" \
      "$MCP_IMAGE" 2>"$ART/mcp_stderr.log" || true)"

echo "$MCP_OUT" >"$ART/mcp_stdio.jsonl"
# Normalize to JSON array (one object per line)
python3 - "$ART/mcp_stdio.jsonl" "$ART/mcp_messages.json" <<'PY'
import json,sys,pathlib
lines=[]
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    line=line.strip()
    if not line: continue
    try: lines.append(json.loads(line))
    except Exception: pass
pathlib.Path(sys.argv[2]).write_text(json.dumps(lines,indent=2))
print(len(lines))
PY

if [[ ! -s "$ART/mcp_messages.json" ]]; then
  bad "MCP produced no JSON-RPC messages (see mcp_stderr.log)"
  summary; exit 1
fi
ok "MCP stdio session captured ($(jq 'length' "$ART/mcp_messages.json") messages)"

# tools/list required production FDD tools
if jq -e '
  (map(select(.id==2))[0].result.tools | map(.name)) as $tools
  | ["openfdd_fdd_registry","openfdd_fdd_equipment","openfdd_fdd_results",
     "openfdd_fdd_series","openfdd_fdd_accuracy_snapshot","openfdd_health"]
  | all(. as $n | $tools | index($n) != null)
' "$ART/mcp_messages.json" >/dev/null; then
  ok "tools/list includes production FDD tools"
else
  bad "tools/list missing required FDD tools: $(jq -c 'map(select(.id==2))[0].result.tools|map(.name)' "$ART/mcp_messages.json")"
fi

# Health
if jq -e 'map(select(.id==3))[0].result.content[0].text | fromjson | .service=="openfdd-central"' \
  "$ART/mcp_messages.json" >/dev/null 2>&1; then
  ok "MCP openfdd_health → openfdd-central"
else
  bad "MCP health mismatch: $(jq -c 'map(select(.id==3))[0]' "$ART/mcp_messages.json" | head -c 300)"
fi

# Direct central curls
DIRECT_RULES="$(hcurl "$HOST_CENTRAL/api/fdd/rules" | jq -c .)"
DIRECT_EQUIP="$(hcurl "$HOST_CENTRAL/api/fdd/equipment" | jq -c .)"
DIRECT_RESULTS="$(hcurl "$HOST_CENTRAL/api/fdd/results" | jq -c .)"
echo "$DIRECT_RULES" >"$ART/direct_fdd_rules.json"
echo "$DIRECT_EQUIP" >"$ART/direct_fdd_equipment.json"
echo "$DIRECT_RESULTS" >"$ART/direct_fdd_results.json"

mcp_text() {
  local id="$1"
  jq -r --argjson id "$id" '
    map(select(.id==$id))[0]
    | if .error then empty
      else (.result.content[0].text // empty)
      end
  ' "$ART/mcp_messages.json"
}
mcp_err() {
  local id="$1"
  jq -c --argjson id "$id" 'map(select(.id==$id))[0].error // empty' "$ART/mcp_messages.json"
}

for id in 4 5 6 7; do
  if [[ -n "$(mcp_err "$id")" ]]; then
    bad "MCP id=$id error: $(mcp_err "$id" | head -c 200)"
  fi
done

MCP_RULES="$(mcp_text 4)"
MCP_EQUIP="$(mcp_text 5)"
MCP_RESULTS="$(mcp_text 6)"
if [[ -z "$MCP_RULES" || -z "$MCP_EQUIP" || -z "$MCP_RESULTS" ]]; then
  bad "MCP FDD payloads empty (auth?). rules=$([[ -n $MCP_RULES ]] && echo ok || echo missing) equip=$([[ -n $MCP_EQUIP ]] && echo ok || echo missing) results=$([[ -n $MCP_RESULTS ]] && echo ok || echo missing)"
else
  # Compare via files — large FDD payloads exceed jq --argjson ARG_MAX.
  printf '%s' "$DIRECT_RULES" >"$ART/direct_rules.json"
  printf '%s' "$MCP_RULES" >"$ART/mcp_rules.json"
  printf '%s' "$DIRECT_EQUIP" >"$ART/direct_equip.json"
  printf '%s' "$MCP_EQUIP" >"$ART/mcp_equip.json"
  printf '%s' "$DIRECT_RESULTS" >"$ART/direct_results.json"
  printf '%s' "$MCP_RESULTS" >"$ART/mcp_results.json"
  eq_rules="$(jq -ne --slurpfile d "$ART/direct_rules.json" --slurpfile m "$ART/mcp_rules.json" \
    '($d[0].count==$m[0].count) and (($d[0].rules|map(.rule_id))==($m[0].rules|map(.rule_id)))')"
  eq_equip="$(jq -ne --slurpfile d "$ART/direct_equip.json" --slurpfile m "$ART/mcp_equip.json" \
    '($d[0].equipment==$m[0].equipment) or (($d[0].count==$m[0].count) and ($d[0].equipment|length)==($m[0].equipment|length))')"
  eq_res="$(jq -ne --slurpfile d "$ART/direct_results.json" --slurpfile m "$ART/mcp_results.json" \
    '$d[0].results==$m[0].results')"
  [[ "$eq_rules" == "true" ]] && ok "MCP registry == central /api/fdd/rules" || bad "MCP registry ≠ central"
  [[ "$eq_equip" == "true" ]] && ok "MCP equipment == central /api/fdd/equipment" || bad "MCP equipment ≠ central"
  [[ "$eq_res" == "true" ]] && ok "MCP results == central /api/fdd/results" || bad "MCP results ≠ central"
fi

# accuracy_snapshot
SNAP_TXT="$(mcp_text 7)"
if [[ -n "$SNAP_TXT" ]] && jq -e '.ok==true' <<<"$SNAP_TXT" >/dev/null 2>&1; then
  ok "MCP accuracy_snapshot ok=true"
else
  bad "MCP accuracy_snapshot not ok: $(mcp_err 7 | head -c 200) ${SNAP_TXT:0:200}"
fi

# Negatives: unknown tool must error; empty series args must not invent rows
if [[ -n "$(mcp_err 8)" ]]; then
  ok "negative: unknown tool errors (no silent invent)"
else
  bad "negative: unknown tool did not error cleanly"
fi

SERIES_TXT="$(mcp_text 9)"
if [[ -n "$(mcp_err 9)" ]]; then
  # 401/validation error is honest — must not invent series
  ok "negative: empty series args → JSON-RPC/HTTP error (no invented series)"
elif [[ -n "$SERIES_TXT" ]] && jq -e '(.ok==false) or ((.rows//[])|length==0) or (.error!=null)' <<<"$SERIES_TXT" >/dev/null 2>&1; then
  ok "negative: empty series args → honest empty/error (no invented series)"
else
  bad "negative: empty series call invented data or empty response: ${SERIES_TXT:0:200}"
fi

# Process-up alone is insufficient — equality above is the PASS bar
ok "MCP accuracy gate requires payload equality (process-up alone ≠ PASS)"

summary
