#!/usr/bin/env bash
# Gate 16 — Playwright real-stack product workflows (P1-M3).
# Requires live SPA on UI_BASE. Fails hard when stack is up but e2e fails.
# Prefers host Playwright; falls back to mcr.microsoft.com/playwright when
# host OS libs (e.g. libatk) are missing (common on minimal CI/lab hosts).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Playwright product workflows (real stack)"

if [[ "${OPENFDD_PLAYWRIGHT_SKIP:-0}" == "1" ]]; then
  skip "OPENFDD_PLAYWRIGHT_SKIP=1"
  summary
  exit 0
fi

spa_code="$(http_code_retry --max-time 10 "$UI_BASE/")"
if [[ "$spa_code" != "200" && "$spa_code" != "301" && "$spa_code" != "302" ]]; then
  bad "SPA unreachable at $UI_BASE (HTTP $spa_code) — gate 16 requires live stack"
  summary
  exit 1
fi
ok "SPA $UI_BASE → HTTP $spa_code"

# Prefer Caddy :80 when live — matches remote LAN bookmarks (still loopback
# secure-context; product.spec also stubs missing randomUUID for the LAN case).
if [[ -z "${OPENFDD_PLAYWRIGHT_BASE_URL:-}" ]]; then
  caddy_code="$(http_code_retry --max-time 5 "http://127.0.0.1/" || true)"
  if [[ "$caddy_code" == "200" || "$caddy_code" == "301" || "$caddy_code" == "302" ]]; then
    export OPENFDD_PLAYWRIGHT_BASE_URL="http://127.0.0.1"
    ok "Playwright base → Caddy $OPENFDD_PLAYWRIGHT_BASE_URL"
  fi
fi
# Optional real LAN IP (non-secure context) when bench publishes one.
if [[ -n "${OPENFDD_LAN_BASE:-}" ]]; then
  lan_code="$(http_code_retry --max-time 5 "$OPENFDD_LAN_BASE/" || true)"
  if [[ "$lan_code" == "200" || "$lan_code" == "301" || "$lan_code" == "302" ]]; then
    export OPENFDD_PLAYWRIGHT_BASE_URL="$OPENFDD_LAN_BASE"
    ok "Playwright base → LAN $OPENFDD_PLAYWRIGHT_BASE_URL (non-secure context)"
  else
    skip "OPENFDD_LAN_BASE=$OPENFDD_LAN_BASE unreachable (HTTP $lan_code) — keeping ${OPENFDD_PLAYWRIGHT_BASE_URL:-$UI_BASE}"
  fi
fi

WEB="$ROOT/frontend/web"
if [[ ! -f "$WEB/package.json" ]]; then
  bad "missing $WEB/package.json"
  summary
  exit 1
fi

export OPENFDD_PLAYWRIGHT_BASE_URL="${OPENFDD_PLAYWRIGHT_BASE_URL:-$UI_BASE}"
export OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi
if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" && -f "$ROOT/workspace/bootstrap_credentials.once.txt" ]]; then
  OPENFDD_ADMIN_PASSWORD="$(
    awk -F': *' '/^admin:/{print $2; exit}' "$ROOT/workspace/bootstrap_credentials.once.txt" | tr -d '\r'
  )"
  export OPENFDD_ADMIN_PASSWORD
fi

# Curl-level Caddy /login redirect when Caddy is the Playwright base.
if [[ "$OPENFDD_PLAYWRIGHT_BASE_URL" == "http://127.0.0.1" || "$OPENFDD_PLAYWRIGHT_BASE_URL" == "http://127.0.0.1/" ]]; then
  if ! OPENFDD_CADDY_BASE=http://127.0.0.1 "$ROOT/scripts/openfdd_caddy_smoke.sh"; then
    bad "Caddy smoke failed (/, /api/health, /login→/auth)"
    summary
    exit 1
  fi
  ok "Caddy smoke (incl. /login redirect)"
fi

# Pin Playwright image to package.json version when possible.
PW_VER="$(node -p "require('$WEB/package.json').devDependencies['@playwright/test'].replace(/^[^\d]*/, '')" 2>/dev/null || echo "1.62.1")"
PW_IMAGE="${OPENFDD_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v${PW_VER}-jammy}"

host_playwright_ok() {
  pushd "$WEB" >/dev/null
  [[ -d node_modules ]] || npm ci >/dev/null
  npx playwright install chromium >/dev/null 2>&1 || true
  # Probe launch (shared libs)
  if node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ headless: true });
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
" >/dev/null 2>&1; then
    popd >/dev/null
    return 0
  fi
  popd >/dev/null
  return 1
}

run_host() {
  pushd "$WEB" >/dev/null
  npx playwright test e2e/product.spec.ts e2e/smoke.spec.ts --reporter=list
  local rc=$?
  popd >/dev/null
  return "$rc"
}

run_docker() {
  echo "${DIM}using Playwright image $PW_IMAGE (host libs missing)${RST}"
  docker pull "$PW_IMAGE" >/dev/null
  # Map host loopback SPA into the container via host networking.
  docker run --rm --network host \
    -e OPENFDD_PLAYWRIGHT_BASE_URL="$OPENFDD_PLAYWRIGHT_BASE_URL" \
    -e OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1 \
    -e OPENFDD_ADMIN_PASSWORD="${OPENFDD_ADMIN_PASSWORD:-}" \
    -e CI=1 \
    -v "$WEB:/work" -w /work \
    "$PW_IMAGE" \
    bash -lc 'npm ci --silent && npx playwright test e2e/product.spec.ts e2e/smoke.spec.ts --reporter=list'
}

LOG="$ART/16_playwright_web.log"
set +e
if [[ "${OPENFDD_PLAYWRIGHT_FORCE_DOCKER:-0}" == "1" ]] || ! host_playwright_ok; then
  run_docker 2>&1 | tee "$LOG"
  rc=${PIPESTATUS[0]}
else
  ok "host Playwright launch probe passed"
  run_host 2>&1 | tee "$LOG"
  rc=${PIPESTATUS[0]}
fi
set -e

if [[ "$rc" -eq 0 ]]; then
  ok "Playwright product + smoke suites passed"
else
  bad "Playwright failed (exit $rc) — see $LOG"
fi

summary
exit "$rc"
