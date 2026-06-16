#!/usr/bin/env bash
# Hardcoded paired FDD smoke — bensserver bench 5007 + Acme OAT/web (same schedule).
#
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --short      # 30m, toggle @15m
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --standard   # 2h, toggle every 15m
#   OPENFDD_LIVE_ACME=1 ./scripts/smoke_paired_fdd_harness.sh --overnight  # 12h, toggle every 15m
#
# Step 1: site_parity_smoke.py (UI + API revision match)
# Step 2: smoke_paired_fdd_harness.py (hardcoded FDD phase toggles + PyArrow/SQL parity)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="standard"
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tryout) MODE="tryout"; shift ;;
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
