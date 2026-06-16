#!/usr/bin/env bash
# Thin wrapper — see smoke_paired_fdd_harness.sh
# short / standard / overnight default to --detached (bench 5007 + Acme in-depth runs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="standard"
EXTRA=()
ATTACHED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --short|--standard|--overnight|--tryout) MODE="${1#--}"; shift ;;
    --detached) EXTRA+=("--detached"); shift ;;
    --attached) ATTACHED=1; shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done
if [[ "$MODE" != "tryout" && "$ATTACHED" != "1" ]]; then
  EXTRA+=("--detached")
fi
export OPENFDD_LIVE_ACME=1
exec "${ROOT}/scripts/smoke_paired_fdd_harness.sh" "--${MODE}" "${EXTRA[@]}"
