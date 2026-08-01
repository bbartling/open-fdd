#!/usr/bin/env bash
# Gate 10 — React SPA product surface (post–Phase-2).
# Asserts SPA routes + HTML shell + web asset markers + UI generation APIs.
# Replaces Streamlit LabShell /lab gate (10_lab_ux_ia.sh).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "React SPA — routes + shell + generation"

central_auth_setup

# --- /api/ui/generation ------------------------------------------------------
GEN="$(central "$CENTRAL_BASE/api/ui/generation" || echo '{}')"
echo "$GEN" >"$ART/ui_generation.json"
if jq -e '.generation=="react"' <<<"$GEN" >/dev/null 2>&1; then
  ok "generation=react"
else
  bad "generation!=react: $(jq -c . <<<"$GEN")"
fi
if jq -e '.default_generation=="react"' <<<"$GEN" >/dev/null 2>&1; then
  ok "default_generation=react"
else
  bad "default_generation!=react"
fi

# --- SPA HTML shell ----------------------------------------------------------
HTML="$(curl -fsS --max-time 15 "$UI_BASE/" || true)"
echo "$HTML" | head -c 500 >"$ART/spa_index_snip.html"
if grep -qiE '<div id="root"|/assets/.*\.js' <<<"$HTML"; then
  ok "SPA index has #root / asset script"
else
  bad "SPA index missing React shell markers"
fi
# Must not look like Streamlit
if grep -qiE 'streamlit|stApp|MainMenu' <<<"$HTML"; then
  bad "SPA index looks like Streamlit"
else
  ok "SPA index is not Streamlit"
fi

# --- Product routes (SPA may return index.html for all; HTTP 200 is enough) ---
ROUTES=(/ /auth /jobs /upload /mapping /rules /findings /reports /metering /wattlab)
for path in "${ROUTES[@]}"; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$UI_BASE$path" || echo 000)"
  if [[ "$code" == "200" || "$code" == "301" || "$code" == "302" ]]; then
    ok "SPA $path → HTTP $code"
  else
    bad "SPA $path → HTTP $code"
  fi
done

# Streamlit Lab path must not be the product surface
lab_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$UI_BASE/lab" || echo 000)"
if [[ "$lab_code" == "200" ]]; then
  # React may still serve index for unknown routes — ensure no LabShell in assets
  skip "HTTP 200 on /lab (SPA fallback) — checking assets for LabShell absence"
else
  ok "/lab not a dedicated Streamlit Lab route (HTTP $lab_code)"
fi

# --- Web asset markers -------------------------------------------------------
JS="$ART/web_assets.js"
if web_asset_js "$JS"; then
  ok "extracted web SPA JS assets ($(wc -c <"$JS") bytes)"
  NEEDLES=(/jobs /upload /findings /reports /wattlab /api/ui/generation)
  MISS=0
  for n in "${NEEDLES[@]}"; do
    if grep -qF "$n" "$JS"; then
      ok "asset mentions $n"
    else
      bad "asset missing $n"
      MISS=1
    fi
  done
  if grep -qiE 'lab-app-shell|vibe19-lab-sidebar|Energy Model' "$JS"; then
    bad "Streamlit Lab markers still present in web assets"
  else
    ok "no Streamlit LabShell markers in web assets"
  fi
  [[ "$MISS" -eq 0 ]]
else
  bad "could not extract web SPA assets (is web up / built?)"
fi

# --- Migration metrics (cutover observability) -------------------------------
if MET="$(central "$CENTRAL_BASE/api/ui/migration-metrics" 2>/dev/null)"; then
  echo "$MET" >"$ART/migration_metrics.json"
  if jq -e 'type=="object"' <<<"$MET" >/dev/null 2>&1; then
    ok "GET /api/ui/migration-metrics object"
  else
    bad "migration-metrics unexpected shape"
  fi
else
  bad "GET /api/ui/migration-metrics"
fi

summary
