#!/usr/bin/env bash
# Start paired FDD smoke fully detached from the IDE terminal (systemd user unit preferred).
#
# Cursor/agents: NEVER wait on this process. Poll status only:
#   ./scripts/smoke_paired_fdd_status.sh --mode short
#
# Examples:
#   ./scripts/run_paired_fdd_smoke_isolated.sh --short --bench-only
#   ./scripts/run_paired_fdd_smoke_isolated.sh --short   # bench + Acme, skips UI parity
#   ./scripts/run_paired_fdd_smoke_isolated.sh --overnight --bench-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="short"
BENCH_ONLY=0
SKIP_PARITY=1
EXTRA=()

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tryout|--short|--standard|--overnight)
      MODE="${1#--}"
      shift
      ;;
    --bench-only) BENCH_ONLY=1; shift ;;
    --with-parity) SKIP_PARITY=0; shift ;;
    --with-acme) BENCH_ONLY=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

LOG="/tmp/paired_fdd_smoke_${MODE}_$(date -u +%Y%m%d_%H%M%S).log"
PIDFILE="/tmp/paired_fdd_smoke_${MODE}.pid"
STATUS="/tmp/paired_fdd_smoke_${MODE}.status.json"
UNIT="openfdd-paired-fdd-smoke-${MODE}"

HARNESS_ARGS=("--${MODE}")
[[ "$BENCH_ONLY" == "1" ]] && HARNESS_ARGS+=(--bench-only)
[[ "$SKIP_PARITY" == "1" ]] && HARNESS_ARGS+=(--skip-parity)
HARNESS_ARGS+=("${EXTRA[@]}")

chmod +x "${ROOT}/scripts/smoke_paired_fdd_worker.sh"

_run_setsid() {
  setsid "${ROOT}/scripts/smoke_paired_fdd_worker.sh" "${HARNESS_ARGS[@]}" >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
}

_run_systemd() {
  # Transient user service — survives IDE disconnect; not a child of the agent shell.
  systemd-run --user \
    --unit="$UNIT" \
    --description="Open-FDD paired FDD smoke (${MODE})" \
    --working-directory="$ROOT" \
    --property=KillMode=control-group \
    --property=CollectMode=inactive \
    --setenv=OPENFDD_REPO_ROOT="$ROOT" \
    --setenv=PYTHONPATH="$ROOT:$ROOT/workspace/api" \
    --setenv=OPENFDD_LIVE_ACME="${OPENFDD_LIVE_ACME:-1}" \
    --property=StandardOutput=append:"$LOG" \
    --property=StandardError=append:"$LOG" \
    "${ROOT}/scripts/smoke_paired_fdd_worker.sh" "${HARNESS_ARGS[@]}" >/dev/null
  # Best-effort pid for status helpers (main python process)
  sleep 1
  pgrep -f "smoke_paired_fdd_harness.py --${MODE}" | head -1 >"$PIDFILE" || true
}

if command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user reset-failed "$UNIT" 2>/dev/null || true
  _run_systemd
  LAUNCHER="systemd-run --user (unit=${UNIT})"
else
  _run_setsid
  LAUNCHER="setsid+nohup"
fi

cat <<EOF
==> Isolated paired FDD smoke launched (${LAUNCHER})
    mode:        ${MODE}
    bench_only:  ${BENCH_ONLY}
    skip_parity: ${SKIP_PARITY}
    log:         ${LOG}
    status:      ${STATUS}
    pid file:    ${PIDFILE}
    poll:        ./scripts/smoke_paired_fdd_status.sh --mode ${MODE}
    DO NOT tail -f or wait from Cursor — read status JSON only.
EOF
