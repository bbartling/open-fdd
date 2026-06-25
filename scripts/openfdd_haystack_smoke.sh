#!/usr/bin/env bash
# Manual Haystack API smoke against a live Open-FDD edge + optional live nHaystack station.
# Does NOT run in CI by default. Requires local env vars — never prints credentials.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"

BASE="${OPENFDD_BASE_URL:-http://127.0.0.1:8080}"
AUTH_FILE="${OPENFDD_AUTH_PATH:-$ROOT/workspace/auth.env.local}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/workspace/logs/haystack_smoke_${TS}"
mkdir -p "$OUT"

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: set $name before running Haystack smoke" >&2
    exit 1
  fi
}

require_env OPENFDD_HAYSTACK_BASE
require_env OPENFDD_HAYSTACK_USER
require_env OPENFDD_HAYSTACK_PASS

export OPENFDD_HAYSTACK_ENABLED=1

echo "==> Haystack smoke → $OUT"
echo "    base=$BASE haystack=$OPENFDD_HAYSTACK_BASE"

TOKEN="$(openfdd_rust_login_smoke "$BASE" "$AUTH_FILE")"
AUTH=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

curl_json() {
  local method="$1" path="$2" body="${3:-{}}"
  curl -fsS -X "$method" "${AUTH[@]}" -d "$body" "$BASE$path" | tee "$OUT/$(echo "$path" | tr '/:' '__').json"
}

curl_json GET /api/haystack/status
curl_json POST /api/haystack/test
curl_json GET /api/haystack/about
curl_json GET /api/haystack/ops
curl_json POST /api/haystack/nav
curl_json POST /api/haystack/read '{"filter":"point","limit":20}'

if [[ -n "${OPENFDD_HAYSTACK_READ_IDS_FILE:-}" && -f "$OPENFDD_HAYSTACK_READ_IDS_FILE" ]]; then
  ids="$(python3 - <<'PY'
import json, os
path = os.environ["OPENFDD_HAYSTACK_READ_IDS_FILE"]
ids = [line.strip() for line in open(path) if line.strip() and not line.startswith("#")]
print(json.dumps({"ids": ids}))
PY
)"
  curl_json POST /api/haystack/read "$ids"
fi

if [[ "${OPENFDD_HAYSTACK_SMOKE_IMPORT:-0}" == "1" ]]; then
  curl_json POST /api/haystack/import '{"filter":"site or equip or point","limit":500}'
fi

curl_json GET /api/haystack/driver/tree
curl_json GET /api/model/haystack

echo "==> PASS — artifacts in $OUT"

# Future parity hook (not executed here):
# OPENFDD_SMOKE_HAYSTACK_PARITY=1
# OPENFDD_HAYSTACK_PARITY_PROFILE=workspace/smoke-profiles/local/local_haystack_5007_parity.local.toml
