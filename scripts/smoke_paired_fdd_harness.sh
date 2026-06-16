#!/usr/bin/env bash
# Hardcoded paired FDD smoke — bensserver bench 5007 + Acme OAT/web (same schedule).
#
# Always run in-depth modes (short / standard / overnight) DETACHED so IDE/SSH drops
# do not kill the harness. Use --detached or nohup (see docs/operations/paired-fdd-smoke.md).
#
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --tryout
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --short --detached
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --standard --detached
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight --detached
#
# Step 1: site_parity_smoke.py (UI + API revision match)
# Step 2: smoke_paired_fdd_harness.py (hardcoded FDD phase toggles + PyArrow/SQL parity)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="standard"
EXTRA=()
DETACHED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tryout) MODE="tryout"; shift ;;
    --short) MODE="short"; shift ;;
    --standard) MODE="standard"; shift ;;
    --overnight) MODE="overnight"; shift ;;
    --detached) DETACHED=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

if [[ "$DETACHED" == "1" ]]; then
  LOG="/tmp/paired_fdd_smoke_${MODE}_$(date -u +%Y%m%d_%H%M%S).log"
  PIDFILE="/tmp/paired_fdd_smoke_${MODE}.pid"
  CHILD=()
  for arg in "${EXTRA[@]}"; do
    [[ "$arg" != "--detached" ]] && CHILD+=("$arg")
  done
  echo "==> Detached paired FDD smoke (mode=${MODE})"
  echo "    log: ${LOG}"
  nohup "$0" "--${MODE}" "${CHILD[@]}" >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "    pid: $(cat "$PIDFILE") (also in ${PIDFILE})"
  echo "    tail -f ${LOG}"
  exit 0
fi

PYTHON="${ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

export OPENFDD_LIVE_ACME=1

FLAG="--standard"
case "$MODE" in
  tryout) FLAG="--tryout" ;;
  short) FLAG="--short" ;;
  overnight) FLAG="--overnight" ;;
esac

echo "==> Paired FDD smoke (mode=${MODE}) — parity + hardcoded bench/acme FDD toggles"
"$PYTHON" scripts/smoke_paired_fdd_harness.py "$FLAG" "${EXTRA[@]}"

echo ""
echo "OK — reports: reports/paired_fdd_smoke_validation.md"
