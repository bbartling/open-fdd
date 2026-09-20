#!/usr/bin/env bash
# Scan final GHCR image digests with Trivy (Wave U U6). Not a Nessus substitute.
set -euo pipefail
TAG="${1:?usage: $0 sha-<7> [central|web|mqtt|fieldbus|mcp|all]}"
SCOPE="${2:-all}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${ARTIFACT_DIR:-$ROOT/reports/trivy}/$TAG"
mkdir -p "$OUT"

images=()
case "$SCOPE" in
  all) images=(central web mqtt fieldbus mcp) ;;
  central|web|mqtt|fieldbus|mcp) images=("$SCOPE") ;;
  *) echo "unknown scope $SCOPE" >&2; exit 2 ;;
esac

if ! command -v trivy >/dev/null 2>&1; then
  echo "BLOCKED: trivy not installed" >&2
  exit 2
fi

fail=0
for name in "${images[@]}"; do
  ref="ghcr.io/bbartling/openfdd-${name}:${TAG}"
  echo "==> trivy image $ref"
  if ! trivy image --exit-code 1 --severity HIGH,CRITICAL \
    --format json --output "$OUT/${name}.json" "$ref"; then
    echo "FAIL: $ref has HIGH/CRITICAL" >&2
    fail=1
  else
    echo "PASS: $ref"
  fi
done
exit "$fail"
