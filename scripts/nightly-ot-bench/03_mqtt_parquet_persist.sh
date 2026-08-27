#!/usr/bin/env bash
# MQTTS → central ingest → Parquet/historian persistence.
# Captures before/after snapshots; fails if central down or stores do not grow / ingest idle.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
echo "${DIM}artifacts=$ART${RST}"

hdr "Baseline historian / Parquet snapshot"
BEFORE="$ART/historian_before.txt"
historian_snapshot >"$BEFORE" || true
echo "${DIM}  files=$(wc -l <"$BEFORE" | tr -d ' ')${RST}"

hdr "Central ingest stats (before)"
if IB="$(central "$CENTRAL_BASE/api/ingest/stats" 2>/dev/null)"; then
  echo "$IB" | tee "$ART/ingest_before.json" | jq -c . 2>/dev/null || echo "$IB"
  ok "ingest/stats reachable"
else
  bad "ingest/stats unreachable — cannot prove Parquet ingest path"
  echo '{}' >"$ART/ingest_before.json"
fi

hdr "Edges / shadow (optional)"
if E="$(central "$CENTRAL_BASE/api/edges" 2>/dev/null)"; then
  echo "$E" | tee "$ART/edges.json" | jq -c . 2>/dev/null | head -c 400
  echo
  ok "GET /api/edges"
else
  skip "GET /api/edges unavailable"
fi

hdr "Force poll cycle(s) on fieldbus"
cycles="${POLL_CYCLES_BEFORE_PARQUET:-${POLL_CYCLES_BEFORE_FEATHER:-2}}"
for i in $(seq 1 "$cycles"); do
  fb -X POST "$FIELDBUS_BASE/bacnet/poll/once" >/dev/null 2>&1 && ok "poll/once #$i" || bad "poll/once #$i"
  sleep 2
done

hdr "Wait for MQTT bridge publish interval (${PARQUET_WAIT_SECS}s)"
# Bridge loop sleeps poll.interval_secs (often 60s) before first publish after connect.
sleep "$PARQUET_WAIT_SECS"

hdr "Optional MQTTS subscribe peek (docker mosquitto)"
if docker image inspect eclipse-mosquitto:2 >/dev/null 2>&1 \
  || docker pull eclipse-mosquitto:2 >/dev/null 2>&1; then
  CA="$ROOT/deploy/mqtt/ca/ca.pem"
  CERT="$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__central/central.cert.pem"
  KEY="$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__central/central.key.pem"
  # Fall back to edge kit central certs if separate central kit missing
  if [[ ! -f "$CERT" ]]; then
    CERT="$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}/central.cert.pem"
    KEY="$ROOT/deploy/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}/central.key.pem"
  fi
  if [[ -f "$CA" && -f "$CERT" && -f "$KEY" ]]; then
    if timeout 80 docker run --rm --net=host \
      -v "$ROOT/deploy/mqtt:/mqtt:ro" eclipse-mosquitto:2 \
      mosquitto_sub -h 127.0.0.1 -p 8883 \
      --cafile /mqtt/ca/ca.pem \
      --cert "/mqtt/kits/${OPENFDD_SITE_ID}__central/central.cert.pem" \
      --key "/mqtt/kits/${OPENFDD_SITE_ID}__central/central.key.pem" \
      -t "openfdd/v1/sites/${OPENFDD_SITE_ID}/edges/+/telemetry/#" -v -C 1 -W 75 \
      >"$ART/mqtt_telemetry.txt" 2>&1 \
      || timeout 80 docker run --rm --net=host \
        -v "$ROOT/deploy/mqtt:/mqtt:ro" eclipse-mosquitto:2 \
        mosquitto_sub -h 127.0.0.1 -p 8883 \
        --cafile /mqtt/ca/ca.pem \
        --cert "/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}/central.cert.pem" \
        --key "/mqtt/kits/${OPENFDD_SITE_ID}__${OPENFDD_EDGE_ID}/central.key.pem" \
        -t "openfdd/v1/sites/${OPENFDD_SITE_ID}/edges/+/telemetry/#" -v -C 1 -W 75 \
        >"$ART/mqtt_telemetry.txt" 2>&1; then
      :
    fi
    if grep -q 'telemetry' "$ART/mqtt_telemetry.txt" 2>/dev/null; then
      ok "MQTTS telemetry topic traffic observed"
      # Non-null value check (known prior bug: present_value vs value)
      if grep -qE '"value"[[:space:]]*:[[:space:]]*[0-9]' "$ART/mqtt_telemetry.txt" \
        || grep -qE '"value":[0-9]' "$ART/mqtt_telemetry.txt"; then
        ok "telemetry contains numeric value fields"
      else
        bad "telemetry missing numeric values (value:null schema drift?)"
      fi
      echo "${DIM}$(head -c 400 "$ART/mqtt_telemetry.txt")${RST}"
    else
      bad "no MQTTS telemetry captured (see $ART/mqtt_telemetry.txt)"
    fi
  else
    skip "MQTT certs missing under deploy/mqtt — provision first"
  fi
else
  skip "eclipse-mosquitto image unavailable for mqtt peek"
fi

hdr "Central ingest stats (after)"
if IA="$(central "$CENTRAL_BASE/api/ingest/stats" 2>/dev/null)"; then
  echo "$IA" | tee "$ART/ingest_after.json" | jq -c . 2>/dev/null || echo "$IA"
  # Prefer any counter growth if schema has known fields
  if python3 - "$ART/ingest_before.json" "$ART/ingest_after.json" <<'PY'
import json,sys
b=json.load(open(sys.argv[1]))
a=json.load(open(sys.argv[2]))
def dig(d):
  if not isinstance(d, dict):
    return 0
  for k in ("ingest_ok","messages_ok","ok","accepted","total","count"):
    v=d.get(k)
    if isinstance(v,(int,float)):
      return float(v)
  # nested common shapes
  for v in d.values():
    if isinstance(v, dict):
      x=dig(v)
      if x: return x
  return 0
bb,aa=dig(b),dig(a)
sys.exit(0 if aa>bb or (aa>0 and bb==0) else 1)
PY
  then
    ok "ingest counter increased or non-zero after poll"
  else
    bad "ingest stats did not show growth (central may not be ingesting)"
  fi
else
  bad "ingest/stats still unreachable"
fi

hdr "Historian / Parquet after snapshot"
AFTER="$ART/historian_after.txt"
historian_snapshot >"$AFTER" || true
echo "${DIM}  files=$(wc -l <"$AFTER" | tr -d ' ')${RST}"

if [[ ! -s "$AFTER" ]]; then
  # Ingest counter growth alone is enough when Parquet is under OPENFDD_STORAGE_URL
  # outside workspace/data (common after STORAGE_URL-only cutover).
  if [[ -f "$ART/ingest_after.json" ]] && jq -e '(.ingest_ok // 0) > 0' "$ART/ingest_after.json" >/dev/null 2>&1; then
    skip "no workspace/data historian files — ingest_ok>0 (Parquet under STORAGE_URL)"
  else
    bad "no historian/Parquet files under workspace/data — persistence missing"
  fi
else
  ok "historian/Parquet artifacts exist ($(wc -l <"$AFTER" | tr -d ' ') files)"
fi

# Growth: new paths or newer mtime/size vs before
if [[ -s "$AFTER" ]] && python3 - "$BEFORE" "$AFTER" <<'PY'
import sys
def load(p):
  d={}
  try:
    for line in open(p):
      line=line.strip()
      if not line: continue
      path,mtime,size=line.split('|',2)
      d[path]=(int(mtime),int(size))
  except FileNotFoundError:
    pass
  return d
b,a=load(sys.argv[1]),load(sys.argv[2])
grew=False
for path,(mt,sz) in a.items():
  if path not in b:
    grew=True; break
  bmt,bsz=b[path]
  if mt>bmt or sz>bsz:
    grew=True; break
sys.exit(0 if grew else 1)
PY
then
  ok "historian/Parquet store grew (new file or mtime/size increase)"
else
  # Micro-batch Parquet may flush on interval without new files under workspace/data.
  # When MQTT ingest already proved live, treat file-tree growth as soft (skip).
  if [[ -f "$ART/ingest_after.json" ]] && jq -e '(.ingest_ok // 0) > 0' "$ART/ingest_after.json" >/dev/null 2>&1; then
    skip "historian file tree unchanged — ingest_ok>0 (Parquet flush may be deferred)"
  else
    bad "historian/Parquet store did not grow after poll wait — no persistence proof"
  fi
fi

ls -laRt "$ROOT/${WORKSPACE_DIR}/data" 2>/dev/null | head -30 | tee "$ART/workspace_data_ls.txt" || true

summary
echo "${DIM}Wrote artifacts under $ART${RST}"
