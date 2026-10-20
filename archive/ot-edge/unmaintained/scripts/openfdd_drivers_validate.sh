#!/usr/bin/env bash
# Bench/field driver validation: BACnet (commission), Modbus, Haystack, JSON API.
# Requires live stack + operator workspace config (no hardcoded bench IPs in repo).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BRIDGE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_FILE:-$ROOT/workspace/auth.env.local}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_DRIVERS_VALIDATE_LOG:-$ROOT/workspace/logs/drivers_validate_$STAMP}"
PASS=0
FAIL=0
SKIP=0

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/run.log") 2>&1

echo "==> openfdd_drivers_validate ($STAMP)"
echo "    bridge=$BRIDGE commission=$COMMISSION log=$LOG_DIR"

record() {
  local driver="$1" status="$2" detail="${3:-}"
  case "$status" in
    PASS) PASS=$((PASS + 1)); echo "PASS $driver${detail:+ — $detail}" ;;
    FAIL) FAIL=$((FAIL + 1)); echo "FAIL $driver${detail:+ — $detail}" >&2 ;;
    SKIP) SKIP=$((SKIP + 1)); echo "SKIP $driver${detail:+ — $detail}" ;;
  esac
}

TOKEN=""
if [[ -f "$AUTH" ]]; then
  TOKEN="$(openfdd_auth_login_token "$BRIDGE" "$AUTH" integrator 2>/dev/null || true)"
fi
AUTH_H=()
[[ -n "$TOKEN" ]] && AUTH_H=(-H "Authorization: Bearer $TOKEN")

# --- JSON API ---
json_api_endpoints="$ROOT/workspace/data/json_api/endpoints.json"
json_endpoint_count() {
  jq 'if type == "array" then length elif .endpoints then (.endpoints | length) else 0 end' "$1" 2>/dev/null || echo 0
}
if [[ ! -f "$json_api_endpoints" ]]; then
  if grep -qE '^OPENFDD_JSON_API_URL=' "$ROOT/workspace/data.env.local" 2>/dev/null; then
    record json-api SKIP "restart bridge after OPENFDD_JSON_API_URL seed (3.2.4+)"
  else
    record json-api SKIP "no workspace/data/json_api/endpoints.json — set OPENFDD_JSON_API_URL or add endpoints"
  fi
else
  count="$(json_endpoint_count "$json_api_endpoints")"
  if [[ "$count" -eq 0 ]]; then
    record json-api SKIP "endpoints.json empty"
  elif curl -fsS "${AUTH_H[@]}" "$BRIDGE/api/json-api/poll/status" -o "$LOG_DIR/json_api_status.json" 2>/dev/null; then
    ok="$(jq -r '.ok // false' "$LOG_DIR/json_api_status.json" 2>/dev/null || echo false)"
    configured="$(jq -r '.configured // false' "$LOG_DIR/json_api_status.json" 2>/dev/null || echo false)"
    status="$(jq -r '.status // ""' "$LOG_DIR/json_api_status.json" 2>/dev/null || echo "")"
    if [[ "$ok" == "true" && "$configured" == "true" && "$status" == "ready" ]]; then
      record json-api PASS "configured points=$count"
    elif [[ "$ok" == "true" && "$configured" != "true" ]]; then
      record json-api FAIL "not_configured (set OPENFDD_JSON_API_URL + restart bridge, or POST /api/json-api/register)"
    else
      record json-api FAIL "$(jq -r '.error // .message // "status not ok"' "$LOG_DIR/json_api_status.json" 2>/dev/null)"
    fi
  else
    record json-api FAIL "GET /api/json-api/poll/status"
  fi
fi

# --- Modbus ---
if curl -fsS "${AUTH_H[@]}" "$BRIDGE/api/modbus/commission/status" -o "$LOG_DIR/modbus_status.json" 2>/dev/null; then
  mode="$(jq -r '.config.mode // "unknown"' "$LOG_DIR/modbus_status.json" 2>/dev/null)"
  if [[ "$mode" == "live" ]]; then
    if curl -fsS "${AUTH_H[@]}" -X POST "$BRIDGE/api/modbus/poll-once" -H 'Content-Type: application/json' -d '{}' \
      -o "$LOG_DIR/modbus_poll.json" 2>/dev/null; then
      record modbus PASS "$(jq -r '.points_read // .ok' "$LOG_DIR/modbus_poll.json" 2>/dev/null || echo polled)"
    else
      record modbus FAIL "poll-once"
    fi
  else
    record modbus SKIP "mode=$mode (set OPENFDD_MODBUS_MODE=live)"
  fi
else
  record modbus FAIL "commission/status"
fi

# --- BACnet (commission host-network) ---
BACNET_DEVICE="${OPENFDD_BACNET_VALIDATE_DEVICE:-}"
BACNET_HOST="${OPENFDD_BACNET_VALIDATE_HOST:-}"
if [[ -z "$BACNET_DEVICE" || -z "$BACNET_HOST" ]]; then
  record bacnet SKIP "set OPENFDD_BACNET_VALIDATE_DEVICE and OPENFDD_BACNET_VALIDATE_HOST for field read"
else
  read_body="$(jq -nc --arg pid "bacnet:${BACNET_DEVICE}:analog-input:1173" '{point_id:$pid}')"
  if curl -fsS "${AUTH_H[@]}" -X POST "$COMMISSION/api/bacnet/read" \
    -H 'Content-Type: application/json' -d "$read_body" -o "$LOG_DIR/bacnet_read.json" 2>/dev/null; then
    val="$(jq -r '.value // .present_value // empty' "$LOG_DIR/bacnet_read.json" 2>/dev/null)"
    if [[ -n "$val" && "$val" != "null" ]]; then
      record bacnet PASS "device $BACNET_DEVICE sample=$val"
    else
      record bacnet FAIL "read returned no value ($(cat "$LOG_DIR/bacnet_read.json"))"
    fi
  else
    record bacnet FAIL "commission read device $BACNET_DEVICE"
  fi
fi

# --- Haystack ---
STRICT="${OPENFDD_DRIVERS_VALIDATE_STRICT:-0}"
if curl -fsS "${AUTH_H[@]}" "$BRIDGE/api/haystack/status" -o "$LOG_DIR/haystack_status.json" 2>/dev/null; then
  enabled="$(jq -r '.enabled // .config.enabled // false' "$LOG_DIR/haystack_status.json" 2>/dev/null)"
  password_set="$(jq -r '.password_set // .config.password_set // false' "$LOG_DIR/haystack_status.json" 2>/dev/null)"
  if [[ "$STRICT" == "1" && "$password_set" != "true" ]]; then
    record haystack FAIL "OPENFDD_HAYSTACK_PASS not set in workspace/data.env.local"
  elif [[ "$enabled" != "true" ]]; then
    record haystack SKIP "not enabled — configure workspace/haystack/local.nhaystack.toml + OPENFDD_HAYSTACK_*"
  elif curl -fsS "${AUTH_H[@]}" -X POST "$BRIDGE/api/haystack/test" -H 'Content-Type: application/json' -d '{}' \
    -o "$LOG_DIR/haystack_test.json" 2>/dev/null; then
    ok="$(jq -r '.ok // false' "$LOG_DIR/haystack_test.json" 2>/dev/null)"
    if [[ "$ok" == "true" ]]; then
      curl -fsS "${AUTH_H[@]}" -X POST "$BRIDGE/api/haystack/poll-once" -H 'Content-Type: application/json' -d '{}' \
        -o "$LOG_DIR/haystack_poll.json" 2>/dev/null || true
      record haystack PASS "$(jq -r '.points // .message // "connected"' "$LOG_DIR/haystack_test.json" 2>/dev/null)"
    else
      record haystack FAIL "$(jq -r '.error // "test failed"' "$LOG_DIR/haystack_test.json" 2>/dev/null)"
    fi
  else
    record haystack FAIL "POST /api/haystack/test"
  fi
else
  record haystack FAIL "GET /api/haystack/status"
fi

# --- SPARQL (JWT; skip on older images) ---
if [[ -n "$TOKEN" ]]; then
  code="$(curl -s -o "$LOG_DIR/sparql_catalog.json" -w '%{http_code}' "${AUTH_H[@]}" "$BRIDGE/api/model/sparql/predefined" || echo 000)"
  if [[ "$code" == "200" ]]; then
    record sparql PASS "GET /api/model/sparql/predefined"
  elif [[ "$code" == "404" ]]; then
    record sparql SKIP "routes not in image (pre-3.2.3 SPARQL)"
  else
    record sparql FAIL "GET /api/model/sparql/predefined HTTP $code"
  fi
else
  record sparql SKIP "no integrator JWT"
fi

echo ""
echo "==> summary: pass=$PASS fail=$FAIL skip=$SKIP"
echo "    artifacts: $LOG_DIR"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
