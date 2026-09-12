#!/usr/bin/env bash
# Re-pin Railway hub (central → mqtt → web) to OPENFDD_IMAGE_TAG / sha-*.
# Used by scripts/openfdd_railway_release.sh when OPENFDD_RELEASE_EXECUTE=1.
# Never prints tokens or full variable dumps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TAG="${OPENFDD_IMAGE_TAG:-}"
[[ -n "$TAG" ]] || { echo "ERROR: set OPENFDD_IMAGE_TAG=sha-<7>" >&2; exit 2; }
CENTRAL_SVC="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
WEB_SVC="${OPENFDD_RAILWAY_WEB_SVC:-openfdd-web}"
MQTT_SVC="${OPENFDD_RAILWAY_MQTT_SVC:-openfdd-mqtt}"
HUB_BASE="${OPENFDD_API_BASE:-https://openfdd-web-production-af99.up.railway.app}"
SHORT_SHA="${TAG#sha-}"

command -v railway >/dev/null || { echo "railway CLI required" >&2; exit 2; }
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }
railway whoami >/dev/null

echo "=== re-pin central $CENTRAL_SVC -> ghcr.io/bbartling/openfdd-central:${TAG} ==="
railway service source connect --service "$CENTRAL_SVC" \
  --image "ghcr.io/bbartling/openfdd-central:${TAG}"

echo "=== wait central private health ==="
DEADLINE=$((SECONDS + 360))
while (( SECONDS < DEADLINE )); do
  h="$(railway ssh -s "$CENTRAL_SVC" -- sh -lc 'curl -sf http://127.0.0.1:8080/api/health' 2>/dev/null || true)"
  if echo "$h" | jq -e --arg s "$SHORT_SHA" '.ok == true and ((.version // "") | contains($s))' >/dev/null 2>&1; then
    echo "CENTRAL_OK $(echo "$h" | jq -c '{ok,version,multi_tenant}')"
    break
  fi
  sleep 10
done
echo "$h" | jq -e --arg s "$SHORT_SHA" '.ok == true and ((.version // "") | contains($s))' >/dev/null 2>&1 \
  || { echo "ERROR: central health did not reach ${TAG}" >&2; exit 1; }

# Historian packages under STORAGE_URL need parquet root on volume.
railway variable set OPENFDD_PARQUET_ROOT=/workspace/openfdd --service "$CENTRAL_SVC" >/dev/null
# Prefer explicit results dir on volume (Wave M durable).
railway variable set OPENFDD_RULE_RESULTS_DIR=/workspace/openfdd/rule_results --service "$CENTRAL_SVC" >/dev/null || true

echo "=== re-pin mqtt $MQTT_SVC ==="
railway service source connect --service "$MQTT_SVC" \
  --image "ghcr.io/bbartling/openfdd-mqtt:${TAG}"

echo "=== re-pin web $WEB_SVC ==="
railway variable set OPENFDD_NGINX_RESOLVER=auto --service "$WEB_SVC" >/dev/null
railway service source connect --service "$WEB_SVC" \
  --image "ghcr.io/bbartling/openfdd-web:${TAG}"

echo "=== wait public hub health ==="
DEADLINE=$((SECONDS + 240))
while (( SECONDS < DEADLINE )); do
  h="$(curl -sf --max-time 20 "$HUB_BASE/api/health" || true)"
  if echo "$h" | jq -e --arg s "$SHORT_SHA" '.ok == true and ((.version // "") | contains($s))' >/dev/null 2>&1; then
    echo "WEB_OK $(echo "$h" | jq -c '{ok,version,multi_tenant,edges,ingest_ok}')"
    exit 0
  fi
  sleep 10
done
echo "ERROR: public /api/health did not reach ${TAG}" >&2
exit 1
