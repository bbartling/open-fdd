#!/usr/bin/env bash
# Authenticated AI path: login → import package → create job → E+ dump → download.
# User-facing name: E+ dump (legacy API route still /wattlab/dumps until central rename).
#
# Usage:
#   ./scripts/agent_eplus_dump.sh /path/to/package.zip [out_dir]
set -euo pipefail

ZIP="${1:?package zip path required}"
OUT="${2:-/tmp/openfdd_eplus_dump}"
API="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
CREDS="${OPENFDD_CREDS:-$PWD/workspace/bootstrap_credentials.once.txt}"

mkdir -p "$OUT"

USER=$(awk -F': ' '/^admin:/{print $1; exit}' "$CREDS" 2>/dev/null || echo admin)
PASS=$(awk -F': ' '/^admin:/{print $2; exit}' "$CREDS" 2>/dev/null || true)
if [[ -z "${PASS:-}" ]]; then
  echo "Missing password in $CREDS" >&2
  exit 1
fi

TOKEN=$(curl -fsS -X POST "$API/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
if [[ ${#TOKEN} -lt 20 ]]; then
  echo "Login failed (token len=${#TOKEN})" >&2
  exit 1
fi
AUTH="Authorization: Bearer $TOKEN"

echo "== import package =="
IMPORT=$(curl -fsS -X POST "$API/api/csv/import/package" \
  -H "$AUTH" \
  -F "file=@${ZIP};type=application/zip")
echo "$IMPORT" | python3 -m json.tool | head -40
BID=$(echo "$IMPORT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("building_id",""))')
echo "building_id=$BID"

echo "== create job =="
JOB=$(curl -fsS -X POST "$API/api/jobs" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"job_name\":\"agent-eplus-dump-$BID\",\"tags\":[\"agent\",\"eplus-dump\"]}")
JID=$(echo "$JOB" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("job",d).get("job_id",""))')
echo "job_id=$JID"

echo "== build E+ dump (API: /wattlab/dumps) =="
DUMP=$(curl -fsS -X POST "$API/api/jobs/${JID}/wattlab/dumps" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"building_id\":\"$BID\",\"profile\":\"summary\"}")
echo "$DUMP" | python3 -m json.tool
DID=$(echo "$DUMP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["dump"]["dump_id"])')
FNAME=$(echo "$DUMP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["dump"]["filename"])')

echo "== download =="
curl -fsS -H "$AUTH" \
  "$API/api/jobs/${JID}/wattlab/dumps/${DID}/download" \
  -o "$OUT/$FNAME"
ls -lh "$OUT/$FNAME"

echo "== clustering export (pandas-ready) =="
python3 "$(dirname "$0")/eplus_dump_clustering_export.py" \
  --dump-zip "$OUT/$FNAME" \
  --building-id "$BID" \
  --max-long-rows 500000

python3 - <<PY
import zipfile
z=zipfile.ZipFile("$OUT/$FNAME")
names=z.namelist()
print("zip_entries", len(names))
for n in sorted(names)[:30]:
    print(" ", n)
assert any("MANIFEST" in n.upper() or n.endswith(".json") for n in names), "expected MANIFEST/json in dump"
print("ARTIFACT_OK", "$OUT/$FNAME")
PY
