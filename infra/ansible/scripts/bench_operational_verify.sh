#!/usr/bin/env bash
# Operational verification for Open-FDD BACnet bench (discover → model → poll → FDD data).
# Run from bensserver against a deployed edge host (default: bacnet_pi / 192.168.204.12).
#
# Examples:
#   ./scripts/bench_operational_verify.sh --host 192.168.204.12
#   ./scripts/bench_operational_verify.sh --inventory inventory.yml --limit bacnet_pi --wait-minutes 10
#   RUN_WAIT=0 ./scripts/bench_operational_verify.sh --host 192.168.204.12 --skip-wait
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(cd "$DIR/.." && pwd)"
ROOT="$(cd "$ANSIBLE_DIR/../.." && pwd)"

HOST=""
PORT="${OFDD_HTTP_PORT:-}"
INV="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.yml}"
LIMIT=""
AUTH_ENV="${ROOT}/workspace/auth.env.local"
if [[ -f "$AUTH_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a && source "$AUTH_ENV" && set +a
fi
LOGIN_USER="${OFDD_INTEGRATOR_USER:-${OFDD_OPERATOR_USER:-}}"
LOGIN_PASS="${OFDD_INTEGRATOR_PASSWORD:-${OFDD_OPERATOR_PASSWORD:-}}"
MODEL_IMPORT="${ROOT}/workspace/data/bench_import_model.json"
WAIT_MINUTES="${RUN_WAIT_MINUTES:-20}"
SKIP_WAIT=0
DEVICE_INSTANCE=5007
DISCOVER_LOW=5007
DISCOVER_HIGH=5007
POLL_INTERVAL=60
MIN_SAMPLE_ROWS=8
MIN_UNIQUE_TS=3
FAILURES=0

# Same bench points as edge_backup/local/demo/bens-office/points.csv
EXPECTED_POINTS=(
  "5007-analog-input-10014"
  "5007-analog-input-1168"
  "5007-analog-input-1173"
  "5007-analog-input-1192"
)
EXPECTED_RULE_IDS=(
  "bench-stat-zn-t-flatline-1h"
  "bench-oa-h-flatline-1h"
  "bench-oa-h-oob"
)

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log_ok() { printf '  OK   %s\n' "$*"; }
log_fail() { printf '  FAIL %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
log_info() { printf '  ..   %s\n' "$*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --inventory) INV="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --auth-env) AUTH_ENV="$2"; shift 2 ;;
    --wait-minutes) WAIT_MINUTES="$2"; shift 2 ;;
    --skip-wait) SKIP_WAIT=1; shift ;;
    --device) DEVICE_INSTANCE="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

if [[ -z "$HOST" && -n "$LIMIT" && -f "$INV" ]] && command -v ansible-inventory >/dev/null 2>&1; then
  HOST="$(ansible-inventory -i "$INV" --host "$LIMIT" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ansible_host",""))' || true)"
fi
[[ -n "$HOST" ]] || { echo "Need --host or --limit with inventory." >&2; usage 1; }

if [[ -z "$PORT" && "$HOST" =~ ^(127\.0\.0\.1|localhost)$ ]]; then
  PORT="8765"
fi
if [[ -n "$PORT" ]]; then
  BASE="http://${HOST}:${PORT}"
else
  BASE="http://${HOST}"
fi
CURL=(curl -fsS --connect-timeout 10 --max-time 120)

login() {
  local user="$1" pass="$2"
  "${CURL[@]}" -X POST "${BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"username":sys.argv[1],"password":sys.argv[2]}))' "$user" "$pass")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
}

api_get() {
  local path="$1"
  "${CURL[@]}" -H "Authorization: Bearer ${TOKEN}" "${BASE}${path}"
}

api_post() {
  local path="$1"
  local body="${2:-}"
  [[ -n "$body" ]] || body="{}"
  "${CURL[@]}" -X POST -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
    -d "$body" "${BASE}${path}"
}

wait_job() {
  local job_id="$1" label="$2"
  local i=0 max=90
  while [[ $i -lt $max ]]; do
    local st
    st="$(api_get "/api/bacnet/jobs/${job_id}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    if [[ "$st" == "ok" ]]; then
      log_ok "${label} job ${job_id} completed"
      return 0
    fi
    if [[ "$st" == "failed" ]]; then
      log_fail "${label} job ${job_id} failed"
      api_get "/api/bacnet/jobs/${job_id}" >&2 || true
      return 1
    fi
    sleep 5
    i=$((i + 1))
  done
  log_fail "${label} job ${job_id} timed out"
  return 1
}

echo "Open-FDD bench operational verify → ${HOST}"

[[ -n "$LOGIN_USER" && -n "$LOGIN_PASS" ]] || { log_fail "No integrator/operator credentials in ${AUTH_ENV}"; exit 1; }

TOKEN="$(login "$LOGIN_USER" "$LOGIN_PASS")"
log_ok "Authenticated as ${LOGIN_USER}"

HTTP_PROBES="${DIR}/http_probes.py"
if [[ -f "$HTTP_PROBES" ]]; then
  if probe_out="$(python3 "$HTTP_PROBES" check "$BASE" "$LOGIN_USER" "$LOGIN_PASS" 2>/dev/null)"; then
    asset="$(echo "$probe_out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("asset_path",""))')"
    log_ok "Entry probes OK (React dashboard${asset:+ $asset}, login)"
  else
    while IFS= read -r err; do log_fail "$err"; done < <(echo "$probe_out" | python3 -c 'import json,sys; [print(e) for e in json.load(sys.stdin).get("errors",[])]' 2>/dev/null || echo "entry probe failed")
  fi
fi

log_info "BACnet discover ${DISCOVER_LOW}..${DISCOVER_HIGH}"
discover_body="$(python3 -c 'import json,sys; print(json.dumps({"range_low": int(sys.argv[1]), "range_high": int(sys.argv[2])}))' "$DISCOVER_LOW" "$DISCOVER_HIGH")"
discover_resp="$(api_post "/api/bacnet/discover" "$discover_body")"
job_id="$(echo "$discover_resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("job_id",""))')"
[[ -n "$job_id" ]] || { log_fail "discover did not return job_id: $discover_resp"; exit 1; }
wait_job "$job_id" "Discover" || true

inv="$(api_get "/api/bacnet/inventory")"
inv_count="$(echo "$inv" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("point_count",0))')"
if [[ "$inv_count" -ge 4 ]]; then
  log_ok "BACnet inventory point_count=${inv_count}"
else
  log_fail "BACnet inventory point_count=${inv_count} (expected >= 4)"
fi

if [[ -f "$MODEL_IMPORT" ]]; then
  log_info "Import bench BRICK model (AI/data-modeling path)"
  import_body="$(python3 -c 'import json,pathlib,sys; print(json.dumps({"payload": json.loads(pathlib.Path(sys.argv[1]).read_text()), "replace": True}))' "$MODEL_IMPORT")"
  imp="$(api_post "/api/model/import" "$import_body")"
  pts="$(echo "$imp" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("points", d.get("point_count", 0)))' 2>/dev/null || echo 0)"
  log_ok "Model import response points=${pts}"
else
  log_fail "Missing ${MODEL_IMPORT}"
fi

sync="$(api_post "/api/model/bacnet-sync" "{}")"
log_ok "BACnet sync to model: $(echo "$sync" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("synced_points", d.get("ok", d)))' 2>/dev/null || echo ok)"

tree="$(api_get "/api/model/tree")"
for pid in "${EXPECTED_POINTS[@]}"; do
  if echo "$tree" | python3 -c "import json,sys; pts=json.load(sys.stdin).get('points',[]); sys.exit(0 if any(p.get('id')=='$pid' for p in pts) else 1)"; then
    log_ok "Model point ${pid}"
  else
    log_fail "Model missing point ${pid}"
  fi
done

rules="$(api_get "/api/rules/saved")"
for rid in "${EXPECTED_RULE_IDS[@]}"; do
  if echo "$rules" | python3 -c "import json,sys; rs=json.load(sys.stdin).get('rules',[]); sys.exit(0 if any(r.get('id')=='$rid' for r in rs) else 1)"; then
    log_ok "FDD rule ${rid}"
  else
    log_fail "Missing FDD rule ${rid}"
  fi
done

log_info "Trigger one poll cycle"
poll_once="$(api_post "/api/bacnet/poll/once" "{}")"
poll_ok="$(echo "$poll_once" | python3 -c 'import json,sys; p=json.load(sys.stdin).get("poll",{}); print(p.get("ok", False))' 2>/dev/null || echo False)"
poll_samples="$(echo "$poll_once" | python3 -c 'import json,sys; p=json.load(sys.stdin).get("poll",{}); print(p.get("samples",0))' 2>/dev/null || echo 0)"
if [[ "$poll_ok" == "True" || "$poll_ok" == "true" ]] && [[ "${poll_samples:-0}" -gt 0 ]]; then
  log_ok "Poll once samples=${poll_samples}"
else
  log_fail "Poll once failed or zero samples: ${poll_once}"
fi

log_info "Driver tree + on-demand read (refresh PV / priority array)"
driver_tree="$(api_get "/api/bacnet/driver/tree")"
if echo "$driver_tree" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("devices") else 1)'; then
  log_ok "BACnet driver tree loaded"
else
  log_fail "driver tree empty"
fi
read_pv="$(api_post "/api/bacnet/read" "$(python3 -c 'import json; print(json.dumps({"device_instance":5007,"object_identifier":"analog-input,1168","property_identifier":"present-value"}))')")"
if echo "$read_pv" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "value" in d else 1)'; then
  log_ok "On-demand read PV analog-input,1168"
else
  log_fail "read PV failed: ${read_pv}"
fi

log_info "Arrow rule lint (reject legacy evaluate / pandas)"
for case in "legacy|def evaluate(row,cfg): return True" "pandas|import pandas as pd"; do
  label="${case%%|*}"
  code="${case#*|}"
  lint_body="$(python3 -c 'import json,sys; print(json.dumps({"code": sys.argv[1]}))' "$code")"
  lint_resp="$(api_post "/api/playground/lint" "$lint_body")"
  if echo "$lint_resp" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is False else 1)'; then
    log_ok "Lint rejected ${label}"
  else
    log_fail "Lint should reject ${label}"
  fi
done

log_info "FDD batch (Arrow rules)"
fdd_batch="$(api_post "/api/rules/batch" '{"limit":500}')"
if echo "$fdd_batch" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") else 1)'; then
  log_ok "FDD batch completed"
else
  log_fail "FDD batch: ${fdd_batch}"
fi
fault_status="$(api_get "/api/faults/status")"
if echo "$fault_status" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("traffic","green"))'; then
  log_ok "Fault status traffic=$(echo "$fault_status" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("traffic"))')"
fi

poll_status="$(api_get "/api/bacnet/poll/status")"
if echo "$poll_status" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("enabled_points",0)>=4 else 1)'; then
  log_ok "Poll driver enabled_points>=4 interval=${POLL_INTERVAL}s"
else
  log_fail "Poll status: ${poll_status}"
fi

if [[ "$SKIP_WAIT" == 1 ]]; then
  WAIT_MINUTES=0
fi
if [[ "$WAIT_MINUTES" -gt 0 ]]; then
  log_info "Waiting ${WAIT_MINUTES} minutes for ${POLL_INTERVAL}s scrape cadence..."
  sleep "$((WAIT_MINUTES * 60))"
fi

log_info "Validate collected poll + feather data on edge"
exp_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${EXPECTED_POINTS[@]}")"
exp_b64="$(printf '%s' "$exp_json" | base64 -w0 2>/dev/null || printf '%s' "$exp_json" | base64)"

if [[ "$HOST" =~ ^(127\.0\.0\.1|localhost)$ ]]; then
  data_out="$(ROOT="$ROOT" python3 - "$MIN_SAMPLE_ROWS" "$MIN_UNIQUE_TS" "$exp_b64" "$ROOT" <<'PY'
import base64
import csv
import json
import os
import sys
from pathlib import Path

min_rows = int(sys.argv[1])
min_ts = int(sys.argv[2])
expected = set(json.loads(base64.b64decode(sys.argv[3]).decode()))
root = Path(sys.argv[4] or os.environ.get("ROOT", "."))
polls = root / "workspace/bacnet/polls/samples.csv"
feather_root = root / "workspace/data/feather_store/bacnet"

out = {"poll_rows": 0, "unique_ts": 0, "point_ids": [], "feather_files": 0, "errors": []}
if not polls.is_file():
    out["errors"].append(f"missing {polls}")
else:
    rows = list(csv.DictReader(polls.open()))
    out["poll_rows"] = len(rows)
    out["unique_ts"] = len({r.get("timestamp_utc") for r in rows if r.get("timestamp_utc")})
    out["point_ids"] = sorted({r.get("point_id") for r in rows if r.get("point_id")})
    missing = expected - set(out["point_ids"])
    if missing:
        out["errors"].append(f"missing point_ids in samples: {sorted(missing)}")
    if out["poll_rows"] < min_rows:
        out["errors"].append(f"poll_rows {out['poll_rows']} < {min_rows}")
    if out["unique_ts"] < min_ts:
        out["errors"].append(f"unique timestamps {out['unique_ts']} < {min_ts}")

if feather_root.is_dir():
    out["feather_files"] = len(list(feather_root.rglob("latest.*")))
else:
    out["errors"].append(f"missing feather dir {feather_root}")

print(json.dumps(out))
PY
)"
  ssh_out="$data_out"
else
ssh_out="$(ssh -o BatchMode=yes ben@"${HOST}" python3 - "$MIN_SAMPLE_ROWS" "$MIN_UNIQUE_TS" "$exp_b64" <<'PY'
import base64
import csv
import json
import sys
from pathlib import Path

min_rows = int(sys.argv[1])
min_ts = int(sys.argv[2])
expected = set(json.loads(base64.b64decode(sys.argv[3]).decode()))
root = Path("/home/ben/open-fdd")
polls = root / "workspace/bacnet/polls/samples.csv"
feather_root = root / "workspace/data/feather_store/bacnet"

out = {"poll_rows": 0, "unique_ts": 0, "point_ids": [], "feather_files": 0, "errors": []}
if not polls.is_file():
    out["errors"].append(f"missing {polls}")
else:
    rows = list(csv.DictReader(polls.open()))
    out["poll_rows"] = len(rows)
    out["unique_ts"] = len({r.get("timestamp_utc") for r in rows if r.get("timestamp_utc")})
    out["point_ids"] = sorted({r.get("point_id") for r in rows if r.get("point_id")})
    missing = expected - set(out["point_ids"])
    if missing:
        out["errors"].append(f"missing point_ids in samples: {sorted(missing)}")
    if out["poll_rows"] < min_rows:
        out["errors"].append(f"poll_rows {out['poll_rows']} < {min_rows}")
    if out["unique_ts"] < min_ts:
        out["errors"].append(f"unique timestamps {out['unique_ts']} < {min_ts}")

if feather_root.is_dir():
    out["feather_files"] = len(list(feather_root.rglob("latest.*")))
else:
    out["errors"].append(f"missing feather dir {feather_root}")

print(json.dumps(out))
PY
)" || ssh_out='{"errors":["ssh failed"]}'
fi

poll_rows="$(echo "$ssh_out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("poll_rows",0))')"
unique_ts="$(echo "$ssh_out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("unique_ts",0))')"
feather_n="$(echo "$ssh_out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("feather_files",0))')"
ssh_errs="$(echo "$ssh_out" | python3 -c 'import json,sys; e=json.load(sys.stdin).get("errors",[]); print("; ".join(e))')"

if [[ -z "$ssh_errs" ]]; then
  log_ok "samples.csv rows=${poll_rows} unique_ts=${unique_ts} feather_latest=${feather_n}"
else
  log_fail "Data collection: ${ssh_errs} (rows=${poll_rows} ts=${unique_ts})"
fi

stack="$(api_get "/health/stack")"
if echo "$stack" | python3 -c 'import json,sys; s=json.load(sys.stdin); sv=s.get("services",[]); poll=next((x for x in sv if x.get("id")=="bacnet_poll"),{}); sys.exit(0 if poll.get("status") in ("green","yellow") else 1)'; then
  log_ok "Stack health: bacnet_poll OK"
else
  log_fail "Stack health bacnet_poll not OK"
fi

echo "---"
if [[ "$FAILURES" -gt 0 ]]; then
  echo "Bench operational verify FAILED (${FAILURES} issue(s))" >&2
  exit 1
fi
echo "Bench operational verify PASSED for ${HOST}"
exit 0
