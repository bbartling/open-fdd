#!/usr/bin/env bash
# Haystack gates against fieldbus /haystack/*.
# The bench has no live Haystack (SkySpark/Niagara) server, so default expectation is:
#   - endpoints return a clean structured error (upstream unreachable), NOT a panic/500 crash
#   - fieldbus stays healthy afterwards
# Set HAYSTACK_EXPECT_LIVE=1 (with gateway.toml [haystack] pointing at a real server)
# to require successful about/read/nav grids instead.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

EXPECT_LIVE="${HAYSTACK_EXPECT_LIVE:-0}"
ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

# curl that captures body + status without -f so we can assert structured errors
hs_call() {
  # hs_call <method> <path> [json-body]
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --max-time 30 -H 'Content-Type: application/json' "${AUTH_HDR[@]}"
    -o "$ART/hs_resp.json" -w '%{http_code}' -X "$method" "$FIELDBUS_BASE$path")
  [[ -n "$body" ]] && args+=(-d "$body")
  curl "${args[@]}" 2>/dev/null || echo "000"
}

check_endpoint() {
  # check_endpoint <label> <method> <path> [body]
  local label="$1" method="$2" path="$3" body="${4:-}"
  local code resp
  code="$(hs_call "$method" "$path" "$body")"
  resp="$(cat "$ART/hs_resp.json" 2>/dev/null || echo '')"
  cp "$ART/hs_resp.json" "$ART/haystack_$(echo "$label" | tr ' /' '__').json" 2>/dev/null || true
  if [[ "$EXPECT_LIVE" == "1" ]]; then
    if [[ "$code" == "200" ]] && jq -e '.ok==true' <<<"$resp" >/dev/null 2>&1; then
      ok "$label → 200 ok grid"
    else
      bad "$label expected live grid, got HTTP $code: $(head -c 200 <<<"$resp")"
    fi
  else
    if [[ "$code" == "200" ]] && jq -e '.ok==true' <<<"$resp" >/dev/null 2>&1; then
      ok "$label unexpectedly live (HTTP 200 grid) — bench has a haystack server?"
    elif [[ "$code" =~ ^(4|5)[0-9][0-9]$ ]] && jq -e 'type=="object"' <<<"$resp" >/dev/null 2>&1; then
      ok "$label → HTTP $code structured JSON error (clean upstream failure)"
      echo "${DIM}  $(head -c 160 <<<"$resp")${RST}"
    elif [[ "$code" == "000" ]]; then
      bad "$label → connection failed/timeout (fieldbus hung or crashed on haystack path)"
    else
      bad "$label → HTTP $code with non-JSON body (panic/route error?): $(head -c 160 <<<"$resp")"
    fi
  fi
}

hdr "Haystack about/read/nav/his-read via fieldbus"
check_endpoint "GET /haystack/about" GET "/haystack/about"
check_endpoint "POST /haystack/read" POST "/haystack/read" '{"filter":"site"}'
check_endpoint "POST /haystack/nav" POST "/haystack/nav" '{"nav_id":null}'
check_endpoint "POST /haystack/his-read" POST "/haystack/his-read" '{"ids":["@demo"],"range_start":null,"range_end":null}'

hdr "Op allowlist: non-allowlisted haystack ops are not exposed as routes"
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${AUTH_HDR[@]}" \
  -X POST "$FIELDBUS_BASE/haystack/eval" -H 'Content-Type: application/json' -d '{}' 2>/dev/null || echo 000)"
if [[ "$code" == "404" || "$code" == "405" ]]; then
  ok "POST /haystack/eval not exposed (HTTP $code)"
else
  bad "POST /haystack/eval → HTTP $code (should be 404/405; eval must not be reachable)"
fi

hdr "Fieldbus healthy after haystack error paths"
if H="$(fb "$FIELDBUS_BASE/health" 2>/dev/null)" && jq -e '.ok==true' <<<"$H" >/dev/null; then
  ok "fieldbus /health ok after haystack calls"
else
  bad "fieldbus unhealthy after haystack calls"
fi

if [[ "$EXPECT_LIVE" != "1" ]]; then
  skip "positive-path haystack (live grids) not exercised — no Haystack server on bench (set HAYSTACK_EXPECT_LIVE=1 when one exists)"
fi

summary
