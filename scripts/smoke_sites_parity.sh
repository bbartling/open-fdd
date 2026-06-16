#!/usr/bin/env bash
# Thin wrapper — see smoke_paired_fdd_harness.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="standard"
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --short|--standard|--overnight|--tryout) MODE="${1#--}"; shift ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done
export OPENFDD_LIVE_ACME=1
exec "${ROOT}/scripts/smoke_paired_fdd_harness.sh" "--${MODE}" "${EXTRA[@]}"
