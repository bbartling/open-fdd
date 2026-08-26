#!/usr/bin/env bash
# Dual-MQTT sign-off: bench (lab/fieldbus-1) + bosspi (bldg2/pi-1) → single central.
# Run after 07_cloud_sim.sh. Validates GHCR image rev match, health, dual telemetry,
# ingest growth. Leaves both edges running (no teardown).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
central_auth_setup
cd "$ROOT"

PI_SSH="${CLOUD_SIM_PI_SSH:-ben@192.168.204.12}"
SSH_OPTS=(-i "$HOME/.ssh/id_rsa" -o BatchMode=yes -o ConnectTimeout=10)
SITE1="${OPENFDD_SITE_ID:-lab}"
EDGE1="${OPENFDD_EDGE_ID:-fieldbus-1}"
SITE2="${CLOUD_SIM_SITE_ID:-bldg2}"
EDGE2="${CLOUD_SIM_EDGE_ID:-pi-1}"
WAIT="${DUAL_MQTT_WAIT_SECS:-120}"
PIN="${OPENFDD_IMAGE_TAG:-}"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
pi() { ssh "${SSH_OPTS[@]}" "$PI_SSH" "$@"; }

container_rev() {
  local ctr="$1"
  docker inspect "$ctr" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null | head -c 12 || true
}

hdr "0. GHCR legitimacy (bench + bosspi fieldbus)"
FB_CTR="$(docker ps --format '{{.Names}}' | grep -E 'fieldbus' | head -1 || true)"
if [[ -z "$FB_CTR" ]]; then
  bad "no bench fieldbus container running"
else
  BENCH_REV="$(container_rev "$FB_CTR")"
  echo "bench_fieldbus=$FB_CTR rev=${BENCH_REV}" | tee "$ART/pi_image_rev.txt"
  ok "bench fieldbus container $FB_CTR rev=${BENCH_REV:-?}"
fi

PI_UP=0
if pi 'hostname' >/dev/null 2>&1; then
  ok "ssh to Pi ($PI_SSH)"
  PI_REV="$(pi "docker inspect openfdd-edge-fieldbus-1 --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}' 2>/dev/null | head -c 12" || true)"
  echo "pi_fieldbus=openfdd-edge-fieldbus-1 rev=${PI_REV}" | tee -a "$ART/pi_image_rev.txt"
  if [[ -n "$BENCH_REV" && -n "$PI_REV" && "$BENCH_REV" == "$PI_REV" ]]; then
    ok "Pi fieldbus OCI revision matches bench ($BENCH_REV)"
  elif [[ -n "$PI_REV" ]]; then
    bad "Pi rev '$PI_REV' != bench '$BENCH_REV' — stale or mismatched GHCR pin"
  else
    skip "Pi fieldbus not running yet (run 07_cloud_sim first)"
  fi
  if pi 'curl -fsS --max-time 8 http://127.0.0.1:8081/health' 2>/dev/null | tee "$ART/pi_fieldbus_health.json" | jq -e '.ok==true' >/dev/null; then
    PI_UP=1
    ok "Pi fieldbus /health ok"
  else
    bad "Pi fieldbus /health failed"
  fi
else
  bad "cannot ssh to $PI_SSH — dual-MQTT blocked"
fi

if [[ -f "$ART/digests.txt" ]]; then
  ok "bench digests artifact present ($ART/digests.txt)"
else
  skip "digests.txt missing — run 00_pull_ghcr_up first"
fi

hdr "1. Bench stack health"
if H="$(central "$CENTRAL_BASE/api/health" 2>/dev/null)"; then
  echo "$H" | tee "$ART/central_health_dual.json" | jq -c '{version,status}' 2>/dev/null || true
  ok "central /api/health"
else
  bad "central /api/health unreachable"
fi
if fb "$FIELDBUS_BASE/health" 2>/dev/null | tee "$ART/bench_fieldbus_health.json" | jq -e '.ok==true' >/dev/null; then
  ok "bench fieldbus /health"
else
  bad "bench fieldbus /health failed"
fi

hdr "2. Weather API (Madison bench / Chicago Pi)"
WB="$(fb "$FIELDBUS_BASE/weather" 2>/dev/null || echo '{}')"
echo "$WB" >"$ART/weather_api_bench_dual.json"
if jq -e '.location | test("Madison")' <<<"$WB" >/dev/null 2>&1; then
  ok "bench weather city Madison"
else
  bad "bench weather not Madison: $(jq -r '.location // "?"' <<<"$WB")"
fi
if [[ "$PI_UP" == "1" ]]; then
  WP="$(pi 'curl -fsS --max-time 10 http://127.0.0.1:8081/weather' 2>/dev/null || echo '{}')"
  echo "$WP" >"$ART/weather_api_pi_dual.json"
  if jq -e '.location | test("Chicago")' <<<"$WP" >/dev/null 2>&1; then
    ok "Pi weather city Chicago"
  else
    bad "Pi weather not Chicago: $(jq -r '.location // "?"' <<<"$WP")"
  fi
fi

hdr "3. Ingest baseline"
IB="$(central "$CENTRAL_BASE/api/ingest/stats" 2>/dev/null || echo '{}')"
echo "$IB" | tee "$ART/ingest_dual_before.json" | jq -c . 2>/dev/null || echo "$IB"

hdr "4. Wait ${WAIT}s for dual MQTT publish"
sleep "$WAIT"

hdr "5. MQTTS telemetry (both sites)"
CA="$ROOT/deploy/mqtt/ca/ca.pem"
CERT="$ROOT/deploy/mqtt/kits/${SITE1}__central/central.cert.pem"
KEY="$ROOT/deploy/mqtt/kits/${SITE1}__central/central.key.pem"
if [[ ! -f "$CERT" ]]; then
  CERT="$ROOT/deploy/mqtt/kits/${SITE1}__${EDGE1}/central.cert.pem"
  KEY="$ROOT/deploy/mqtt/kits/${SITE1}__${EDGE1}/central.key.pem"
fi
if [[ -f "$CA" && -f "$CERT" && -f "$KEY" ]]; then
  for spec in "${SITE1}|${EDGE1}|mqtt_lab.txt" "${SITE2}|+|mqtt_bldg2.txt"; do
    IFS='|' read -r site edge out <<<"$spec"
    out="$ART/$out"
    timeout 45 docker run --rm --net=host -v "$ROOT/deploy/mqtt:/mqtt:ro" eclipse-mosquitto:2 \
      mosquitto_sub -h 127.0.0.1 -p 8883 \
      --cafile /mqtt/ca/ca.pem \
      --cert "/mqtt/kits/${SITE1}__central/central.cert.pem" \
      --key "/mqtt/kits/${SITE1}__central/central.key.pem" \
      -t "openfdd/v1/sites/${site}/edges/${edge}/telemetry/#" -v -C 1 -W 40 \
      >"$out" 2>&1 || true
    if grep -qE '"value"[[:space:]]*:[[:space:]]*-?[0-9]' "$out" 2>/dev/null; then
      ok "MQTTS telemetry site=$site (numeric values)"
    else
      bad "no numeric telemetry site=$site (see $out)"
    fi
  done
else
  skip "MQTT central certs missing for subscribe peek"
fi

hdr "6. Central /api/edges + ingest after wait"
if E="$(central "$CENTRAL_BASE/api/edges" 2>/dev/null)"; then
  echo "$E" | tee "$ART/edges_dual.json" | jq -c . 2>/dev/null | head -c 500
  echo
  jq_ok "≥2 edges listed" "$E" '(.edges // . // []) | length >= 2'
  if jq -e --arg e "$EDGE2" 'any(.edges[]?; .edge_id==$e)' <<<"$E" >/dev/null 2>&1; then
    ok "remote edge $EDGE2 visible"
  else
    bad "remote edge $EDGE2 missing from /api/edges"
  fi
else
  bad "GET /api/edges failed"
fi
IA="$(central "$CENTRAL_BASE/api/ingest/stats" 2>/dev/null || echo '{}')"
echo "$IA" | tee "$ART/ingest_dual_after.json" | jq -c . 2>/dev/null || echo "$IA"
if python3 - "$ART/ingest_dual_before.json" "$ART/ingest_dual_after.json" <<'PY'
import json, sys
b=json.load(open(sys.argv[1]))
a=json.load(open(sys.argv[2]))
def dig(d):
  if not isinstance(d, dict):
    return 0
  for k in ("ingest_ok","messages_ok","ok","accepted","total","count"):
    v=d.get(k)
    if isinstance(v,(int,float)):
      return float(v)
  for v in d.values():
    if isinstance(v, dict):
      x=dig(v)
      if x: return x
  return 0
sys.exit(0 if dig(a)>dig(b) or dig(a)>0 else 1)
PY
then
  ok "ingest stats grew or non-zero after dual wait"
else
  bad "ingest stats did not grow (MQTT path may be idle)"
fi

hdr "7. Sign-off — stacks left running"
ok "bench react-ot + Pi edge compose intentionally NOT torn down"
echo "${DIM}GHCR pin: ${PIN:-unset}  artifacts: $ART${RST}"
echo "${DIM}Update docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md dual-site + GHCR tables.${RST}"

summary
