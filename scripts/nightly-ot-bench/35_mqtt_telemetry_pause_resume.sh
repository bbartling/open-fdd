#!/usr/bin/env bash
# Gate 35 — MQTT / edge telemetry pause → stall → resume (Option A streaming only).
# Required on every Railway hub stress and local OT bench run.
#
# Path under test: Central POST /api/commands target_id=edge:telemetry
# (MQTT command topic → fieldbus). When local fieldbus REST is reachable,
# also assert suspended/resumed status and force one poll after resume.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh" 2>/dev/null || true

ART="${ARTIFACT_DIR:-$ROOT/reports/mqtt_pause_resume_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-${CENTRAL_BASE:-http://127.0.0.1:8080}}}"
BASE="${BASE%/}"
FIELDBUS_BASE="${FIELDBUS_BASE:-http://127.0.0.1:8081}"
FB_KEY="${OPENFDD_FIELDBUS_API_KEY:-bench-demo-key-1234567890}"
STALL_SECS="${MQTT_PAUSE_STALL_SECS:-45}"
RESUME_WAIT_SECS="${MQTT_PAUSE_RESUME_WAIT_SECS:-90}"
ACK_POLLS="${MQTT_PAUSE_ACK_POLLS:-12}"

auth_hdr=()
tok=""
if [[ -n "${OPENFDD_ADMIN_TOKEN:-}" ]]; then
  tok="$OPENFDD_ADMIN_TOKEN"
elif [[ -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  tok="$(curl -sf --max-time 30 -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "${OPENFDD_ADMIN_USER:-admin}" --arg p "$OPENFDD_ADMIN_PASSWORD" \
      '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty')"
fi
[[ -n "$tok" ]] || { echo "ERROR: need OPENFDD_ADMIN_TOKEN or OPENFDD_ADMIN_PASSWORD" >&2; exit 2; }
auth_hdr=(-H "Authorization: Bearer $tok")

fb_reachable=0
if curl -sf --max-time 3 -H "Authorization: Bearer $FB_KEY" \
  "$FIELDBUS_BASE/telemetry/status" >/dev/null 2>&1; then
  fb_reachable=1
fi
echo "fieldbus_rest_reachable=$fb_reachable base=$FIELDBUS_BASE" | tee "$ART/pause_resume.log"

fb() {
  curl -sf --max-time 30 -H "Authorization: Bearer $FB_KEY" -H "Content-Type: application/json" "$@"
}

ingest_ok() {
  curl -sf --max-time 20 "${auth_hdr[@]}" "$BASE/api/ingest/stats" 2>/dev/null \
    | tee "$1" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin);
print(int(next((d[k] for k in ("ingest_ok","messages_ok","ok","accepted","total","count") if isinstance(d.get(k),(int,float))), 0)))'
}

pick_edge() {
  local edges_json site edge
  edges_json="$(curl -sf --max-time 20 "${auth_hdr[@]}" "$BASE/api/edges")"
  echo "$edges_json" | tee "$ART/edges.json" >/dev/null
  if [[ -n "${EXPECTED_EDGE_ID:-}" ]]; then
    site="$(echo "$edges_json" | jq -r --arg e "$EXPECTED_EDGE_ID" \
      '(.edges // [])[] | select(.edge_id==$e) | (.site_id // empty)' | head -1)"
    edge="$EXPECTED_EDGE_ID"
  elif [[ -n "${EXPECTED_SITE_ID:-}" ]]; then
    site="$EXPECTED_SITE_ID"
    edge="$(echo "$edges_json" | jq -r --arg s "$EXPECTED_SITE_ID" \
      '(.edges // [])[] | select((.site_id // "")==$s and .has_telemetry==true) | .edge_id' | head -1)"
  else
    site="$(echo "$edges_json" | jq -r \
      '(.edges // [])[] | select(.has_telemetry==true) | .site_id // empty' | head -1)"
    edge="$(echo "$edges_json" | jq -r \
      '(.edges // [])[] | select(.has_telemetry==true) | .edge_id' | head -1)"
  fi
  site="${site:-${OPENFDD_SITE_ID:-lab}}"
  edge="${edge:-${OPENFDD_EDGE_ID:-fieldbus-1}}"
  echo "$site" "$edge"
}

issue_telemetry() {
  local action="$1" site="$2" edge="$3"
  local body resp cmd_id status i
  body="$(jq -nc --arg s "$site" --arg e "$edge" --arg a "$action" \
    '{site_id:$s,edge_id:$e,target_id:"edge:telemetry",approved_by:"stress-gate-35",value:{action:$a},ttl_secs:180}')"
  resp="$(curl -sf --max-time 30 "${auth_hdr[@]}" -X POST "$BASE/api/commands" \
    -H 'Content-Type: application/json' -d "$body")"
  echo "$resp" | tee "$ART/cmd_${action}.json" >/dev/null
  echo "$resp" | jq -e '.ok == true' >/dev/null
  cmd_id="$(echo "$resp" | jq -r '.command.command_id // empty')"
  [[ -n "$cmd_id" ]] || { echo "FAIL: no command_id for $action" | tee -a "$ART/pause_resume.log"; return 1; }
  status="pending"
  for ((i = 0; i < ACK_POLLS; i++)); do
    sleep 1
    local ack
    ack="$(curl -sf --max-time 15 "${auth_hdr[@]}" "$BASE/api/commands/${cmd_id}/ack" || echo '{}')"
    echo "$ack" | tee "$ART/ack_${action}_${i}.json" >/dev/null
    status="$(echo "$ack" | jq -r '.ack.status // "pending"')"
    if [[ "$status" == "executed" ]]; then
      echo "ack $action=executed" | tee -a "$ART/pause_resume.log"
      return 0
    fi
    if [[ "$status" == "failed" || "$status" == "rejected" || "$status" == "expired" ]]; then
      echo "FAIL: ack $action status=$status" | tee -a "$ART/pause_resume.log"
      return 1
    fi
  done
  # MQTT may be slow; fieldbus REST can confirm when reachable.
  if [[ "$fb_reachable" == "1" ]]; then
    echo "WARN: ack still $status after ${ACK_POLLS}s — checking fieldbus REST" | tee -a "$ART/pause_resume.log"
    return 0
  fi
  echo "FAIL: no executed ack for $action (last=$status)" | tee -a "$ART/pause_resume.log"
  return 1
}

read -r SITE_ID EDGE_ID < <(pick_edge)
echo "target site=$SITE_ID edge=$EDGE_ID stall=${STALL_SECS}s resume_wait=${RESUME_WAIT_SECS}s" \
  | tee -a "$ART/pause_resume.log"

before="$(ingest_ok "$ART/ingest_before.json")"
echo "ingest_before=$before" | tee -a "$ART/pause_resume.log"

issue_telemetry suspend "$SITE_ID" "$EDGE_ID"

if [[ "$fb_reachable" == "1" ]]; then
  status="$(fb "$FIELDBUS_BASE/telemetry/status")"
  echo "$status" | tee "$ART/telemetry_suspended_status.json"
  echo "$status" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("suspended") is True, s'
  echo "PASS: fieldbus reports suspended=true" | tee -a "$ART/pause_resume.log"
fi

sleep "$STALL_SECS"
mid="$(ingest_ok "$ART/ingest_mid_suspended.json")"
echo "ingest_mid_suspended=$mid (waited ${STALL_SECS}s)" | tee -a "$ART/pause_resume.log"

# While suspended, ingest must not climb. Flat is required; small race (+0..2) allowed.
delta_suspend=$((mid - before))
if [[ "$delta_suspend" -gt 2 ]]; then
  echo "FAIL: ingest advanced while suspended ($before → $mid, delta=$delta_suspend)" \
    | tee -a "$ART/pause_resume.log"
  # Still resume so we leave the edge healthy.
  issue_telemetry resume "$SITE_ID" "$EDGE_ID" || true
  if [[ "$fb_reachable" == "1" ]]; then
    fb -X POST "$FIELDBUS_BASE/telemetry/resume" -d '{"approved_by":"stress-gate-35-cleanup"}' || true
  fi
  exit 1
fi
echo "PASS: ingest stalled while suspended (delta=$delta_suspend)" | tee -a "$ART/pause_resume.log"

issue_telemetry resume "$SITE_ID" "$EDGE_ID"

if [[ "$fb_reachable" == "1" ]]; then
  status="$(fb "$FIELDBUS_BASE/telemetry/status")"
  echo "$status" | tee "$ART/telemetry_resumed_status.json"
  echo "$status" | python3 -c 'import json,sys; s=json.load(sys.stdin); assert s.get("suspended") is False, s'
  fb -X POST "$FIELDBUS_BASE/bacnet/poll/once" >/dev/null || true
  echo "PASS: fieldbus reports suspended=false + poll/once" | tee -a "$ART/pause_resume.log"
fi

sleep "$RESUME_WAIT_SECS"
after="$(ingest_ok "$ART/ingest_after_resume.json")"
echo "ingest_after_resume=$after" | tee -a "$ART/pause_resume.log"

ok=0
if [[ "$after" -gt "$mid" ]]; then
  echo "PASS: ingest climbed after resume $mid → $after" | tee -a "$ART/pause_resume.log"
  ok=1
elif [[ "$fb_reachable" == "1" ]]; then
  # Poll interval can be 300s; REST confirmed resume is enough with live fieldbus.
  echo "PASS: resume confirmed via fieldbus REST (ingest flat over ${RESUME_WAIT_SECS}s)" \
    | tee -a "$ART/pause_resume.log"
  ok=1
elif [[ "${TELEMETRY_LIVE:-0}" == "1" ]]; then
  echo "PASS: TELEMETRY_LIVE=1 waiver after resume (ingest flat)" | tee -a "$ART/pause_resume.log"
  ok=1
fi

if [[ "$ok" -ne 1 ]]; then
  echo "FAIL: ingest did not climb after resume and no fieldbus/live waiver" \
    | tee -a "$ART/pause_resume.log"
  jq -n --argjson before "$before" --argjson mid "$mid" --argjson after "$after" \
    '{ok:false,gate:"mqtt_telemetry_pause_resume",ingest_before:$before,ingest_mid:$mid,ingest_after:$after}' \
    | tee "$ART/pause_resume_verdict.json"
  exit 1
fi

jq -n --arg site "$SITE_ID" --arg edge "$EDGE_ID" \
  --argjson before "$before" --argjson mid "$mid" --argjson after "$after" \
  --argjson fb "$fb_reachable" \
  '{ok:true,gate:"mqtt_telemetry_pause_resume",site_id:$site,edge_id:$edge,
    ingest_before:$before,ingest_mid_suspended:$mid,ingest_after_resume:$after,
    fieldbus_rest:$fb}' \
  | tee "$ART/pause_resume_verdict.json"
echo "OK gate 35 mqtt telemetry pause/resume"
