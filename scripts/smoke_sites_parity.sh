#!/usr/bin/env bash
# Paired smoke: bensserver + Acme parity, then ACME validation cycles.
#
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_sites_parity.sh --short      # 30 min window, 1 cycle
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_sites_parity.sh --standard   # 2h window, 1 cycle (default)
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_sites_parity.sh --overnight  # 4×2h cycles, 120 min apart
#
# Steps:
#   1. site_parity_smoke.py (UI bundle + API revision match)
#   2. acme_overnight_fdd_validate.py (read-only ACME cycles)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LIMIT="${OPENFDD_ANSIBLE_LIMIT:-acme_vm_bbartling}"
LOCAL_BASE="${OPENFDD_LOCAL_BASE:-http://127.0.0.1:8765}"
MODE="standard"
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --local) LOCAL_BASE="$2"; shift 2 ;;
    --short) MODE="short"; shift ;;
    --standard) MODE="standard"; shift ;;
    --overnight) MODE="overnight"; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

PYTHON="${ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"

case "$MODE" in
  short)
    CYCLES=1
    WINDOW=0.5
    SLEEP=0
    ;;
  standard)
    CYCLES=1
    WINDOW=2
    SLEEP=0
    ;;
  overnight)
    CYCLES=4
    WINDOW=2
    SLEEP=120
    ;;
esac

export OPENFDD_LIVE_ACME=1

echo "==> 1/2 Cross-site parity (bensserver vs ${LIMIT})"
"$PYTHON" scripts/site_parity_smoke.py \
  --local "$LOCAL_BASE" \
  --remote-limit "$LIMIT" \
  --json-out "${ROOT}/reports/site_parity_smoke.json"

echo ""
echo "==> 2/2 ACME validation (${CYCLES} cycle(s), ${WINDOW}h window)"
"$PYTHON" scripts/acme_overnight_fdd_validate.py \
  --limit "$LIMIT" \
  --cycles "$CYCLES" \
  --window-hours "$WINDOW" \
  --sleep-minutes "$SLEEP" \
  "${EXTRA[@]}"

echo ""
echo "OK — reports: reports/acme_overnight_fdd_validation.md"
