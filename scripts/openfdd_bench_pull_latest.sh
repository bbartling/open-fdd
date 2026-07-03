#!/usr/bin/env bash
# Pull latest Open-FDD GHCR images (edge + MCP). Tries profile tags then fallbacks.
#
#   cd /home/ben/open-fdd && ./scripts/openfdd_bench_pull_latest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_bench_lib.sh
source "$ROOT/scripts/openfdd_bench_lib.sh"
openfdd_bench_load_profile "$ROOT" || true

EDGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}"
MCP="${OPENFDD_MCP_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-mcp}"
LOG="$ROOT/workspace/logs/ghcr_pull_latest.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

if command -v gh >/dev/null 2>&1; then
  gh auth token 2>/dev/null | docker login ghcr.io -u "${GITHUB_USER:-bbartling}" --password-stdin >>"$LOG" 2>&1 \
    || log "WARN: ghcr docker login failed (try: gh auth refresh -h github.com -s read:packages)"
fi

try_pull() {
  local img="$1" tag="$2"
  log "docker pull ${img}:${tag}"
  if docker pull "${img}:${tag}" >>"$LOG" 2>&1; then
    log "OK ${img}:${tag}"
    return 0
  fi
  log "FAIL ${img}:${tag}"
  return 1
}

use_cached() {
  local img="$1" tag="$2"
  if docker image inspect "${img}:${tag}" >/dev/null 2>&1; then
    log "CACHE using local ${img}:${tag} (GHCR pull failed)"
    return 0
  fi
  return 1
}

EDGE_OK=0
MCP_OK=0

EDGE_TAGS=("nightly" "beta" "${OPENFDD_IMAGE_TAG:-}" "latest" "3.3.0-beta.1" "v3.3.0-beta.1" "3.2.9" "sha-0965e16")
MCP_TAGS=("nightly" "beta" "${OPENFDD_MCP_GHCR_TAG:-}" "latest" "3.3.0-beta.1" "v3.3.0-beta.1" "3.2.9")

for t in "${EDGE_TAGS[@]}"; do
  [[ -z "$t" ]] && continue
  if try_pull "$EDGE" "$t"; then
    export OPENFDD_IMAGE_TAG="$t"
    EDGE_OK=1
    EDGE_SOURCE="ghcr"
    break
  fi
done
if [[ "$EDGE_OK" -eq 0 ]]; then
  for t in "3.2.3" "sha-7165b49"; do
    if use_cached "$EDGE" "$t"; then
      export OPENFDD_IMAGE_TAG="$t"
      EDGE_OK=1
      EDGE_SOURCE="cache"
      break
    fi
  done
fi

for t in "${MCP_TAGS[@]}"; do
  [[ -z "$t" ]] && continue
  if try_pull "$MCP" "$t"; then
    export OPENFDD_MCP_GHCR_TAG="$t"
    MCP_OK=1
    MCP_SOURCE="ghcr"
    break
  fi
done
if [[ "$MCP_OK" -eq 0 ]]; then
  for t in "3.2.3" "v3.2.4"; do
    if use_cached "$MCP" "$t"; then
      export OPENFDD_MCP_GHCR_TAG="$t"
      MCP_OK=1
      MCP_SOURCE="cache"
      break
    fi
  done
fi

EDGE_SOURCE="${EDGE_SOURCE:-none}"
MCP_SOURCE="${MCP_SOURCE:-none}"

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson edge_ok "$EDGE_OK" --argjson mcp_ok "$MCP_OK" \
  --arg edge_tag "${OPENFDD_IMAGE_TAG:-}" --arg mcp_tag "${OPENFDD_MCP_GHCR_TAG:-}" \
  --arg edge_source "${EDGE_SOURCE:-none}" --arg mcp_source "${MCP_SOURCE:-none}" \
  '{timestamp_utc:$ts,edge_ok:$edge_ok,mcp_ok:$mcp_ok,edge_tag:$edge_tag,mcp_tag:$mcp_tag,
    edge_source:$edge_source,mcp_source:$mcp_source,ghcr_latest_pulled:($edge_source=="ghcr")}' \
  >"$ROOT/workspace/logs/ghcr_pull_latest.json"

log "edge_ok=$EDGE_OK ($EDGE_SOURCE) mcp_ok=$MCP_OK ($MCP_SOURCE) edge_tag=${OPENFDD_IMAGE_TAG:-none} mcp_tag=${OPENFDD_MCP_GHCR_TAG:-none}"

ENV_FILE="$ROOT/workspace/logs/ghcr_pull_latest.env"
{
  echo "OPENFDD_IMAGE_TAG=${OPENFDD_IMAGE_TAG:-nightly}"
  echo "OPENFDD_GHCR_TAG=${OPENFDD_IMAGE_TAG:-nightly}"
  echo "OPENFDD_MCP_GHCR_TAG=${OPENFDD_MCP_GHCR_TAG:-nightly}"
  echo "OPENFDD_GHCR_EDGE_SOURCE=${EDGE_SOURCE:-none}"
  echo "OPENFDD_GHCR_MCP_SOURCE=${MCP_SOURCE:-none}"
} >"$ENV_FILE"

[[ "$EDGE_OK" -eq 1 ]]
