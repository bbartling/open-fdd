#!/usr/bin/env bash
# Wave O2 — headers / security.txt / CORS / login rate-limit (no Kali ActiveScan).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/_common.sh" 2>/dev/null || true

ART="${ARTIFACT_DIR:-$ROOT/reports/wave_o_security_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
[[ -n "$BASE" ]] || { echo "set OPENFDD_API_BASE or RAILWAY_BASE" >&2; exit 1; }
BASE="${BASE%/}"

: >"$ART/sec.log"
fail=0

# --- Security headers on SPA root ---
hdrs="$(curl -sI "$BASE/" | tee "$ART/root_headers.txt")"
for needle in "x-content-type-options: nosniff" "referrer-policy:" "x-frame-options:" "content-security-policy:"; do
  if ! echo "$hdrs" | grep -qi "$needle"; then
    echo "FAIL: missing header $needle on /" | tee -a "$ART/sec.log"
    fail=1
  else
    echo "PASS: header $needle" | tee -a "$ART/sec.log"
  fi
done

# --- security.txt must be plain text, not SPA HTML ---
sec_code="$(curl -s -o "$ART/security.txt" -w '%{http_code}' "$BASE/.well-known/security.txt")"
sec_ct="$(curl -sI "$BASE/.well-known/security.txt" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-type"{print tolower($2); exit}')"
if [[ "$sec_code" != "200" ]]; then
  echo "FAIL: security.txt expected 200, got $sec_code" | tee -a "$ART/sec.log"
  fail=1
elif echo "$sec_ct" | grep -qi 'text/html'; then
  echo "FAIL: security.txt Content-Type is HTML ($sec_ct)" | tee -a "$ART/sec.log"
  fail=1
elif ! grep -qi 'Contact:' "$ART/security.txt"; then
  echo "FAIL: security.txt missing Contact:" | tee -a "$ART/sec.log"
  fail=1
else
  echo "PASS: security.txt plain ($sec_ct)" | tee -a "$ART/sec.log"
fi

# --- CORS: disallowed Origin must not be reflected ---
cors="$(curl -sI -H 'Origin: https://evil.example' -H 'Access-Control-Request-Method: GET' \
  -X OPTIONS "$BASE/api/health" | tee "$ART/cors_options.txt" || true)"
if echo "$cors" | grep -qi 'access-control-allow-origin:[[:space:]]*https://evil.example'; then
  echo "FAIL: CORS reflected evil Origin" | tee -a "$ART/sec.log"
  fail=1
else
  echo "PASS: CORS does not reflect evil Origin" | tee -a "$ART/sec.log"
fi

# --- Login rate limit: burst wrong passwords → eventually 429 ---
got_429=0
for i in $(seq 1 12); do
  code="$(curl -s -o "$ART/login_burst_${i}.json" -w '%{http_code}' \
    -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"definitely-wrong-wave-o2"}')"
  if [[ "$code" == "429" ]]; then
    got_429=1
    break
  fi
done
if [[ "$got_429" != "1" ]]; then
  echo "WARN: login burst did not hit 429 in 12 tries (threshold may be higher); not FAIL" | tee -a "$ART/sec.log"
else
  echo "PASS: login rate-limit returned 429" | tee -a "$ART/sec.log"
fi

jq -n --argjson fail "$fail" '{ok: ($fail==0), gate:"wave_o_security", artifact:"'"$ART"'"}' \
  | tee "$ART/sec_verdict.json"
exit "$fail"
