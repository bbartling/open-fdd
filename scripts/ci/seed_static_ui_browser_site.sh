#!/usr/bin/env bash
# Seed one generic CSV building on the disposable CI browser central (starter seed off).
# Prints building_id on stdout; diagnostics on stderr.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CENTRAL="${OPENFDD_STATIC_UI_CENTRAL_BASE:-http://127.0.0.1:8080}"
ADMIN_USER="${OPENFDD_ADMIN_USER:-admin}"
ADMIN_PASS="${OPENFDD_ADMIN_PASSWORD:?OPENFDD_ADMIN_PASSWORD required}"

ZIP="$(mktemp --suffix=.zip)"
trap 'rm -f "$ZIP"' EXIT

BUILDING_ID="$(
  python3 "$ROOT/scripts/ci/static_ui_browser_package.py" --out "$ZIP"
)"

TOKEN="$(
  curl -fsS -X POST "$CENTRAL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")'
)"
if [[ ${#TOKEN} -lt 20 ]]; then
  echo "FAIL: static UI browser seed login failed" >&2
  exit 1
fi

IMPORT_JSON="$(
  curl -fsS -X POST "$CENTRAL/api/csv/import/package" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@${ZIP};filename=openfdd_package.zip;type=application/zip"
)"
if ! python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)' <<<"$IMPORT_JSON"; then
  echo "FAIL: package import for static UI browser seed" >&2
  python3 -m json.tool <<<"$IMPORT_JSON" >&2 || true
  exit 1
fi

echo "static UI browser seed: building_id=$BUILDING_ID" >&2
echo "$BUILDING_ID"
