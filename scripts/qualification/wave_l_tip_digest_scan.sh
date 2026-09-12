#!/usr/bin/env bash
# Wave L L6 — tip digest scan (same sha-<7> for central/web/mqtt/fieldbus).
# Thin wrapper around check_ghcr_tip_stack.sh + optional python-absence.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
cd "$ROOT"

TAG="${1:-${OPENFDD_IMAGE_TAG:-}}"
if [[ -z "$TAG" ]]; then
  if git rev-parse --verify origin/master >/dev/null 2>&1; then
    TAG="sha-$(git rev-parse --short=7 origin/master)"
  else
    TAG="sha-$(git rev-parse --short=7 HEAD)"
  fi
fi

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_l_tip_digest_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
LOG="$ART/tip_digest_scan.log"

set +e
"$ROOT/scripts/check_ghcr_tip_stack.sh" "$TAG" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
set -e
if [[ "$rc" -ne 0 ]]; then
  echo "FAIL: tip digest completeness $TAG" >&2
  exit "$rc"
fi

if [[ "${SKIP_PYTHON_ABSENCE:-0}" != "1" ]]; then
  set +e
  "$ROOT/scripts/check_ghcr_tip_python_absence.sh" "$TAG" 2>&1 | tee -a "$LOG"
  rc2=${PIPESTATUS[0]}
  set -e
  if [[ "$rc2" -ne 0 ]]; then
    echo "FAIL: tip python-absence $TAG" >&2
    exit "$rc2"
  fi
fi

echo "{\"ok\":true,\"tag\":\"$TAG\",\"gate\":\"wave_l_tip_digest_scan\"}" \
  | tee "$ART/tip_digest_scan.json"
echo "PASS tip digest scan $TAG"
exit 0
