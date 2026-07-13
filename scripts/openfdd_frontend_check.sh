#!/usr/bin/env bash
# Frontend / SPA check — login page, shell routes, static assets, no blank 500s.
#
#   ./scripts/openfdd_frontend_check.sh
#   ./scripts/openfdd_frontend_check.sh --base-url http://127.0.0.1:8080
#
# Artifacts: workspace/logs/frontend_check_<timestamp>/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASE="${OPENFDD_API_BASE:-${OPENFDD_BRIDGE_BASE:-http://127.0.0.1:8080}}"
CURL_TLS=()
PASS=0
FAIL=0
WARN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,9p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ "$BASE" == https://* ]]; then CURL_TLS=(-k); fi

ARTIFACT="$ROOT/workspace/logs/frontend_check_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ARTIFACT"

ok() { echo "  OK  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL $1" >&2; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN $1" >&2; WARN=$((WARN + 1)); }

echo "==> Frontend check at $BASE"
echo "    artifacts: $ARTIFACT"

# Reachability
code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' "$BASE/api/health" || echo 000)"
if [[ "$code" != "200" ]]; then
  fail "edge not healthy (HTTP $code) — start with ./scripts/openfdd_cargo_up.sh or openfdd_local_up.sh"
  echo "PASS=$PASS FAIL=$FAIL WARN=$WARN" | tee "$ARTIFACT/summary.txt"
  exit 1
fi
ok "edge reachable"

check_html() {
  local route="$1"
  local must_root="${2:-0}"
  local out="$ARTIFACT/route$(echo "$route" | tr '/' '_' | sed 's/^_//').html"
  [[ -z "${out##*route.html}" ]] && out="$ARTIFACT/route_index.html"
  local code
  code="$(curl "${CURL_TLS[@]}" -sS -o "$out" -w '%{http_code}' "${BASE}${route}")" || code=000
  if [[ "$code" == "500" ]]; then
    fail "SPA $route → HTTP 500"
    return
  fi
  if [[ "$code" -ge 400 ]]; then
    fail "SPA $route → HTTP $code"
    return
  fi
  if [[ "$must_root" == "1" ]]; then
    if ! grep -q 'id="root"' "$out"; then
      fail "SPA $route missing id=\"root\" (wrong or empty shell)"
      return
    fi
    if ! grep -qE '/assets/index-[A-Za-z0-9_-]+\.js' "$out"; then
      fail "SPA $route missing /assets/index-*.js — rebuild: (cd workspace/dashboard && npm run build)"
      return
    fi
  fi
  ok "SPA $route ($code)"
}

check_html "/" 1
check_html "/login" 1

# Client-side routes: edge should still serve the SPA shell (not 404 HTML from missing file)
for route in \
  /csv-workbench \
  /model \
  /sql-fdd \
  /plot \
  /reports \
  /bacnet \
  /modbus \
  /haystack \
  /json-api \
  /data-management \
  /exports \
  /host \
  /live-fdd-validation \
  /agent; do
  check_html "$route" 1
done

# Asset file from index must download (not 404)
js_path="$(grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' "$ARTIFACT/route_index.html" | head -1 || true)"
css_path="$(grep -oE '/assets/index-[A-Za-z0-9_-]+\.css' "$ARTIFACT/route_index.html" | head -1 || true)"
if [[ -n "$js_path" ]]; then
  code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/bundle.js" -w '%{http_code}' "${BASE}${js_path}")" || code=000
  if [[ "$code" == "200" && -s "$ARTIFACT/bundle.js" ]]; then
    ok "JS asset $js_path ($(wc -c <"$ARTIFACT/bundle.js") bytes)"
  else
    fail "JS asset $js_path → HTTP $code"
  fi
else
  fail "could not parse JS asset path from index.html"
fi
if [[ -n "$css_path" ]]; then
  code="$(curl "${CURL_TLS[@]}" -sS -o "$ARTIFACT/bundle.css" -w '%{http_code}' "${BASE}${css_path}")" || code=000
  if [[ "$code" == "200" && -s "$ARTIFACT/bundle.css" ]]; then
    ok "CSS asset $css_path"
  else
    fail "CSS asset $css_path → HTTP $code"
  fi
else
  warn "no CSS asset path in index.html"
fi

# Favicon (soft)
code="$(curl "${CURL_TLS[@]}" -sS -o /dev/null -w '%{http_code}' "$BASE/favicon.svg")" || code=000
if [[ "$code" == "200" ]]; then
  ok "favicon.svg"
else
  warn "favicon.svg → HTTP $code"
fi

# Optional: dashboard unit tests when node_modules present
if [[ "${OPENFDD_SKIP_VITEST:-0}" == "1" ]]; then
  warn "skip vitest (OPENFDD_SKIP_VITEST=1)"
elif [[ -d "$ROOT/workspace/dashboard/node_modules" ]]; then
  echo "==> vitest (dashboard unit tests)"
  if (cd "$ROOT/workspace/dashboard" && npm test -- --run >"$ARTIFACT/vitest.log" 2>&1); then
    ok "npm test (vitest)"
  else
    fail "npm test failed — see $ARTIFACT/vitest.log"
    tail -n 30 "$ARTIFACT/vitest.log" >&2 || true
  fi
else
  warn "skip vitest (no workspace/dashboard/node_modules)"
fi

jq -nc \
  --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg base "$BASE" \
  --arg dir "$ARTIFACT" \
  --argjson pass "$PASS" \
  --argjson fail "$FAIL" \
  --argjson warn "$WARN" \
  '{finished_at:$finished,base:$base,artifact_dir:$dir,pass:$pass,fail:$fail,warn:$warn}' \
  >"$ARTIFACT/final_report.json"

echo
echo "Frontend check: pass=$PASS fail=$FAIL warn=$WARN"
echo "Report: $ARTIFACT/final_report.json"
if [[ "$FAIL" -ne 0 ]]; then
  echo "Frontend check FAILED" >&2
  exit 1
fi
echo "Frontend check PASS"
