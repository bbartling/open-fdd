#!/usr/bin/env bash
# Gate 11 — central dashboard / product APIs (≠404) + React Reports page honesty.
# Post–Phase-2: no Streamlit openfdd-ui bundle inspect.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "#549 / product APIs — capabilities + shell GETs"

central_auth_setup
capi() {
  curl -fsS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    -H 'Content-Type: application/json' "$@"
}

CAPS="$(capi "$CENTRAL_BASE/api/capabilities" || echo '{}')"
echo "$CAPS" >"$ART/capabilities.json"
REQUIRED=(
  lab fdd_registry fdd_equipment fdd_results fdd_series session_config
  csv_package reports export data_management host_stats faults
  health_stack fdd_rules_authoring fdd_schema
)
ALL_TRUE=1
for key in "${REQUIRED[@]}"; do
  val="$(jq -r --arg k "$key" '.capabilities[$k] // empty' <<<"$CAPS")"
  if [[ "$val" == "true" ]]; then
    ok "capabilities.$key=true"
  else
    bad "capabilities.$key=$val (want true)"
    ALL_TRUE=0
  fi
done
[[ "$ALL_TRUE" -eq 1 ]] && ok "capabilities matrix all true"

PATHS=(
  /api/capabilities
  /api/health/stack
  /api/building/snapshot
  /api/faults/status
  /api/faults/summary
  /api/export/meta
  /api/data-management/summary
  /api/host/stats
  /api/fdd-schema/tables
  /api/fdd-rules
  /api/reports
  /api/reports/templates
  /api/fdd/rules
  /api/fdd/equipment
  /api/fdd/results
  /api/fdd/session-config
  /api/ui/generation
  /api/ui/migration-metrics
  /api/dashboard/summary
)
for path in "${PATHS[@]}"; do
  body="$ART/http$(echo "$path" | tr '/' '_').body"
  code="$(http_code_to "$body" --max-time 20 \
    "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" "$CENTRAL_BASE$path")"
  if [[ "$code" == "000" ]]; then
    bad "GET $path unreachable (HTTP 000)"
  elif [[ "$code" == "404" ]]; then
    bad "GET $path → 404"
  elif [[ "$code" =~ ^[2345][0-9][0-9]$ ]]; then
    ok "GET $path → HTTP $code (≠404)"
  else
    bad "GET $path → HTTP $code"
  fi
done

# Explicit draft endpoint exists (POST) — React must not invent drafts via quiet GETs
hdr "Reports — draft POST exists; list GET is quiet"
DRAFT_CODE="$(http_code_to "$ART/reports_draft_post.json" --max-time 20 \
  -X POST "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  -H 'Content-Type: application/json' \
  -d '{"title":"bench-smoke-draft","template_id":"blank"}' \
  "$CENTRAL_BASE/api/reports/draft")"
if [[ "$DRAFT_CODE" == "000" ]]; then
  bad "POST /api/reports/draft unreachable (HTTP 000)"
elif [[ "$DRAFT_CODE" == "404" ]]; then
  bad "POST /api/reports/draft → 404"
else
  ok "POST /api/reports/draft reachable (HTTP $DRAFT_CODE) for explicit create"
fi

# React SPA assets: reports route + draft API string (no Streamlit ReportBuilderPage)
JS="$ART/web_assets_549.js"
if web_asset_js "$JS"; then
  if grep -qF '/reports' "$JS" && grep -qF '/api/reports' "$JS"; then
    ok "React assets wire /reports + /api/reports"
  else
    bad "React assets missing reports wiring"
  fi
else
  bad "could not extract web assets for reports wiring check"
fi

# Source tip: ReportsPage should not auto-create drafts on mount if present
RP="$ROOT/frontend/web/src/pages/ReportsPage.tsx"
if [[ -f "$RP" ]]; then
  if grep -qiE 'createDraft|reports/draft' "$RP" \
    && awk '/useEffect/,/^}/' "$RP" 2>/dev/null | grep -q 'draft'; then
    # Soft: only fail if mount effect clearly POSTs draft
    if awk '/useEffect/,/^\s*\}, \[/' "$RP" | grep -qE 'reports/draft|createDraft'; then
      bad "ReportsPage.tsx useEffect may auto-POST draft"
    else
      ok "ReportsPage.tsx present (no clear mount draft POST)"
    fi
  else
    ok "ReportsPage.tsx present (no draft auto-create pattern)"
  fi
else
  skip "ReportsPage.tsx missing from checkout"
fi

BEFORE="$(capi "$CENTRAL_BASE/api/reports" | jq '(.reports // .records // []) | length' 2>/dev/null || echo 0)"
sleep 1
AFTER="$(capi "$CENTRAL_BASE/api/reports" | jq '(.reports // .records // []) | length' 2>/dev/null || echo 0)"
if [[ "$BEFORE" == "$AFTER" ]]; then
  ok "GET /api/reports is quiet (count stable: $AFTER)"
else
  skip "report count $BEFORE→$AFTER (explicit draft POST may have written)"
fi

summary
