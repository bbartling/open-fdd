#!/usr/bin/env bash
# Persistent OT polling for bench — simulates production bootstrap (always on).
#
# Start (default: unlimited cycles — leave running):
#   ./scripts/openfdd_bacnet_poll_daemon.sh start
#
# Bounded window for a single test phase only:
#   OPENFDD_BACNET_DAEMON_MAX_CYCLES=5 ./scripts/openfdd_bacnet_poll_daemon.sh run-for 5
#
# Stop immediately:
#   ./scripts/openfdd_bacnet_poll_daemon.sh stop
#
# Status:
#   ./scripts/openfdd_bacnet_poll_daemon.sh status
#
# One-shot foreground run (no background pid):
#   ./scripts/openfdd_bacnet_poll_daemon.sh run-for 5
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/openfdd_auth_lib.sh
source "$ROOT/scripts/openfdd_auth_lib.sh"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"

openfdd_bench_load_profile "$ROOT" || true

BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
COMMISSION="${OPENFDD_COMMISSION_BASE:-http://127.0.0.1:9091}"
AUTH="${OPENFDD_AUTH_ENV:-$ROOT/workspace/auth.env.local}"
INTERVAL="${OPENFDD_DRIVER_POLL_INTERVAL_SEC:-60}"
MAX_CYCLES="${OPENFDD_BACNET_DAEMON_MAX_CYCLES:-0}"
OUT="${OPENFDD_BACNET_DAEMON_DIR:-$ROOT/workspace/logs/bacnet_poll_daemon}"
PID_FILE="$OUT/daemon.pid"
LOG_FILE="$OUT/daemon.log"

CURL_TLS=()
[[ "$BASE" == https://* ]] && CURL_TLS=(-k)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

poll_loop() {
  mkdir -p "$OUT"
  : >"$OUT/cycles.jsonl"
  local limit="${1:-$MAX_CYCLES}"
  log "daemon start interval=${INTERVAL}s max_cycles=${limit:-unlimited} base=$BASE commission=$COMMISSION out=$OUT"

  local n=0
  while true; do
    n=$((n + 1))
    local ts token stack_ok bacnet_whois_ok bacnet_poll_ok modbus_ok fdd_ok
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    stack_ok=false
    bacnet_whois_ok=false
    bacnet_poll_ok=false
    modbus_ok=false
    fdd_ok=false

    token="$(openfdd_auth_login_token "$BASE" "$AUTH" integrator 2>/dev/null || true)"
    if [[ -n "$token" ]]; then
      local hdr=(-H "Authorization: Bearer $token")
      local live modbus_read_ok=false bacnet_read_ok=false modbus_value="" bacnet_value=""
      jq -e '.ok == true' <<< "$(curl "${CURL_TLS[@]}" -fsS "${hdr[@]}" "$BASE/api/health" 2>/dev/null || echo '{}')" \
        >/dev/null 2>&1 && stack_ok=true

      live="$(openfdd_bench_live_ot_poll "$BASE" "$COMMISSION" "$token" "$ROOT")"
      echo "$live" >"$OUT/live_ot_cycle_${n}.json"
      jq -e '.modbus_read_ok == true' <<<"$live" >/dev/null 2>&1 && { modbus_read_ok=true; modbus_ok=true; }
      jq -e '.bacnet_read_ok == true' <<<"$live" >/dev/null 2>&1 && bacnet_read_ok=true
      jq -e '.bacnet_whois_ok == true' <<<"$live" >/dev/null 2>&1 && bacnet_whois_ok=true
      modbus_value="$(jq -r '.modbus_value // empty' <<<"$live")"
      bacnet_value="$(jq -r '.bacnet_value // empty' <<<"$live")"

      jq -e '.ok == true or (.last_poll.ok // false) == true' <<< "$(curl "${CURL_TLS[@]}" -fsS \
        "${hdr[@]}" "$BASE/api/bacnet/poll/status" 2>/dev/null || echo '{}')" \
        >/dev/null 2>&1 && bacnet_poll_ok=true

      jq -e '.ok == true or .status != null or .run_id != null' <<< "$(curl "${CURL_TLS[@]}" -fsS \
        "${hdr[@]}" "$BASE/api/validation-runs/current/status" 2>/dev/null || echo '{}')" \
        >/dev/null 2>&1 && fdd_ok=true
    fi

    jq -nc \
      --arg ts "$ts" --argjson cycle "$n" \
      --argjson stack "$stack_ok" --argjson whois "$bacnet_whois_ok" \
      --argjson bacnet_poll "$bacnet_poll_ok" --argjson modbus_read "$modbus_read_ok" \
      --argjson bacnet_read "$bacnet_read_ok" --argjson fdd "$fdd_ok" \
      --arg modbus_value "$modbus_value" --arg bacnet_value "$bacnet_value" \
      '{timestamp_utc:$ts,cycle:$cycle,stack_ok:$stack,bacnet_whois_ok:$whois,
        bacnet_poll_ok:$bacnet_poll,modbus_read_ok:$modbus_read,bacnet_read_ok:$bacnet_read,
        modbus_poll_ok:$modbus_read,modbus_value:$modbus_value,bacnet_value:$bacnet_value,
        fdd_status_ok:$fdd}' \
      >>"$OUT/cycles.jsonl"

    log "cycle=$n stack=$stack_ok bacnet_read=$bacnet_read_ok(${bacnet_value:-?}) whois=$bacnet_whois_ok modbus_read=$modbus_read_ok(${modbus_value:-?}) fdd=$fdd_ok"
    if [[ -n "${limit:-}" && "$limit" -gt 0 && "$n" -ge "$limit" ]]; then
      log "daemon stop after max_cycles=$limit"
      break
    fi
    sleep "$INTERVAL"
  done
}

cmd="${1:-start}"

case "$cmd" in
  start)
    mkdir -p "$OUT"
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "already running pid=$(cat "$PID_FILE") log=$LOG_FILE"
      exit 0
    fi
    export OPENFDD_BACNET_DAEMON_MAX_CYCLES="${OPENFDD_BACNET_DAEMON_MAX_CYCLES:-0}"
    nohup bash "$0" run >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    echo "started pid=$(cat "$PID_FILE") interval=${INTERVAL}s max_cycles=${OPENFDD_BACNET_DAEMON_MAX_CYCLES} log=$LOG_FILE"
    ;;
  run-for)
    cycles="${2:-${OPENFDD_BACNET_DAEMON_MAX_CYCLES:-5}}"
    poll_loop "$cycles"
    ;;
  run)
    poll_loop "${OPENFDD_BACNET_DAEMON_MAX_CYCLES:-0}"
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "stopped"
    else
      echo "not running"
    fi
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running pid=$(cat "$PID_FILE") log=$LOG_FILE"
      tail -3 "$LOG_FILE" 2>/dev/null || true
    else
      echo "not running"
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|status|run-for [cycles]}" >&2
    exit 2
    ;;
esac
