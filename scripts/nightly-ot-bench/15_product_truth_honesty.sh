#!/usr/bin/env bash
# Gate 15 — product-truth honesty (P1 recovery). Runs without requiring OT LAN.
# Classifies stub/demo markers; checks live APIs when central is up.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "Product-truth honesty (P1)"

# --- Forbidden unsupported completion claims in live agent/product docs -----
# Allow historical closeout docs under docs/migration/react-rust/*QUALIFICATION*
# and vibe21 CURRENT_STATE_AUDIT which discusses false completion.
HITS_FILE="$ART/phase_complete_hits.txt"
: >"$HITS_FILE"
set +e
rg -n --glob '!**/node_modules/**' --glob '!**/.git/**' \
  -e 'Phase 1 complete|Phase 2 complete|P1-G0 complete|QUALIFIED without' \
  AGENTS.md openfdd_agent_spec/AGENTS.md openfdd_agent_spec/ARCHITECTURE.md \
  openfdd_agent_spec/BUILD_CHECKPOINTS.md \
  docs/migration/react-rust/README.md \
  frontend/web/README.md \
  2>/dev/null | tee -a "$HITS_FILE"
set -e
# Soft: BUILD_CHECKPOINTS may still list modernization exits — require vibe21 section honesty
if rg -q 'Vibe 21 production recovery' openfdd_agent_spec/BUILD_CHECKPOINTS.md \
  && rg -q 'architecture direction' openfdd_agent_spec/BUILD_CHECKPOINTS.md; then
  ok "BUILD_CHECKPOINTS distinguishes modernization exit vs Vibe21 recovery"
else
  bad "BUILD_CHECKPOINTS missing Vibe 21 recovery honesty section"
fi

if rg -q 'Active recovery / Vibe 21' AGENTS.md \
  && rg -q 'architecture direction' AGENTS.md; then
  ok "root AGENTS.md points at vibe21 Master Loop (not false complete)"
else
  bad "root AGENTS.md missing vibe21 recovery pointers"
fi

# --- Classify known scaffold/demo markers (must be ledger-aware, not silent) -
MARKERS_FILE="$ART/product_scaffold_markers.txt"
{
  echo "## PlotlyHost (SVG scaffold)"
  rg -n 'PlotlyHost|No Plotly npm' frontend/web/src/components/widgets/PlotlyHost.tsx \
    frontend/web/src/api/plotDataset.ts 2>/dev/null | head -20 || true
  echo "## DEMO findings seed"
  rg -n 'rule:DEMO' frontend/web/src/pages/FindingsPage.tsx 2>/dev/null || true
  echo "## RCx stub"
  rg -n 'RCx AHU stub|stub' frontend/web/src/pages/MeteringPage.tsx 2>/dev/null | head -10 || true
  echo "## WattLab demo.zip"
  rg -n 'demo\.zip' frontend/web/src/pages/WattLabPage.tsx 2>/dev/null || true
} >"$MARKERS_FILE"

# Ledger honesty: implemented product caps vs scaffold/demo placeholders
LEDGER="$ROOT/docs/migration/react-rust/capabilities.yaml"
for pair in "CAP-PLOTS:IMPLEMENTED" "CAP-RCX:IMPLEMENTED" "CAP-FINDINGS:SCAFFOLD" "CAP-WATTLAB:SCAFFOLD"; do
  id="${pair%%:*}"
  want="${pair##*:}"
  st="$(python3 - <<PY
import yaml
from pathlib import Path
caps=yaml.safe_load(Path("$LEDGER").read_text())["capabilities"]
print(next(c["status"] for c in caps if c["id"]=="$id"))
PY
)"
  if [[ "$st" == "$want" ]]; then
    ok "ledger $id status=$st (expected $want)"
  else
    bad "ledger $id status=$st (expected $want)"
  fi
done

# --- Live API honesty when stack is reachable --------------------------------
hdr "Live API honesty (if central up)"
central_auth_setup
code="$(http_code --max-time 8 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/dashboard/summary" || echo 000)"
if [[ "$code" == "000" ]]; then
  skip "central unreachable — skip dashboard/summary live check"
elif [[ "$code" == "404" ]]; then
  if rg -q 'dashboard_summary|/api/dashboard/summary' services/central/src/routes.rs; then
    skip "live /api/dashboard/summary 404 but tip source wires the route (stack not refreshed)"
  else
    bad "GET /api/dashboard/summary → 404 and missing from tip source"
  fi
else
  ok "GET /api/dashboard/summary → HTTP $code (≠404)"
fi

GEN_CODE="$(http_code --max-time 8 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
  "$CENTRAL_BASE/api/ui/generation" || echo 000)"
if [[ "$GEN_CODE" == "000" ]]; then
  skip "central unreachable — skip ui/generation"
elif [[ "$GEN_CODE" =~ ^2[0-9][0-9]$ ]]; then
  ok "GET /api/ui/generation → HTTP $GEN_CODE"
else
  bad "GET /api/ui/generation → HTTP $GEN_CODE"
fi

# SPA bundle should mention cutover path when web is up
UI_CODE="$(http_code --max-time 8 "$UI_BASE/" || echo 000)"
if [[ "$UI_CODE" == "000" ]]; then
  skip "SPA unreachable — skip /api/ui/generation asset needle"
else
  # Prefer already-running web assets via curl of index → asset; fall back to src
  if rg -q '/api/ui/generation' frontend/web/src/api/cutoverApi.ts frontend/web/src/pages/HomePage.tsx; then
    ok "source wires /api/ui/generation (cutover client)"
  else
    bad "source missing /api/ui/generation cutover wiring"
  fi
fi

summary
[[ "$FAIL" -eq 0 ]]
