#!/usr/bin/env bash
# Thin wrapper for standalone HTTPS peer probe (Wave U U3).
# Config lint (CI):  ./scripts/security/probe_standalone_https.sh
# Peer soak:         OPENFDD_HTTPS_PEER_PROBE=1 ./scripts/security/probe_standalone_https.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${ARTIFACT_DIR:-$ROOT/reports/security}/standalone_https_probe.json"
mkdir -p "$(dirname "$OUT")"
args=(--out "$OUT")
if [[ "${OPENFDD_HTTPS_PEER_PROBE:-}" == "1" ]]; then
  args+=(--peer-probe)
fi
exec python3 "$ROOT/scripts/security/peer_probe_https.py" "${args[@]}" "$@"
