#!/usr/bin/env bash
# Hub-admin historian compaction against the Railway ACME/OT hub.
# Prefer after continuous AFDD cycles or when small-file fan-out returns.
# Never prints secrets. Requires Railway CLI linked to gleaming-cooperation/production.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
HUB="${OPENFDD_HUB_BASE:-https://openfdd-web-production-af99.up.railway.app}"
CENTRAL_SVC="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
PLAN_ONLY="${PLAN_ONLY:-0}"
WAIT="${WAIT:-1}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
env -u RAILWAY_TOKEN railway variable list --service "$CENTRAL_SVC" --json >"$tmp"
export OPENFDD_ADMIN_PASSWORD
OPENFDD_ADMIN_PASSWORD="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("OPENFDD_ADMIN_PASSWORD",""))' "$tmp")"
[[ -n "$OPENFDD_ADMIN_PASSWORD" ]] || {
  echo "ERROR: OPENFDD_ADMIN_PASSWORD missing from Railway vars" >&2
  exit 2
}

TOKEN="$(curl -sS -X POST "$HUB/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,os; print(json.dumps({"username":"admin","password":os.environ["OPENFDD_ADMIN_PASSWORD"]}))')" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")')"
[[ -n "$TOKEN" ]] || {
  echo "ERROR: hub admin login failed" >&2
  exit 2
}

plan_only_json=false
[[ "$PLAN_ONLY" == "1" ]] && plan_only_json=true
wait_json=true
[[ "$WAIT" == "0" ]] && wait_json=false

body="$(python3 -c "import json; print(json.dumps({'confirm':True,'wait':$wait_json,'plan_only':$plan_only_json}))")"
echo "POST /api/historian/compaction confirm=true wait=$wait_json plan_only=$plan_only_json"
curl -sS -X POST "$HUB/api/historian/compaction" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$body" \
  --max-time "${COMPACT_MAX_SECS:-1800}" \
  | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("ok=", d.get("ok"), "keys=", sorted(d.keys()))
plans=d.get("plans")
if plans is not None:
  n=sum(len(p.get("input_paths") or []) for p in plans)
  print(f"plan_only plans={len(plans)} files={n}")
results=d.get("results")
if results is not None:
  n=sum(int(r.get("input_files") or 0) for r in results)
  print(f"apply partitions={len(results)} input_files={n}")
summary=d.get("summary")
if summary:
  print("summary=", summary)
sys.exit(0 if d.get("ok") is not False else 1)
'
