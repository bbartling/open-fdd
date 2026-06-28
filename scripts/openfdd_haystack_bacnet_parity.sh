#!/usr/bin/env bash
# BACnet vs Haystack parity smoke (issue #402 H-02). Requires live OT + configured profile.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
AUTH="$ROOT/workspace/auth.env.local"
PROFILE="${OPENFDD_HAYSTACK_PARITY_PROFILE:-}"
if [[ -z "$PROFILE" ]]; then
  echo "ERROR: set OPENFDD_HAYSTACK_PARITY_PROFILE to your configured parity TOML (copy from local_haystack_5007_parity.local.toml.example)." >&2
  exit 2
fi
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_PARITY_ARTIFACT_DIR:-$ROOT/workspace/logs/haystack_bacnet_parity_${RUN_TS}}"
mkdir -p "$LOG_DIR"

if [[ ! -f "$PROFILE" ]]; then
  echo "ERROR: parity profile not found: $PROFILE" >&2
  echo "Copy workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml.example and set haystack_id values." >&2
  exit 2
fi

TOKEN="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator)"
DEVICE="$(grep -E '^device_instance' "$PROFILE" | head -1 | awk -F= '{gsub(/ /,"",$2); print $2}')"
if [[ -z "$DEVICE" ]] || ! [[ "$DEVICE" =~ ^[0-9]+$ ]]; then
  echo "ERROR: profile must define numeric [bacnet] device_instance (found: '${DEVICE:-<empty>}')" >&2
  exit 2
fi
TEMP_TOL="${OPENFDD_PARITY_TEMP_TOL:-1.0}"
HUM_TOL="${OPENFDD_PARITY_HUM_TOL:-5.0}"

echo "Parity run profile=$PROFILE device=$DEVICE artifact=$LOG_DIR" | tee "$LOG_DIR/run.log"

curl -fsS -X POST "${BASE}/api/bacnet/whois" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --argjson lo "$DEVICE" --argjson hi "$DEVICE" '{low_limit:$lo,high_limit:$hi}')" \
  | tee "$LOG_DIR/whois.json" >/dev/null

pass=0
fail=0
while IFS= read -r block; do
  role="$(echo "$block" | awk -F= '/^role/ {print $2}' | tr -d ' "')"
  bacnet_obj="$(echo "$block" | awk -F= '/^bacnet_object/ {print $2}' | tr -d ' "')"
  haystack_id="$(echo "$block" | awk -F= '/^haystack_id/ {print $2}' | tr -d ' "')"
  [[ -z "$role" || -z "$bacnet_obj" || -z "$haystack_id" ]] && continue
  [[ "$haystack_id" == *replace* ]] && continue

  obj_type="${bacnet_obj%%,*}"
  obj_inst="${bacnet_obj##*,}"

  bacnet_val="$(curl -fsS -X POST "${BASE}/api/bacnet/read" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --argjson dev "$DEVICE" --arg t "$obj_type" --argjson i "$obj_inst" \
      '{device_instance:$dev,object_type:$t,object_instance:$i}')" \
    | jq -r '.present_value // .value // empty' 2>/dev/null || true)"

  haystack_val="$(curl -fsS -X POST "${BASE}/api/haystack/read" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg id "$haystack_id" '{ids:[$id]}')" \
    | jq -r '.. | objects | select(has("curVal")) | .curVal // empty' 2>/dev/null | head -1)"

  tol="$TEMP_TOL"
  [[ "$role" == *"_h" ]] && tol="$HUM_TOL"
  delta="$(awk -v a="$bacnet_val" -v b="$haystack_val" 'BEGIN{if(a==""||b==""){print "nan"} else {printf "%.4f", (a-b)<0?-(a-b):(a-b)}}')"
  ok=false
  if [[ "$delta" != "nan" ]] && awk -v d="$delta" -v t="$tol" 'BEGIN{exit !(d<=t)}'; then
    ok=true
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
  fi

  jq -nc \
    --arg role "$role" \
    --arg bacnet_object "$bacnet_obj" \
    --arg haystack_id "$haystack_id" \
    --arg bacnet_value "$bacnet_val" \
    --arg haystack_value "$haystack_val" \
    --arg delta "$delta" \
    --argjson tol "$tol" \
    --argjson pass "$([ "$ok" = true ] && echo true || echo false)" \
    '{role:$role,bacnet_object:$bacnet_object,haystack_id:$haystack_id,bacnet_value:$bacnet_value,haystack_value:$haystack_value,absolute_delta:($delta|tonumber?),tolerance:$tol,pass:$pass}' \
    >>"$LOG_DIR/comparisons.jsonl"
done < <(awk '/^\[points\./,/^\[/ {print}' "$PROFILE" | grep -E '^(role|bacnet_object|haystack_id)')

echo "Parity complete pass=$pass fail=$fail" | tee -a "$LOG_DIR/run.log"
[[ "$fail" -eq 0 && "$pass" -gt 0 ]] || exit 1
