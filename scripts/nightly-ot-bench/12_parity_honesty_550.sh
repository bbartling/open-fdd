#!/usr/bin/env bash
# Gate 12 — #550 honesty: no “54 full parity”; registry proven/ported counts;
# SCHED-1 string occ_mode ingest spot-check. React SPA assets (not openfdd-web).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "#550 parity honesty"

central_auth_setup
capi() {
  curl -fsS --max-time 30 "${CENTRAL_AUTH_HDR[@]+"${CENTRAL_AUTH_HDR[@]}"}" \
    -H 'Content-Type: application/json' "$@"
}

# Docs must not claim full cookbook parity
PARITY_DOC="$ROOT/docs/rules/cookbook/parity-matrix.md"
if [[ -f "$PARITY_DOC" ]]; then
  if grep -qiE '54 full parity|full parity with all 54|all 54 rules.*parity' "$PARITY_DOC"; then
    if grep -qF 'Do not claim “54 full parity.”' "$PARITY_DOC" \
      || grep -qF 'Do not claim "54 full parity."' "$PARITY_DOC"; then
      ok "parity-matrix.md forbids “54 full parity” claim"
    else
      bad "parity-matrix.md appears to claim 54 full parity"
    fi
  else
    ok "parity-matrix.md has no rogue 54-full-parity claim"
  fi
  if grep -qiE 'sql_screening|parity_level|Wave 0' "$PARITY_DOC"; then
    ok "parity-matrix.md states Wave 0 parity_level honesty"
  else
    bad "parity-matrix.md missing Wave 0 / sql_screening honesty language"
  fi
  if grep -qiE 'proven_building_100|ported_from_cookbook' "$PARITY_DOC"; then
    bad "parity-matrix.md still uses legacy proven_building_100/ported_from_cookbook labels"
  else
    ok "parity-matrix.md has no legacy proven/ported labels"
  fi
else
  bad "missing $PARITY_DOC"
fi

# React SPA bundle must not claim full parity
JS="$ART/web_assets_550.js"
if web_asset_js "$JS"; then
  if grep -qiE '54 full parity|full cookbook parity|all 54 rules proven' "$JS"; then
    bad "React SPA claims 54/full cookbook parity"
  else
    ok "React SPA does not claim 54/full cookbook parity"
  fi
else
  bad "could not extract web assets for parity claim check"
fi

# Registry counts via live API (Wave 0 ladder)
RULES="$(capi "$CENTRAL_BASE/api/fdd/rules" || echo '{}')"
echo "$RULES" >"$ART/fdd_rules_parity.json"
SCREEN="$(jq '[.rules[]? | select(.parity_status=="sql_screening")] | length' <<<"$RULES")"
CONCEPT="$(jq '[.rules[]? | select(.parity_status=="concept_only")] | length' <<<"$RULES")"
LEGACY="$(jq '[.rules[]? | select(.parity_status=="proven_building_100" or .parity_status=="ported_from_cookbook" or .parity_status=="skipped_missing_roles")] | length' <<<"$RULES")"
TOTAL="$(jq '[.rules[]?] | length' <<<"$RULES")"
echo "${DIM}  registry sql_screening=$SCREEN concept_only=$CONCEPT legacy=$LEGACY total=$TOTAL${RST}"
if [[ "$TOTAL" -eq 68 ]]; then
  ok "registry total=68 (62 diagnostics + 4 SQL-only analytics + UTIL-MONTHLY/INTERVAL)"
else
  bad "registry total=$TOTAL (expected 68)"
fi
if [[ "$LEGACY" -eq 0 ]]; then
  ok "no legacy parity_status labels on tip"
else
  bad "legacy parity_status still present count=$LEGACY"
fi
if [[ "$SCREEN" -ge 50 ]]; then
  ok "sql_screening dominant (actual $SCREEN)"
else
  bad "sql_screening count=$SCREEN (expected majority after Wave 0)"
fi

# SCHED-1 string occ_mode ingest spot-check
hdr "SCHED-1 occ_mode string role"
SCHED_META="$(jq -c '.rules[]? | select(.rule_id=="SCHED-1")' <<<"$RULES")"
echo "$SCHED_META" >"$ART/sched1_meta.json"
if jq -e '(.required_roles // []) | index("occ_mode") != null' <<<"$SCHED_META" >/dev/null 2>&1; then
  ok "SCHED-1 required_roles includes occ_mode"
else
  bad "SCHED-1 missing occ_mode role: $SCHED_META"
fi
SQL_FILE="$ROOT/sql_rules/sched1_unoccupied_runtime.sql"
if [[ -f "$SQL_FILE" ]] && grep -qE 'LOWER\([^)]*occ_mode' "$SQL_FILE" && grep -q "unoccupied" "$SQL_FILE"; then
  ok "SCHED-1 SQL compares string occ_mode (LOWER = unoccupied)"
else
  bad "SCHED-1 SQL missing string occ_mode compare"
fi

cat >"$ART/issue_550_backlog.txt" <<EOF
#550 KEEP OPEN — Wave 0 honesty ladder; higher parity levels still backlog.
- sql_screening=$SCREEN concept_only=$CONCEPT total=$TOTAL
- Do not claim 54 full parity.
- Promote levels only via pandas↔DataFusion fixtures (scripts/sql_pandas_oracle_check.py + fdd_rules).
- SCHED-1 string occ_mode ingest spot-check: PASS (role + SQL).
EOF
ok "wrote #550 KEEP OPEN backlog note → issue_550_backlog.txt"
echo "${DIM}$(cat "$ART/issue_550_backlog.txt")${RST}"

summary
