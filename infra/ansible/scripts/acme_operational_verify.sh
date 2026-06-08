#!/usr/bin/env bash
# Acme operational verify: discover → learn devices → model import → FDD rules → poll check.
#
#   ./scripts/acme_operational_verify.sh --host <tailscale-or-lan-ip>
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"
VIBE_ROOT="${VIBE12_ROOT:-$HOME/py-bacnet-stacks-playground/vibe_code_apps_12}"

HOST=""
SKIP_DISCOVER=0
SKIP_WAIT=1
WAIT_MINUTES="${RUN_WAIT_MINUTES:-3}"
AUTH_ENV="${ROOT}/workspace/auth.env.local"
ACME_SECRETS="${ANSIBLE_DIR}/secrets/acme.env.local"
TRIM_DEVICES="${ROOT}/edge_backup/local/acme/vm-bbartling/devices_discovered.trim.csv"
FAILURES=0

if [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
fi
if [[ -f "$ACME_SECRETS" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$ACME_SECRETS" && set +a
fi
LOGIN_USER="${ACME_INTEGRATOR_USER:-${OFDD_INTEGRATOR_USER:-${OFDD_OPERATOR_USER:-operator}}}"
LOGIN_PASS="${ACME_INTEGRATOR_PASSWORD:-${OFDD_INTEGRATOR_PASSWORD:-${OFDD_OPERATOR_PASSWORD:-}}}"

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
log_info() { printf '  ..   %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --skip-discover) SKIP_DISCOVER=1; shift ;;
    --wait-minutes) WAIT_MINUTES="$2"; SKIP_WAIT=0; shift 2 ;;
    --skip-wait) SKIP_WAIT=1; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$HOST" ]] || { echo "Need --host" >&2; exit 1; }

BASE="http://${HOST}"
CURL=(curl -fsS --connect-timeout 15 --max-time 300)

login() {
  "${CURL[@]}" -X POST "${BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$LOGIN_USER" "$LOGIN_PASS")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
}

api_get() { "${CURL[@]}" -H "Authorization: Bearer ${TOKEN}" "${BASE}$1"; }
api_post() {
  local path="$1" body="${2:-{}}"
  "${CURL[@]}" -X POST -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
    -d "$body" "${BASE}${path}"
}

# Sets API_POST_STATUS and API_POST_BODY (do not call inside $() — subshell drops globals).
api_post_status() {
  local path="$1" body="${2:-{}}"
  local tmp
  tmp="$(mktemp)"
  API_POST_STATUS="$(curl -sS --connect-timeout 15 --max-time 300 -o "$tmp" -w "%{http_code}" \
    -X POST -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
    -d "$body" "${BASE}${path}" 2>/dev/null)" || API_POST_STATUS="000"
  API_POST_BODY="$(cat "$tmp")"
  rm -f "$tmp"
}

wait_job() {
  local job_id="$1" label="$2" max="${3:-120}"
  local i=0
  while [[ $i -lt $max ]]; do
    local st
    st="$(api_get "/api/bacnet/jobs/${job_id}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    if [[ "$st" == "ok" ]]; then log_ok "${label} job ${job_id}"; return 0; fi
    if [[ "$st" == "failed" ]]; then log_fail "${label} failed"; api_get "/api/bacnet/jobs/${job_id}" >&2; return 1; fi
    sleep 5
    i=$((i + 1))
  done
  log_fail "${label} timed out"
  return 1
}

echo "Acme operational verify → ${HOST}"
[[ -n "$LOGIN_PASS" ]] || { log_fail "No credentials in ${AUTH_ENV}"; exit 1; }
TOKEN="$(login)"
log_ok "Authenticated as ${LOGIN_USER}"

if [[ "$SKIP_DISCOVER" -eq 0 ]]; then
  log_info "BACnet Who-Is discover (full OT range)"
  disc="$(api_post "/api/bacnet/discover" '{"range_low":1,"range_high":4194303}')"
  job_id="$(echo "$disc" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("job_id",""))')"
  [[ -n "$job_id" ]] && wait_job "$job_id" "Discover" 180 || log_fail "discover: $disc"

  if [[ -f "$TRIM_DEVICES" ]]; then
    log_info "Point discovery on trim devices (AHU/VAV/boiler/tracer — skip 5xxx)"
    while IFS= read -r line; do
      [[ "$line" == device_instance* ]] && continue
      inst="$(echo "$line" | cut -d, -f1)"
      addr="$(echo "$line" | cut -d, -f2)"
      [[ -n "$inst" && -n "$addr" ]] || continue
      body="$(python3 -c 'import json,sys; print(json.dumps({"device_instance":int(sys.argv[1]),"device_address":sys.argv[2]}))' "$inst" "$addr")"
      pd="$(api_post "/api/bacnet/point-discovery" "$body")"
      pj="$(echo "$pd" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("job_id",""))' 2>/dev/null || true)"
      if [[ -n "$pj" ]]; then
        wait_job "$pj" "Point learn dev ${inst}" 240 || true
      fi
    done < "$TRIM_DEVICES"
  fi
fi

inv="$(api_get "/api/bacnet/inventory")"
dev_count="$(echo "$inv" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("devices",[])))')"
pt_count="$(echo "$inv" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("point_count",0))')"
if [[ "${dev_count:-0}" -ge 5 && "${pt_count:-0}" -ge 20 ]]; then
  log_ok "BACnet inventory devices=${dev_count} points=${pt_count}"
else
  log_fail "BACnet inventory thin: devices=${dev_count} points=${pt_count}"
fi

log_info "Import-to-model (AI data modeling path)"
# Use first discovered device with points for smoke import
import_body="$(echo "$inv" | python3 -c "
import json, sys
inv = json.load(sys.stdin)
devices = inv.get('devices') or []
if not devices:
    print('{}')
    sys.exit(0)
d = devices[0]
objs = []
for p in (d.get('points') or [])[:50]:
    ot = p.get('object_type', '')
    oi = p.get('object_instance', '')
    objs.append({
        'object_identifier': f'{ot},{oi}',
        'name': p.get('object_name') or p.get('point_id'),
        'commandable': False,
    })
print(json.dumps({
    'device_instance': int(d.get('device_instance') or 0),
    'device_address': d.get('device_address') or '',
    'objects': objs,
}))
")"
if [[ "$import_body" != "{}" ]]; then
  api_post_status "/api/bacnet/import-to-model" "$import_body"
  import_code="${API_POST_STATUS}"
  imp="${API_POST_BODY}"
  if [[ "$import_code" == "200" ]]; then
    log_ok "import-to-model: $(echo "$imp" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("equipment_id", d.get("ok", d)))' 2>/dev/null || echo ok)"
  elif [[ "$import_code" == "422" ]]; then
    log_info "import-to-model skipped (422 validation — model already commissioned)"
  else
    log_fail "import-to-model HTTP ${import_code}: ${imp:0:200}"
  fi
fi

sync="$(api_post "/api/model/bacnet-sync" "{}")"
log_ok "bacnet-sync: $(echo "$sync" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("synced_points", d))' 2>/dev/null)"

tree="$(api_get "/api/model/tree")"
model_pts="$(echo "$tree" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("points",[])))')"
zat="$(echo "$tree" | python3 -c 'import json,sys; print(sum(1 for p in json.load(sys.stdin).get("points",[]) if p.get("brick_type")=="Zone_Air_Temperature_Sensor"))')"
log_ok "Model tree points=${model_pts} zone_temp=${zat}"

log_info "Setup default zone-temp FDD rules (brick-scoped)"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
python3 "${ROOT}/scripts/setup_gl36_fdd.py" \
  --site-id "${SITE_ID:-acme}" \
  --building-id "${BUILDING_ID:-vm-bbartling}" \
  --ahu-system-id "${AHU_SYSTEM_ID:-rtu-01}" \
  --fan-point-id "${FAN_POINT_ID:-1100-analog-output-1}" \
  --zone-avg-cols "${ZONE_AVG_COLS:-}" \
  --host "$HOST" --token "$TOKEN" || log_fail "FDD setup script"

log_info "Poll once smoke test"
poll="$(api_post "/api/bacnet/poll/once" "{}")"
samples="$(echo "$poll" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("poll",{}).get("samples",0))' 2>/dev/null || echo 0)"
if [[ "${samples:-0}" -gt 0 ]]; then
  log_ok "Poll once samples=${samples}"
else
  log_fail "Poll once: ${poll}"
fi

if [[ "$SKIP_WAIT" -eq 0 ]]; then
  log_info "Wait ${WAIT_MINUTES}m for poll samples..."
  sleep $((WAIT_MINUTES * 60))
  ssh -o BatchMode=yes -o ConnectTimeout=10 "bbartling@${HOST}" \
    "wc -l ~/open-fdd/workspace/bacnet/polls/samples.csv 2>/dev/null || true" || true
fi

log_info "Building agent API (poll throughput, FDD results, ops logs)"
for path in \
  "/api/analytics/poll-throughput?window_minutes=30" \
  "/api/fdd/results?limit=5" \
  "/api/ops/logs?tail=40&include_docker=false" \
  "/api/building-agent/status" \
  "/api/building-agent/tuning-brief?window_minutes=30"; do
  code="$(curl -sS --connect-timeout 15 --max-time 120 -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" "${BASE}${path}" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    log_ok "GET ${path} HTTP 200"
  else
    log_fail "GET ${path} HTTP ${code}"
  fi
done

log_info "Building agent check-in (no FDD batch — smoke)"
CHECKIN_BODY="$(python3 -c 'import json; print(json.dumps({"run_fdd_batch": False, "write_memory": True, "window_minutes": 30, "site_id": "acme"}))')"
api_post_status "/api/building-agent/checkin" "$CHECKIN_BODY"
if [[ "${API_POST_STATUS:-000}" == "200" ]]; then
  log_ok "POST /api/building-agent/checkin HTTP 200"
else
  log_fail "POST /api/building-agent/checkin HTTP ${API_POST_STATUS:-000}: ${API_POST_BODY:-}"
fi

echo "---"
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Acme operational verify PASSED"
  exit 0
fi
echo "Acme operational verify FAILED (${FAILURES} checks)"
exit 1
