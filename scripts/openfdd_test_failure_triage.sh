#!/usr/bin/env bash
# Triage patch-cycle FAIL — test harness vs product bug (expert reviewer).
# Usage: ./scripts/openfdd_test_failure_triage.sh [patch_dir]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH="${1:-$(cat "$ROOT/workspace/logs/patch_latest.dir" 2>/dev/null || echo "")}"
OUT="${PATCH}/TRIAGE.md"

[[ -n "$PATCH" && -d "$PATCH" ]] || {
  echo "Usage: $0 <patch_dir>" >&2
  exit 1
}

log() { echo "$*" >>"$OUT"; }

: >"$OUT"
log "# Patch cycle failure triage"
log ""
log "Patch: \`$PATCH\`"
log "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log ""

# Classify common false positives / test rewrites
check_file() {
  local f="$1" label="$2"
  [[ -f "$f" ]] || return 0
  if grep -q '^FAIL' "$f" 2>/dev/null; then
    log "## $label"
    grep '^FAIL' "$f" | head -15 >>"$OUT"
    log ""
  fi
}

check_file "$PATCH/validation/docker_health/summary.txt" "Docker health"
check_file "$PATCH/validation/drivers/summary.txt" "Drivers"
check_file "$PATCH/validation/hour_test/failures.txt" "Hour test (1m drivers)"
check_file "$PATCH/wonky.txt" "Wonky (may be expected)"

log "## Rewrite vs product — heuristics"
log ""
log "| Symptom | Likely | Action |"
log "|---------|--------|--------|"
log "| MCP sidecar FAIL, edge PASS | Test waited for wrong image location | Fixed in mcp_eval — sidecar pull |"
log "| haystack-gateway unhealthy + haystack test PASS | Healthcheck bug #401 | Wonky not FAIL |"
log "| fault rule PATCH 404 | API route not shipped yet | Adjust hour test or skip until PR lands |"
log "| RDF/SPARQL 404 | #406 not merged | SKIP expected — not product driver fail |"
log "| ZAP caddy-tls FAIL, caddy-http PASS | trustAll / cert SAN | Check zap_config.conf |"
log "| Who-Is OK, driver tree empty | Discovery test too strict | Review disc-bacnet thresholds |"
log "| hour test FAIL minute 1 | Stack not updated to new tag | Re-run after site_update |"
log ""

if [[ -f "$PATCH/validation/hour_test/result.json" ]]; then
  log "## Hour test JSON"
  log '```json'
  cat "$PATCH/validation/hour_test/result.json" >>"$OUT"
  log '```'
fi

echo "$OUT"
cat "$OUT"
