#!/usr/bin/env bash
# Final rigorous phase: 10m pcap + 1/min soak (stores/FDD/drivers) + minute pcap analysis + ZAP.
#
# Run at END of openfdd_323_test or standalone after stack is up:
#   ./scripts/openfdd_soak_pcap_zap_finalize.sh
#
# Env:
#   OPENFDD_SOAK_MINUTES=10          (default)
#   OPENFDD_PCAP_DURATION_SEC=600    (match soak)
#   OPENFDD_RUN_ZAP=1                (default)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOAK_MIN="${OPENFDD_SOAK_MINUTES:-10}"
PCAP_SEC="${OPENFDD_PCAP_DURATION_SEC:-$((SOAK_MIN * 60))}"
RUN_ZAP="${OPENFDD_RUN_ZAP:-1}"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${OPENFDD_FINALIZE_DIR:-$ROOT/workspace/logs/finalize_${SOAK_MIN}m_${RUN_TS}}"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/finalize.log") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

cat >"$LOG_DIR/README.md" <<EOF
# Open-FDD finalize — soak + pcap + ZAP

- Soak: ${SOAK_MIN} minutes @ 60s (historian/Arrow/FDD/driver polls)
- PCAP: ${PCAP_SEC}s multi-protocol capture
- Minute-bucket pcap validation
- OWASP ZAP baseline on dashboard/API

No git clone — docker pull/test only.
EOF

FAIL=0
phase_ok() { log "OK: $*"; }
phase_fail() { log "FAIL: $*"; FAIL=1; }

# Bench-wide filter (BACnet, Modbus 1502, bridge, commission, Haystack HTTPS)
export OPENFDD_PCAP_DURATION_SEC="$PCAP_SEC"
export OPENFDD_PCAP_DIR="$LOG_DIR/pcap"
export OPENFDD_PCAP_FILTER="${OPENFDD_PCAP_FILTER:-(udp port 47808 or tcp port 1502 or tcp port 8080 or tcp port 9091 or tcp port 443 or tcp port 502) and not port 22 and not port 53}"

log "=== Phase A: start ${PCAP_SEC}s pcap (background) ==="
"$ROOT/scripts/openfdd_ot_pcap_capture.sh" | tee "$LOG_DIR/pcap_start.log"
PCAP_DIR="$(cat "$ROOT/workspace/logs/pcap_latest.dir")"
echo "$PCAP_DIR" >"$LOG_DIR/pcap_dir.txt"

log "=== Phase B: ${SOAK_MIN}m soak (stores + FDD + drivers each minute) ==="
export OPENFDD_SOAK_MINUTES="$SOAK_MIN"
export OPENFDD_SOAK_DIR="$LOG_DIR/soak"
if "$ROOT/scripts/openfdd_stores_fdd_soak.sh" | tee "$LOG_DIR/soak.log"; then
  phase_ok "soak stores/FDD"
else
  phase_fail "soak stores/FDD"
fi

log "=== Phase C: wait for pcap container ==="
PCAP_CONTAINER="$(cat "$PCAP_DIR/container.name" 2>/dev/null || echo ofdd-pcap-capture)"
while docker ps -q -f "name=^${PCAP_CONTAINER}$" 2>/dev/null | grep -q .; do
  sleep 5
done
sleep 2
[[ -f "$PCAP_DIR/openfdd_ot.pcap" ]] || phase_fail "pcap file missing"

log "=== Phase D: pcap summary + minute buckets ==="
"$ROOT/scripts/openfdd_ot_pcap_analyze.sh" "$PCAP_DIR" | tee "$LOG_DIR/pcap_analysis.log" || phase_fail "pcap analyze"
export OPENFDD_PCAP_MIN_BACNET="${OPENFDD_PCAP_MIN_BACNET:-1}"
export OPENFDD_PCAP_MIN_MODBUS="${OPENFDD_PCAP_MIN_MODBUS:-1}"
export OPENFDD_PCAP_MIN_HTTP8080="${OPENFDD_PCAP_MIN_HTTP8080:-3}"
if "$ROOT/scripts/openfdd_pcap_minute_validate.sh" "$PCAP_DIR" | tee "$LOG_DIR/pcap_minute.log"; then
  phase_ok "pcap minute buckets"
else
  phase_fail "pcap minute buckets"
fi

if [[ "$RUN_ZAP" == "1" ]]; then
  log "=== Phase E: OWASP ZAP — direct + Caddy HTTP + Caddy TLS matrix ==="
  export OPENFDD_ZAP_MATRIX_DIR="$LOG_DIR/zap_matrix"
  if [[ "${OPENFDD_ZAP_CADDY_MATRIX:-1}" == "1" ]]; then
    if "$ROOT/scripts/openfdd_zap_caddy_matrix.sh" | tee "$LOG_DIR/zap_matrix.log"; then
      phase_ok "ZAP caddy matrix (direct/http/tls)"
    else
      phase_fail "ZAP caddy matrix"
    fi
  else
    export OPENFDD_ZAP_OUT_DIR="$LOG_DIR/zap"
    export OPENFDD_ZAP_TARGET="${OPENFDD_ZAP_TARGET:-http://127.0.0.1:8080}"
    if "$ROOT/scripts/openfdd_zap_scan.sh" | tee "$LOG_DIR/zap.log"; then
      phase_ok "ZAP scan (single target)"
    else
      phase_fail "ZAP scan"
    fi
  fi
else
  log "SKIP ZAP (OPENFDD_RUN_ZAP=0)"
fi

jq -nc \
  --arg ts "$RUN_TS" --arg dir "$LOG_DIR" --arg pcap "$PCAP_DIR" \
  --argjson fail "$FAIL" \
  --slurpfile soak "$LOG_DIR/soak/soak_result.json" \
  --slurpfile pcapm "$PCAP_DIR/minute_validate.json" \
  --slurpfile zapm "$LOG_DIR/zap_matrix/zap_matrix_result.json" \
  --slurpfile zap "$LOG_DIR/zap/zap_result.json" \
  '{
    run_ts:$ts, artifact_dir:$dir, pcap_dir:$pcap,
    soak: ($soak[0] // {}),
    pcap_minute: ($pcapm[0] // {}),
    zap_matrix: ($zapm[0] // {}),
    zap: ($zap[0] // {}),
    passed: ($fail == 0)
  }' >"$LOG_DIR/finalize_result.json" 2>/dev/null || \
  jq -nc --arg dir "$LOG_DIR" --argjson fail "$FAIL" '{artifact_dir:$dir,passed:($fail==0)}' >"$LOG_DIR/finalize_result.json"

log "=== FINALIZE DONE fail=$FAIL artifact=$LOG_DIR ==="
[[ "$FAIL" -eq 0 ]]
