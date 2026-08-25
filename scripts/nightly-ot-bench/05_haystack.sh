#!/usr/bin/env bash
# Haystack gates against fieldbus /haystack/* + optional live Niagara SomeRandomPoint.
#
# Default (HAYSTACK_EXPECT_LIVE=0): endpoints must return structured errors / not crash.
# Live (HAYSTACK_EXPECT_LIVE=1): require successful about/read and a changing SomeRandomPoint.
#
# Niagara nHaystack needs HTTP Basic + insecure TLS (see rusty-haystack demo/niagara_sample).
# Fieldbus on rusty-haystack v0.8.1 cannot Basic-auth yet — when live is requested and
# fieldbus returns the Basic-not-supported error, fall back to direct HTTPS probe using
# HAYSTACK_USER / HAYSTACK_PASS (same as demo) so the bench still validates the point.
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

HS_URL="${HAYSTACK_BASE_URL:-https://192.168.204.11/haystack}"
HS_FILTER="${HAYSTACK_POINT_FILTER:-point and dis==\"SomeRandomPoint\"}"
HS_USER="${HAYSTACK_USER:-${OPENFDD_HAYSTACK_USER:-}}"
HS_PASS="${HAYSTACK_PASS:-${OPENFDD_HAYSTACK_PASS:-}}"

hs_call() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --max-time 30 -H 'Content-Type: application/json' "${AUTH_HDR[@]}"
    -o "$ART/hs_resp.json" -w '%{http_code}' -X "$method" "$FIELDBUS_BASE$path")
  [[ -n "$body" ]] && args+=(-d "$body")
  curl "${args[@]}" 2>/dev/null || echo "000"
}

check_endpoint() {
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

extract_cur_val() {
  # Prefer JSON curVal / number fields; Zinc fallback n:NNN
  python3 - <<'PY'
import json, re, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    m = re.search(r"\bn:(-?\d+(?:\.\d+)?)\b", raw)
    print(m.group(1) if m else "")
    raise SystemExit
# fieldbus grid
rows = (((d.get("grid") or {}).get("rows")) if isinstance(d, dict) else None) or []
if not rows and isinstance(d, dict) and "rows" in d:
    rows = d.get("rows") or []
for row in rows:
    if not isinstance(row, dict):
        continue
    for k in ("curVal", "out", "val", "value"):
        if k in row and row[k] is not None:
            s = str(row[k])
            m = re.search(r"-?\d+(?:\.\d+)?", s)
            if m:
                print(m.group(0))
                raise SystemExit
# Zinc body
m = re.search(r"\bn:(-?\d+(?:\.\d+)?)\b", raw)
print(m.group(1) if m else "")
PY
}

live_somerandom_via_fieldbus() {
  local body r1 r2 v1 v2
  body="$(jq -nc --arg f "$HS_FILTER" '{filter:$f}')"
  r1="$(fb -X POST "$FIELDBUS_BASE/haystack/read" -d "$body" 2>/dev/null || true)"
  echo "$r1" >"$ART/haystack_somerandom_1.json"
  v1="$(extract_cur_val <<<"$r1")"
  sleep 3
  r2="$(fb -X POST "$FIELDBUS_BASE/haystack/read" -d "$body" 2>/dev/null || true)"
  echo "$r2" >"$ART/haystack_somerandom_2.json"
  v2="$(extract_cur_val <<<"$r2")"
  echo "${DIM}  fieldbus SomeRandomPoint v1=$v1 v2=$v2${RST}"
  if [[ -n "$v1" && -n "$v2" && "$v1" != "$v2" ]]; then
    ok "SomeRandomPoint changed via fieldbus ($v1 → $v2)"
    return 0
  fi
  return 1
}

live_somerandom_direct() {
  local u="$HS_URL" a1 a2 v1 v2
  [[ -n "$HS_USER" && -n "$HS_PASS" ]] || return 2
  a1="$(curl -fsSk --max-time 20 -u "$HS_USER:$HS_PASS" \
    -H 'Accept: text/zinc' "$u/about" 2>/dev/null || true)"
  echo "$a1" >"$ART/haystack_direct_about.zinc"
  [[ -n "$a1" ]] || return 1
  ok "direct Niagara /about (Basic + insecure TLS)"
  local enc
  enc="$(F="$HS_FILTER" python3 -c 'import urllib.parse,os; print(urllib.parse.quote(os.environ["F"]))')"
  v1="$(curl -fsSk --max-time 20 -u "$HS_USER:$HS_PASS" -H 'Accept: text/zinc' \
    "$u/read?filter=$enc" 2>/dev/null | tee "$ART/haystack_direct_read_1.zinc" | extract_cur_val)"
  sleep 3
  v2="$(curl -fsSk --max-time 20 -u "$HS_USER:$HS_PASS" -H 'Accept: text/zinc' \
    "$u/read?filter=$enc" 2>/dev/null | tee "$ART/haystack_direct_read_2.zinc" | extract_cur_val)"
  echo "${DIM}  direct SomeRandomPoint v1=$v1 v2=$v2${RST}"
  if [[ -n "$v1" && -n "$v2" && "$v1" != "$v2" ]]; then
    ok "SomeRandomPoint changed via direct Niagara HTTPS ($v1 → $v2)"
    return 0
  fi
  return 1
}

if [[ "$EXPECT_LIVE" == "1" ]]; then
  hdr "Live SomeRandomPoint (Niagara Random → In10)"
  if live_somerandom_via_fieldbus; then
    :
  else
    skip "fieldbus live read did not show changing SomeRandomPoint (Basic auth gap on rusty-haystack 0.8.1?)"
    rc=0
    live_somerandom_direct || rc=$?
    if [[ "$rc" -eq 2 ]]; then
      bad "HAYSTACK_EXPECT_LIVE=1 but HAYSTACK_USER/PASS unset — cannot probe Niagara directly"
    elif [[ "$rc" -ne 0 ]]; then
      bad "SomeRandomPoint did not change on direct probe (is Random wired on 192.168.204.11?)"
    fi
  fi
else
  skip "positive-path haystack (live grids) not exercised — set HAYSTACK_EXPECT_LIVE=1 + creds when Niagara is up"
fi

summary
