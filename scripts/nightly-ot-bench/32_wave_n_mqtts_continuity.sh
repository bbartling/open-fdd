#!/usr/bin/env bash
# Wave N — MQTTS continuity: ingest_ok / edges must advance across poll windows.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ART="${ARTIFACT_DIR:-$ROOT/reports/wave_n_mqtts_cont_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
[[ -n "$BASE" ]] || { echo "set OPENFDD_API_BASE or RAILWAY_BASE" >&2; exit 1; }
BASE="${BASE%/}"
# Default one full 300s cycle + buffer; set WAVE_N_CONTINUITY_SECS=600 for two cycles.
WAIT_SECS="${WAVE_N_CONTINUITY_SECS:-320}"

auth_hdr=()
if [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  tok="$(curl -sf -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
    | jq -r '.token // .access_token')"
  auth_hdr=(-H "Authorization: Bearer $tok")
fi

snap() {
  local name="$1"
  curl -sf "${auth_hdr[@]}" "$BASE/api/health" | tee "$ART/health_${name}.json"
  curl -sf "${auth_hdr[@]}" "$BASE/api/ingest/stats" 2>/dev/null | tee "$ART/ingest_${name}.json" || echo '{}' >"$ART/ingest_${name}.json"
  curl -sf "${auth_hdr[@]}" "$BASE/api/edges" 2>/dev/null | tee "$ART/edges_${name}.json" || echo '{}' >"$ART/edges_${name}.json"
}

ingest_val() {
  python3 - "$1" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
for k in ("ingest_ok","messages_ok","ok","accepted","total","count"):
    v=d.get(k)
    if isinstance(v,(int,float)):
        print(int(v)); raise SystemExit
print(0)
PY
}

edge_count() {
  python3 - "$1" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
if isinstance(d,list):
    print(len(d)); raise SystemExit
edges=d.get("edges") or d.get("items") or []
print(len(edges) if isinstance(edges,list) else 0)
PY
}

# O13: after tip re-pin, ingest_ok/edges reset (since-boot). Wait out a short grace
# so we do not FAIL-NEW solely because central just restarted.
grace_after_boot() {
  local health uptime need sleep_for
  health="$(curl -sf "${auth_hdr[@]}" "$BASE/api/health" || echo '{}')"
  uptime="$(echo "$health" | jq -r '.uptime_secs // 0')"
  need="${WAVE_N_BOOT_GRACE_SECS:-90}"
  if [[ "$uptime" =~ ^[0-9]+$ ]] && (( uptime < need )); then
    sleep_for=$((need - uptime))
    echo "boot grace: uptime_secs=$uptime < $need — sleep ${sleep_for}s (ingest_ok is since-boot)" | tee "$ART/boot_grace.log"
    sleep "$sleep_for"
  fi
  if echo "$health" | jq -e 'has("historian_present") and .historian_present == false' >/dev/null 2>&1; then
    echo "WARN: historian_present=false — volume may be missing (not just counters reset)" | tee -a "$ART/boot_grace.log"
  fi
}

grace_after_boot

snap before
b_ing="$(ingest_val "$ART/ingest_before.json")"
b_edges="$(edge_count "$ART/edges_before.json")"
echo "before ingest_ok=$b_ing edges=$b_edges wait=${WAIT_SECS}s" | tee "$ART/continuity.log"
sleep "$WAIT_SECS"
snap after
a_ing="$(ingest_val "$ART/ingest_after.json")"
a_edges="$(edge_count "$ART/edges_after.json")"
echo "after ingest_ok=$a_ing edges=$a_edges" | tee -a "$ART/continuity.log"

ok=0
if [[ "$a_ing" -gt "$b_ing" ]]; then
  echo "PASS: ingest_ok advanced $b_ing → $a_ing" | tee -a "$ART/continuity.log"
  ok=1
elif [[ "$a_edges" -gt 0 && "$TELEMETRY_LIVE:-0" == "1" ]]; then
  # Dedup may hold counter flat; require live flag + edges present
  echo "PASS: edges present ($a_edges) with TELEMETRY_LIVE=1 (counter flat)" | tee -a "$ART/continuity.log"
  ok=1
fi

if [[ "$ok" -ne 1 ]]; then
  echo "FAIL: MQTTS continuity — ingest did not advance and no live-edge waiver" | tee -a "$ART/continuity.log"
  jq -n '{ok:false,gate:"wave_n_mqtts_continuity"}' | tee "$ART/continuity_verdict.json"
  exit 1
fi
jq -n --argjson before "$b_ing" --argjson after "$a_ing" \
  '{ok:true,gate:"wave_n_mqtts_continuity",ingest_before:$before,ingest_after:$after}' \
  | tee "$ART/continuity_verdict.json"
