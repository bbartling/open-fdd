#!/usr/bin/env bash
# Grok / local gate — Overview + FDD + RCx backend comb + optional Playwright UI.
#
#   OPENFDD_BUILDING_ID=OPENFDD_SYNTHETIC_59_RULE_WEEK_V1 \
#   OPENFDD_ADMIN_PASSWORD=... \
#   ./scripts/gates/ui_fdd_rcx_validate.sh
#
# Railway follow-on (optional):
#   OPENFDD_API_BASE=https://... OPENFDD_BUILDING_ID=BUILDING_100 ...
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Preserve caller building/API base — .env may pin a different lab default (e.g. BENS_BENCH_OT).
_PRESERVE_BUILDING="${OPENFDD_BUILDING_ID:-}"
_PRESERVE_API_BASE="${OPENFDD_API_BASE:-}"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
if [[ -n "$_PRESERVE_BUILDING" ]]; then
  OPENFDD_BUILDING_ID="$_PRESERVE_BUILDING"
fi
if [[ -n "$_PRESERVE_API_BASE" ]]; then
  OPENFDD_API_BASE="$_PRESERVE_API_BASE"
fi

BUILDING="${OPENFDD_BUILDING_ID:-}"
BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
ART="${ARTIFACT_DIR:-$ROOT/reports/ui_fdd_rcx_gate_$(date -u +%Y%m%dT%H%M%SZ)}"
export ARTIFACT_DIR="$ART"
mkdir -p "$ART"

if [[ -z "$BUILDING" ]]; then
  echo "FAIL: set OPENFDD_BUILDING_ID (parameterized; no product hardcode)" >&2
  exit 1
fi

echo "== backend probe building=$BUILDING base=$BASE =="
if ! OPENFDD_BUILDING_ID="$BUILDING" OPENFDD_API_BASE="$BASE" ARTIFACT_DIR="$ART" \
  python3 "$ROOT/scripts/gates/ui_fdd_rcx_backend_probe.py"; then
  echo "FAIL: backend probe — see $ART/summary.json" >&2
  exit 1
fi

if [[ "${OPENFDD_UI_GATE_SKIP_PLAYWRIGHT:-0}" == "1" ]]; then
  echo "SKIP: OPENFDD_UI_GATE_SKIP_PLAYWRIGHT=1"
  exit 0
fi

WEB="$ROOT/frontend/web"
UI_BASE="${OPENFDD_PLAYWRIGHT_BASE_URL:-http://127.0.0.1:3000}"
spa_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$UI_BASE/" || true)"
if [[ "$spa_code" != "200" && "$spa_code" != "301" && "$spa_code" != "302" ]]; then
  echo "SKIP: SPA not reachable at $UI_BASE (HTTP $spa_code) — backend probe PASS only"
  exit 0
fi

if [[ -z "${OPENFDD_ADMIN_PASSWORD:-}" ]]; then
  echo "SKIP: OPENFDD_ADMIN_PASSWORD unset — backend probe PASS only"
  exit 0
fi

export OPENFDD_PLAYWRIGHT_BASE_URL="$UI_BASE"
export OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1
export OPENFDD_GATE_BUILDING_ID="$BUILDING"

echo "== Playwright FDD/RCx UI gate =="
(
  cd "$WEB"
  if [[ -f e2e/fdd-rcx-gate.spec.ts ]]; then
    npx playwright test e2e/fdd-rcx-gate.spec.ts --reporter=line
  else
    npx playwright test e2e/product.spec.ts --grep "RCx Plotly" --reporter=line
  fi
)
echo "PASS: ui_fdd_rcx_validate artifacts=$ART"
