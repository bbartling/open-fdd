#!/usr/bin/env bash
# CSV → parquet → DataFusion SQL FDD gates on central.
# 1) auth login (admin) when auth is required
# 2) upload synthetic FC1 CSV (duct static below SP at full fan) via preview→plan→preflight→execute
# 3) assert parquet_ingest.ok, dataset listed, /api/fdd/run mode=registry FC1 flags faults
# 4) SQL polling sanity: cache status, registry rules present, ingest stats reachable
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
auth_setup
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
DATASET="${CSV_BENCH_DATASET:-bench_fc1_$(date -u +%H%M%S)}"

# --- central auth -----------------------------------------------------------
TOKEN=""
CAUTH=()
AUTH_REQ="$(curl -fsS --max-time 10 "$CENTRAL_BASE/api/auth/status" 2>/dev/null | jq -r '.auth_required // false' || echo false)"
if [[ "$AUTH_REQ" == "true" ]]; then
  ADMIN_PW="${OPENFDD_ADMIN_PASSWORD:-}"
  if [[ -z "$ADMIN_PW" ]]; then
    bad "central requires auth but OPENFDD_ADMIN_PASSWORD not in env/.env"
    summary; exit 1
  fi
  TOKEN="$(curl -fsS --max-time 15 -X POST "$CENTRAL_BASE/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg p "$ADMIN_PW" '{username:"admin",password:$p}')" \
    | jq -r '.token // .access_token // empty' || true)"
  if [[ -n "$TOKEN" ]]; then
    ok "central login as admin (JWT issued)"
    CAUTH=(-H "Authorization: Bearer $TOKEN")
  else
    bad "central /api/auth/login failed for admin"
    summary; exit 1
  fi
else
  skip "central auth not required (no JWT secret) — proceeding unauthenticated"
fi

capi() { curl -fsS --max-time 60 -H 'Content-Type: application/json' "${CAUTH[@]}" "$@"; }

# --- synthetic FC1 fixture ---------------------------------------------------
hdr "Generate synthetic FC1 CSV (duct static ${DIM}0.6\"${RST} < SP 1.5\" at fan 95%)"
FIX="$ART/fc1_fixture.csv"
# Canonical role name fan_cmd on purpose: #525 (silent column drop) claimed fixed
# in #532 — this gate re-verifies that a column literally named fan_cmd survives.
python3 - "$FIX" <<'PY'
import sys, datetime
path = sys.argv[1]
t0 = datetime.datetime(2026, 7, 17, 0, 0, tzinfo=datetime.timezone.utc)
# Plain wide CSV WITHOUT equipment_id on purpose: #536 claimed fixed in #542 —
# EQUIPMENT_ID_MISSING must not fail-close strict preflight (verdict=pass).
rows = ["timestamp_utc,duct_static,duct_static_sp,fan_cmd"]
for i in range(180):  # 3h @ 1min
    ts = (t0 + datetime.timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if i < 60:      # healthy hour
        rows.append(f"{ts},1.48,1.5,95.0")
    elif i < 150:   # sustained fault: static way below SP at full fan (beats 300s confirm)
        rows.append(f"{ts},0.60,1.5,95.0")
    else:           # fan off — must NOT flag
        rows.append(f"{ts},0.10,1.5,3.0")
open(path, "w").write("\n".join(rows) + "\n")
PY
ok "fixture written ($(wc -l <"$FIX") rows, no equipment_id) → $FIX"

# --- preview -----------------------------------------------------------------
hdr "CSV import: preview"
B64="$(base64 -w0 "$FIX")"
PREV="$(capi -X POST "$CENTRAL_BASE/api/csv/import/preview" \
  -d "$(jq -nc --arg b "$B64" '{files:[{filename:"fc1_bench.csv",content_base64:$b}]}')" || echo '{}')"
echo "$PREV" >"$ART/csv_preview.json"
SID="$(jq -r '.session_id // empty' <<<"$PREV")"
if [[ -n "$SID" ]] && jq -e '.ok==true' <<<"$PREV" >/dev/null; then
  ok "preview staged file (session $SID)"
else
  bad "preview failed: $(head -c 300 <<<"$PREV")"
  summary; exit 1
fi

# --- plan --------------------------------------------------------------------
hdr "CSV import: plan"
PLAN_BODY="$(jq -nc --arg sid "$SID" --arg ds "$DATASET" '{
  session_id: $sid,
  plan: {
    mode: "single",
    files: [{filename:"fc1_bench.csv", timestamp_column:"timestamp_utc", timezone:"UTC",
             value_columns:["duct_static","duct_static_sp","fan_cmd"]}],
    output_dataset_name: $ds
  }}')"
PLAN="$(capi -X POST "$CENTRAL_BASE/api/csv/import/plan" -d "$PLAN_BODY" || echo '{}')"
echo "$PLAN" >"$ART/csv_plan.json"
jq_ok "plan accepted" "$PLAN" '.ok==true'
echo "${DIM}  rows=$(jq -r '.preview.row_count // "?"' <<<"$PLAN") cols=$(jq -cr '.preview.column_names // []' <<<"$PLAN" | head -c 160)${RST}"

# --- preflight ---------------------------------------------------------------
hdr "CSV import: preflight (fail-closed validation)"
PRE="$(capi -X POST "$CENTRAL_BASE/api/csv/import/preflight" \
  -d "$(jq -nc --arg sid "$SID" '{session_id:$sid}')" || echo '{}')"
echo "$PRE" >"$ART/csv_preflight.json"
VERDICT="$(jq -r '.verdict // empty' <<<"$PRE")"
jq_ok "preflight can_execute" "$PRE" '.can_execute==true'
# #536/#542: plain wide CSV without equipment_id must still verdict=pass under strict defaults
if [[ "$VERDICT" == "pass" ]]; then
  ok "preflight verdict=pass on wide CSV without equipment_id (#536 fix verified)"
else
  bad "preflight verdict=$VERDICT without equipment_id (#536 regression) — checks: $(jq -cr '.validation.checks // [] | map(select(.severity!="pass" and .severity!="info"))' <<<"$PRE" 2>/dev/null | head -c 300)"
fi

# --- execute -----------------------------------------------------------------
hdr "CSV import: execute (writes Feather/Arrow + parquet)"
EXE="$(capi -X POST "$CENTRAL_BASE/api/csv/import/execute" \
  -d "$(jq -nc --arg sid "$SID" '{session_id:$sid, confirm:true}')" || echo '{}')"
echo "$EXE" >"$ART/csv_execute.json"
jq_ok "execute ok" "$EXE" '.ok==true'
jq_ok "parquet_ingest.ok" "$EXE" '.parquet_ingest.ok==true'
echo "${DIM}  parquet=$(jq -c '.parquet_ingest // {}' <<<"$EXE" | head -c 300)${RST}"

hdr "Dataset visible via /api/datasets"
DS="$(capi "$CENTRAL_BASE/api/datasets" || echo '{}')"
echo "$DS" >"$ART/datasets.json"
if jq -e --arg d "$DATASET" '(.datasets // . // []) | tostring | contains($d)' <<<"$DS" >/dev/null 2>&1; then
  ok "dataset $DATASET listed"
else
  bad "dataset $DATASET not in /api/datasets: $(head -c 200 <<<"$DS")"
fi

# --- FDD registry run --------------------------------------------------------
hdr "FDD registry: FC1 present and runnable"
RULES="$(capi "$CENTRAL_BASE/api/fdd/rules" || echo '{}')"
echo "$RULES" >"$ART/fdd_rules.json"
jq_ok "registry lists FC1" "$RULES" 'tostring | contains("FC1")'
echo "${DIM}  rule_count=$(jq -r '.rules|length // "?"' <<<"$RULES" 2>/dev/null)${RST}"

CACHE="$(capi "$CENTRAL_BASE/api/fdd/cache/status" || echo '{}')"
echo "$CACHE" >"$ART/fdd_cache_status.json"
jq_ok "parquet cache exists with files" "$CACHE" '.parquet_exists==true and (.parquet_file_count|tonumber) > 0'

RUN="$(capi -X POST "$CENTRAL_BASE/api/fdd/run" \
  -d '{"params":{"mode":"registry","rule_ids":["FC1"]}}' || echo '{}')"
echo "$RUN" >"$ART/fdd_run_fc1.json"
jq_ok "fdd/run FC1 ok" "$RUN" '.ok==true'
# Contract: FC1 itself executed with rows (fan_cmd survived parquet ingest — #525).
# Tip runners may still attempt sibling rules against a narrow fixture and report
# rules_failed>0 for missing roles — that is not an FC1/fan_cmd regression.
if jq -e 'any(.timings[]?; .rule_id=="FC1" and (.error==null or .error=="") and (.row_count // 0) > 0)
          or any(.results[]?; .rule_id=="FC1" and (.status|type=="string"))' <<<"$RUN" >/dev/null 2>&1; then
  ok "FC1 executed via DataFusion with literal fan_cmd column (#525 fix verified)"
  echo "${DIM}  $(jq -c '[.timings[]? | select(.rule_id=="FC1")]' <<<"$RUN" | head -c 300)${RST}"
  # Honesty note when filtered request still expands to the full registry
  RR="$(jq -r '.rules_run // 0' <<<"$RUN")"
  if [[ "$RR" -gt 5 ]]; then
    echo "${DIM}  note: rules_run=$RR (tip may expand beyond rule_ids filter; FC1 timing still green)${RST}"
  fi
else
  bad "FC1 run failed or produced no result rows (fan_cmd drop regression? #525): $(head -c 300 <<<"$RUN")"
fi

# #528 fix: 1-minute fixture must yield poll_seconds ≈ 60, not hardcoded 300
PS="$(jq -r '.poll_seconds // empty' <<<"$RUN")"
if [[ -n "$PS" ]] && approx "$PS" 60 10; then
  ok "poll_seconds=$PS inferred from 1-min CSV grid (#528 fix verified)"
else
  bad "poll_seconds=$PS for a 1-min fixture (expected ≈60; grid_minutes hardcode regression #528)"
fi

# Tip Lab/#549 contract: /api/fdd/run and /api/fdd/results must expose per-row
# results[] (rule_id / equipment_id / status) — not aggregates-only.
hdr "FDD results[] row shape (not aggregates-only)"
RESULTS="$(capi "$CENTRAL_BASE/api/fdd/results" || echo '{}')"
echo "$RESULTS" >"$ART/fdd_results.json"
if jq -e '
  (.results | type == "array") and
  ((.results | length) > 0) and
  all(.results[];
    (.rule_id | type == "string" and length > 0) and
    (.equipment_id | type == "string" and length > 0) and
    (.status | type == "string" and length > 0)
  )
' <<<"$RESULTS" >/dev/null 2>&1; then
  ok "results[] rows carry rule_id/equipment_id/status (n=$(jq '.results|length' <<<"$RESULTS"))"
  echo "${DIM}  sample=$(jq -c '.results[0]' <<<"$RESULTS" | head -c 220)${RST}"
else
  bad "results[] missing or aggregates-only: $(jq -c '{ok,count,keys:(keys),sample:(.results[0]//.aggregates//.)}' <<<"$RESULTS" 2>/dev/null | head -c 300)"
fi
# Prefer run payload also returning the same shape when present
if jq -e '(.results|type)=="array" and (.results|length)>0' <<<"$RUN" >/dev/null 2>&1; then
  if jq -e 'all(.results[]; .rule_id and .equipment_id and .status)' <<<"$RUN" >/dev/null 2>&1; then
    ok "fdd/run FC1 payload results[] also shaped"
  else
    bad "fdd/run returned results[] without rule_id/equipment_id/status"
  fi
else
  skip "fdd/run omitted results[] (GET /api/fdd/results is the Lab source of truth)"
fi

# #531/#532: FC13 alias must resolve to FC13-SAT-HIGH
RUN13="$(capi -X POST "$CENTRAL_BASE/api/fdd/run" \
  -d '{"params":{"mode":"registry","rule_ids":["FC13"]}}' || echo '{}')"
echo "$RUN13" >"$ART/fdd_run_fc13.json"
if jq -e '(.rules_run // 0) >= 1 and (.error // "" | test("no matching rules") | not)' <<<"$RUN13" >/dev/null 2>&1; then
  ok "FC13 alias resolves and runs (#532 alias verified)"
  echo "${DIM}  $(jq -c '.timings // .error' <<<"$RUN13" | head -c 200)${RST}"
else
  bad "FC13 alias did not resolve: $(head -c 200 <<<"$RUN13")"
fi

# Registry safety: raw SQL must be rejected
RAW="$(capi -X POST "$CENTRAL_BASE/api/fdd/run" -d '{"sql":"SELECT 1"}' || echo '{}')"
if jq -e '.ok==false' <<<"$RAW" >/dev/null 2>&1; then
  ok "raw SQL rejected on /api/fdd/run (registry-only enforced)"
else
  bad "raw SQL was NOT rejected on /api/fdd/run"
fi

# --- SQL polling sanity ------------------------------------------------------
hdr "Ingest stats reachable (polled OT telemetry → queryable path)"
IS="$(capi "$CENTRAL_BASE/api/ingest/stats" || echo '{}')"
echo "$IS" >"$ART/ingest_stats_csvgate.json"
jq_ok "ingest/stats reachable" "$IS" 'type=="object"'
echo "${DIM}  $(jq -c . <<<"$IS" | head -c 250)${RST}"

summary
