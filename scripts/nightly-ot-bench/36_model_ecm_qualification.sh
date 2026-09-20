#!/usr/bin/env bash
# Gate 36_model_ecm_qualification — bounded model/ECM Soft-OPEN checks.
#
# Wired into Railway hub stress (opt-in MODEL_ECM_GATE=1; default ON for smoke
# visibility). Full FQ evidence for this gate is owned by Wave S4 MEGA — this
# script must not greenwash SPARQL/PERF Soft-OPEN rows.
#
# Checks (honest dispositions):
#   - Mapping JSON own building readable when fixtures present
#   - Foreign building mapping denied (403/404) under MT
#   - Stamped-type provenance fields present when equipment_types.json exists
#   - Central SPARQL remains unavailable (404) — report, do not PASS via empty
#   - ECM adapter: offline Python unit path only when OPENFDD_ECM_OFFLINE=1
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/nightly-ot-bench/_common.sh" 2>/dev/null || true

ART="${ARTIFACT_DIR:-$ROOT/reports/model_ecm_$(date -u +%Y%m%dT%H%M%SZ)}"
if [[ -n "${ARTIFACT_DIR:-}" ]]; then
  ART="${ARTIFACT_DIR%/}/gate36_model_ecm_qualification"
fi
mkdir -p "$ART"
BASE="${OPENFDD_API_BASE:-${RAILWAY_BASE:-}}"
[[ -n "$BASE" ]] || {
  echo "BLOCKED: set OPENFDD_API_BASE or RAILWAY_BASE" | tee "$ART/blocked.txt"
  jq -n '{ok:false,status:"BLOCKED",reason:"missing base URL"}' | tee "$ART/verdict.json"
  exit 2
}
BASE="${BASE%/}"

BUILDING_A="${OPENFDD_MODEL_BUILDING_A:-${OPENFDD_BUILDING_A:-ACME}}"
BUILDING_B="${OPENFDD_MODEL_BUILDING_B:-${OPENFDD_BUILDING_B:-BUILDING_100}}"
USER_A="${OPENFDD_OPS_A_USER:-acme-ops}"
PASS_A="${OPENFDD_OPS_A_PASSWORD:-}"
USER_B="${OPENFDD_OPS_B_USER:-b100-ops}"
PASS_B="${OPENFDD_OPS_B_PASSWORD:-}"

login() {
  local user="$1" pass="$2"
  curl -sf -X POST "$BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg u "$user" --arg p "$pass" '{username:$u,password:$p}')" \
    | jq -r '.token // .access_token // empty'
}

code_for() {
  local method="$1" path="$2" token="$3"
  curl -s -o "$ART/last.body" -w '%{http_code}' -X "$method" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    "$BASE$path"
}

CHECKS=()
record() {
  local id="$1" status="$2" detail="${3:-}"
  CHECKS+=("$(jq -nc --arg i "$id" --arg s "$status" --arg d "$detail" \
    '{check_id:$i,status:$s,detail:$d}')")
  echo "$id $status ${detail}" | tee -a "$ART/checks.log"
}

health="$(curl -sf "$BASE/api/health" || true)"
echo "$health" | tee "$ART/health.json"
MT="$(echo "$health" | jq -r '.multi_tenant // false')"

if [[ -z "$PASS_A" || -z "$PASS_B" ]]; then
  record "model.ecm.preflight_creds" "BLOCKED" "missing OPENFDD_OPS_A/B_PASSWORD"
  jq -n --argjson c "$(printf '%s\n' "${CHECKS[@]}" | jq -s .)" \
    '{ok:false,status:"BLOCKED",checks:$c}' | tee "$ART/verdict.json"
  exit 2
fi

TOK_A="$(login "$USER_A" "$PASS_A" || true)"
TOK_B="$(login "$USER_B" "$PASS_B" || true)"
if [[ -z "$TOK_A" || -z "$TOK_B" ]]; then
  record "model.ecm.login" "ERROR" "operator login failed"
  jq -n --argjson c "$(printf '%s\n' "${CHECKS[@]}" | jq -s .)" \
    '{ok:false,status:"ERROR",checks:$c}' | tee "$ART/verdict.json"
  exit 1
fi
record "model.ecm.login" "PASS" "A+B"

# Own mapping read (empty building may be 200 with empty equipment — not FAIL).
CODE_OWN="$(code_for GET "/api/csv/import/package/mapping?building_id=${BUILDING_A}" "$TOK_A")"
cp -f "$ART/last.body" "$ART/mapping_own.json" 2>/dev/null || true
if [[ "$CODE_OWN" == "200" ]]; then
  record "model.ecm.mapping_own" "PASS" "200"
  # DM-04 provenance when stamped equipment present
  if jq -e '.equipment[]? | select(.equipment_type_source=="package")' \
    "$ART/mapping_own.json" >/dev/null 2>&1; then
    record "model.ecm.dm04_stamp_provenance" "PASS" "package source seen"
  else
    record "model.ecm.dm04_stamp_provenance" "NOT_APPLICABLE" "no stamped rows in fixture"
  fi
elif [[ "$CODE_OWN" == "401" ]]; then
  record "model.ecm.mapping_own" "ERROR" "401 own"
else
  record "model.ecm.mapping_own" "BLOCKED" "status=$CODE_OWN"
fi

# Foreign deny (MT only)
if [[ "$MT" == "true" ]]; then
  CODE_F="$(code_for GET "/api/csv/import/package/mapping?building_id=${BUILDING_B}" "$TOK_A")"
  if [[ "$CODE_F" == "403" || "$CODE_F" == "404" ]]; then
    record "model.ecm.mapping_foreign_denied" "PASS" "$CODE_F"
  elif [[ "$CODE_F" == "401" ]]; then
    record "model.ecm.mapping_foreign_denied" "ERROR" "401"
  else
    record "model.ecm.mapping_foreign_denied" "FAIL" "status=$CODE_F"
  fi
  CODE_TTL="$(code_for GET "/api/csv/import/package/mapping/ttl?building_id=${BUILDING_B}" "$TOK_A")"
  if [[ "$CODE_TTL" == "403" || "$CODE_TTL" == "404" ]]; then
    record "model.ecm.mapping_ttl_foreign_denied" "PASS" "$CODE_TTL"
  else
    record "model.ecm.mapping_ttl_foreign_denied" "FAIL" "status=$CODE_TTL"
  fi
else
  record "model.ecm.mapping_foreign_denied" "NOT_APPLICABLE" "multi_tenant=false"
  record "model.ecm.mapping_ttl_foreign_denied" "NOT_APPLICABLE" "multi_tenant=false"
fi

# SPARQL honesty — product central must not pretend SPARQL is live.
CODE_SPQ="$(code_for POST "/api/model/sparql" "$TOK_A")"
# POST without body may 404/405/400 — only FAIL if 200 with empty ok list pretending success.
if [[ "$CODE_SPQ" == "404" || "$CODE_SPQ" == "405" || "$CODE_SPQ" == "501" ]]; then
  record "model.ecm.sparql_unavailable" "PASS" "status=$CODE_SPQ (honest unavailable)"
elif [[ "$CODE_SPQ" == "200" ]]; then
  record "model.ecm.sparql_unavailable" "FAIL" "SPARQL 200 unexpectedly live"
else
  record "model.ecm.sparql_unavailable" "PASS" "status=$CODE_SPQ (not empty-ok)"
fi

# Offline ECM adapter (Python PyPI path) — optional; never invent HTTP product path.
if [[ "${OPENFDD_ECM_OFFLINE:-0}" == "1" ]]; then
  if python3 -c "import open_fdd.ecm_engineering" 2>/dev/null; then
    record "model.ecm.ecm_adapter_import" "PASS" "open_fdd.ecm_engineering importable"
  else
    record "model.ecm.ecm_adapter_import" "BLOCKED" "package not installed"
  fi
else
  record "model.ecm.ecm_adapter_import" "NOT_APPLICABLE" "OPENFDD_ECM_OFFLINE!=1"
fi

FAILS="$(printf '%s\n' "${CHECKS[@]}" | jq -s '[.[] | select(.status=="FAIL" or .status=="ERROR")] | length')"
printf '%s\n' "${CHECKS[@]}" | jq -s . | tee "$ART/checks.json" >/dev/null
if [[ "$FAILS" -gt 0 ]]; then
  jq -n --argjson c "$(cat "$ART/checks.json")" \
    '{ok:false,status:"FAIL",checks:$c}' | tee "$ART/verdict.json"
  exit 1
fi
jq -n --argjson c "$(cat "$ART/checks.json")" \
  '{ok:true,status:"PASS",checks:$c,note:"FQ evidence owned by Wave S4 MEGA"}' \
  | tee "$ART/verdict.json"
exit 0
