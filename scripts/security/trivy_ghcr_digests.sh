#!/usr/bin/env bash
# Scan final GHCR image digests with Trivy (Wave U U6 / UA-05). Not a Nessus substitute.
# Prefer digest refs when RepoDigests are known; tag scans must still record digests.
set -euo pipefail
TAG="${1:?usage: $0 sha-<7> [central|web|mqtt|fieldbus|mcp|caddy|all]}"
SCOPE="${2:-all}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${ARTIFACT_DIR:-$ROOT/reports/trivy}/$TAG"
mkdir -p "$OUT"

images=()
case "$SCOPE" in
  all) images=(central web mqtt fieldbus mcp caddy) ;;
  central|web|mqtt|fieldbus|mcp|caddy) images=("$SCOPE") ;;
  *) echo "unknown scope $SCOPE" >&2; exit 2 ;;
esac

if ! command -v trivy >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
  echo "BLOCKED: trivy (or docker for aquasec/trivy) not available" >&2
  exit 2
fi

trivy_cmd() {
  if command -v trivy >/dev/null 2>&1; then
    trivy "$@"
  else
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$OUT:$OUT" aquasec/trivy:latest "$@"
  fi
}

fail=0
missing=0
for name in "${images[@]}"; do
  if [[ "$name" == "caddy" ]]; then
    ref="docker.io/library/caddy:2.9-alpine"
  else
    ref="ghcr.io/bbartling/openfdd-${name}:${TAG}"
  fi
  echo "==> trivy image $ref"
  if ! trivy_cmd image --exit-code 1 --severity HIGH,CRITICAL \
    --format json --output "$OUT/${name}.json" "$ref"; then
    # Distinguish pull/missing from findings: empty/missing report → missing.
    if [[ ! -s "$OUT/${name}.json" ]]; then
      echo "FAIL: missing/unreadable report for $ref" >&2
      missing=1
    else
      echo "FAIL: $ref has HIGH/CRITICAL (or scanner error — inspect JSON)" >&2
      fail=1
    fi
  else
    echo "PASS: $ref"
  fi
done

# Record tool/DB metadata when available.
{
  echo "tag=$TAG"
  echo "scanned_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  trivy_cmd --version 2>/dev/null || true
} >"$OUT/SCANNER.txt" || true

if [[ "$missing" -ne 0 ]]; then
  exit 2
fi
exit "$fail"
