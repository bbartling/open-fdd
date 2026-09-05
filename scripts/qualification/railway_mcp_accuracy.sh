#!/usr/bin/env bash
# Railway-tier MCP accuracy — NO local/disposable central fallback.
# Requires explicit HTTPS hub + exact MCP image (sha-* or digest).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/nightly-ot-bench/lib.sh"
load_bench_env

BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
MCP_IMAGE="${OPENFDD_MCP_IMAGE:-}"
ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
MCP_NAME="openfdd-mcp-railway-$$"

cleanup() { docker rm -f "$MCP_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if [[ -z "$BASE" ]]; then
  echo "ERROR: OPENFDD_API_BASE required (Railway HTTPS)" >&2
  exit 1
fi
if [[ "$BASE" != https://* ]]; then
  echo "ERROR: Railway MCP gate requires https:// hub, got: $BASE" >&2
  exit 1
fi
if [[ -z "$MCP_IMAGE" ]]; then
  echo "ERROR: OPENFDD_MCP_IMAGE required (exact sha-* or digest; no silent :nightly)" >&2
  exit 1
fi
# Accept only :sha-<hex> tags or @sha256:<digest> references.
if [[ ! "$MCP_IMAGE" =~ @sha256:[0-9a-fA-F]{64}$ && ! "$MCP_IMAGE" =~ :sha-[0-9a-fA-F]{7,}$ ]]; then
  echo "ERROR: refusing non-immutable MCP image $MCP_IMAGE — pin :sha-<7+> or @sha256:<64>" >&2
  exit 1
fi
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  echo "ERROR: OPENFDD_ADMIN_PASSWORD required" >&2
  exit 1
fi

hdr "Railway MCP accuracy vs $BASE"
echo "MCP_IMAGE=$MCP_IMAGE"

docker pull "$MCP_IMAGE" >/dev/null
MCP_REV="$(docker inspect "$MCP_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true)"
echo "mcp_rev=${MCP_REV:-unknown}" | tee "$ART/mcp_image_meta.txt"

TOK="$(curl -sf --max-time 25 -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg p "$OPENFDD_ADMIN_PASSWORD" '{username:"admin",password:$p}')" \
  | jq -r '.token // empty')"
[[ -n "$TOK" ]] || { echo "ERROR: admin login failed on Railway" >&2; exit 1; }

hcurl() { curl -fsS --max-time 45 -H "Authorization: Bearer $TOK" "$@"; }

HEALTH="$(hcurl "$BASE/api/health")"
echo "$HEALTH" >"$ART/direct_health.json"
jq -e '.ok==true' <<<"$HEALTH" >/dev/null

DIRECT_RULES="$(hcurl "$BASE/api/fdd/rules")"
DIRECT_EQUIP="$(hcurl "$BASE/api/fdd/equipment")"
DIRECT_RESULTS="$(hcurl "$BASE/api/fdd/results")"
printf '%s' "$DIRECT_RULES" >"$ART/direct_rules.json"
printf '%s' "$DIRECT_EQUIP" >"$ART/direct_equip.json"
printf '%s' "$DIRECT_RESULTS" >"$ART/direct_results.json"

MCP_OUT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"openfdd_health","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"openfdd_fdd_registry","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"openfdd_fdd_equipment","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"openfdd_fdd_results","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"openfdd_fdd_accuracy_snapshot","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"openfdd_no_such_tool","arguments":{}}}' \
  | docker run -i --rm --name "$MCP_NAME" --network host \
      -e OPENFDD_API_BASE="$BASE" \
      -e OPENFDD_MCP_TOKEN="$TOK" \
      "$MCP_IMAGE" 2>"$ART/mcp_stderr.log" || true)"

echo "$MCP_OUT" >"$ART/mcp_stdio.jsonl"
python3 - "$ART/mcp_stdio.jsonl" "$ART/mcp_messages.json" <<'PY'
import json,sys,pathlib
lines=[]
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    line=line.strip()
    if not line: continue
    try: lines.append(json.loads(line))
    except Exception: pass
pathlib.Path(sys.argv[2]).write_text(json.dumps(lines,indent=2))
print(len(lines))
PY

[[ -s "$ART/mcp_messages.json" ]] || { echo "ERROR: no MCP JSON-RPC output" >&2; exit 1; }

jq -e '
  (map(select(.id==2))[0].result.tools | map(.name)) as $tools
  | ["openfdd_fdd_registry","openfdd_fdd_equipment","openfdd_fdd_results",
     "openfdd_fdd_series","openfdd_fdd_accuracy_snapshot","openfdd_health"]
  | all(. as $n | $tools | index($n) != null)
' "$ART/mcp_messages.json" >/dev/null

mcp_text() {
  jq -r --argjson id "$1" '
    map(select(.id==$id))[0]
    | if .error then empty else (.result.content[0].text // empty) end
  ' "$ART/mcp_messages.json"
}
mcp_err() {
  jq -c --argjson id "$1" 'map(select(.id==$id))[0].error // empty' "$ART/mcp_messages.json"
}

for id in 4 5 6 7; do
  [[ -z "$(mcp_err "$id")" ]] || { echo "ERROR: MCP id=$id $(mcp_err "$id")" >&2; exit 1; }
done

printf '%s' "$(mcp_text 4)" >"$ART/mcp_rules.json"
printf '%s' "$(mcp_text 5)" >"$ART/mcp_equip.json"
printf '%s' "$(mcp_text 6)" >"$ART/mcp_results.json"

jq -ne --slurpfile d "$ART/direct_rules.json" --slurpfile m "$ART/mcp_rules.json" \
  '($d[0].count==$m[0].count) and (($d[0].rules|map(.rule_id))==($m[0].rules|map(.rule_id)))' | grep -qx true
jq -ne --slurpfile d "$ART/direct_equip.json" --slurpfile m "$ART/mcp_equip.json" \
  '($d[0].count==$m[0].count)' | grep -qx true
jq -ne --slurpfile d "$ART/direct_results.json" --slurpfile m "$ART/mcp_results.json" \
  '$d[0].results==$m[0].results' | grep -qx true

SNAP="$(mcp_text 7)"
jq -e '.ok==true' <<<"$SNAP" >/dev/null

[[ -n "$(mcp_err 8)" ]] || { echo "ERROR: unknown tool did not error" >&2; exit 1; }

ok "Railway MCP == REST parity @ $BASE (mcp_rev=${MCP_REV:0:12})"
summary
exit 0
