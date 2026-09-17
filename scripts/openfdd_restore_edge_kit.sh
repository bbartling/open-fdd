#!/usr/bin/env bash
# Restore a signed MQTT edge kit under deploy/mqtt/kits/{site}__{edge}/ via hub API.
# Usage:
#   OPENFDD_API_BASE=https://… OPENFDD_ADMIN_TOKEN=… \
#     ./scripts/openfdd_restore_edge_kit.sh [site_id] [edge_id]
#
# Same ZIP as Operations → Download edge kit (public PEMs + edge.json only).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_ID="${1:-${OPENFDD_SITE_ID:-ACME}}"
EDGE_ID="${2:-${OPENFDD_EDGE_ID:-pi-1}}"
TENANT_ID="${OPENFDD_TENANT_ID:-acme}"
BUILDING_ID="${OPENFDD_BUILDING_ID:-${SITE_ID}}"
BASE="${OPENFDD_API_BASE:-}"
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$ROOT/.env" && set +a
  BASE="${OPENFDD_API_BASE:-$BASE}"
  # Re-apply CLI / Railway defaults after .env (local lab ids must not win).
  SITE_ID="${1:-${OPENFDD_SITE_ID:-ACME}}"
  EDGE_ID="${2:-${OPENFDD_EDGE_ID:-pi-1}}"
  TENANT_ID="${OPENFDD_TENANT_ID:-acme}"
  BUILDING_ID="${OPENFDD_BUILDING_ID:-${SITE_ID}}"
fi

[[ -n "$BASE" ]] || { echo "ERROR: set OPENFDD_API_BASE" >&2; exit 2; }

TOKEN="${OPENFDD_ADMIN_TOKEN:-}"
if [[ -z "$TOKEN" && -n "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  TOKEN="$(curl -sf --max-time 30 -X POST "${BASE%/}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"${OPENFDD_ADMIN_PASSWORD}\"}" \
    | jq -r '.token // .access_token // empty')"
fi
[[ -n "$TOKEN" ]] || { echo "ERROR: set OPENFDD_ADMIN_TOKEN or OPENFDD_ADMIN_PASSWORD for login" >&2; exit 2; }

KIT_DIR="$ROOT/deploy/mqtt/kits/${SITE_ID}__${EDGE_ID}"
TMP_ZIP="$(mktemp "${TMPDIR:-/tmp}/openfdd-edge-kit.XXXXXX.zip")"
trap 'rm -f "$TMP_ZIP"' EXIT

echo "== POST /api/mqtt/edge-kits site=$SITE_ID edge=$EDGE_ID tenant=$TENANT_ID building=$BUILDING_ID =="
HTTP="$(curl -sS -w '%{http_code}' -o "$TMP_ZIP" \
  -X POST "${BASE%/}/api/mqtt/edge-kits" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"site_id\":\"${SITE_ID}\",\"edge_id\":\"${EDGE_ID}\",\"tenant_id\":\"${TENANT_ID}\",\"building_id\":\"${BUILDING_ID}\"}")"
if [[ "$HTTP" != "200" ]]; then
  echo "ERROR: edge-kits HTTP $HTTP (CA key may be absent on hub — reuse backup kit)" >&2
  exit 2
fi
if ! unzip -t "$TMP_ZIP" >/dev/null 2>&1; then
  echo "ERROR: response is not a ZIP (check token / hub mqtt CA)" >&2
  exit 2
fi

mkdir -p "$KIT_DIR"
unzip -o -q "$TMP_ZIP" -d "$KIT_DIR"
chmod 600 "$KIT_DIR"/edge.key.pem 2>/dev/null || true

for f in ca.pem edge.cert.pem edge.key.pem edge.json; do
  [[ -f "$KIT_DIR/$f" ]] || { echo "ERROR: kit missing $f after unzip" >&2; exit 2; }
done

echo "OK restored edge kit at $KIT_DIR"
echo "Next: OPENFDD_EDGE_KIT_DIR=$KIT_DIR ./scripts/openfdd_fieldbus_railway_up.sh sha-<7>"
